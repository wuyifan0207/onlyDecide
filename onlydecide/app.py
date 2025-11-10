from flask import Flask, jsonify, request, render_template_string, Response, make_response
import os
import json
import time
import io
import csv
import threading
import requests

# 复用现有核心逻辑
import test as core
import db

app = Flask(__name__)

# 诊断：记录每次请求的路径，帮助定位404来源
@app.before_request
def _log_incoming_request_path():
    try:
        core.write_echo(f"收到请求: {request.method} {request.path}")
    except Exception:
        pass

# 初始化核心组件（使用 test.py 中的密钥与配置）
dc = core.OKXDataCollector(core.OKX_API_KEY, core.OKX_SECRET, core.OKX_PASSWORD)
ai = core.DeepSeekAI(core.DEEPSEEK_API_KEY)

# 数据库初始化
DB_PATH = os.path.join(os.path.dirname(__file__), 'decisions.db')
db.init_db(DB_PATH)


def generate_and_store_ai_decision():
    """采集数据、生成AI决策并写入数据库与日志（单次执行）。"""
    try:
        symbol = getattr(core, 'SYMBOL', 'ETH-USDT-SWAP')
        klines_5 = dc.get_kline_data(symbol=symbol, bar="5m", limit=6)
        klines_30 = dc.get_kline_data(symbol=symbol, bar="30m", limit=6)
        klines_2h = dc.get_kline_data(symbol=symbol, bar="2H", limit=6)
        klines_1d = dc.get_kline_data(symbol=symbol, bar="1D", limit=6)
        current_price = dc.get_current_price(symbol=symbol)

        market_data = {
            "current_price": current_price,
            "kline_5min": klines_5,
            "kline_30min": klines_30,
            "kline_2h": klines_2h,
            "kline_1d": klines_1d
        }
        account_status = dc.get_account_balance()
        position_info = dc.get_position_info(symbol=symbol)

        # 使用当前符号写入历史与提示
        recent_rows = db.get_recent_decisions(DB_PATH, symbol=symbol, limit=10)
        history_for_prompt = db.summarize_history_for_prompt(recent_rows)

        decision = ai.get_trading_decision(market_data, account_status, position_info, history=history_for_prompt, symbol=symbol)

        try:
            db.insert_decision(DB_PATH, symbol, market_data, account_status, position_info, decision)
            td = (decision or {}).get('trading_decision', {})
            core.write_echo(f"自动AI决策完成：action={td.get('action')} conf={td.get('confidence_level')} price={market_data['current_price']}")
        except Exception as e:
            core.write_error(f"写入AI决策到数据库失败: {e}")

        # 若交易模式为 live，则尝试执行交易
        try:
            mode = globals().get('TRADING_MODE', 'simulation')
        except Exception:
            mode = 'simulation'
        if str(mode).lower() == 'live':
            try:
                core.write_echo("交易模式=live，开始执行交易")
                executor = core.OKXTradingExecutor(dc, ai)
                ok = executor.execute_trade(decision, current_price, is_test=False)
                if ok:
                    core.write_echo("交易执行完成")
                else:
                    core.write_echo("交易未执行或失败")
            except Exception as e:
                core.write_error(f"执行交易失败: {e}")
        else:
            # 仿真模式：将决策映射为模拟持仓开/平仓，应用自定义仓位与杠杆
            try:
                symbol = getattr(core, 'SYMBOL', 'ETH-USDT-SWAP')
                td = (decision or {}).get('trading_decision', {})
                pm = (decision or {}).get('position_management', {})
                action = (td.get('action') or 'hold').lower()

                # 读取当前是否有模拟持仓
                open_pos = db.sim_get_open_position(DB_PATH, symbol=symbol)

                # 仿真平仓规则：
                # - 若已有持仓且出现下一条信号(open_long/open_short/hold)，则以当前价平仓
                if open_pos:
                    if action in ('open_long', 'open_short', 'hold'):
                        lev = int(getattr(core, 'LEVERAGE', 1) or 1)
                        db.sim_close_position(DB_PATH, open_pos['id'], exit_price=current_price, leverage=lev)
                        try:
                            core.write_echo(f"模拟平仓: id={open_pos['id']} exit={current_price:.2f} 杠杆={lev}x")
                        except Exception:
                            pass
                        # 若当前信号是开仓，则在同一价格开新仓（信号切换）
                        if action in ('open_long', 'open_short'):
                            # 计算开仓数量：优先使用用户自定义USDT->ETH，否则使用AI建议
                            try:
                                size_eth = float(pm.get('position_size') or 0.0)
                            except Exception:
                                size_eth = 0.0
                            if bool(getattr(core, 'USER_OVERRIDE_ENABLED', False)) and (getattr(core, 'USER_OVERRIDE_POSITION_SIZE', None) is not None):
                                try:
                                    usdt_amt = float(getattr(core, 'USER_OVERRIDE_POSITION_SIZE', 0) or 0)
                                except Exception:
                                    usdt_amt = 0.0
                                try:
                                    size_eth = (usdt_amt / current_price) if (current_price and current_price > 0) else 0.0
                                    core.write_echo(f"模拟交易应用自定义仓位: {usdt_amt:.2f} USDT -> {size_eth:.6f} ETH")
                                except Exception:
                                    pass
                            # 边界处理
                            min_sz = float(getattr(core, 'MIN_ORDER_SIZE', 0.001) or 0.001)
                            max_sz = float(getattr(core, 'MAX_ORDER_SIZE', 10.0) or 10.0)
                            size_eth = max(min_sz, min(size_eth, max_sz)) if size_eth > 0 else 0.0
                            if size_eth > 0:
                                side = 'long' if action == 'open_long' else 'short'
                                tp_price = pm.get('take_profit_price') or None
                                sl_price = pm.get('stop_loss_price') or None
                                db.sim_open_position(DB_PATH, symbol, side, size_eth, current_price, tp_price=tp_price, sl_price=sl_price)
                                core.write_echo(f"模拟开仓: {side} size={size_eth:.6f} @ {current_price:.2f}")
                else:
                    # 无持仓时，若为开仓信号则按设置开仓
                    if action in ('open_long', 'open_short'):
                        try:
                            size_eth = float(pm.get('position_size') or 0.0)
                        except Exception:
                            size_eth = 0.0
                        if bool(getattr(core, 'USER_OVERRIDE_ENABLED', False)) and (getattr(core, 'USER_OVERRIDE_POSITION_SIZE', None) is not None):
                            try:
                                usdt_amt = float(getattr(core, 'USER_OVERRIDE_POSITION_SIZE', 0) or 0)
                            except Exception:
                                usdt_amt = 0.0
                            size_eth = (usdt_amt / current_price) if (current_price and current_price > 0) else 0.0
                            try:
                                core.write_echo(f"模拟交易应用自定义仓位: {usdt_amt:.2f} USDT -> {size_eth:.6f} ETH")
                            except Exception:
                                pass
                        min_sz = float(getattr(core, 'MIN_ORDER_SIZE', 0.001) or 0.001)
                        max_sz = float(getattr(core, 'MAX_ORDER_SIZE', 10.0) or 10.0)
                        size_eth = max(min_sz, min(size_eth, max_sz)) if size_eth > 0 else 0.0
                        if size_eth > 0:
                            side = 'long' if action == 'open_long' else 'short'
                            tp_price = pm.get('take_profit_price') or None
                            sl_price = pm.get('stop_loss_price') or None
                            db.sim_open_position(DB_PATH, symbol, side, size_eth, current_price, tp_price=tp_price, sl_price=sl_price)
                            core.write_echo(f"模拟开仓: {side} size={size_eth:.6f} @ {current_price:.2f}")
            except Exception as e:
                core.write_error(f"模拟交易处理失败: {e}")
    except Exception as e:
        core.write_error(f"自动AI决策失败: {e}")


