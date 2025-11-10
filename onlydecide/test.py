#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
ETH永续合约交易程序
交易所: OKX
AI: Deepseek
交易对: ETHUSDT
杠杆: 50倍
版本: v6 - 增加多时间维度K线数据
"""

import os
import time
import hmac
import hashlib
import base64
import json
import requests
import logging
import re
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional
import urllib.parse

# ==================== 基础配置 ====================
OKX_API_KEY = "xxxxxxxxxxxxxxxx"
OKX_SECRET = "xxxxxxxxxxxxxxxxxxxxxxxxx"
OKX_PASSWORD = "xxxxxxxxxxxxxxxxxxxxxxxxxx"
DEEPSEEK_API_KEY = "xxxxxxxxxxxxxxxxxxxx"

# 测试模式控制变量
jymkcs = False  # 仅做数据采集与AI决策，关闭交易模块测试

SYMBOL = "ETH-USDT-SWAP"
LEVERAGE = 50  # 默认杠杆
# 交易尺寸下限与上限（单位：ETH）
# OKX 永续合约 ctVal=0.1，最小张数 0.01 => 最小ETH约 0.001
MIN_ORDER_SIZE = 0.0001  # 最小下单量（ETH）
MAX_ORDER_SIZE = 10.0   # 最大下单量（ETH），用于安全夹紧
AI_FREQUENCY = 300
CHECK_PENDING_ORDERS_INTERVAL = 30  # 检查挂单间隔

# 运行时用户覆盖参数（由Web端动态设置）
USER_OVERRIDE_ENABLED = False
USER_OVERRIDE_POSITION_SIZE: Optional[float] = None
# 统一U本位：固定仓位以USDT金额填写
USER_POSITION_UNIT: str = 'USDT'

# 交易模式控制（由Web端动态设置）
TRADING_MODE = 'simulation'  # 'simulation' 或 'live'

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger()

ERROR_FILE = "baocuo.txt"
ECHO_FILE = "huixian.txt"


def write_error(message: str):
    """写入错误信息到报错文件"""
    # 同步输出到控制台
    logger.error(message)
    try:
        with open(ERROR_FILE, "a", encoding="utf-8") as f:
            f.write(f"{datetime.now()} - ERROR: {message}\n")
    except Exception as e:
        # 文件写入失败也在控制台打印
        logger.error(f"无法写入错误文件: {e}")


def write_echo(message: str):
    """写入回显信息到回显文件"""
    # 同步输出到控制台
    logger.info(message)
    try:
        with open(ECHO_FILE, "a", encoding="utf-8") as f:
            f.write(f"{datetime.now()} - ECHO: {message}\n")
    except Exception as e:
        # 文件写入失败也在控制台打印
        logger.error(f"无法写入回显文件: {e}")


# ==================== 模块1: 信息收集模块 ====================
class OKXDataCollector:
    """OKX数据收集器"""

    def __init__(self, api_key: str, secret: str, password: str):
        self.api_key = api_key
        self.secret = secret
        self.password = password
        self.base_url = "https://www.okx.com"

    def _generate_signature(self, timestamp: str, method: str, request_path: str, body: str = "") -> str:
        """生成OKX API签名"""
        try:
            if body is None:
                body = ""

            message = timestamp + method.upper() + request_path + body

            mac = hmac.new(
                bytes(self.secret, encoding='utf-8'),
                bytes(message, encoding='utf-8'),
                digestmod='sha256'
            )
            signature = base64.b64encode(mac.digest()).decode()
            return signature

        except Exception as e:
            write_error(f"生成签名失败: {e}")
            raise

    def _get_timestamp(self) -> str:
        """获取OKX格式的时间戳"""
        now = datetime.now(timezone.utc)
        timestamp = now.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'
        return timestamp

    def _make_request(self, method: str, endpoint: str, params: Dict = None) -> Dict:
        """发送API请求"""
        try:
            # 构建请求路径和URL
            request_path = endpoint
            url = self.base_url + endpoint

            timestamp = self._get_timestamp()
            body = ""

            # 处理GET请求参数
            if method.upper() == 'GET' and params:
                query_string = '&'.join([f"{k}={v}" for k, v in params.items()])
                request_path = endpoint + '?' + query_string
                url = self.base_url + request_path
            elif method.upper() == 'POST' and params:
                body = json.dumps(params, separators=(',', ':'))

            signature = self._generate_signature(timestamp, method.upper(), request_path, body)

            headers = {
                'OK-ACCESS-KEY': self.api_key,
                'OK-ACCESS-SIGN': signature,
                'OK-ACCESS-TIMESTAMP': timestamp,
                'OK-ACCESS-PASSPHRASE': self.password,
                'Content-Type': 'application/json'
            }

            # 打印详细的请求信息（脱敏）
            sensitive_headers = {"OK-ACCESS-KEY", "OK-ACCESS-SIGN", "OK-ACCESS-PASSPHRASE"}
            sanitized_headers = {k: ('***' if k in sensitive_headers else v) for k, v in headers.items()}
            write_echo(f"准备请求: {method.upper()} {url}")
            if method.upper() == 'GET' and params:
                write_echo(f"查询参数: {params}")
            elif method.upper() == 'POST':
                write_echo(f"请求体长度: {len(body)} 字符")
                write_echo(f"请求体: {body}")
            write_echo(f"请求头(脱敏): {sanitized_headers}")

            start_time = time.time()

            if method.upper() == 'GET':
                response = requests.get(url, headers=headers, timeout=10)
            else:
                response = requests.post(url, headers=headers, data=body, timeout=10)

            duration_ms = (time.time() - start_time) * 1000
            write_echo(f"API请求完成: {method} {endpoint} - 状态码: {response.status_code} - 耗时: {duration_ms:.1f}ms")

            response.raise_for_status()
            result = response.json()

            # 打印响应摘要
            try:
                resp_preview = json.dumps(result)[:1000]
            except Exception:
                resp_preview = str(result)[:1000]
            write_echo(f"响应预览(截断): {resp_preview}")

            if result['code'] != '0':
                error_msg = f"API错误: {result['msg']} (代码: {result['code']})"
                # 记录详细的错误信息
                write_error(f"{error_msg} - 请求路径: {request_path}, 参数: {params}")
                raise Exception(error_msg)

            return result['data']

        except requests.exceptions.RequestException as e:
            write_error(f"网络请求失败: {e} - URL: {url}")
            raise
        except Exception as e:
            write_error(f"API请求失败: {e}")
            raise

    def get_kline_data(self, symbol: str = SYMBOL, bar: str = "5m", limit: int = 6) -> List[Dict]:
        """获取K线数据"""
        try:
            endpoint = "/api/v5/market/candles"
            params = {
                'instId': symbol,
                'bar': bar,
                'limit': limit
            }

            data = self._make_request('GET', endpoint, params)
            klines = []

            for candle in data:
                klines.append({
                    "timestamp": datetime.fromtimestamp(int(candle[0]) / 1000).strftime('%Y-%m-%d %H:%M:%S'),
                    "open": float(candle[1]),
                    "high": float(candle[2]),
                    "low": float(candle[3]),
                    "close": float(candle[4]),
                    "volume": float(candle[5])
                })

            write_echo(f"获取{bar}K线数据成功: {len(klines)}根")
            return klines

        except Exception as e:
            write_error(f"获取{bar}K线数据失败: {e}")
            # 返回模拟数据避免程序中断
            current_time = datetime.now()
            base_price = 3500.0

            # 根据时间间隔生成不同的模拟数据
            if bar == "5m":
                time_delta = timedelta(minutes=5)
            elif bar == "30m":
                time_delta = timedelta(minutes=30)
            elif bar == "2H":
                time_delta = timedelta(hours=2)
            elif bar == "1D":
                time_delta = timedelta(days=1)
            else:
                time_delta = timedelta(minutes=5)

            klines = []
            for i in range(limit, 0, -1):
                klines.append({
                    "timestamp": (current_time - i * time_delta).strftime('%Y-%m-%d %H:%M:%S'),
                    "open": base_price + i * 5,
                    "high": base_price + i * 5 + 20,
                    "low": base_price + i * 5 - 10,
                    "close": base_price + i * 5 + 8,
                    "volume": 1500.0 + i * 100
                })

            return klines

    def get_current_price(self, symbol: str = SYMBOL) -> float:
        """获取当前价格（随传入交易对切换）"""
        try:
            write_echo(f"请求当前价格: {symbol}")
            endpoint = "/api/v5/market/ticker"
            params = {'instId': symbol}
            data = self._make_request('GET', endpoint, params)
            price = float(data[0]['last'])
            write_echo(f"当前价格[{symbol}]: {price:.2f} USDT")
            return price
        except Exception as e:
            write_error(f"获取当前价格失败: {e}")
            write_echo("使用默认价格 3500.0 USDT")
            return 3500.0  # 默认价格

    def get_account_balance(self) -> Dict:
        """获取账户余额信息"""
        try:
            endpoint = "/api/v5/account/balance"
            data = self._make_request('GET', endpoint)

            if not data:
                raise Exception("账户数据为空")

            account_data = data[0]
            total_equity = float(account_data['totalEq']) if account_data.get('totalEq') else 0
            details = account_data['details'][0] if account_data.get('details') and len(
                account_data['details']) > 0 else {}
            available_balance = float(details.get('availEq', 0))

            return {
                "available_OKX": available_balance,
                "total_equity": total_equity
            }

        except Exception as e:
            write_error(f"获取账户余额失败: {e}")
            return {
                "available_OKX": 4.51,
                "total_equity": 4.52
            }

    def get_position_info(self, symbol: str = SYMBOL) -> Dict:
        """获取持仓信息"""
        try:
            endpoint = "/api/v5/account/positions"
            params = {'instId': symbol}
            data = self._make_request('GET', endpoint, params)

            position_data = {
                "position_side": "flat",
                "position_size": 0.0,
                "entry_price": 0.0,
                "leverage": LEVERAGE
            }

            if data and len(data) > 0:
                pos = data[0]
                pos_size = float(pos.get('pos', '0'))

                if pos_size > 0:
                    position_data["position_side"] = "long"
                    position_data["position_size"] = pos_size
                    position_data["entry_price"] = float(pos.get('avgPx', '0'))
                elif pos_size < 0:
                    position_data["position_side"] = "short"
                    position_data["position_size"] = abs(pos_size)
                    position_data["entry_price"] = float(pos.get('avgPx', '0'))

            return position_data

        except Exception as e:
            write_error(f"获取持仓信息失败: {e}")
            return {
                "position_side": "flat",
                "position_size": 0.0,
                "entry_price": 0.0,
                "leverage": LEVERAGE
            }

    def get_algo_orders(self, algo_id: str = None) -> List[Dict]:
        # 已移除交易相关接口：算法订单查询
        # 保留纯数据采集模式，不再访问交易/算法订单端点
        write_echo("算法订单接口已移除（纯AI/数据模式）")
        return []

    def get_pending_orders(self, symbol: str = SYMBOL) -> List[Dict]:
        # 已移除交易相关接口：挂单查询
        write_echo("挂单查询接口已移除（纯AI/数据模式）")
        return []

    def has_pending_orders_or_tpsl(self) -> bool:
        # 已移除交易相关接口：挂单/止盈止损检测
        write_echo("挂单/止盈止损检测已移除（纯AI/数据模式）")
        return False

    def cancel_algo_order(self, algo_id: str, inst_id: str = SYMBOL) -> bool:
        # 已移除交易相关接口：撤销算法订单
        write_echo("撤销算法订单接口已移除（纯AI/数据模式）")
        return False

    def cancel_all_algo_orders(self, inst_id: str = SYMBOL) -> bool:
        # 已移除交易相关接口：批量撤销算法订单
        write_echo("批量撤销算法订单接口已移除（纯AI/数据模式）")
        return False


# ==================== 模块2: AI输入模块 ====================
class DeepSeekAI:
    """DeepSeek AI交易决策"""

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://api.deepseek.com/v1/chat/completions"
        self.last_profit = 0.0  # 记录上次策略盈利

    def get_trading_decision(self, market_data: Dict, account_status: Dict, position_info: Dict, history: Optional[List[Dict]] = None, symbol: Optional[str] = None) -> Dict:
        """获取AI交易决策"""
        try:
            # 在AI请求前记录账户状态和持仓信息
            write_echo("=== AI请求账户状态 ===")
            write_echo(f"可用余额: {account_status['available_OKX']:.6f} USDT")
            write_echo(f"账户总权益: {account_status['total_equity']:.6f} USDT")
            write_echo(f"上次策略盈利: {self.last_profit:.6f} USDT")

            # 构建AI提示词 - 优化版模板（包含历史上下文）
            prompt = self._build_prompt(market_data, account_status, position_info, history)
            write_echo(f"构建AI提示词完成，长度: {len(prompt)} 字符")

            headers = {
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {self.api_key}'
            }

            # 优化的系统提示词 - 根据用户要求更新（随当前交易对同步）
            base_asset = (symbol or SYMBOL).split('-')[0]
            system_prompt = """角色定位：你是顶级交易员，专注于OKX交易所的{base_asset}永续合约交易，并且与其他交易员互相竞争
