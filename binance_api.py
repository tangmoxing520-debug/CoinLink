"""
币安API安全封装模块
提供安全的币安合约交易API调用，包含签名、错误处理、重试机制
"""
import hmac
import hashlib
import time
import requests
import logging
from typing import Dict, Optional, Tuple
from datetime import datetime
import urllib3
import math

from config import (
    BINANCE_FUTURES_API_URL, BINANCE_API_KEY, BINANCE_SECRET_KEY,
    VERIFY_SSL, PROXY_ENABLED, PROXY_URL, REQUEST_TIMEOUT
)


class BinanceAPIError(Exception):
    """币安API错误"""
    def __init__(self, message: str, code: int = None, response: Dict = None):
        self.message = message
        self.code = code
        self.response = response
        super().__init__(self.message)


class BinanceAPIClient:
    """币安API客户端 - 安全封装"""
    
    def __init__(self, api_key: str = None, secret_key: str = None):
        self.api_key = api_key or BINANCE_API_KEY
        self.secret_key = secret_key or BINANCE_SECRET_KEY
        self.base_url = BINANCE_FUTURES_API_URL
        
        # 网络配置
        self.verify_ssl = VERIFY_SSL
        self.proxy_enabled = PROXY_ENABLED
        self.proxy_url = PROXY_URL
        self.timeout = REQUEST_TIMEOUT

        # 仅当用户显式关闭 SSL 验证时才禁用告警
        if not self.verify_ssl:
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        
        # 创建会话
        self.session = requests.Session()
        if self.proxy_enabled and self.proxy_url:
            self.session.proxies = {
                'http': self.proxy_url,
                'https': self.proxy_url
            }
        
        self.session.headers.update({
            'X-MBX-APIKEY': self.api_key,
            'Content-Type': 'application/json'
        })
        
        # 重试配置
        self.max_retries = 3
        self.retry_delay = 1  # 秒

        # exchangeInfo 缓存（用于数量精度/stepSize 校验）
        self._exchange_info_cache: Optional[Dict] = None
        self._exchange_info_cache_time: float = 0.0
        self._exchange_info_ttl_seconds: int = 300
        
        # 验证API密钥
        if self.api_key and self.secret_key:
            if not self._validate_api_keys():
                raise BinanceAPIError("API密钥验证失败，请检查config.env中的配置")
    
    def _validate_api_keys(self) -> bool:
        """验证API密钥是否有效"""
        try:
            # 尝试获取账户信息
            account = self.get_account()
            return account is not None
        except Exception as e:
            logging.warning(f"API密钥验证失败: {e}")
            return False
    
    def _generate_signature(self, params: Dict) -> str:
        """生成API签名"""
        query_string = '&'.join([f"{k}={v}" for k, v in sorted(params.items())])
        signature = hmac.new(
            self.secret_key.encode('utf-8'),
            query_string.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        return signature
    
    def _make_request(
        self,
        method: str,
        endpoint: str,
        params: Dict = None,
        signed: bool = False,
        retry: bool = True
    ) -> Dict:
        """
        发送API请求（带重试机制）
        
        Args:
            method: HTTP方法 (GET/POST/DELETE)
            endpoint: API端点
            params: 请求参数
            signed: 是否需要签名
            retry: 是否重试
            
        Returns:
            API响应数据
        """
        if params is None:
            params = {}
        
        url = f"{self.base_url}/{endpoint}"
        
        # 添加时间戳（签名请求需要）
        if signed:
            # recvWindow 防止时间漂移导致 -1021
            params.setdefault('recvWindow', 5000)
            params['timestamp'] = int(time.time() * 1000)
            params['signature'] = self._generate_signature(params)
        
        last_error = None
        for attempt in range(self.max_retries if retry else 1):
            try:
                if method.upper() == 'GET':
                    response = self.session.get(
                        url,
                        params=params,
                        timeout=self.timeout,
                        verify=self.verify_ssl
                    )
                elif method.upper() == 'POST':
                    response = self.session.post(
                        url,
                        params=params,
                        timeout=self.timeout,
                        verify=self.verify_ssl
                    )
                elif method.upper() == 'DELETE':
                    response = self.session.delete(
                        url,
                        params=params,
                        timeout=self.timeout,
                        verify=self.verify_ssl
                    )
                else:
                    raise ValueError(f"不支持的HTTP方法: {method}")
                
                # 检查响应状态
                if 200 <= response.status_code < 300:
                    data = response.json() if response.text else {}
                    # 检查币安API错误码
                    if isinstance(data, dict) and 'code' in data and data['code'] != 200:
                        raise BinanceAPIError(
                            data.get('msg', 'API错误'),
                            code=data.get('code'),
                            response=data
                        )
                    return data
                else:
                    error_data = response.json() if response.text else {}
                    raise BinanceAPIError(
                        f"HTTP {response.status_code}: {error_data.get('msg', response.text)}",
                        code=response.status_code,
                        response=error_data
                    )
                    
            except requests.exceptions.Timeout:
                last_error = f"请求超时 (尝试 {attempt + 1}/{self.max_retries})"
                if attempt < self.max_retries - 1:
                    time.sleep(self.retry_delay * (attempt + 1))
                    continue
                    
            except requests.exceptions.ConnectionError as e:
                last_error = f"连接错误: {e} (尝试 {attempt + 1}/{self.max_retries})"
                if attempt < self.max_retries - 1:
                    time.sleep(self.retry_delay * (attempt + 1))
                    continue
                    
            except BinanceAPIError:
                raise  # 币安API错误不重试
                
            except Exception as e:
                last_error = f"请求失败: {e} (尝试 {attempt + 1}/{self.max_retries})"
                if attempt < self.max_retries - 1:
                    time.sleep(self.retry_delay * (attempt + 1))
                    continue
        
        # 所有重试都失败
        raise BinanceAPIError(f"请求失败: {last_error}")
    
    # ========== 账户相关API ==========
    
    def get_account(self) -> Dict:
        """获取账户信息"""
        return self._make_request('GET', 'account', signed=True)
    
    def get_balance(self) -> float:
        """获取USDT余额"""
        try:
            account = self.get_account()
            for asset in account.get('assets', []):
                if asset['asset'] == 'USDT':
                    return float(asset['availableBalance'])
            return 0.0
        except Exception as e:
            logging.error(f"获取余额失败: {e}")
            return 0.0
    
    def get_position(self, symbol: str) -> Optional[Dict]:
        """获取持仓信息"""
        try:
            positions = self._make_request('GET', 'positionRisk', {'symbol': symbol}, signed=True)
            for pos in positions:
                if pos['symbol'] == symbol and float(pos['positionAmt']) != 0:
                    return pos
            return None
        except Exception as e:
            logging.error(f"获取持仓失败 {symbol}: {e}")
            return None

    def get_all_positions(self) -> list:
        """获取所有持仓（非零仓位）"""
        try:
            positions = self._make_request('GET', 'positionRisk', params={}, signed=True)
            if not isinstance(positions, list):
                return []
            out = []
            for pos in positions:
                try:
                    amt = float(pos.get('positionAmt', 0) or 0)
                    if amt != 0:
                        out.append(pos)
                except Exception:
                    continue
            return out
        except Exception as e:
            logging.error(f"获取全量持仓失败: {e}")
            return []
    
    # ========== 交易相关API ==========
    
    def set_leverage(self, symbol: str, leverage: int) -> bool:
        """设置杠杆倍数"""
        try:
            params = {
                'symbol': symbol,
                'leverage': leverage
            }
            result = self._make_request('POST', 'leverage', params, signed=True)
            logging.info(f"✅ 设置杠杆: {symbol} {leverage}x")
            return True
        except Exception as e:
            logging.error(f"❌ 设置杠杆失败 {symbol}: {e}")
            return False
    
    def set_margin_type(self, symbol: str, margin_type: str = 'ISOLATED') -> bool:
        """设置保证金模式 (ISOLATED=逐仓, CROSSED=全仓)"""
        try:
            params = {
                'symbol': symbol,
                'marginType': margin_type
            }
            result = self._make_request('POST', 'marginType', params, signed=True)
            logging.info(f"✅ 设置保证金模式: {symbol} {margin_type}")
            return True
        except Exception as e:
            # 如果已经设置过，会返回错误，这是正常的
            if 'No need to change margin type' in str(e):
                logging.info(f"ℹ️ 保证金模式已设置: {symbol} {margin_type}")
                return True
            logging.warning(f"⚠️ 设置保证金模式失败 {symbol}: {e}")
            return False
    
    def place_order(
        self,
        symbol: str,
        side: str,  # BUY or SELL
        order_type: str,  # MARKET, LIMIT
        quantity: float = None,
        price: float = None,
        reduce_only: bool = False,
        close_position: bool = False,
        client_order_id: str = None
    ) -> Dict:
        """
        下单
        
        Args:
            symbol: 交易对
            side: 方向 (BUY/SELL)
            order_type: 订单类型 (MARKET/LIMIT)
            quantity: 数量
            price: 价格 (限价单需要)
            reduce_only: 只减仓
            close_position: 平仓
            
        Returns:
            订单信息
        """
        params = {
            'symbol': symbol,
            'side': side,
            'type': order_type,
            'newOrderRespType': 'RESULT'  # 返回完整订单信息
        }

        # 幂等：使用 client order id（避免网络抖动导致重复下单）
        if client_order_id:
            params['newClientOrderId'] = str(client_order_id)
        
        if close_position:
            params['closePosition'] = 'true'
        else:
            if quantity is None:
                raise ValueError("quantity不能为空（除非closePosition=true）")
            params['quantity'] = quantity
        
        if order_type == 'LIMIT':
            if price is None:
                raise ValueError("限价单需要price参数")
            params['price'] = price
            params['timeInForce'] = 'GTC'  # Good Till Cancel
        
        if reduce_only:
            params['reduceOnly'] = 'true'
        
        try:
            result = self._make_request('POST', 'order', params, signed=True)
            logging.info(f"✅ 下单成功: {symbol} {side} {order_type} {quantity or 'CLOSE'}")
            return result
        except BinanceAPIError as e:
            # 幂等：如果是 clientOrderId 重复，则返回已存在订单
            try:
                msg = (e.message or "").lower()
                if client_order_id and ("duplicate" in msg or "clientorderid" in msg or "newclientorderid" in msg):
                    existing = self.get_order_by_client_order_id(symbol, client_order_id)
                    logging.warning(f"⚠️ clientOrderId 重复，返回已存在订单: {symbol} {client_order_id}")
                    return existing
            except Exception:
                pass
            logging.error(f"❌ 下单失败 {symbol}: {e.message}")
            raise
    
    def cancel_order(self, symbol: str, order_id: int) -> Dict:
        """取消订单"""
        params = {
            'symbol': symbol,
            'orderId': order_id
        }
        return self._make_request('DELETE', 'order', params, signed=True)
    
    def get_order(self, symbol: str, order_id: int) -> Dict:
        """查询订单状态"""
        params = {
            'symbol': symbol,
            'orderId': order_id
        }
        return self._make_request('GET', 'order', params, signed=True)

    def get_order_by_client_order_id(self, symbol: str, client_order_id: str) -> Dict:
        """通过 clientOrderId 查询订单（用于幂等/重试场景）"""
        params = {
            'symbol': symbol,
            'origClientOrderId': str(client_order_id)
        }
        return self._make_request('GET', 'order', params, signed=True)
    
    def get_open_orders(self, symbol: str = None) -> list:
        """获取当前挂单"""
        params = {}
        if symbol:
            params['symbol'] = symbol
        return self._make_request('GET', 'openOrders', params, signed=True)
    
    # ========== 市场数据API ==========
    
    def get_ticker_price(self, symbol: str) -> Optional[float]:
        """获取当前价格"""
        try:
            params = {'symbol': symbol}
            data = self._make_request('GET', 'ticker/price', params, signed=False)
            return float(data['price'])
        except Exception as e:
            logging.error(f"获取价格失败 {symbol}: {e}")
            return None
    
    def get_klines(
        self,
        symbol: str,
        interval: str = '15m',
        limit: int = 50,
        start_time: int = None,
        end_time: int = None
    ) -> list:
        """获取K线数据"""
        params = {
            'symbol': symbol,
            'interval': interval,
            'limit': limit
        }
        if start_time:
            params['startTime'] = start_time
        if end_time:
            params['endTime'] = end_time
        
        return self._make_request('GET', 'klines', params, signed=False)

    def get_exchange_info(self, use_cache: bool = True) -> Dict:
        """
        获取合约交易对规则（用于 stepSize / minQty 等）
        Binance Futures: /fapi/v1/exchangeInfo
        """
        now = time.time()
        if use_cache and self._exchange_info_cache and (now - self._exchange_info_cache_time) < self._exchange_info_ttl_seconds:
            return self._exchange_info_cache
        data = self._make_request('GET', 'exchangeInfo', params={}, signed=False, retry=True)
        if isinstance(data, dict):
            self._exchange_info_cache = data
            self._exchange_info_cache_time = now
        return data

    def _get_symbol_lot_filter(self, symbol: str) -> Optional[Dict]:
        try:
            info = self.get_exchange_info(use_cache=True) or {}
            symbols = info.get('symbols', []) if isinstance(info, dict) else []
            for s in symbols:
                if s.get('symbol') == symbol:
                    for f in s.get('filters', []) or []:
                        if f.get('filterType') == 'LOT_SIZE':
                            return f
            return None
        except Exception:
            return None

    def adjust_quantity(self, symbol: str, quantity: float) -> Tuple[float, str]:
        """
        将数量按交易对 LOT_SIZE 规则向下取整（避免下单被拒）
        Returns: (adjusted_qty, reason)
        """
        try:
            q = float(quantity)
            if q <= 0:
                return 0.0, "quantity<=0"
            lot = self._get_symbol_lot_filter(symbol)
            if not lot:
                # 无法获取规则时退化：保留 3 位小数
                return round(q, 3), "fallback_round_3"
            step = float(lot.get('stepSize', 0) or 0)
            min_qty = float(lot.get('minQty', 0) or 0)
            if step <= 0:
                return round(q, 3), "fallback_round_3"
            # floor to step
            steps = math.floor(q / step)
            adj = steps * step
            # 避免浮点误差
            adj = float(f"{adj:.12f}")
            if min_qty > 0 and adj < min_qty:
                return 0.0, f"below_minQty({min_qty})"
            return adj, f"stepSize({step})"
        except Exception as e:
            return round(float(quantity), 3), f"fallback_round_3({e})"
    
    # ========== 工具方法 ==========
    
    def check_api_connection(self) -> Tuple[bool, str]:
        """检查API连接"""
        try:
            # 测试公开接口
            self.get_ticker_price('BTCUSDT')
            # 测试私有接口
            if self.api_key and self.secret_key:
                self.get_account()
            return True, "API连接正常"
        except Exception as e:
            return False, f"API连接失败: {e}"
    
    def validate_trade_params(
        self,
        symbol: str,
        side: str,
        quantity: float,
        leverage: int = None
    ) -> Tuple[bool, str]:
        """
        验证交易参数
        
        Returns:
            (是否有效, 错误信息)
        """
        # 检查交易对
        if not symbol or len(symbol) < 6:
            return False, "交易对格式错误"
        
        # 检查方向
        if side not in ['BUY', 'SELL']:
            return False, "交易方向错误，必须是BUY或SELL"
        
        # 检查数量
        if quantity <= 0:
            return False, "交易数量必须大于0"
        
        # 检查余额（需要API调用）
        if self.api_key and self.secret_key:
            try:
                balance = self.get_balance()
                # 估算所需保证金（简化计算）
                price = self.get_ticker_price(symbol)
                if price:
                    required_margin = (quantity * price) / (leverage or 1)
                    if balance < required_margin * 1.1:  # 10%缓冲
                        return False, f"余额不足: 需要{required_margin:.2f} USDT, 当前{balance:.2f} USDT"
            except Exception as e:
                logging.warning(f"余额检查失败: {e}")
        
        return True, ""