def _background_ai_loop():
    """后台循环：按 AI_FREQUENCY 周期自动生成并写库。"""
    try:
        core.write_echo(f"自动AI决策线程已启动")
    except Exception:
        pass
    while True:
        # 每轮动态读取频率，支持页面调整后端刷新间隔
        freq = int(getattr(core, 'AI_FREQUENCY', 10) or 10)
        generate_and_store_ai_decision()
        try:
            time.sleep(max(1, freq))
        except Exception:
            time.sleep(10)


def tail_file(path: str, max_lines: int = 80):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
            return [line.strip() for line in lines[-max_lines:]]
    except Exception:
        return []


@app.route('/')
def index():
    ai_freq = getattr(core, 'AI_FREQUENCY', 10)
    symbol = getattr(core, 'SYMBOL', 'ETH-USDT-SWAP')
    leverage = getattr(core, 'LEVERAGE', 50)
    # 使用外部模板 index_dump.html
    template_path = os.path.join(os.path.dirname(__file__), 'index_dump.html')
    source = 'index_dump.html'
    index_charset = 'utf-8'
    try:
        # 以字节读取，优先utf-8，失败则尝试gbk与latin-1，避免页面出现乱码
        with open(template_path, 'rb') as f:
            raw = f.read()
        try:
            template = raw.decode('utf-8')
            index_charset = 'utf-8'
        except Exception:
            try:
                template = raw.decode('gbk')
                index_charset = 'gbk'
            except Exception:
                template = raw.decode('latin-1')
                index_charset = 'latin-1'
        try:
            core.write_echo(f"index模板来源: {source}; 编码: {index_charset}; 长度: {len(template)}; 含btStatsPanel: {'btStatsPanel' in template}")
        except Exception:
            pass
    except Exception as e:
        # 强制使用 index_dump.html，读取失败直接返回错误
        try:
            core.write_error(f"读取 index_dump.html 失败: {e}")
        except Exception:
            pass
        resp = make_response("缺少 index_dump.html 或无法读取", 500)
        resp.headers['X-Index-Source'] = 'error'
        resp.headers['X-Index-Charset'] = 'unknown'
        return resp
    min_size = float(getattr(core, 'MIN_ORDER_SIZE', 0.02))
    max_size = float(getattr(core, 'MAX_ORDER_SIZE', 0.1))
    html = render_template_string(template, ai_freq=ai_freq, symbol=symbol, leverage=leverage, min_size=min_size, max_size=max_size)
    resp = make_response(html)
    resp.headers['X-Index-Source'] = source
    resp.headers['X-Index-Charset'] = index_charset
    return resp