核心目标：在小资金实盘环境下，通过精准策略在激烈竞争中保持优势并实现稳定盈利
环境认知：
1. 充满顶级对手的高效合约市场
2. {base_asset}合约高波动性带来的机会与风险并存
3. 需要非同一般的环境适应性
4. 小资金实盘操作不需要太多风险控制，目的为盈利，风险控制在下单量中即可
5. 所有交易中杠杆倍数默认为50倍
6. 最小下单量{min_order_size}{base_asset}，最大下单量{max_order_size}{base_asset}
7. 除已提供的信息外，需要其他辅助面与技术面信息自行查询大量信息后决定，如特朗普与马斯克的推特账号等
8. 根据所有已掌握的信息与自行查询的信息如布林带，市场1小时K线图等进行开仓与止盈止损操作
9. 因为我每次交易前都为空仓，所以仅能进行一个方向的交易，我需要高频盈利，参考合约手续费的情况下，止盈不能少于50%，也就是当前价格+/-0.5%
10.当前交易策略为每次开仓时设置好止盈止损，在止盈或止损之前，不会进行任何平仓操作与浮盈加仓操作，需要仔细考虑止盈止损价格后进行开仓操作
11.看好机会之后执行操作，也就是以30分钟K线图与一小时K线图和波动性为主，进行小仓位翻盘操作，盈利撤出等操作
实时状态信息：
1. 账户状态
- 可用余额: {available_OKX} USDT
- 账户总权益: {total_equity} USDT
2. 上次策略的盈利为 {last_profit} USDT(亏损时为负数)
3. 策略框架
- 多时间维度分析(5m/30m/2h/1d)
- 链上数据与市场情绪结合
- 参数调整与风险控制
4. 风险管理
- 单次风险暴露不超过总资金的20%
- 总持仓风险不超过总资金的20%
- 实时监控策略衰减信号
- 保持策略多样性和快速切换能力
5. 执行要求
- 小资金仓位管理
- 明确盈利
基于以上信息和你通过联网查询了解到的所有信息，按照如下Json进行回显来进行实盘操作。
{{
  "trading_decision": {{
    "action": "hold",                        // 操作类型: open_long-开多仓, open_short-开空仓, hold-不开仓
    "confidence_level": "medium",            // 信心等级: high-高, medium-中, low-低
    "reason": ""  // 简要决策理由
  }},
  "position_management": {{
    "position_size": 0.1,                    // 建议持仓数量({base_asset})，0表示空仓
    "stop_loss_price": 3450.0,               // 建议止损价格(USDT)
    "take_profit_price": 3580.0              // 建议止盈价格(USDT)
  }}
}}"""

            # 格式化系统提示词（随账户与交易对动态填充）
            formatted_system_prompt = system_prompt.format(
                base_asset=base_asset,
                min_order_size=MIN_ORDER_SIZE,
                max_order_size=MAX_ORDER_SIZE,
                available_OKX=account_status.get("available_OKX", 0.0),
                total_equity=account_status.get("total_equity", 0.0),
                last_profit=self.last_profit
            )

            payload = {
                "model": "deepseek-chat",
                "messages": [
                    {
                        "role": "system",
                        "content": formatted_system_prompt
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                "temperature": 1,
                "max_tokens": 2000
            }
            # 记录实际发送到AI的系统提示词（已格式化，包含当前交易对）
            try:
                logger.info("DeepSeek系统提示词：%s", formatted_system_prompt)
            except Exception:
                pass
            try:
                write_echo(f"系统提示词(交易对): {base_asset}; 已格式化并发送")
            except Exception:
                pass
            write_echo("准备调用AI接口 deepseek-chat，温度: 1, max_tokens: 2000")
            ai_start = time.time()
            response = requests.post(self.base_url, headers=headers, json=payload, timeout=30)
            response.raise_for_status()
            result = response.json()
            ai_duration = time.time() - ai_start
            write_echo(f"AI响应耗时: {ai_duration:.2f}秒")
            ai_response = result['choices'][0]['message']['content']
            write_echo("AI原始响应接收成功")
            # 记录AI原始响应到回显文件以便调试
            write_echo(f"AI原始响应: {ai_response}")

            decision = self._parse_ai_response(ai_response)

            # 记录AI决策详细信息
            write_echo("=== AI交易决策 ===")
            write_echo(f"操作类型: {decision['trading_decision']['action']}")
            write_echo(f"信心等级: {decision['trading_decision']['confidence_level']}")
            write_echo(f"决策理由: {decision['trading_decision']['reason']}")
            try:
                cur_px = float(market_data.get('current_price', 0))
                sz_eth = float(decision['position_management']['position_size'])
                sz_usdt = sz_eth * cur_px if cur_px > 0 else 0.0
                write_echo(f"建议仓位: {sz_usdt:.2f} USDT")
            except Exception:
                write_echo(f"建议仓位(ETH): {decision['position_management']['position_size']:.6f} ETH")
            write_echo(f"建议止盈: {decision['position_management']['take_profit_price']:.2f} USDT")
            write_echo(f"建议止损: {decision['position_management']['stop_loss_price']:.2f} USDT")

            action = decision['trading_decision']['action']
            if action in ['open_long', 'open_short']:
                write_echo("📈 开仓信号")
            else:
                write_echo("⏸️ 保持空仓")

            return decision

        except Exception as e:
            write_error(f"AI决策获取失败: {e}")
            # 返回保守的持有决策
            return {
                "trading_decision": {
                    "action": "hold",
                    "confidence_level": "low",
                    "reason": f"AI处理失败: {str(e)}"
                },
                "position_management": {
                    "position_size": 0,
                    "stop_loss_price": 0,
                    "take_profit_price": 0
                }
            }

    def _build_prompt(self, market_data: Dict, account_status: Dict, position_info: Dict, history: Optional[List[Dict]] = None) -> str:
        """构建AI输入提示词 - 优化版模板（加入历史上下文）"""
        logger.info(history)
        try:
            write_echo(
                f"AI提示词包含: 当前价{market_data['current_price']:.2f}, "
                f"K线长度 5m={len(market_data['kline_5min'])}, 30m={len(market_data['kline_30min'])}, "
                f"2h={len(market_data['kline_2h'])}, 1d={len(market_data['kline_1d'])}"
            )
        except Exception:
            pass
        input_data = {
            "market_data": {
                "current_price": market_data["current_price"],
                "kline_5min": market_data["kline_5min"],
                "kline_30min": market_data["kline_30min"],
                "kline_2h": market_data["kline_2h"],
                "kline_1d": market_data["kline_1d"]
            },
            "account_status": {
                "available_OKX": account_status["available_OKX"],
                "total_equity": account_status["total_equity"],
                "last_profit": self.last_profit
            },
            "position_info": {
                "position_side": position_info["position_side"],
                "position_size": position_info["position_size"],
                "entry_price": position_info["entry_price"],
                "leverage": position_info["leverage"]
            },
            "decision_history": history or []
        }

        return json.dumps(input_data, indent=2, ensure_ascii=False)

    def _parse_ai_response(self, response: str) -> Dict:
        """解析AI响应 - 优化解析能力"""
        try:
            write_echo("开始解析AI响应")
            # 首先尝试直接解析整个响应
            try:
                decision = json.loads(response)
                if self._validate_decision_format(decision):
                    write_echo("直接解析JSON成功")
                    return decision
            except:
                pass

            # 如果直接解析失败，尝试提取符合我们模板的JSON部分
            pattern = r'\{\s*"trading_decision"\s*:\s*\{[^{}]*\},\s*"position_management"\s*:\s*\{[^{}]*\}\s*\}'
            matches = re.findall(pattern, response, re.DOTALL)

            for match in matches:
                try:
                    # 清理JSON字符串
                    json_str = match.replace('\n', ' ').replace('\t', ' ')
                    # 移除多余的空白字符
                    json_str = re.sub(r'\s+', ' ', json_str).strip()

                    decision = json.loads(json_str)
                    if self._validate_decision_format(decision):
                        write_echo("从响应中成功提取标准JSON决策")
                        return decision
                except Exception as e:
                    write_error(f"提取的JSON解析失败: {e}")
                    continue

            # 如果正则匹配失败，尝试手动构建标准格式
            write_echo("尝试手动构建标准格式决策")
            return self._build_standard_decision_from_response(response)

        except Exception as e:
            write_error(f"解析AI响应失败: {e}")
            # 返回默认的持有决策
            return {
                "trading_decision": {
                    "action": "hold",
                    "confidence_level": "low",
                    "reason": "AI响应解析失败，采用保守策略"
                },
                "position_management": {
                    "position_size": 0,
                    "stop_loss_price": 0,
                    "take_profit_price": 0
                }
            }

    def _build_standard_decision_from_response(self, response: str) -> Dict:
        """从AI响应中手动构建标准格式决策"""
        try:
            # 默认决策
            decision = {
                "trading_decision": {
                    "action": "hold",
                    "confidence_level": "medium",
                    "reason": ""
                },
                "position_management": {
                    "position_size": 0,
                    "stop_loss_price": 0,
                    "take_profit_price": 0
                }
            }

            # 尝试从响应中提取action
            action_patterns = [
                r'"action"\s*:\s*"(\w+)"',
                r'action["\']?\s*:\s*["\']?(\w+)',
                r'操作["\']?\s*:\s*["\']?(\w+)'
            ]

            for pattern in action_patterns:
                match = re.search(pattern, response, re.IGNORECASE)
                if match:
                    action = match.group(1).lower()
                    valid_actions = ["hold", "open_long", "open_short"]  # 移除了平仓操作
                    if action in valid_actions:
                        decision["trading_decision"]["action"] = action
                        break

            # 尝试提取reason
            reason_patterns = [
                r'"reason"\s*:\s*"([^"]*)"',
                r'reason["\']?\s*:\s*["\']?([^"\']+)',
                r'理由["\']?\s*:\s*["\']?([^"\']+)'
            ]

            for pattern in reason_patterns:
                match = re.search(pattern, response, re.IGNORECASE)
                if match:
                    reason = match.group(1).strip()
                    if reason:
                        decision["trading_decision"]["reason"] = reason
                        break

            # 如果没找到reason，使用默认值
            if not decision["trading_decision"]["reason"]:
                decision["trading_decision"]["reason"] = "基于多时间维度K线分析做出的决策"

            write_echo(f"手动构建决策: {decision['trading_decision']['action']}")
            return decision

        except Exception as e:
            write_error(f"手动构建决策失败: {e}")
            raise

    def _validate_decision_format(self, decision: Dict) -> bool:
        """验证决策格式是否符合模板"""
        try:
            # 检查必需字段是否存在
            if "trading_decision" not in decision or "position_management" not in decision:
                return False

            td = decision["trading_decision"]
            pm = decision["position_management"]

            if not all(field in td for field in ["action", "confidence_level", "reason"]):
                return False

            if not all(field in pm for field in ["position_size", "stop_loss_price", "take_profit_price"]):
                return False

            # 验证action值的有效性（移除了平仓操作）
            valid_actions = ["hold", "open_long", "open_short"]
            if td["action"] not in valid_actions:
                return False

            # 验证confidence_level值的有效性
            valid_confidences = ["high", "medium", "low"]
            if td["confidence_level"] not in valid_confidences:
                return False

            return True

        except:
            return False

    def update_profit(self, profit: float):
        """更新上次策略盈利"""
        self.last_profit = profit


# ==================== 模块4: 交易执行模块 ====================
class OKXTradingExecutor:
    """OKX交易执行器"""

    def __init__(self, data_collector: OKXDataCollector, ai_processor: DeepSeekAI):
        self.dc = data_collector
        self.ai = ai_processor
        self.current_tp_sl_orders = {}  # 存储当前止盈止损订单ID

    # ==================== 入场过滤与指标计算 ====================
    def _calc_ema_series(self, closes: List[float], period: int) -> List[float]:
        """计算EMA序列，返回与closes同长度的EMA列表（用于判断斜率与趋势）"""
        if not closes:
            return []
        k = 2 / (period + 1)
        ema_vals: List[float] = []
        ema = closes[0]
        for c in closes:
            ema = c * k + ema * (1 - k)
            ema_vals.append(ema)
        return ema_vals

    def _calc_atr(self, klines: List[Dict], period: int = 14) -> float:
        """基于K线计算ATR，默认14周期。K线需包含high/low/close"""
        if not klines:
            return 0.0
        highs = [k['high'] for k in klines]
        lows = [k['low'] for k in klines]
        closes = [k['close'] for k in klines]
        trs: List[float] = []
        prev_close = closes[0]
        for i in range(1, len(klines)):
            tr = max(highs[i] - lows[i], abs(highs[i] - prev_close), abs(lows[i] - prev_close))
            trs.append(tr)
            prev_close = closes[i]
        if not trs:
            return 0.0
        # 简化ATR：最近period内均值
        window = trs[-period:] if len(trs) >= period else trs
        return sum(window) / max(1, len(window))

    def _compute_filters(self, current_price: float) -> Dict:
        """获取30m/2h趋势与30m波动率，返回过滤用指标"""
        try:
            k30 = self.dc.get_kline_data(bar="30m", limit=60)
            k2h = self.dc.get_kline_data(bar="2H", limit=60)
        except Exception:
            k30, k2h = [], []

        closes30 = [k['close'] for k in k30]
        closes2h = [k['close'] for k in k2h]

        ema20_30_series = self._calc_ema_series(closes30, 20)
        ema50_30_series = self._calc_ema_series(closes30, 50)
        ema20_2h_series = self._calc_ema_series(closes2h, 20)
        ema50_2h_series = self._calc_ema_series(closes2h, 50)

        # 取最后与前一值判断斜率
        def last_two(vals: List[float]) -> tuple:
            if len(vals) >= 2:
                return vals[-1], vals[-2]
            elif len(vals) == 1:
                return vals[-1], vals[-1]
            else:
                return 0.0, 0.0

        ema20_30, ema20_30_prev = last_two(ema20_30_series)
        ema50_30, ema50_30_prev = last_two(ema50_30_series)
        ema20_2h, ema20_2h_prev = last_two(ema20_2h_series)
        ema50_2h, ema50_2h_prev = last_two(ema50_2h_series)

        slope20_30 = ema20_30 - ema20_30_prev
        slope50_30 = ema50_30 - ema50_30_prev
        slope20_2h = ema20_2h - ema20_2h_prev
        slope50_2h = ema50_2h - ema50_2h_prev

        bullish = (ema20_30 > ema50_30) and (ema20_2h > ema50_2h) and (slope20_30 > 0) and (slope20_2h >= 0)
        bearish = (ema20_30 < ema50_30) and (ema20_2h < ema50_2h) and (slope20_30 < 0) and (slope20_2h <= 0)

        atr30 = self._calc_atr(k30, 14)
        atr_ratio = atr30 / max(1e-9, current_price)

        return {
            'ema20_30': ema20_30,
            'ema50_30': ema50_30,
            'ema20_2h': ema20_2h,
            'ema50_2h': ema50_2h,
            'slope20_30': slope20_30,
            'slope20_2h': slope20_2h,
            'bullish': bullish,
            'bearish': bearish,
            'atr': atr30,
            'atr_ratio': atr_ratio
        }

    def _normalize_tpsl_by_atr(self, action: str, entry_price: float, decision: Dict, atr: float) -> tuple:
        """用ATR校正TP/SL，确保最小0.5%目标、合理RR（≥1.8）"""
        pm = (decision or {}).get('position_management', {})
        tp_price = float(pm.get('take_profit_price') or 0)
        sl_price = float(pm.get('stop_loss_price') or 0)

        # 基础SL距离：1.2*ATR
        sl_dist = max(atr * 1.2, 0.0001)
        min_tp_dist = max(atr * 1.8, entry_price * 0.005)  # 至少0.5%

        if action == 'open_long':
            # 默认值或不合理值则用ATR方案
            if sl_price <= 0 or sl_price >= entry_price:
                sl_price = entry_price - sl_dist
            if tp_price <= 0 or tp_price <= entry_price or (tp_price - entry_price) < 1.4 * (entry_price - sl_price):
                tp_price = entry_price + max(min_tp_dist, (entry_price - sl_price) * 1.8)
        else:  # open_short
            if sl_price <= 0 or sl_price <= entry_price:
                sl_price = entry_price + sl_dist
            if tp_price <= 0 or tp_price >= entry_price or (entry_price - tp_price) < 1.4 * (sl_price - entry_price):
                tp_price = entry_price - max(min_tp_dist, (sl_price - entry_price) * 1.8)

        return tp_price, sl_price

    def execute_trade(self, decision: Dict, current_price: float, is_test: bool = False) -> bool:
        """执行交易决策 - 优化版本，只处理开仓"""
        try:
            write_echo(f"当前价格: {current_price:.2f} USDT, 测试模式: {is_test}")
            action = decision["trading_decision"]["action"]
            position_size = decision["position_management"]["position_size"]

            # 低置信度过滤：置信度为low则不入场
            try:
                conf = str(decision["trading_decision"].get("confidence_level") or "").lower()
                if conf == 'low':
                    write_echo("触发过滤：置信度为low，保持空仓")
                    return True
            except Exception:
                pass

            # 如启用用户覆盖，则使用固定仓位
            try:
                if USER_OVERRIDE_ENABLED and USER_OVERRIDE_POSITION_SIZE is not None:
                    # 固定仓位以USDT金额填写，转换为ETH数量
                    usdt_amt = float(USER_OVERRIDE_POSITION_SIZE)
                    eth_size = (usdt_amt / max(1e-9, float(current_price)))
                    position_size = eth_size
                    write_echo(f"使用固定仓位(U本位): {usdt_amt:.2f} USDT -> {eth_size:.6f} ETH")
            except Exception as e:
                write_error(f"应用用户仓位覆盖失败: {e}")

            # 夹紧到允许范围，避免过小直接被置0导致不下单
            if position_size <= 0:
                position_size = 0
            else:
                position_size = max(MIN_ORDER_SIZE, min(position_size, MAX_ORDER_SIZE))

            write_echo(f"执行: {action}, 仓位: {position_size:.4f} ETH")

            if action == "hold":
                write_echo("保持空仓")
                return True

            elif action in ["open_long", "open_short"]:
                # 趋势与波动过滤：避免逆势与过度/不足波动区间入场
                filters = self._compute_filters(current_price)
                write_echo(
                    f"过滤指标: 30m EMA20={filters['ema20_30']:.2f}, EMA50={filters['ema50_30']:.2f}, "
                    f"2h EMA20={filters['ema20_2h']:.2f}, EMA50={filters['ema50_2h']:.2f}, ATR30={filters['atr']:.2f}, "
                    f"ATR/Price={filters['atr_ratio']:.4f}, bullish={filters['bullish']}, bearish={filters['bearish']}"
                )

                atr_ok = 0.0015 <= filters['atr_ratio'] <= 0.02  # 过窄易噪声，过宽风险过大
                if action == 'open_long':
                    entry_ok = filters['bullish'] and (current_price > filters['ema20_30']) and \
                               ((current_price - filters['ema20_30']) <= 2.0 * max(1e-9, filters['atr']))
                    if not (entry_ok and atr_ok):
                        write_echo("触发过滤：不满足多头趋势或波动率区间，保持空仓")
                        return True
                else:  # open_short
                    entry_ok = filters['bearish'] and (current_price < filters['ema20_30']) and \
                               ((filters['ema20_30'] - current_price) <= 2.0 * max(1e-9, filters['atr']))
                    if not (entry_ok and atr_ok):
                        write_echo("触发过滤：不满足空头趋势或波动率区间，保持空仓")
                        return True

                if position_size > 0:
                    success = self._place_order(action, position_size)
                    if success:
                        write_echo("✅ 开仓成功")
                        # 等待5秒后下止盈止损单
                        time.sleep(5)

                        # 获取实际的开仓价格
                        entry_price = self._get_entry_price_with_retry()
                        if entry_price is None:
                            write_error("无法获取开仓价格，使用当前价格")
                            entry_price = current_price

                        write_echo(f"实际开仓价格: {entry_price:.2f} USDT")

                        # 根据是否为测试模式选择止盈止损价格
                        if is_test:
                            # 测试模式使用固定±10逻辑
                            if action == "open_long":
                                tp_price = entry_price + 10  # 多单止盈：开仓价+10
                                sl_price = entry_price - 10  # 多单止损：开仓价-10
                            else:  # open_short
                                tp_price = entry_price - 10  # 空单止盈：开仓价-10
                                sl_price = entry_price + 10  # 空单止损：开仓价+10
                            write_echo(f"测试模式止盈止损: 止盈{tp_price:.2f}, 止损{sl_price:.2f}")
                        else:
                            # 优先采用AI建议，但用ATR做合理性校正（最小0.5%目标，RR≥1.8）
                            tp_price, sl_price = self._normalize_tpsl_by_atr(action, entry_price, decision, filters['atr'])
                            write_echo(f"ATR校正后TP/SL: 止盈{tp_price:.2f}, 止损{sl_price:.2f}")

                        # 验证止盈止损价格合理性
                        if action == "open_long":
                            if tp_price <= entry_price or sl_price >= entry_price:
                                write_error("止盈止损价格不合理，多单止盈应高于开仓价，止损应低于开仓价")
                                return False
                        else:  # open_short
                            if tp_price >= entry_price or sl_price <= entry_price:
                                write_error("止盈止损价格不合理，空单止盈应低于开仓价，止损应高于开仓价")
                                return False

                        tp_sl_success = self._place_tp_sl_orders_with_retry(
                            action.replace('open_', ''),  # 提取long或short
                            position_size,
                            tp_price,
                            sl_price
                        )
                        if tp_sl_success:
                            write_echo("✅ 止盈止损设置成功")
                        else:
                            write_error("❌ 止盈止损设置失败")
                    return success
                else:
                    write_echo("仓位为0，跳过开仓")
                    return True

            else:
                write_error(f"未知交易动作: {action}")
                return False

        except Exception as e:
            write_error(f"执行交易失败: {e}")
            return False

    def _get_entry_price_with_retry(self, max_retries: int = 5, wait_seconds: int = 2) -> float:
        """重试获取开仓价格"""
        for attempt in range(max_retries):
            try:
                position_info = self.dc.get_position_info()
                write_echo(
                    f"开仓价重试{attempt + 1}/{max_retries} - 持仓: side={position_info['position_side']}, "
                    f"size={position_info['position_size']}, entry={position_info['entry_price']}"
                )
                if position_info["position_size"] > 0 and position_info["entry_price"] > 0:
                    write_echo(f"获取到开仓价格: {position_info['entry_price']:.2f}")
                    return position_info["entry_price"]
                else:
                    write_echo(f"未获取到有效开仓价格，重试 {attempt + 1}/{max_retries}")
            except Exception as e:
                write_error(f"获取开仓价格失败 (尝试 {attempt + 1}): {e}")

            if attempt < max_retries - 1:
                time.sleep(wait_seconds)

        return None

    def _place_tp_sl_orders_with_retry(self, pos_side: str, eth_size: float, tp_price: float, sl_price: float,
                                       max_retries: int = 5) -> bool:
        """下止盈止损单并重试直到成功"""
        if pos_side == "flat" or eth_size <= 0:
            write_echo("无持仓或持仓为0，跳过止盈止损设置")
            return True

        for attempt in range(max_retries):
            try:
                write_echo(f"尝试设置止盈止损 (尝试 {attempt + 1}/{max_retries})")
                write_echo(f"止盈价格: {tp_price:.2f}, 止损价格: {sl_price:.2f}")

                algo_ids = self._place_tp_sl_order(pos_side, eth_size, tp_price, sl_price)
                write_echo(f"止盈止损返回AlgoIDs: {algo_ids}")

                if algo_ids:
                    # 存储订单ID
                    self.current_tp_sl_orders = algo_ids
                    write_echo(f"止盈止损设置成功: 止盈{tp_price:.2f}, 止损{sl_price:.2f}")

                    # 等待5秒后验证
                    time.sleep(5)

                    # 验证订单是否存在
                    if self._verify_tp_sl_orders_exist(algo_ids):
                        write_echo("✅ 止盈止损订单验证成功")
                        return True
                    else:
                        write_echo("止盈止损订单验证失败，准备重试")
                else:
                    write_error("止盈止损下单返回空结果")

            except Exception as e:
                write_error(f"止盈止损设置失败 (尝试 {attempt + 1}): {e}")

            # 如果不是最后一次尝试，等待后重试
            if attempt < max_retries - 1:
                write_echo("等待5秒后重试...")
                time.sleep(5)

        write_error("止盈止损设置达到最大重试次数，最终失败")
        return False

    def _verify_tp_sl_orders_exist(self, algo_ids: Dict) -> bool:
        """验证止盈止损订单是否存在"""
        try:
            algo_orders = self.dc.get_algo_orders()

            tp_exists = any(order['algoId'] == algo_ids['tp_algo_id'] for order in algo_orders)
            sl_exists = any(order['algoId'] == algo_ids['sl_algo_id'] for order in algo_orders)

            write_echo(f"止盈单存在: {tp_exists}, 止损单存在: {sl_exists}")
            return tp_exists and sl_exists

        except Exception as e:
            write_error(f"验证止盈止损订单失败: {e}")
            return False

    def _cancel_current_tp_sl_orders(self):
        """撤销当前止盈止损订单"""
        try:
            if self.current_tp_sl_orders:
                write_echo("撤销当前止盈止损订单...")
                for algo_id in self.current_tp_sl_orders.values():
                    self.dc.cancel_algo_order(algo_id)
                self.current_tp_sl_orders = {}
                write_echo("止盈止损订单撤销成功")
        except Exception as e:
            write_error(f"撤销止盈止损订单失败: {e}")

    def _place_tp_sl_order(self, pos_side: str, eth_size: float, tp_price: float, sl_price: float) -> Dict:
        """下止盈止损单"""
        try:
            endpoint = "/api/v5/trade/order-algo"

            # 确定止盈止损方向
            if pos_side == "long":
                # 多单：止损是卖出，止盈也是卖出
                tp_params = {
                    'instId': SYMBOL,
                    'tdMode': 'cross',
                    'side': 'sell',
                    'ordType': 'conditional',
                    'sz': self._convert_eth_to_contracts(eth_size),
                    'tpTriggerPx': str(tp_price),
                    'tpOrdPx': '-1',  # -1表示市价
                    'posSide': 'long'
                }

                sl_params = {
                    'instId': SYMBOL,
                    'tdMode': 'cross',
                    'side': 'sell',
                    'ordType': 'conditional',
                    'sz': self._convert_eth_to_contracts(eth_size),
                    'slTriggerPx': str(sl_price),
                    'slOrdPx': '-1',  # -1表示市价
                    'posSide': 'long'
                }

            elif pos_side == "short":
                # 空单：止损是买入，止盈也是买入
                tp_params = {
                    'instId': SYMBOL,
                    'tdMode': 'cross',
                    'side': 'buy',
                    'ordType': 'conditional',
                    'sz': self._convert_eth_to_contracts(eth_size),
                    'tpTriggerPx': str(tp_price),
                    'tpOrdPx': '-1',  # -1表示市价
                    'posSide': 'short'
                }

                sl_params = {
                    'instId': SYMBOL,
                    'tdMode': 'cross',
                    'side': 'buy',
                    'ordType': 'conditional',
                    'sz': self._convert_eth_to_contracts(eth_size),
                    'slTriggerPx': str(sl_price),
                    'slOrdPx': '-1',  # -1表示市价
                    'posSide': 'short'
                }
            else:
                raise ValueError(f"无效的持仓方向: {pos_side}")

            write_echo(f"止盈单参数: {tp_params}")
            write_echo(f"止损单参数: {sl_params}")

            # 下止盈单
            tp_result = self.dc._make_request('POST', endpoint, tp_params)
            tp_algo_id = tp_result[0]['algoId']
            write_echo(f"止盈单下单成功, AlgoID: {tp_algo_id}")
            try:
                write_echo(f"止盈下单返回: {json.dumps(tp_result, ensure_ascii=False)}")
            except Exception:
                write_echo(f"止盈下单返回(字符串): {str(tp_result)}")

            # 下止损单
            sl_result = self.dc._make_request('POST', endpoint, sl_params)
            sl_algo_id = sl_result[0]['algoId']
            write_echo(f"止损单下单成功, AlgoID: {sl_algo_id}")
            try:
                write_echo(f"止损下单返回: {json.dumps(sl_result, ensure_ascii=False)}")
            except Exception:
                write_echo(f"止损下单返回(字符串): {str(sl_result)}")

            return {
                'tp_algo_id': tp_algo_id,
                'sl_algo_id': sl_algo_id
            }

        except Exception as e:
            write_error(f"下止盈止损单失败: {e}")
            raise

    def _place_order(self, action: str, eth_size: float) -> bool:
        """下单 - 修复版本"""
        try:
            endpoint = "/api/v5/trade/order"

            # 确定买卖方向
            if action == "open_long":
                side = "buy"
                posSide = "long"
            elif action == "open_short":
                side = "sell"
                posSide = "short"
            else:
                raise ValueError(f"无效的开仓动作: {action}")

            # 将ETH数量转换为张数 (合约面值ctVal=0.1)
            contract_size = self._convert_eth_to_contracts(eth_size)
            write_echo(f"准备下单: {action} {eth_size} ETH ({contract_size}张)")

            params = {
                'instId': SYMBOL,
                'tdMode': 'cross',
                'side': side,
                'ordType': 'market',
                'sz': str(contract_size),
                'lever': str(LEVERAGE),
                'posSide': posSide  # 关键修复：添加持仓方向参数
            }

            write_echo(f"下单参数: {params}")
            result = self.dc._make_request('POST', endpoint, params)
            try:
                write_echo(f"下单返回: {json.dumps(result, ensure_ascii=False)}")
            except Exception:
                write_echo(f"下单返回(字符串): {str(result)}")
            write_echo(f"下单成功: {side} {posSide} {eth_size} ETH ({contract_size}张)")
            return True

        except Exception as e:
            write_error(f"下单失败: {e}")
            # 特定错误处理
            if "insufficient" in str(e).lower():
                write_error("可能原因：账户余额不足")
            elif "posSide" in str(e).lower():
                write_error("可能原因：持仓模式与posSide参数不匹配")
            elif "51000" in str(e):
                write_error("明确错误：posSide参数错误，请检查持仓模式设置")
            return False

    def _close_position(self, action: str) -> bool:
        """平仓 - 仅用于测试"""
        try:
            position_info = self.dc.get_position_info()

            if position_info["position_size"] == 0:
                write_echo("无持仓可平")
                return True

            endpoint = "/api/v5/trade/order"

            # 根据平仓动作确定方向
            if action == "close_long":  # 平多仓
                side = "sell"
                posSide = "long"
            elif action == "close_short":  # 平空仓
                side = "buy"
                posSide = "short"
            else:
                raise ValueError(f"无效的平仓动作: {action}")

            # 将持仓的ETH数量转换为张数
            contract_size = self._convert_eth_to_contracts(position_info["position_size"])

            params = {
                'instId': SYMBOL,
                'tdMode': 'cross',
                'side': side,
                'ordType': 'market',
                'sz': str(contract_size),
                'posSide': posSide  # 关键修复：添加持仓方向参数
            }

            write_echo(f"平仓参数: {params}")
            result = self.dc._make_request('POST', endpoint, params)
            try:
                write_echo(f"平仓返回: {json.dumps(result, ensure_ascii=False)}")
            except Exception:
                write_echo(f"平仓返回(字符串): {str(result)}")
            write_echo(f"平仓成功: {side} {posSide} {position_info['position_size']} ETH ({contract_size}张)")
            return True

        except Exception as e:
            write_error(f"平仓失败: {e}")
            return False

    def _convert_eth_to_contracts(self, eth_size: float) -> str:
        """
        将ETH数量转换为合约张数
        根据诊断结果，合约面值ctVal=0.1，所以1张=0.1 ETH
        最小下单数量minSz=0.01张
        """
        CONTRACT_VALUE = 0.1  # 每张合约代表的ETH数量
        MIN_CONTRACT_SIZE = 0.01  # 最小下单张数

        # 计算张数
        contracts = eth_size / CONTRACT_VALUE

        # 验证是否满足最小下单要求
        if contracts < MIN_CONTRACT_SIZE:
            raise ValueError(f"转换后的张数({contracts:.4f})小于最小要求({MIN_CONTRACT_SIZE})")

        # 格式化为字符串，保留小数点后2位（因为最小精度是0.01）
        return f"{contracts:.2f}"

    def test_trading_module(self) -> bool:
        """测试交易模块 - 修复版本，包含止盈止损测试"""
        try:
            write_echo("=== 开始交易模块测试 ===")

            # 3.1 测试开多单
            write_echo("3.1 测试开多单...")
            success = self._place_order("open_long", MIN_ORDER_SIZE)
            if not success:
                write_error("开多单测试失败")
                return False
            write_echo("开多单成功")
            time.sleep(3)

            # 3.1.2 测试多单止盈止损模块
            write_echo("3.1.2 测试多单止盈止损模块...")

            # 获取实际的开仓价格
            entry_price = self._get_entry_price_with_retry()
            if entry_price is None:
                # 如果无法获取开仓价格，使用当前价格
                current_price = self.dc.get_current_price()
                entry_price = current_price
                write_echo(f"使用当前价格作为开仓价格: {entry_price:.2f} USDT")
            else:
                write_echo(f"实际开仓价格: {entry_price:.2f} USDT")

            # 多单：止盈 = 开仓价+10，止损 = 开仓价-10
            tp_price = entry_price + 10
            sl_price = entry_price - 10

            write_echo(f"多单止盈止损设置: 止盈{tp_price:.2f}, 止损{sl_price:.2f}")

            tp_sl_success = self._place_tp_sl_orders_with_retry("long", MIN_ORDER_SIZE, tp_price, sl_price)
            if not tp_sl_success:
                write_error("多单止盈止损测试失败")
                return False
            write_echo("多单止盈止损设置成功")
            time.sleep(3)

            # 3.1.3 测试多单止盈止损模块，撤回当前多单止盈止损单
            write_echo("3.1.3 撤回多单止盈止损单...")
            self._cancel_current_tp_sl_orders()
            write_echo("多单止盈止损单撤回成功")

            # 3.2 测试平多单
            write_echo("3.2 测试平多单...")
            success = self._close_position("close_long")
            if not success:
                write_error("平多单测试失败")
                return False
            write_echo("平多单成功")
            time.sleep(3)

            # 3.3 测试开空单
            write_echo("3.3 测试开空单...")
            success = self._place_order("open_short", MIN_ORDER_SIZE)
            if not success:
                write_error("开空单测试失败")
                return False
            write_echo("开空单成功")
            time.sleep(3)

            # 3.3.2 测试空单止盈止损模块
            write_echo("3.3.2 测试空单止盈止损模块...")

            # 获取实际的开仓价格
            entry_price = self._get_entry_price_with_retry()
            if entry_price is None:
                # 如果无法获取开仓价格，使用当前价格
                current_price = self.dc.get_current_price()
                entry_price = current_price
                write_echo(f"使用当前价格作为开仓价格: {entry_price:.2f} USDT")
            else:
                write_echo(f"实际开仓价格: {entry_price:.2f} USDT")

            # 空单：止盈 = 开仓价-10，止损 = 开仓价+10
            tp_price = entry_price - 10
            sl_price = entry_price + 10

            write_echo(f"空单止盈止损设置: 止盈{tp_price:.2f}, 止损{sl_price:.2f}")

            tp_sl_success = self._place_tp_sl_orders_with_retry("short", MIN_ORDER_SIZE, tp_price, sl_price)
            if not tp_sl_success:
                write_error("空单止盈止损测试失败")
                return False
            write_echo("空单止盈止损设置成功")
            time.sleep(3)

            # 3.3.3 测试空单止盈止损模块，撤回当前空单止盈止损单
            write_echo("3.3.3 撤回空单止盈止损单...")
            self._cancel_current_tp_sl_orders()
            write_echo("空单止盈止损单撤回成功")

            # 3.4 测试平空单
            write_echo("3.4 测试平空单...")
            success = self._close_position("close_short")
            if not success:
                write_error("平空单测试失败")
                return False
            write_echo("平空单成功")

            write_echo("✅ 交易模块测试全部通过")
            return True

        except Exception as e:
            write_error(f"交易模块测试失败: {e}")
            return False


# ==================== 测试流程 ====================
class TradingBotTester:
    """交易机器人测试器"""

    def __init__(self, data_collector: OKXDataCollector, ai_processor: DeepSeekAI,
                 trading_executor: OKXTradingExecutor):
        self.dc = data_collector
        self.ai = ai_processor
        self.executor = trading_executor

    def run_full_test(self) -> bool:
        """运行完整测试流程"""
        try:
            write_echo("=== 开始完整测试流程 ===")

            # 1. 测试信息收集模块
            write_echo("1. 测试信息收集模块...")
            success = self.test_data_collection()
            if not success:
                write_error("信息收集模块测试失败")
                return False
            write_echo("1信息收集模块运行正常")

            # 2. 测试AI输入输出模块
            write_echo("2. 测试AI输入输出模块...")
            success = self.test_ai_module()
            if not success:
                write_error("AI输入输出模块测试失败")
                return False

            # 3. 测试交易模块（如果jymkcs为True）
            if jymkcs:
                write_echo("3. 测试交易模块...")
                success = self.executor.test_trading_module()
                if not success:
                    write_error("交易模块测试失败")
                    return False

            write_echo("✅ 所有测试通过，进入正式交易")
            return True

        except Exception as e:
            write_error(f"完整测试流程失败: {e}")
            return False

    def test_data_collection(self) -> bool:
        """测试信息收集模块"""
        try:
            # 测试K线数据获取
            klines_5min = self.dc.get_kline_data(bar="5m")
            klines_30min = self.dc.get_kline_data(bar="30m")
            klines_2h = self.dc.get_kline_data(bar="2H")
            klines_1d = self.dc.get_kline_data(bar="1D")

            if not klines_5min or len(klines_5min) == 0:
                write_error("5分钟K线数据获取失败")
                return False
            if not klines_30min or len(klines_30min) == 0:
                write_error("30分钟K线数据获取失败")
                return False
            if not klines_2h or len(klines_2h) == 0:
                write_error("2小时K线数据获取失败")
                return False
            if not klines_1d or len(klines_1d) == 0:
                write_error("日K线数据获取失败")
                return False

            # 测试账户余额获取
            balance = self.dc.get_account_balance()
            if balance["available_OKX"] == 0 and balance["total_equity"] == 0:
                write_error("账户余额获取失败")
                return False

            # 测试持仓信息获取
            position = self.dc.get_position_info()
            if position is None:
                write_error("持仓信息获取失败")
                return False

            write_echo("信息收集模块测试成功")
            return True

        except Exception as e:
            write_error(f"信息收集模块测试失败: {e}")
            return False

    def test_ai_module(self) -> bool:
        """测试AI输入输出模块"""
        try:
            # 获取测试数据
            klines_5min = self.dc.get_kline_data(bar="5m")
            klines_30min = self.dc.get_kline_data(bar="30m")
            klines_2h = self.dc.get_kline_data(bar="2H")
            klines_1d = self.dc.get_kline_data(bar="1D")
            current_price = klines_5min[0]['close'] if klines_5min else 0

            market_data = {
                "current_price": current_price,
                "kline_5min": klines_5min,
                "kline_30min": klines_30min,
                "kline_2h": klines_2h,
                "kline_1d": klines_1d
            }

            account_status = self.dc.get_account_balance()
            position_info = self.dc.get_position_info()

            # 记录AI输入
            write_echo("=== AI输入数据 ===")
            input_data = {
                "market_data": market_data,
                "account_status": account_status,
                "position_info": position_info
            }
            write_echo(json.dumps(input_data, indent=2, ensure_ascii=False))

            # 获取AI决策
            ai_decision = self.ai.get_trading_decision(market_data, account_status, position_info)

            # 记录AI输出
            write_echo("=== AI输出数据 ===")
            write_echo(json.dumps(ai_decision, indent=2, ensure_ascii=False))

            write_echo("AI输入输出模块测试成功")
            return True

        except Exception as e:
            write_error(f"AI输入输出模块测试失败: {e}")
            return False


# ==================== 主程序 ====================
class ETHTradingBot:
    """ETH交易机器人主程序"""

    def __init__(self):
        self.data_collector = OKXDataCollector(OKX_API_KEY, OKX_SECRET, OKX_PASSWORD)
        self.ai_processor = DeepSeekAI(DEEPSEEK_API_KEY)
        write_echo("交易机器人初始化完成（纯AI/数据模式）")

    def run_tests(self) -> bool:
        """运行测试流程（已简化为跳过交易模块）"""
        write_echo("跳过交易模块测试，直接进入AI决策循环")
        return True

    def run_dynamic_cycle(self):
        """执行动态交易周期"""
        try:
            write_echo("开始动态AI决策周期")

            # 1. 收集市场数据
            klines_5min = self.data_collector.get_kline_data(bar="5m", limit=6)
            klines_30min = self.data_collector.get_kline_data(bar="30m", limit=6)
            klines_2h = self.data_collector.get_kline_data(bar="2H", limit=6)
            klines_1d = self.data_collector.get_kline_data(bar="1D", limit=6)
            current_price = self.data_collector.get_current_price()

            market_data = {
                "current_price": current_price,
                "kline_5min": klines_5min,
                "kline_30min": klines_30min,
                "kline_2h": klines_2h,
                "kline_1d": klines_1d
            }

            write_echo(f"当前价格: {current_price:.2f} USDT")
            write_echo(
                f"收集K线数据: 5min×{len(klines_5min)}, 30min×{len(klines_30min)}, 2h×{len(klines_2h)}, 1d×{len(klines_1d)}")

            # 2. 获取账户状态
            account_status = self.data_collector.get_account_balance()

            # 3. 获取持仓信息
            position_info = self.data_collector.get_position_info()

            # 4. AI决策
            ai_decision = self.ai_processor.get_trading_decision(
                market_data, account_status, position_info
            )
            write_echo("=== AI决策输出 ===")
            write_echo(json.dumps(ai_decision, indent=2, ensure_ascii=False))

            # 5. 根据交易模式决定是否执行交易
            try:
                mode = TRADING_MODE
            except Exception:
                mode = 'simulation'

            if str(mode).lower() == 'live':
                write_echo("交易模式=live，尝试执行交易")
                try:
                    ok = self.trading_executor.execute_trade(ai_decision, current_price, is_test=False)
                    if ok:
                        write_echo("交易执行完成")
                    else:
                        write_echo("交易未执行或失败")
                except Exception as e:
                    write_error(f"执行交易失败: {e}")
            else:
                write_echo("交易模式为 simulation（仿真），本周期不下单")

            write_echo("AI决策周期完成")
            return AI_FREQUENCY  # 返回频率后再次检查

        except Exception as e:
            write_error(f"动态交易周期执行失败: {e}")
            return AI_FREQUENCY  # 出错时返回正常频率

    def run_continuously(self):
        """持续运行 - 动态版本"""
        write_echo("开始动态运行（仅AI决策，不下单）")

        while True:
            try:
                # 执行动态周期并获取下次检查间隔
                next_interval = self.run_dynamic_cycle()

                write_echo(f"等待 {next_interval} 秒后继续检查")
                time.sleep(next_interval)

            except KeyboardInterrupt:
                write_echo("程序被用户中断")
                break
            except Exception as e:
                write_error(f"主循环异常: {e}")
                write_echo("30秒后重试...")
                time.sleep(30)


if __name__ == "__main__":
    bot = ETHTradingBot()

    write_echo("=== 策略程序启动 ===")
    write_echo(f"交易对: {SYMBOL}")
    write_echo(f"杠杆: {LEVERAGE}倍")
    write_echo(f"AI决策频率: {AI_FREQUENCY}秒")

    # 直接进入AI决策循环

    bot.run_continuously()
