import sqlite3
import json
from typing import List, Dict, Optional
from datetime import datetime, timezone


def init_db(db_path: str):
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS decisions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                symbol TEXT NOT NULL,
                current_price REAL,
                action TEXT,
                confidence_level TEXT,
                reason TEXT,
                position_size REAL,
                stop_loss_price REAL,
                take_profit_price REAL,
                market_data_json TEXT,
                account_status_json TEXT,
                position_info_json TEXT,
                raw_decision_json TEXT,
                executed INTEGER DEFAULT 0
            );
            """
        )
        # 模拟持仓/交易记录表（单表同时记录开平仓与盈亏）
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS sim_positions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,            -- long / short
                size_eth REAL NOT NULL,
                entry_price REAL NOT NULL,
                tp_price REAL,
                sl_price REAL,
                status TEXT NOT NULL,          -- open / closed
                open_time TEXT NOT NULL,
                close_time TEXT,
                exit_price REAL,
                pnl_usdt REAL,                 -- 已实现盈亏（平仓后写入）
                pnl_pct REAL                   -- 已实现盈亏百分比
            );
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_decisions_symbol_time
            ON decisions(symbol, timestamp);
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_sim_positions_symbol_status
            ON sim_positions(symbol, status);
            """
        )
        conn.commit()
    finally:
        conn.close()


def _dumps(obj) -> str:
    try:
        return json.dumps(obj, ensure_ascii=False)
    except Exception:
        return "{}"