# 已移除：/api/trading_config 与 /api/trading_config2

@app.route('/api/config', methods=['GET', 'POST'])
def api_config():
    # 支持读取与更新核心交易配置：杠杆与固定仓位
    try:
        if request.method == 'POST':
            payload = request.get_json(silent=True) or {}
            # 更新杠杆
            if 'leverage' in payload:
                try:
                    lv = int(float(payload.get('leverage') or 0))
                    if lv > 0:
                        core.LEVERAGE = lv
                        try:
                            core.write_echo(f"更新杠杆为: {lv}x")
                        except Exception:
                            pass
                except Exception:
                    pass
            # 更新固定仓位开关
            if 'override_enabled' in payload:
                try:
                    core.USER_OVERRIDE_ENABLED = bool(payload.get('override_enabled'))
                except Exception:
                    pass
            # 更新固定仓位数值（USDT）
            if 'override_position_size' in payload:
                try:
                    v = payload.get('override_position_size')
                    core.USER_OVERRIDE_POSITION_SIZE = (None if v is None or v == '' else float(v))
                except Exception:
                    pass
            # 可选：单位（目前仅支持 USDT）
            if 'position_unit' in payload:
                try:
                    u = str(payload.get('position_unit') or '').upper()
                    if u in ('USDT', 'COIN'):
                        core.USER_POSITION_UNIT = u
                except Exception:
                    pass
            # 更新自动AI频率（秒）
            if 'ai_frequency' in payload:
                try:
                    f = int(float(payload.get('ai_frequency') or 0))
                    if f > 0:
                        core.AI_FREQUENCY = f
                        try:
                            core.write_echo(f"更新AI频率为: {f}s")
                        except Exception:
                            pass
                except Exception:
                    pass
        cfg = {
            'symbol': getattr(core, 'SYMBOL', 'ETH-USDT-SWAP'),
            'leverage': getattr(core, 'LEVERAGE', 50),
            'override_enabled': getattr(core, 'USER_OVERRIDE_ENABLED', False),
            'override_position_size': getattr(core, 'USER_OVERRIDE_POSITION_SIZE', None),
            'position_unit': getattr(core, 'USER_POSITION_UNIT', 'USDT'),
            'ai_frequency': getattr(core, 'AI_FREQUENCY', 10)
        }
        return jsonify({'success': True, 'config': cfg})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# 轻量级交易模式接口（仅供前端展示切换，不触发真实交易）
TRADING_MODE = 'simulation'

@app.route('/api/trading_mode', methods=['GET', 'POST'])
def api_trading_mode():
    global TRADING_MODE
    if request.method == 'GET':
        return jsonify({'success': True, 'mode': TRADING_MODE})
    try:
        payload = request.get_json(silent=True) or {}
        mode = str(payload.get('mode', '')).lower()
        if mode not in ('simulation', 'live'):
            return jsonify({'success': False, 'error': 'invalid mode'}), 400
        TRADING_MODE = mode
        try:
            core.write_echo(f"切换交易模式: {mode}")
        except Exception:
            pass
        return jsonify({'success': True, 'mode': TRADING_MODE})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/routes')
def api_routes():
    """列出所有已注册路由，便于诊断404问题"""
    try:
        rules = []
        for rule in app.url_map.iter_rules():
            rules.append(str(rule))
        return jsonify({'success': True, 'routes': sorted(rules)})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/symbol', methods=['GET', 'POST'])
