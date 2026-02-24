import requests
import pandas as pd
from typing import Dict, List, Optional
import time
import random
from config import EXCHANGE, API_BASE_URL
from gate_data_fetcher import GateDataFetcher

class BaseDataFetcher:
    """数据获取器基类"""
    
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'CryptoMonitor/1.0',
            'Accept': 'application/json'
        })
        self.last_request_time = 0
        self.min_request_interval = 1
        self.offline_mode = False
        
    def _rate_limit(self):
        """速率控制"""
        current_time = time.time()
        elapsed = current_time - self.last_request_time
        if elapsed < self.min_request_interval:
            time.sleep(self.min_request_interval - elapsed)
        self.last_request_time = time.time()
    
    def _make_request_with_retry(self, url: str, params: Dict = None, max_retries: int = 3) -> Optional[Dict]:
        """带重试的请求方法"""
        if self.offline_mode:
            return self._get_mock_data(url, params)
            
        for attempt in range(max_retries):
            try:
                self._rate_limit()
                response = self.session.get(url, params=params, timeout=10)
                response.raise_for_status()
                return response.json()
            except requests.exceptions.ConnectionError as e:
                print(f"连接错误 (尝试 {attempt + 1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt  # 指数退避
                    print(f"等待 {wait_time} 秒后重试...")
                    time.sleep(wait_time)
                else:
                    print("所有重试失败，切换到离线模式")
                    self.offline_mode = True
                    return self._get_mock_data(url, params)
            except requests.exceptions.Timeout as e:
                print(f"请求超时 (尝试 {attempt + 1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    time.sleep(2)
                else:
                    print("请求超时，切换到离线模式")
                    self.offline_mode = True
                    return self._get_mock_data(url, params)
            except Exception as e:
                print(f"请求失败 (尝试 {attempt + 1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    time.sleep(2)
                else:
                    print("请求失败，切换到离线模式")
                    self.offline_mode = True
                    return self._get_mock_data(url, params)
        return None
    
    def _get_mock_data(self, url: str, params: Dict = None) -> Optional[Dict]:
        """生成模拟数据用于离线模式"""
        print("⚠️  使用模拟数据（离线模式）")
        return None

class CoinGeckoDataFetcher(BaseDataFetcher):
    """CoinGecko 数据获取器"""
    
    def get_top_coins_by_category(self, category: str, top_n: int = 5) -> List[Dict]:
        """获取指定分类的龙头币种"""
        try:
            params = {
                'vs_currency': 'usd',
                'order': 'market_cap_desc',
                'per_page': top_n,
                'page': 1,
                'sparkline': False,
                'price_change_percentage': '1h,24h,7d'
            }
            
            data = self._make_request_with_retry(
                f"{API_BASE_URL}/coins/markets",
                params
            )
            
            if data:
                return data[:top_n]
            else:
                return self._get_mock_coins_data(category, top_n)
            
        except Exception as e:
            print(f"CoinGecko获取{category}分类数据失败: {e}")
            return self._get_mock_coins_data(category, top_n)
    
    def get_price_history(self, symbol: str, interval: str = '1h') -> pd.DataFrame:
        """获取价格历史数据 - 支持不同时间间隔"""
        try:
            # 根据间隔参数调整days和interval
            interval_map = {
                '5m': {'days': 1, 'interval': 'minutely'},
                '15m': {'days': 1, 'interval': 'minutely'},
                '1h': {'days': 1, 'interval': 'hourly'},
                '4h': {'days': 7, 'interval': 'hourly'},
                '24h': {'days': 30, 'interval': 'daily'}
            }
            
            config = interval_map.get(interval, {'days': 1, 'interval': 'hourly'})
            
            params = {
                'vs_currency': 'usd',
                'days': config['days'],
                'interval': config['interval']
            }
            
            data = self._make_request_with_retry(
                f"{API_BASE_URL}/coins/{symbol}/market_chart",
                params
            )
            
            if data and 'prices' in data:
                prices = data['prices']
                df = pd.DataFrame(prices, columns=['timestamp', 'price'])
                df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
                df.set_index('timestamp', inplace=True)
                return df
            else:
                return self._create_mock_history_data(interval)
            
        except Exception as e:
            print(f"CoinGecko获取{symbol}价格历史失败: {e}")
            return self._create_mock_history_data(interval)
    
    def _get_mock_coins_data(self, category: str, top_n: int) -> List[Dict]:
        """生成模拟币种数据"""
        base_prices = {
            'bitcoin': 45000, 'ethereum': 3000, 'solana': 100, 'cardano': 0.5,
            'matic-network': 0.8, 'optimism': 2.5, 'arbitrum': 1.2,
            'uniswap': 8, 'aave': 90, 'maker': 1500,
            'dogecoin': 0.15, 'shiba-inu': 0.00001
        }
        
        mock_coins = []
        for coin_id in list(base_prices.keys())[:top_n]:
            base_price = base_prices[coin_id]
            current_price = base_price * (1 + random.uniform(-0.02, 0.02))
            change_24h = random.uniform(-5, 10)
            
            mock_coins.append({
                'id': coin_id,
                'symbol': coin_id[:3],
                'name': coin_id.capitalize(),
                'current_price': current_price,
                'price_change_percentage_24h_in_currency': change_24h,
                'total_volume': current_price * random.uniform(10000, 100000),
                'price_change_24h': current_price * (change_24h / 100)
            })
        
        return mock_coins
    
    def _create_mock_history_data(self, interval: str) -> pd.DataFrame:
        """创建模拟历史数据"""
        import numpy as np
        from datetime import datetime, timedelta
        
        base_price = 45000
        
        # 根据间隔设置数据点数
        points_map = {
            '5m': 288,   # 24小时 * 12 (每5分钟)
            '15m': 96,    # 24小时 * 4 (每15分钟)
            '1h': 24,     # 24小时
            '4h': 42,     # 7天 * 6 (每4小时)
            '24h': 30     # 30天
        }
        
        points = points_map.get(interval, 24)
        
        # 生成时间序列
        if interval == '5m':
            timestamps = [datetime.now() - timedelta(minutes=5*i) for i in range(points, 0, -1)]
        elif interval == '15m':
            timestamps = [datetime.now() - timedelta(minutes=15*i) for i in range(points, 0, -1)]
        elif interval == '1h':
            timestamps = [datetime.now() - timedelta(hours=i) for i in range(points, 0, -1)]
        elif interval == '4h':
            timestamps = [datetime.now() - timedelta(hours=4*i) for i in range(points, 0, -1)]
        else:  # 24h
            timestamps = [datetime.now() - timedelta(days=i) for i in range(points, 0, -1)]
        
        prices = base_price + np.random.normal(0, base_price * 0.01, points).cumsum()
        
        df = pd.DataFrame({
            'timestamp': timestamps,
            'price': prices
        })
        df.set_index('timestamp', inplace=True)
        return df

class BinanceDataFetcher(BaseDataFetcher):
    """Binance 数据获取器"""
    
    def get_top_coins_by_category(self, category: str, top_n: int = 5) -> List[Dict]:
        """获取指定分类的龙头币种"""
        from config import CRYPTO_CATEGORIES
        
        try:
            symbols = CRYPTO_CATEGORIES[category][EXCHANGE][:top_n]
            coins_data = []
            
            for symbol in symbols:
                # 获取24小时行情数据
                params = {'symbol': symbol}
                
                data = self._make_request_with_retry(
                    f"{API_BASE_URL}/ticker/24hr",
                    params
                )
                
                if data:
                    # 转换为统一格式
                    coin_data = {
                        'id': symbol.lower(),
                        'symbol': symbol,
                        'name': symbol.replace('USDT', ''),
                        'current_price': float(data['lastPrice']),
                        'price_change_percentage_24h_in_currency': float(data['priceChangePercent']),
                        'total_volume': float(data.get('volume', 0)),
                        'price_change_24h': float(data['priceChange'])
                    }
                    coins_data.append(coin_data)
                else:
                    # 如果单个币种获取失败，使用模拟数据
                    mock_coin = self._get_mock_binance_coin_data(symbol)
                    coins_data.append(mock_coin)
            
            return coins_data
            
        except Exception as e:
            print(f"Binance获取{category}分类数据失败: {e}")
            return self._get_mock_binance_coins_data(category, top_n)
    
    def get_price_history(self, symbol: str, interval: str = '1h') -> pd.DataFrame:
        """获取K线数据 - 支持多时间间隔"""
        try:
            # 映射间隔参数
            interval_map = {
                '5m': '5m',
                '15m': '15m', 
                '1h': '1h',
                '4h': '4h',
                '24h': '1d'
            }
            
            binance_interval = interval_map.get(interval, '1h')
            
            # 设置数据点数
            limit_map = {
                '5m': 288,   # 24小时数据
                '15m': 96,    # 24小时数据
                '1h': 24,     # 24小时数据
                '4h': 42,     # 7天数据
                '24h': 30     # 30天数据
            }
            
            limit = limit_map.get(interval, 24)
            
            params = {
                'symbol': symbol.upper(),
                'interval': binance_interval,
                'limit': limit
            }
            
            data = self._make_request_with_retry(
                f"{API_BASE_URL}/klines",
                params
            )
            
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
                
                return df[['open', 'high', 'low', 'close', 'volume']]
            else:
                return self._create_mock_history_data(interval)
            
        except Exception as e:
            print(f"Binance获取{symbol}K线数据失败: {e}")
            return self._create_mock_history_data(interval)
    
    def _get_mock_binance_coins_data(self, category: str, top_n: int) -> List[Dict]:
        """生成模拟Binance币种数据"""
        from config import CRYPTO_CATEGORIES
        
        symbols = CRYPTO_CATEGORIES[category][EXCHANGE][:top_n]
        coins_data = []
        
        base_prices = {
            'BTCUSDT': 45000, 'ETHUSDT': 3000, 'SOLUSDT': 100, 'ADAUSDT': 0.5,
            'MATICUSDT': 0.8, 'OPUSDT': 2.5, 'ARBUSDT': 1.2,
            'UNIUSDT': 8, 'AAVEUSDT': 90, 'MKRUSDT': 1500,
            'DOGEUSDT': 0.15, 'SHIBUSDT': 0.00001
        }
        
        for symbol in symbols:
            base_price = base_prices.get(symbol, 100)
            current_price = base_price * (1 + random.uniform(-0.02, 0.02))
            change_24h = random.uniform(-5, 10)
            
            coins_data.append({
                'id': symbol.lower(),
                'symbol': symbol,
                'name': symbol.replace('USDT', ''),
                'current_price': current_price,
                'price_change_percentage_24h_in_currency': change_24h,
                'total_volume': current_price * random.uniform(10000, 100000),
                'price_change_24h': current_price * (change_24h / 100)
            })
        
        return coins_data
    
    def _get_mock_binance_coin_data(self, symbol: str) -> Dict:
        """生成单个模拟币种数据"""
        base_prices = {
            'BTCUSDT': 45000, 'ETHUSDT': 3000, 'SOLUSDT': 100, 'ADAUSDT': 0.5,
            'MATICUSDT': 0.8, 'OPUSDT': 2.5, 'ARBUSDT': 1.2,
            'UNIUSDT': 8, 'AAVEUSDT': 90, 'MKRUSDT': 1500,
            'DOGEUSDT': 0.15, 'SHIBUSDT': 0.00001
        }
        
        base_price = base_prices.get(symbol, 100)
        current_price = base_price * (1 + random.uniform(-0.02, 0.02))
        change_24h = random.uniform(-5, 10)
        
        return {
            'id': symbol.lower(),
            'symbol': symbol,
            'name': symbol.replace('USDT', ''),
            'current_price': current_price,
            'price_change_percentage_24h_in_currency': change_24h,
            'total_volume': current_price * random.uniform(10000, 100000),
            'price_change_24h': current_price * (change_24h / 100)
        }
    
    def _create_mock_history_data(self, interval: str) -> pd.DataFrame:
        """创建模拟历史数据"""
        import numpy as np
        from datetime import datetime, timedelta
        
        base_price = 45000
        
        # 根据间隔设置数据点数
        points_map = {
            '5m': 288,   # 24小时 * 12 (每5分钟)
            '15m': 96,    # 24小时 * 4 (每15分钟)
            '1h': 24,     # 24小时
            '4h': 42,     # 7天 * 6 (每4小时)
            '24h': 30     # 30天
        }
        
        points = points_map.get(interval, 24)
        
        # 生成时间序列
        if interval == '5m':
            timestamps = [datetime.now() - timedelta(minutes=5*i) for i in range(points, 0, -1)]
        elif interval == '15m':
            timestamps = [datetime.now() - timedelta(minutes=15*i) for i in range(points, 0, -1)]
        elif interval == '1h':
            timestamps = [datetime.now() - timedelta(hours=i) for i in range(points, 0, -1)]
        elif interval == '4h':
            timestamps = [datetime.now() - timedelta(hours=4*i) for i in range(points, 0, -1)]
        else:  # 24h
            timestamps = [datetime.now() - timedelta(days=i) for i in range(points, 0, -1)]
        
        prices = base_price + np.random.normal(0, base_price * 0.01, points).cumsum()
        
        df = pd.DataFrame({
            'timestamp': timestamps,
            'close': prices
        })
        df.set_index('timestamp', inplace=True)
        return df

def create_data_fetcher():
    """创建数据获取器工厂函数"""
    # 统一使用 GateDataFetcher，它已支持币安合约API
    if EXCHANGE == 'binance':
        return GateDataFetcher()
    elif EXCHANGE == 'gate':
        return GateDataFetcher()
    else:
        return CoinGeckoDataFetcher()