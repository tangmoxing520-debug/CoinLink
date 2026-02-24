import requests
import pandas as pd
import time
import random
import hmac
import hashlib
from typing import Dict, List, Optional
from base_fetcher import BaseDataFetcher
from config import BINANCE_API_KEY, BINANCE_SECRET_KEY, API_BASE_URL

class BinanceDataFetcher(BaseDataFetcher):
    def __init__(self, offline_mode=False):
        super().__init__(offline_mode)
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'CryptoMonitor/1.0',
            'Accept': 'application/json'
        })
        
        # 只有在有API Key时才设置认证头
        if BINANCE_API_KEY:
            self.session.headers.update({
                'X-MBX-APIKEY': BINANCE_API_KEY
            })
            self.has_auth = True
            self.min_request_interval = 0.1  # 有认证时速率限制较宽松
        else:
            self.has_auth = False
            self.min_request_interval = 0.5  # 无认证时降低请求频率
            
        self.last_request_time = 0
        
    def _rate_limit(self):
        """速率控制"""
        current_time = time.time()
        elapsed = current_time - self.last_request_time
        if elapsed < self.min_request_interval:
            time.sleep(self.min_request_interval - elapsed)
        self.last_request_time = time.time()
    
    def _make_request(self, endpoint: str, params: Dict = None) -> Optional[Dict]:
        """封装请求，包含重试机制"""
        if self.offline_mode:
            return self._get_mock_data(endpoint, params)
            
        max_retries = 3
        for attempt in range(max_retries):
            try:
                self._rate_limit()
                
                url = f"{API_BASE_URL}{endpoint}"
                
                # 只有在有Secret Key且需要签名的接口才添加签名
                if BINANCE_SECRET_KEY and params and self._endpoint_requires_signature(endpoint):
                    query_string = '&'.join([f"{k}={v}" for k, v in params.items()])
                    signature = hmac.new(
                        BINANCE_SECRET_KEY.encode('utf-8'),
                        query_string.encode('utf-8'),
                        hashlib.sha256
                    ).hexdigest()
                    params['signature'] = signature
                
                response = self.session.get(url, params=params, timeout=10)
                
                # 处理速率限制
                if response.status_code == 429:
                    wait_time = (2 ** attempt) + random.uniform(0.1, 1.0)
                    auth_status = "有认证" if self.has_auth else "无认证"
                    print(f"Binance速率限制({auth_status})，等待 {wait_time:.1f} 秒后重试...")
                    time.sleep(wait_time)
                    continue
                
                # 处理IP限制（无认证时常见）
                if response.status_code == 418:
                    wait_time = (2 ** attempt) * 10  # IP被禁，等待更长时间
                    print(f"IP被限制访问，等待 {wait_time} 秒后重试...")
                    time.sleep(wait_time)
                    continue
                    
                response.raise_for_status()
                return response.json()
                
            except requests.exceptions.Timeout:
                print(f"Binance请求超时 (尝试 {attempt + 1}/{max_retries})")
                if attempt < max_retries - 1:
                    time.sleep(2)
                continue
            except requests.exceptions.ConnectionError:
                print(f"Binance连接错误 (尝试 {attempt + 1}/{max_retries})，切换到离线模式")
                self.offline_mode = True
                return self._get_mock_data(endpoint, params)
            except requests.exceptions.RequestException as e:
                print(f"Binance请求失败 (尝试 {attempt + 1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    time.sleep(2)
                else:
                    print(f"所有重试失败，切换到离线模式")
                    self.offline_mode = True
                    return self._get_mock_data(endpoint, params)
        
        return None
    
    def _endpoint_requires_signature(self, endpoint: str) -> bool:
        """检查端点是否需要签名"""
        # 这些公开API端点不需要签名
        public_endpoints = [
            '/ticker/24hr',
            '/ticker/price',
            '/klines',
            '/ticker/bookTicker',
            '/ticker'
        ]
        
        return endpoint not in public_endpoints
    
    def _get_mock_data(self, endpoint: str, params: Dict = None) -> Optional[Dict]:
        """生成模拟数据用于离线测试"""
        print("⚠️  Binance使用模拟数据（离线模式）")
        
        if "/ticker/24hr" in endpoint:
            # 模拟24小时行情数据
            symbol = params.get('symbol', 'BTCUSDT') if params else 'BTCUSDT'
            base_prices = {
                'BTCUSDT': 45000, 'ETHUSDT': 3000, 'SOLUSDT': 100,
                'ADAUSDT': 0.5, 'DOTUSDT': 7, 'MATICUSDT': 0.8
            }
            
            base_price = base_prices.get(symbol, 100)
            current_price = base_price * (1 + random.uniform(-0.05, 0.05))
            price_change = current_price - base_price
            price_change_percent = (price_change / base_price) * 100
            
            return {
                'symbol': symbol,
                'priceChange': price_change,
                'priceChangePercent': price_change_percent,
                'weightedAvgPrice': current_price,
                'prevClosePrice': base_price,
                'lastPrice': current_price,
                'lastQty': 1.0,
                'bidPrice': current_price * 0.999,
                'askPrice': current_price * 1.001,
                'openPrice': base_price,
                'highPrice': current_price * 1.05,
                'lowPrice': current_price * 0.95,
                'volume': random.uniform(1000000, 50000000),
                'quoteVolume': random.uniform(50000000, 200000000),
                'openTime': int((time.time() - 86400) * 1000),
                'closeTime': int(time.time() * 1000),
                'firstId': 1,
                'lastId': 1000,
                'count': 1000
            }
        
        return None
    
    def get_top_coins_by_category(self, category: str, top_n: int = 5) -> List[Dict]:
        """获取指定分类的龙头币种"""
        from config import CRYPTO_CATEGORIES, EXCHANGE
        
        try:
            symbols = CRYPTO_CATEGORIES[category][EXCHANGE][:top_n]
            coins_data = []
            
            for symbol in symbols:
                # 获取24小时行情数据
                params = {'symbol': symbol}
                data = self._make_request('/ticker/24hr', params)
                
                if data:
                    # 转换为统一格式
                    coin_data = {
                        'id': symbol.lower(),
                        'symbol': symbol,
                        'name': symbol.replace('USDT', '/USDT'),
                        'current_price': float(data['lastPrice']),
                        'market_cap': float(data.get('quoteVolume', 0)),
                        'market_cap_rank': len(coins_data) + 1,
                        'price_change_percentage_1h_in_currency': 0,  # Binance不直接提供1小时变化
                        'price_change_percentage_24h_in_currency': float(data['priceChangePercent']),
                        'price_change_percentage_7d_in_currency': 0,  # 需要额外计算
                        'total_volume': float(data.get('volume', 0)),
                        'price_change_24h': float(data['priceChange'])
                    }
                    coins_data.append(coin_data)
            
            return coins_data
            
        except Exception as e:
            print(f"Binance获取{category}分类数据失败: {e}")
            return []
    
    def get_price_history(self, symbol: str, interval: str = '1h', limit: int = 24) -> pd.DataFrame:
        """获取K线数据"""
        try:
            # 映射间隔参数
            interval_map = {
                '5m': '5m', '15m': '15m', '1h': '1h', 
                '4h': '4h', '1d': '1d'
            }
            binance_interval = interval_map.get(interval, '1h')
            
            params = {
                'symbol': symbol.upper(),
                'interval': binance_interval,
                'limit': limit
            }
            
            data = self._make_request('/klines', params)
            
            if data:
                df = pd.DataFrame(data, columns=[
                    'open_time', 'open', 'high', 'low', 'close', 'volume',
                    'close_time', 'quote_asset_volume', 'number_of_trades',
                    'taker_buy_base_asset_volume', 'taker_buy_quote_asset_volume', 'ignore'
                ])
                
                # 转换数据类型
                df['open_time'] = pd.to_datetime(df['open_time'], unit='ms')
                df.set_index('open_time', inplace=True)
                
                numeric_columns = ['open', 'high', 'low', 'close', 'volume']
                for col in numeric_columns:
                    df[col] = pd.to_numeric(df[col], errors='coerce')
                
                # 重命名列以保持接口一致
                df = df.rename(columns={'open_time': 'timestamp'})
                
                return df[['open', 'high', 'low', 'close', 'volume']]
            else:
                return self._create_mock_history_data()
            
        except Exception as e:
            print(f"Binance获取{symbol}K线数据失败: {e}")
            return self._create_mock_history_data()
    
    def get_current_price(self, symbol: str) -> Optional[float]:
        """获取当前价格"""
        try:
            params = {'symbol': symbol.upper()}
            data = self._make_request('/ticker/price', params)
            
            if data and 'price' in data:
                return float(data['price'])
            else:
                return None
                
        except Exception as e:
            print(f"Binance获取{symbol}当前价格失败: {e}")
            return None