def api_symbol():
    """获取或更新当前交易对（币种）。"""
    try:
        if request.method == 'GET':
            sym = getattr(core, 'SYMBOL', 'ETH-USDT-SWAP')
            return jsonify({'success': True, 'symbol': sym})
        else:
            payload = request.get_json(force=True, silent=True) or {}
            new_sym = str(payload.get('symbol', '')).strip()
            if not new_sym:
                return jsonify({'success': False, 'error': '缺少symbol参数'}), 400
            # 简单校验：必须包含USDT-SWAP后缀
            if '-USDT-SWAP' not in new_sym:
                return jsonify({'success': False, 'error': '仅支持USDT永续合约，如 ETH-USDT-SWAP'}), 400
            core.SYMBOL = new_sym
            try:
                core.write_echo(f"更新交易对: {new_sym}")
            except Exception:
                pass
            return jsonify({'success': True, 'symbol': new_sym})
    except Exception as e:
        core.write_error(f"交易对更新失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/summary')
def api_summary():
    try:
        symbol = getattr(core, 'SYMBOL', 'ETH-USDT-SWAP')
        klines_5 = dc.get_kline_data(symbol=symbol, bar="5m", limit=6)
        klines_30 = dc.get_kline_data(symbol=symbol, bar="30m", limit=6)
        klines_2h = dc.get_kline_data(symbol=symbol, bar="2H", limit=6)
        klines_1d = dc.get_kline_data(symbol=symbol, bar="1D", limit=6)
        current_price = dc.get_current_price(symbol=symbol)
    except Exception as e:
        core.write_error(f"API summary 数据采集失败: {e}")
        klines_5, klines_30, klines_2h, klines_1d = [], [], [], []
        current_price = 3500.0

    try:
        account_status = dc.get_account_balance()
    except Exception as e:
        core.write_error(f"API summary 账户状态失败: {e}")
        account_status = {"available_OKX": 0.0, "total_equity": 0.0, "available_OKXWALLET": 0.0}

    try:
        position_info = dc.get_position_info(symbol=getattr(core, 'SYMBOL', 'ETH-USDT-SWAP'))
    except Exception as e:
        core.write_error(f"API summary 持仓信息失败: {e}")
        position_info = {"position_side": "flat", "position_size": 0.0, "entry_price": 0.0, "leverage": getattr(core, 'LEVERAGE', 50)}

    return jsonify({
        "market_data": {
            "current_price": current_price,
            "kline_5min": klines_5,
            "kline_30min": klines_30,
            "kline_2h": klines_2h,
            "kline_1d": klines_1d
        },
        "account_status": account_status,
        "position_info": position_info
    })


@app.route('/api/ai_decision')
def api_ai_decision():
    try:
        symbol = getattr(core, 'SYMBOL', 'ETH-USDT-SWAP')
        klines_5 = dc.get_kline_data(symbol=symbol, bar="5m", limit=6)
        klines_30 = dc.get_kline_data(symbol=symbol, bar="30m", limit=6)
        klines_2h = dc.get_kline_data(symbol=symbol, bar="2H", limit=6)
        klines_1d = dc.get_kline_data(symbol=symbol, bar="1D", limit=6)
        current_price = dc.get_current_price(symbol=symbol)

        market_data = {
            "current_price": current_price,
            "kline_5min": klines_5,
            "kline_30min": klines_30,
            "kline_2h": klines_2h,
            "kline_1d": klines_1d
        }
        account_status = dc.get_account_balance()
        position_info = dc.get_position_info(symbol=symbol)
        
        # 读取最近历史用于上下文提示
        recent_rows = db.get_recent_decisions(DB_PATH, symbol=symbol, limit=10)
        history_for_prompt = db.summarize_history_for_prompt(recent_rows)

        decision = ai.get_trading_decision(market_data, account_status, position_info, history=history_for_prompt, symbol=symbol)

        # 写入数据库
        try:
            db.insert_decision(DB_PATH, symbol, market_data, account_status, position_info, decision)
        except Exception as e:
            core.write_error(f"写入AI决策到数据库失败: {e}")

        return jsonify({"success": True, "decision": decision, "current_price": current_price})
    except Exception as e:
        core.write_error(f"AI决策调用失败: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/logs')
def api_logs():
    echo_lines = tail_file(core.ECHO_FILE, max_lines=80)
    error_lines = tail_file(core.ERROR_FILE, max_lines=80)
    return jsonify({"echo": echo_lines, "error": error_lines})

@app.route('/api/logs/clear', methods=['POST','GET'], strict_slashes=False)
def api_logs_clear():
    try:
        # 可选: 通过查询参数只清空其中一种日志：?type=echo 或 ?type=error
        t = (request.args.get('type') or '').strip().lower()
        if t in ('echo', 'error'):
            p = getattr(core, 'ECHO_FILE' if t=='echo' else 'ERROR_FILE', None)
            if not p:
                return jsonify({"success": False, "error": f"{t} 文件未配置"}), 500
            try:
                # 删除并重建空文件；删除失败则回退为截断
                if os.path.exists(p):
                    try:
                        os.remove(p)
                    except Exception:
                        pass
                with open(p, 'w', encoding='utf-8') as f:
                    f.write('')
                return jsonify({"success": True, "cleared": 1, "type": t})
            except Exception as e:
                core.write_error(f"清空日志文件失败({p}): {e}")
                return jsonify({"success": False, "error": str(e)}), 500

        paths = [getattr(core, 'ECHO_FILE', None), getattr(core, 'ERROR_FILE', None)]
        cleared = 0
        for p in paths:
            if not p:
                continue
            try:
                # 删除并重建空文件；删除失败则回退为截断
                if os.path.exists(p):
                    try:
                        os.remove(p)
                    except Exception:
                        pass
                with open(p, 'w', encoding='utf-8') as f:
                    f.write('')
                cleared += 1
            except Exception as e:
                core.write_error(f"清空日志文件失败({p}): {e}")
        return jsonify({"success": True, "cleared": cleared})
    except Exception as e:
        core.write_error(f"清空日志失败: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/logs/clear_echo', methods=['POST','GET'], strict_slashes=False)
def api_logs_clear_echo():
    try:
        p = getattr(core, 'ECHO_FILE', None)
        if not p:
            return jsonify({"success": False, "error": "ECHO_FILE 未配置"}), 500
        # 删除并重建空文件；删除失败则回退为截断
        if os.path.exists(p):
            try:
                os.remove(p)
            except Exception:
                pass
        with open(p, 'w', encoding='utf-8') as f:
            f.write('')
        return jsonify({"success": True, "cleared": 1})
    except Exception as e:
        core.write_error(f"清空回显失败: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/logs/clear_error', methods=['POST','GET'], strict_slashes=False)
def api_logs_clear_error():
    try:
        p = getattr(core, 'ERROR_FILE', None)
        if not p:
            return jsonify({"success": False, "error": "ERROR_FILE 未配置"}), 500
        # 删除并重建空文件；删除失败则回退为截断
        if os.path.exists(p):
            try:
                os.remove(p)
            except Exception:
                pass
        with open(p, 'w', encoding='utf-8') as f:
            f.write('')
        return jsonify({"success": True, "cleared": 1})
    except Exception as e:
        core.write_error(f"清空错误日志失败: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/available_symbols')
def api_available_symbols():
    try:
        url = 'https://www.okx.com/api/v5/public/instruments'
        params = {'instType': 'SWAP'}
        resp = requests.get(url, params=params, timeout=10)
        data = resp.json() if resp.ok else {}
        items = (data or {}).get('data', [])
        symbols = []
        for it in items:
            inst_id = (it or {}).get('instId')
            if inst_id and inst_id.endswith('-USDT-SWAP'):
                symbols.append(inst_id)
        symbols = sorted(list(set(symbols)))[:200]
        return jsonify({'success': True, 'symbols': symbols})
    except Exception as e:
        core.write_error(f"获取可用交易对失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

# 兜底：如果 /api/symbol 未正确注册，使用 before_request 捕获并转发
@app.before_request
def _fallback_symbol_route():
    try:
        if request.path == '/api/symbol':
            # 若正常注册已生效，直接返回 None 继续路由匹配
            for rule in app.url_map.iter_rules():
                if str(rule) == '/api/symbol':
                    return None
            # 未注册时，直接调用视图函数作为兜底
            return api_symbol()
    except Exception:
        # 任何异常都不影响正常请求流程
        return None


@app.route('/api/decision_history')
def api_decision_history():
    try:
        symbol = request.args.get('symbol', getattr(core, 'SYMBOL', 'ETH-USDT-SWAP'))
        page_str = request.args.get('page')
        page_size_str = request.args.get('page_size')
        limit_str = request.args.get('limit')

        def to_int(s, default):
            try:
                return int(s)
            except Exception:
                return default

        if page_str or page_size_str:
            page = max(1, to_int(page_str or '1', 1))
            page_size = max(1, min(200, to_int(page_size_str or '10', 10)))
            result = db.get_decisions_paginated(DB_PATH, symbol=symbol, page=page, page_size=page_size)
            # 精简输出字段
            output = []
            for r in result.get('data', []):
                output.append({
                    "id": r.get("id"),
                    "timestamp": r.get("timestamp"),
                    "symbol": r.get("symbol"),
                    "current_price": r.get("current_price"),
                    "action": r.get("action"),
                    "confidence_level": r.get("confidence_level"),
                    "reason": r.get("reason"),
                    "position_size": r.get("position_size"),
                    "stop_loss_price": r.get("stop_loss_price"),
                    "take_profit_price": r.get("take_profit_price"),
                })
            return jsonify({"success": True, "total": result.get('total', 0), "data": output})
        else:
            limit = max(1, min(200, to_int(limit_str or '10', 10)))
            rows = db.get_recent_decisions(DB_PATH, symbol=symbol, limit=limit)
            output = []
            for r in rows:
                output.append({
                    "id": r.get("id"),
                    "timestamp": r.get("timestamp"),
                    "symbol": r.get("symbol"),
                    "current_price": r.get("current_price"),
                    "action": r.get("action"),
                    "confidence_level": r.get("confidence_level"),
                    "reason": r.get("reason"),
                    "position_size": r.get("position_size"),
                    "stop_loss_price": r.get("stop_loss_price"),
                    "take_profit_price": r.get("take_profit_price"),
                })
            return jsonify({"success": True, "total": len(output), "data": output})
    except Exception as e:
        core.write_error(f"读取决策历史失败: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# === 回测：基于实际执行交易的简单配对交易回测 ===
def simulate_backtest_history(db_path: str, symbol: str, initial_equity: float, fee_rate: float = 0.0, override_size: float = None, override_leverage: float = None):
    """基于数据库中实际执行的交易进行回测（含TP/SL命中判定）。

    规则：
    - 只回测真正开单的单子，而不是所有AI返回的信号
    - 开单前会检查有没有持仓，如果有的话就会跳过开单
    - 当检测到TP/SL命中时按该时刻价格平仓；若未命中，则在下一条信号到来时以该信号的价格平仓；
    - hold：不新开仓；若当前有仓位，则在该信号时刻视为平仓（若之前未命中TP/SL）；
    - 盈亏以 USDT 计（ETH数量 * 价格差），手续费按费率对开/平两侧计提（notional * fee_rate）。
    - 末尾未平仓不强制平仓。
    """
    rows = db.get_all_decisions(db_path, symbol)
    ordered = list(reversed(rows))  # 时间正序

    trades = []
    equity = float(initial_equity)
    peak = equity
    max_dd = 0.0
    equity_curve = []  # [{time, equity}]
    # 杠杆倍数（未提供则使用全局默认，最低为1）
    try:
        default_leverage = getattr(core, 'LEVERAGE', 1)
    except Exception:
        default_leverage = 1
    lev = (override_leverage if (override_leverage is not None and override_leverage > 0) else default_leverage) or 1

    i = 0
    n = len(ordered)
    position = None  # {side, entry_price, size, enter_time, tp, sl}

    def parse_float(x, default=0.0):
        try:
            return float(x)
        except Exception:
            return default

    # 在曲线中加入起始点，避免前端“数据不足”
    try:
        start_ts = (ordered[0].get('timestamp') if ordered else None)
    except Exception:
        start_ts = None
    equity_curve.append({'time': (start_ts or 'START'), 'equity': equity})

    while i < n:
        row = ordered[i]
        price_i = parse_float(row.get('current_price'))
        action_i = (row.get('action') or 'hold').lower()
        size_i = parse_float(row.get('position_size'))
        ts_i = row.get('timestamp')

        # 检查是否有持仓，如果有持仓则跳过开单（模拟真实交易逻辑）
        if position is None:
            if action_i == 'open_long' and size_i > 0:
                position = {
                    'side': 'long',
                    'entry_price': price_i,
                    'size': (override_size if (override_size is not None and override_size > 0) else size_i),
                    'enter_time': ts_i,
                    'tp': parse_float(row.get('take_profit_price'), None),
                    'sl': parse_float(row.get('stop_loss_price'), None)
                }
                # 记录开仓时间点权益
                equity_curve.append({'time': ts_i, 'equity': equity})
            elif action_i == 'open_short' and size_i > 0:
                position = {
                    'side': 'short',
                    'entry_price': price_i,
                    'size': (override_size if (override_size is not None and override_size > 0) else size_i),
                    'enter_time': ts_i,
                    'tp': parse_float(row.get('take_profit_price'), None),
                    'sl': parse_float(row.get('stop_loss_price'), None)
                }
                # 记录开仓时间点权益
                equity_curve.append({'time': ts_i, 'equity': equity})
            i += 1
            continue

        # 已有持仓：从当前位置向后扫描，寻找最早的TP/SL命中或下一条信号
        j = i
        exit_j = None
        exit_price = None
        exit_time = None
        exit_reason = None  # 'tp'|'sl'|'signal'

        while j < n:
            rj = ordered[j]
            price_j = parse_float(rj.get('current_price'))
            action_j = (rj.get('action') or 'hold').lower()
            ts_j = rj.get('timestamp')

            tp = position.get('tp')
            sl = position.get('sl')
            side = position['side']
            # TP/SL判定（以决策序列中最早出现为准）
            if tp is not None and sl is not None:
                if side == 'long':
                    if price_j >= tp:
                        exit_j, exit_price, exit_time, exit_reason = j, price_j, ts_j, 'tp'
                        break
                    if price_j <= sl:
                        exit_j, exit_price, exit_time, exit_reason = j, price_j, ts_j, 'sl'
                        break
                else:  # short
                    if price_j <= tp:
                        exit_j, exit_price, exit_time, exit_reason = j, price_j, ts_j, 'tp'
                        break
                    if price_j >= sl:
                        exit_j, exit_price, exit_time, exit_reason = j, price_j, ts_j, 'sl'
                        break

            # 若未命中TP/SL，遇到下一条信号则以该信号价格平仓
            if action_j in ('open_long', 'open_short', 'hold'):
                exit_j, exit_price, exit_time, exit_reason = j, price_j, ts_j, 'signal'
                break

            j += 1

        if exit_j is None:
            # 序列末尾仍持仓，则不强制平仓，结束
            break

        # 计算盈亏并记录交易
        side = position['side']
        entry_price = position['entry_price']
        size_pos = position['size']
        # 计算毛盈亏并按杠杆放大；手续费同样按杠杆放大
        pnl_gross = (exit_price - entry_price) * size_pos if side == 'long' else (entry_price - exit_price) * size_pos
        pnl = pnl_gross * lev
        fee_entry = fee_rate * entry_price * size_pos * lev
        fee_exit = fee_rate * exit_price * size_pos * lev
        pnl_net = pnl - fee_entry - fee_exit
        equity += pnl_net
        ret_pct = ((exit_price - entry_price) / entry_price) if side == 'long' else ((entry_price - exit_price) / entry_price)

        trades.append({
            'enter_time': position['enter_time'],
            'exit_time': exit_time,
            'side': side,
            'entry_price': entry_price,
            'exit_price': exit_price,
            'size': size_pos,
            'pnl_usdt': pnl_net,
            'return_pct': ret_pct,
            'exit_reason': exit_reason
        })

        # 更新回撤与权益曲线
        if equity > peak:
            peak = equity
        dd = (peak - equity) / peak if peak > 0 else 0.0
        if dd > max_dd:
            max_dd = dd
        equity_curve.append({'time': exit_time, 'equity': equity})

        # 移动索引到退出点，并根据当前行是否开新仓
        position = None
        i = exit_j
        # 继续循环会在此行检查是否开新仓

    # 若曲线点位仍不足两点，补充结束点
    if len(equity_curve) < 2:
        try:
            end_ts = (ordered[-1].get('timestamp') if ordered else None)
        except Exception:
            end_ts = None
        equity_curve.append({'time': (end_ts or 'END'), 'equity': equity})

    wins = sum(1 for t in trades if (t.get('pnl_usdt') or 0) > 0)
    num_trades = len(trades)
    win_rate = (wins / num_trades) if num_trades > 0 else 0.0
    metrics = {
        'starting_equity': float(initial_equity),
        'ending_equity': equity,
        'total_pnl': equity - float(initial_equity),
        'num_trades': num_trades,
        'win_rate': win_rate,
        'max_drawdown': max_dd,
        'position_size_override': (override_size if override_size is not None else None),
        'leverage_used': (override_leverage if override_leverage is not None else getattr(core, 'LEVERAGE', 50))
    }
    return metrics, trades, equity_curve


@app.route('/api/backtest')
def api_backtest():
    try:
        symbol = request.args.get('symbol') or getattr(core, 'SYMBOL', 'ETH-USDT-SWAP')
        initial_equity = request.args.get('initial_equity', '10000')
        fee_rate = request.args.get('fee_rate', '0')
        # 新增：自定义仓位与杠杆
        override_size_str = request.args.get('position_size')
        override_leverage_str = request.args.get('leverage')
        try:
            initial_equity = float(initial_equity)
        except Exception:
            initial_equity = 10000.0
        try:
            fee_rate = float(fee_rate)
        except Exception:
            fee_rate = 0.0
        try:
            override_size = float(override_size_str) if override_size_str is not None else None
        except Exception:
            override_size = None
        try:
            override_leverage = float(override_leverage_str) if override_leverage_str is not None else None
        except Exception:
            override_leverage = None
        try:
            core.write_echo(f"回测参数: override_size={override_size}, override_leverage={override_leverage}, fee_rate={fee_rate}, symbol={symbol}")
        except Exception:
            pass
        metrics, trades, curve = simulate_backtest_history(DB_PATH, symbol, initial_equity, fee_rate, override_size=override_size, override_leverage=override_leverage)
        return jsonify({'success': True, 'metrics': metrics, 'trades': trades, 'curve': curve})
    except Exception as e:
        core.write_error(f"回测计算失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


# 诊断用：简单Ping路由，排除环境问题
@app.route('/api/ping')
def api_ping():
    return jsonify({'success': True, 'msg': 'pong'})

# 诊断用：为回测新增别名路由，排除特定路径匹配问题
@app.route('/api/backtest2')
def api_backtest2():
    try:
        symbol = request.args.get('symbol') or getattr(core, 'SYMBOL', 'ETH-USDT-SWAP')
        initial_equity = request.args.get('initial_equity', '10000')
        fee_rate = request.args.get('fee_rate', '0')
        # 新增：自定义仓位与杠杆（别名路由）
        override_size_str = request.args.get('position_size')
        override_leverage_str = request.args.get('leverage')
        try:
            initial_equity = float(initial_equity)
        except Exception:
            initial_equity = 10000.0
        try:
            fee_rate = float(fee_rate)
        except Exception:
            fee_rate = 0.0
        try:
            override_size = float(override_size_str) if override_size_str is not None else None
        except Exception:
            override_size = None
        try:
            override_leverage = float(override_leverage_str) if override_leverage_str is not None else None
        except Exception:
            override_leverage = None
        try:
            core.write_echo(f"回测参数(backtest2): override_size={override_size}, override_leverage={override_leverage}, fee_rate={fee_rate}, symbol={symbol}")
        except Exception:
            pass
        metrics, trades, curve = simulate_backtest_history(DB_PATH, symbol, initial_equity, fee_rate, override_size=override_size, override_leverage=override_leverage)
        return jsonify({'success': True, 'metrics': metrics, 'trades': trades, 'curve': curve})
    except Exception as e:
        core.write_error(f"回测计算失败(backtest2): {e}")
        return jsonify({'success': False, 'error': str(e)}), 500




# ==================== 通知系统模块 ====================

class NotificationManager:
    """通知管理模块"""
    
    def __init__(self):
        self.telegram_enabled = False
        self.email_enabled = False
        self.telegram_config = {}
        self.email_config = {}
    
    def send_notification(self, title, message, level='info'):
        """发送通知"""
        timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
        full_message = f"[{timestamp}] {title}: {message}"
        
        # 记录到日志
        if level == 'error':
            core.write_error(f"通知: {full_message}")
        else:
            core.write_echo(f"通知: {full_message}")
        
        # 这里可以集成Telegram、邮件等通知渠道
        # 目前先记录到日志
        return True


# 初始化通知管理器
notification_manager = NotificationManager()


@app.route('/api/notifications', methods=['POST'])
def api_send_notification():
    """发送通知接口"""
    try:
        payload = request.get_json(force=True, silent=True) or {}
        title = payload.get('title', '系统通知')
        message = payload.get('message', '')
        level = payload.get('level', 'info')
        
        success = notification_manager.send_notification(title, message, level)
        
        return jsonify({
            'success': success,
            'message': '通知已发送'
        })
        
    except Exception as e:
        core.write_error(f"发送通知失败: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/decision_history/export')
def api_decision_history_export():
    try:
        symbol = request.args.get('symbol')
        fmt = (request.args.get('format') or 'csv').lower()
        rows = db.get_all_decisions(DB_PATH, symbol=symbol)
        if fmt == 'json':
            # 精简字段输出
            output = []
            for r in rows:
                output.append({
                    "id": r.get("id"),
                    "timestamp": r.get("timestamp"),
                    "symbol": r.get("symbol"),
                    "current_price": r.get("current_price"),
                    "action": r.get("action"),
                    "confidence_level": r.get("confidence_level"),
                    "reason": r.get("reason"),
                    "position_size": r.get("position_size"),
                    "stop_loss_price": r.get("stop_loss_price"),
                    "take_profit_price": r.get("take_profit_price"),
                    "executed": r.get("executed", 0)
                })
            return jsonify({"success": True, "data": output})
        # 默认CSV
        sio = io.StringIO()
        # 写入BOM以便Excel识别UTF-8
        sio.write('\ufeff')
        writer = csv.writer(sio)
        writer.writerow(['id','timestamp','symbol','current_price','action','confidence_level','reason','position_size','stop_loss_price','take_profit_price','executed'])
        for r in rows:
            writer.writerow([
                r.get('id'), r.get('timestamp'), r.get('symbol'), r.get('current_price'), r.get('action'),
                r.get('confidence_level'), r.get('reason'), r.get('position_size'), r.get('stop_loss_price'), r.get('take_profit_price'),
                r.get('executed', 0)
            ])
        csv_content = sio.getvalue()
        filename = f"decision_history_{(symbol or 'all').replace('-', '_')}.csv"
        resp = Response(csv_content, mimetype='text/csv; charset=utf-8')
        resp.headers['Content-Disposition'] = f'attachment; filename="{filename}"'
        return resp
    except Exception as e:
        core.write_error(f"导出决策历史失败: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/decision_history/clear', methods=['POST'])
def api_decision_history_clear():
    """清除所有历史决策数据"""
    try:
        deleted_count = db.clear_all_decisions(DB_PATH)
        core.write_echo(f"已清除所有历史决策数据，共删除 {deleted_count} 条记录")
        return jsonify({
            "success": True,
            "deleted_count": deleted_count,
            "message": f"已清除 {deleted_count} 条历史决策记录"
        })
    except Exception as e:
        core.write_error(f"清除历史决策数据失败: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/_routes')
def _routes():
    try:
        rules = []
        for r in app.url_map.iter_rules():
            rules.append({
                'rule': str(r),
                'endpoint': r.endpoint,
                'methods': sorted(list(r.methods or []))
            })
        return jsonify({'success': True, 'routes': rules})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


if __name__ == '__main__':
    core.write_echo("启动Web界面：Flask Dashboard")
    try:
        # 确保交易对路由已注册
        try:
            app.add_url_rule('/api/symbol', view_func=api_symbol, methods=['GET','POST'])
            core.write_echo("通过add_url_rule确保 /api/symbol 已注册")
        except Exception as e:
            core.write_error(f"补注册 /api/symbol 失败或已存在: {e}")
        # 兜底：在此处定义并注册 /api/symbol2，确保至少有一个可用的交易对接口
        try:
            def api_symbol2():
                try:
                    if request.method == 'GET':
                        sym = getattr(core, 'SYMBOL', 'ETH-USDT-SWAP')
                        return jsonify({'success': True, 'symbol': sym})
                    else:
                        payload = request.get_json(force=True, silent=True) or {}
                        new_sym = str(payload.get('symbol', '')).strip()
                        if not new_sym:
                            return jsonify({'success': False, 'error': '缺少symbol参数'}), 400
                        if '-USDT-SWAP' not in new_sym:
                            return jsonify({'success': False, 'error': '仅支持USDT永续合约，如 ETH-USDT-SWAP'}), 400
                        core.SYMBOL = new_sym
                        try:
                            core.write_echo(f"更新交易对(兜底): {new_sym}")
                        except Exception:
                            pass
                        return jsonify({'success': True, 'symbol': new_sym})
                except Exception as e:
                    core.write_error(f"symbol2失败: {e}")
                    return jsonify({'success': False, 'error': str(e)}), 500
            app.add_url_rule('/api/symbol2', view_func=api_symbol2, methods=['GET','POST'])
            core.write_echo("兜底注册 /api/symbol2 成功")
        except Exception as e:
            core.write_error(f"兜底注册 /api/symbol2 失败: {e}")
        # 补注册：确保 /api/logs/clear* 路由存在（部分环境下装饰器可能未生效）
        try:
            app.add_url_rule('/api/logs/clear', view_func=api_logs_clear, methods=['GET','POST'])
            app.add_url_rule('/api/logs/clear_echo', view_func=api_logs_clear_echo, methods=['GET','POST'])
            app.add_url_rule('/api/logs/clear_error', view_func=api_logs_clear_error, methods=['GET','POST'])
            core.write_echo("通过add_url_rule确保 /api/logs/clear* 已注册")
        except Exception as e:
            core.write_error(f"补注册 /api/logs/clear* 失败或已存在: {e}")
        # 诊断：输出已注册路由
        for r in app.url_map.iter_rules():
            try:
                core.write_echo(f"已注册路由: {r.rule} [{','.join(sorted(list(r.methods or [])))}] -> {r.endpoint}")
            except Exception:
                print("已注册路由:", r)
    except Exception as e:
        core.write_error(f"列出路由失败: {e}")
    # 启动后台AI线程（守护线程，不阻塞退出）
    try:
        bg = threading.Thread(target=_background_ai_loop, name='AIBackgroundLoop', daemon=True)
        bg.start()
    except Exception as e:
        core.write_error(f"后台AI线程启动失败: {e}")
    # 监听到所有网卡，允许外网访问；端口 5123
    app.run(host='0.0.0.0', port=5123, debug=False)