def insert_decision(
    db_path: str,
    symbol: str,
    market_data: Dict,
    account_status: Dict,
    position_info: Dict,
    decision: Dict,
    executed: int = 0
) -> int:
    ts = datetime.now(timezone.utc).isoformat()
    td = decision.get("trading_decision", {})
    pm = decision.get("position_management", {})

    row = (
        ts,
        symbol,
        float(market_data.get("current_price") or 0),
        td.get("action"),
        td.get("confidence_level"),
        td.get("reason"),
        float(pm.get("position_size") or 0),
        float(pm.get("stop_loss_price") or 0),
        float(pm.get("take_profit_price") or 0),
        _dumps(market_data),
        _dumps(account_status),
        _dumps(position_info),
        _dumps(decision),
        executed
    )

    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO decisions (
                timestamp, symbol, current_price, action, confidence_level, reason,
                position_size, stop_loss_price, take_profit_price,
                market_data_json, account_status_json, position_info_json, raw_decision_json, executed
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            row,
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()

def sim_open_position(
    db_path: str,
    symbol: str,
    side: str,
    size_eth: float,
    entry_price: float,
    tp_price: float = None,
    sl_price: float = None,
    open_time: Optional[str] = None
) -> int:
    """在模拟表中开仓一条记录（status=open）"""
    if open_time is None:
        open_time = datetime.now(timezone.utc).isoformat()

    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO sim_positions (
                symbol, side, size_eth, entry_price, tp_price, sl_price,
                status, open_time
            ) VALUES (?, ?, ?, ?, ?, ?, 'open', ?)
            """,
            (symbol, side, size_eth, entry_price, tp_price, sl_price, open_time)
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()

def sim_get_open_position(db_path: str, symbol: Optional[str] = None) -> Optional[Dict]:
    """获取当前开仓的模拟持仓（如存在则返回最新一条）"""
    conn = sqlite3.connect(db_path)
    try:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        if symbol:
            cur.execute(
                """
                SELECT * FROM sim_positions
                WHERE status = 'open' AND symbol = ?
                ORDER BY open_time DESC
                LIMIT 1
                """,
                (symbol,)
            )
        else:
            cur.execute(
                """
                SELECT * FROM sim_positions
                WHERE status = 'open'
                ORDER BY open_time DESC
                LIMIT 1
                """
            )
        row = cur.fetchone()
        return ({k: row[k] for k in row.keys()}) if row else None
    finally:
        conn.close()

def sim_close_position(
    db_path: str,
    position_id: int,
    exit_price: float,
    close_time: Optional[str] = None,
    leverage: Optional[float] = None
) -> bool:
    """平掉指定的模拟持仓并计算已实现盈亏。

    参数:
    - leverage: 若提供则按该杠杆倍数放大盈亏（默认不放大）。
    """
    if close_time is None:
        close_time = datetime.now(timezone.utc).isoformat()

    # 读取开仓信息以计算盈亏
    conn = sqlite3.connect(db_path)
    try:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM sim_positions WHERE id = ?", (position_id,))
        row = cur.fetchone()
        if not row:
            return False
        side = row['side']
        entry_price = float(row['entry_price'] or 0)
        size_eth = float(row['size_eth'] or 0)

        # 多空方向盈亏：多单 (exit-entry)*size；空单 (entry-exit)*size
        if side == 'long':
            pnl_base = (exit_price - entry_price) * size_eth
        else:
            pnl_base = (entry_price - exit_price) * size_eth

        # 按杠杆放大（若提供且有效）
        try:
            lev = float(leverage) if (leverage is not None) else 1.0
            if lev <= 0:
                lev = 1.0
        except Exception:
            lev = 1.0
        pnl = pnl_base * lev

        pnl_pct = 0.0
        try:
            if entry_price > 0:
                pnl_pct = (pnl / (entry_price * size_eth)) * 100.0
        except Exception:
            pnl_pct = 0.0

        cur.execute(
            """
            UPDATE sim_positions
            SET status = 'closed', close_time = ?, exit_price = ?, pnl_usdt = ?, pnl_pct = ?
            WHERE id = ?
            """,
            (close_time, exit_price, pnl, pnl_pct, position_id)
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()

def sim_list_positions(db_path: str, symbol: Optional[str] = None, limit: int = 50) -> List[Dict]:
    """列出模拟持仓/交易记录，时间倒序"""
    conn = sqlite3.connect(db_path)
    try:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        if symbol:
            cur.execute(
                """
                SELECT * FROM sim_positions
                WHERE symbol = ?
                ORDER BY open_time DESC
                LIMIT ?
                """,
                (symbol, limit)
            )
        else:
            cur.execute(
                """
                SELECT * FROM sim_positions
                ORDER BY open_time DESC
                LIMIT ?
                """,
                (limit,)
            )
        rows = cur.fetchall()
        return [{k: r[k] for k in r.keys()} for r in rows]
    finally:
        conn.close()

def sim_clear(db_path: str) -> int:
    """清空模拟持仓/交易记录"""
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM sim_positions")
        before = cur.fetchone()[0]
        cur.execute("DELETE FROM sim_positions")
        conn.commit()
        cur.execute("SELECT COUNT(*) FROM sim_positions")
        after = cur.fetchone()[0]
        return before - after
    finally:
        conn.close()


def get_recent_decisions(
    db_path: str,
    symbol: Optional[str] = None,
    limit: int = 10
) -> List[Dict]:
    conn = sqlite3.connect(db_path)
    try:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        if symbol:
            cur.execute(
                """
                SELECT * FROM decisions
                WHERE symbol = ?
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                (symbol, limit),
            )
        else:
            cur.execute(
                """
                SELECT * FROM decisions
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                (limit,),
            )
        rows = cur.fetchall()
        results: List[Dict] = []
        for r in rows:
            item = {k: r[k] for k in r.keys()}
            # 还原部分JSON字段，便于直接用于AI提示词历史上下文
            try:
                item["decision"] = json.loads(item.get("raw_decision_json") or "{}")
            except Exception:
                item["decision"] = {}
            results.append(item)
        return results
    finally:
        conn.close()


def summarize_history_for_prompt(rows: List[Dict]) -> List[Dict]:
    """将数据库中的历史决策提炼为轻量结构，便于注入提示词"""
    summarized: List[Dict] = []
    for r in rows:
        d = r.get("decision") or {}
        td = d.get("trading_decision", {})
        pm = d.get("position_management", {})
        summarized.append({
            "timestamp": r.get("timestamp"),
            "symbol": r.get("symbol"),
            "current_price": r.get("current_price"),
            "action": td.get("action"),
            "confidence_level": td.get("confidence_level"),
            "reason": td.get("reason"),
            "position_size": pm.get("position_size"),
            "stop_loss_price": pm.get("stop_loss_price"),
            "take_profit_price": pm.get("take_profit_price"),
        })
    return summarized


def get_decisions_paginated(
    db_path: str,
    symbol: Optional[str],
    page: int,
    page_size: int
) -> Dict:
    """分页查询历史决策，返回总数与当前页数据（时间倒序）"""
    conn = sqlite3.connect(db_path)
    try:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        # 总数
        if symbol:
            cur.execute("SELECT COUNT(*) AS cnt FROM decisions WHERE symbol = ?", (symbol,))
        else:
            cur.execute("SELECT COUNT(*) AS cnt FROM decisions")
        total = int(cur.fetchone()[0])

        # 页码范围处理
        if page < 1:
            page = 1
        if page_size < 1:
            page_size = 10
        offset = (page - 1) * page_size

        # 数据查询（时间倒序）
        if symbol:
            cur.execute(
                """
                SELECT * FROM decisions
                WHERE symbol = ?
                ORDER BY timestamp DESC
                LIMIT ? OFFSET ?
                """,
                (symbol, page_size, offset),
            )
        else:
            cur.execute(
                """
                SELECT * FROM decisions
                ORDER BY timestamp DESC
                LIMIT ? OFFSET ?
                """,
                (page_size, offset),
            )
        rows = cur.fetchall()
        data: List[Dict] = []
        for r in rows:
            item = {k: r[k] for k in r.keys()}
            try:
                item["decision"] = json.loads(item.get("raw_decision_json") or "{}")
            except Exception:
                item["decision"] = {}
            data.append(item)
        return {"total": total, "data": data}
    finally:
        conn.close()


def get_all_decisions(db_path: str, symbol: Optional[str] = None) -> List[Dict]:
    """获取全部历史决策（可按symbol筛选），时间倒序"""
    conn = sqlite3.connect(db_path)
    try:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        if symbol:
            cur.execute(
                """
                SELECT * FROM decisions
                WHERE symbol = ?
                ORDER BY timestamp DESC
                """,
                (symbol,),
            )
        else:
            cur.execute(
                """
                SELECT * FROM decisions
                ORDER BY timestamp DESC
                """
            )
        rows = cur.fetchall()
        results: List[Dict] = []
        for r in rows:
            results.append({k: r[k] for k in r.keys()})
        return results
    finally:
        conn.close()


def clear_all_decisions(db_path: str) -> int:
    """清除所有历史决策数据，返回删除的行数"""
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM decisions")
        count_before = cur.fetchone()[0]
        
        cur.execute("DELETE FROM decisions")
        conn.commit()
        
        cur.execute("SELECT COUNT(*) FROM decisions")
        count_after = cur.fetchone()[0]
        
        return count_before - count_after
    finally:
        conn.close()


def update_decision_executed(db_path: str, decision_id: int, executed: int = 1) -> bool:
    """更新决策的执行状态"""
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE decisions SET executed = ? WHERE id = ?",
            (executed, decision_id)
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()