import requests
import pandas as pd
from typing import Dict, List, Optional
import time
import random
import urllib3
import logging
from config import EXCHANGE, API_BASE_URL, MONITOR_CONFIG, BINANCE_FUTURES_API_URL

logger = logging.getLogger(__name__)

class GateDataFetcher:
    """数据获取器 - 支持币安合约K线API"""
    
    def __init__(self):
        self.session = requests.Session()
        
        # 配置SSL验证
        self.verify_ssl = MONITOR_CONFIG.get('verify_ssl', True)
        self.proxy_enabled = MONITOR_CONFIG.get('proxy_enabled', False)
        self.proxy_url = MONITOR_CONFIG.get('proxy_url', '')
        self.request_timeout = MONITOR_CONFIG.get('request_timeout', 30)
        self.ticker_cache_ttl_seconds = int(MONITOR_CONFIG.get('ticker_cache_ttl_seconds', 10))

        # 仅当用户显式关闭 SSL 验证时才禁用告警
        if not self.verify_ssl:
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        
        # 币安合约API地址
        self.binance_klines_url = f"{BINANCE_FUTURES_API_URL}/klines"
        self.binance_ticker_url = f"{BINANCE_FUTURES_API_URL}/ticker/24hr"

        # 批量 ticker 缓存（最稳妥：短 TTL + 失败回退到逐个请求）
        self._ticker_24h_cache: Dict[str, Dict] = {}
        self._ticker_24h_cache_time: float = 0.0
        
        # 配置代理
        if self.proxy_enabled and self.proxy_url:
            self.session.proxies = {
                'http': self.proxy_url,
                'https': self.proxy_url
            }
        
        # 配置请求头
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'application/json'
        })
        
        self.last_request_time = 0
        self.min_request_interval = 0.5
        # 优化：动态速率限制
        self._request_times = []  # 记录最近请求时间
        self._adaptive_interval = 0.5  # 动态调整的间隔
        self._max_requests_per_second = 2.0  # 每秒最多2个请求
        
    def _rate_limit(self):
        """速率控制（动态调整）"""
        current_time = time.time()
        
        # 清理1秒前的请求记录
        self._request_times = [t for t in self._request_times if current_time - t < 1.0]
        
        # 如果最近1秒内的请求数超过限制，等待
        if len(self._request_times) >= self._max_requests_per_second:
            wait_time = 1.0 - (current_time - self._request_times[0])
            if wait_time > 0:
                time.sleep(wait_time)
                current_time = time.time()
        
        # 基本间隔控制
        elapsed = current_time - self.last_request_time
        if elapsed < self._adaptive_interval:
            time.sleep(self._adaptive_interval - elapsed)
        
        self.last_request_time = time.time()
        self._request_times.append(time.time())
        
        # 动态调整间隔（根据最近请求的响应时间）
        # 如果请求频繁，稍微增加间隔；如果请求稀疏，可以稍微减少
        if len(self._request_times) > 10:
            avg_interval = (self._request_times[-1] - self._request_times[0]) / (len(self._request_times) - 1)
            if avg_interval < 0.3:  # 请求太频繁
                self._adaptive_interval = min(1.0, self._adaptive_interval * 1.1)
            elif avg_interval > 1.0:  # 请求稀疏
                self._adaptive_interval = max(0.3, self._adaptive_interval * 0.9)
    
    def _make_request_with_retry(self, url: str, params: Dict = None, max_retries: int = 3) -> Optional:
        """带重试的请求方法"""
        for attempt in range(max_retries):
            try:
                self._rate_limit()
                logger.debug("请求 (%d/%d): %s", attempt + 1, max_retries, url)
                
                response = self.session.get(
                    url, 
                    params=params, 
                    timeout=self.request_timeout,
                    verify=self.verify_ssl
                )
                
                response.raise_for_status()
                logger.debug("请求成功")
                return response.json()
                
            except requests.exceptions.SSLError as e:
                logger.warning("SSL错误 (%d/%d): %s", attempt + 1, max_retries, e)
                if attempt < max_retries - 1:
                    time.sleep(3)
                    
            except requests.exceptions.ConnectionError as e:
                logger.warning("连接错误 (%d/%d): %s", attempt + 1, max_retries, e)
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)
                    
            except requests.exceptions.Timeout as e:
                logger.warning("请求超时 (%d/%d): %s", attempt + 1, max_retries, e)
                if attempt < max_retries - 1:
                    time.sleep(3)
                    
            except Exception as e:
                logger.warning("请求失败 (%d/%d): %s", attempt + 1, max_retries, e)
                if attempt < max_retries - 1:
                    time.sleep(2)
        
        logger.error("所有重试失败: %s", url)
        return None

    def _get_all_tickers_24hr_cached(self) -> Optional[Dict[str, Dict]]:
        """
        批量获取 24hr ticker，并做短缓存。
        Binance Futures: GET /fapi/v1/ticker/24hr （不带 symbol）返回全市场列表。
        """
        try:
            now = time.time()
            ttl = max(0, int(self.ticker_cache_ttl_seconds))
            if ttl > 0 and self._ticker_24h_cache and (now - self._ticker_24h_cache_time) < ttl:
                return self._ticker_24h_cache

            data = self._make_request_with_retry(self.binance_ticker_url, params=None)
            if not data or not isinstance(data, list):
                return None

            mapping: Dict[str, Dict] = {}
            for item in data:
                sym = item.get('symbol')
                if sym:
                    mapping[str(sym).upper()] = item

            self._ticker_24h_cache = mapping
            self._ticker_24h_cache_time = now
            return mapping
        except Exception:
            return None

    def get_top_coins_by_category(self, category: str, top_n: int = 5) -> List[Dict]:
        """获取指定分类的币种数据 - 使用币安合约API"""
        from config import CRYPTO_CATEGORIES
        
        try:
            symbols = CRYPTO_CATEGORIES[category][EXCHANGE][:top_n]
            coins_data = []
            
            logger.debug("获取 %s 分类数据 (币安合约API)...", category)

            # 最稳妥：优先批量拿全市场 ticker，再本地过滤；失败则回退逐个请求
            ticker_map = self._get_all_tickers_24hr_cached()

            for symbol in symbols:
                data = None
                sym = str(symbol).upper()

                if ticker_map and sym in ticker_map:
                    data = ticker_map[sym]
                else:
                    # 回退：逐个拉取（保持原行为）
                    data = self._make_request_with_retry(
                        self.binance_ticker_url,
                        params={'symbol': sym}
                    )
                
                if data:
                    try:
                        # 注意：这里的 'id' 在本项目内被当作“交易对 symbol”使用（传入下单/取K线）。
                        # 为避免大小写导致的交易所拒单/龙头识别失败，保持与币安一致的 uppercase 形式。
                        coin_data = {
                            'id': str(symbol).upper().replace('_', ''),
                            'symbol': str(symbol).upper().replace('_', ''),
                            'name': symbol.replace('USDT', ''),
                            'current_price': float(data['lastPrice']),
                            'price_change_percentage_24h_in_currency': float(data['priceChangePercent']),
                            'total_volume': float(data.get('quoteVolume', 0)),
                            'price_change_24h': float(data['priceChange'])
                        }
                        coins_data.append(coin_data)
                        logger.debug("%s: $%.4f", symbol, coin_data['current_price'])
                    except (KeyError, ValueError) as e:
                        logger.debug("解析 %s 失败: %s", symbol, e)
                        coins_data.append(self._get_fallback_coin_data(symbol))
                else:
                    coins_data.append(self._get_fallback_coin_data(symbol))
            
            return coins_data
            
        except Exception as e:
            logger.warning("获取%s分类数据失败: %s", category, e)
            return self._get_fallback_data(category, top_n)
    
    def get_price_history(self, symbol: str, interval: str = '5m') -> pd.DataFrame:
        """获取K线数据 - 使用币安合约API: https://fapi.binance.com/fapi/v1/klines"""
        # 映射间隔参数
        interval_map = {
            '5m': '5m',
            '15m': '15m', 
            '1h': '1h',
            '4h': '4h',
            '24h': '1d'
        }
        binance_interval = interval_map.get(interval, '5m')
        
        # 转换交易对格式: btcusdt -> BTCUSDT, BTC_USDT -> BTCUSDT
        binance_symbol = symbol.upper().replace('_', '')
        
        params = {
            'symbol': binance_symbol,
            'interval': binance_interval,
            'limit': 50
        }
        
        logger.debug("获取 %s 的 %s K线数据...", binance_symbol, interval)
        
        # 增强重试：如果数据不足，额外重试一次
        max_attempts = 2
        for attempt in range(max_attempts):
            try:
                data = self._make_request_with_retry(self.binance_klines_url, params, max_retries=3)
                
                if data and isinstance(data, list) and len(data) > 0:
                    # 币安K线格式: [开盘时间, 开, 高, 低, 收, 成交量, 收盘时间, 成交额, 成交笔数, ...]
                    df = pd.DataFrame(data, columns=[
                        'open_time', 'open', 'high', 'low', 'close', 'volume',
                        'close_time', 'quote_volume', 'trades', 'taker_buy_base', 
                        'taker_buy_quote', 'ignore'
                    ])
                    
                    df['timestamp'] = pd.to_datetime(df['open_time'], unit='ms')
                    df.set_index('timestamp', inplace=True)
                    
                    for col in ['open', 'high', 'low', 'close', 'volume']:
                        df[col] = pd.to_numeric(df[col], errors='coerce')
                    
                    # 检查数据质量：至少需要10根K线
                    if len(df) >= 10:
                        logger.debug("获取到 %d 条K线数据", len(df))
                        return df[['open', 'high', 'low', 'close', 'volume']]
                    else:
                        logger.warning("K线数据不足 (%d 条)，需要至少10条", len(df))
                        if attempt < max_attempts - 1:
                            logger.debug("等待后重试...")
                            time.sleep(2)
                            continue
                else:
                    logger.warning("K线数据为空 (尝试 %d/%d)", attempt + 1, max_attempts)
                    if attempt < max_attempts - 1:
                        time.sleep(2)
                        continue
                
            except Exception as e:
                logger.warning("获取K线数据失败 (尝试 %d/%d): %s", attempt + 1, max_attempts, e)
                if attempt < max_attempts - 1:
                    time.sleep(2)
                    continue
        
        # 所有重试失败，返回空DataFrame而不是fallback（避免使用错误数据）
        logger.error("获取 %s 的 %s K线数据失败，返回空DataFrame", binance_symbol, interval)
        return pd.DataFrame(columns=['open', 'high', 'low', 'close', 'volume'])
    
    def _get_fallback_data(self, category: str, top_n: int) -> List[Dict]:
        """备用数据"""
        from config import CRYPTO_CATEGORIES
        symbols = CRYPTO_CATEGORIES[category][EXCHANGE][:top_n]
        return [self._get_fallback_coin_data(s) for s in symbols]
    
    def _get_fallback_coin_data(self, symbol: str) -> Dict:
        """单个币种备用数据"""
        base_prices = {
            'BTCUSDT': 95000, 'ETHUSDT': 3500, 'SOLUSDT': 180, 'ADAUSDT': 0.9,
            'DOTUSDT': 7, 'OPUSDT': 2.5, 'ARBUSDT': 1.2, 'MATICUSDT': 0.5,
            'UNIUSDT': 12, 'AAVEUSDT': 300, 'LINKUSDT': 22, 'MKRUSDT': 2000,
            'DOGEUSDT': 0.35, 'SHIBUSDT': 0.00002, '1000PEPEUSDT': 0.02,
            'WIFUSDT': 2.5, 'BONKUSDT': 0.00003, 'FETUSDT': 2.0, 'TAOUSDT': 500,
            'ONDOUSDT': 1.5, 'XRPUSDT': 2.3, 'FILUSDT': 5, 'SANDUSDT': 0.6,
            'WLDUSDT': 2.5, 'MAGICUSDT': 0.5
        }
        
        clean_symbol = symbol.upper().replace('_', '')
        base_price = base_prices.get(clean_symbol, 10.0)
        current_price = base_price * (1 + random.uniform(-0.01, 0.01))
        
        logger.debug("备用数据: %s - $%.4f", symbol, current_price)
        
        sym = str(symbol).upper().replace('_', '')
        return {
            'id': sym,
            'symbol': sym,
            'name': symbol.replace('USDT', '').replace('_', ''),
            'current_price': current_price,
            'price_change_percentage_24h_in_currency': random.uniform(-3, 5),
            'total_volume': current_price * random.uniform(50000, 200000),
            'price_change_24h': current_price * random.uniform(-0.03, 0.05)
        }
    
    def _create_fallback_history_data(self, interval: str) -> pd.DataFrame:
        """创建备用K线数据"""
        import numpy as np
        from datetime import datetime, timedelta
        
        base_price = 95000
        points = 50
        
        if interval == '5m':
            timestamps = [datetime.now() - timedelta(minutes=5*i) for i in range(points, 0, -1)]
        elif interval == '15m':
            timestamps = [datetime.now() - timedelta(minutes=15*i) for i in range(points, 0, -1)]
        elif interval == '1h':
            timestamps = [datetime.now() - timedelta(hours=i) for i in range(points, 0, -1)]
        else:
            timestamps = [datetime.now() - timedelta(hours=i) for i in range(points, 0, -1)]
        
        prices = [base_price]
        for _ in range(1, points):
            change = np.random.normal(0, base_price * 0.002)
            prices.append(max(prices[-1] + change, base_price * 0.8))
        
        df = pd.DataFrame({'timestamp': timestamps, 'close': prices})
        df.set_index('timestamp', inplace=True)
        
        return df
