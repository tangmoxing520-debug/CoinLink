import requests
import pandas as pd
from typing import Dict, List, Optional
import time
import random
from base_fetcher import BaseDataFetcher
from config import COINGECKO_API_KEY, API_BASE_URL

class CoinGeckoDataFetcher(BaseDataFetcher):
    def __init__(self, offline_mode=False):
        super().__init__(offline_mode)
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'CryptoMonitor/1.0',
            'Accept': 'application/json'
        })
        self.last_request_time = 0
        self.min_request_interval = 2
        
    def _rate_limit(self):
        """速率控制"""
        if not COINGECKO_API_KEY:
            current_time = time.time()
            elapsed = current_time - self.last_request_time
            if elapsed < self.min_request_interval:
                time.sleep(self.min_request_interval - elapsed + random.uniform(0.1, 0.5))
            self.last_request_time = time.time()
    
    def _make_request(self, url: str, params: Dict) -> Optional[Dict]:
        """封装请求，包含重试机制"""
        if self.offline_mode:
            return self._get_mock_data(url, params)
            
        max_retries = 2
        for attempt in range(max_retries):
            try:
                self._rate_limit()
                
                if COINGECKO_API_KEY:
                    params['x_cg_pro_api_key'] = COINGECKO_API_KEY
                    
                response = self.session.get(url, params=params, timeout=10)
                
                if response.status_code == 401:
                    print(f"CoinGecko认证失败 (尝试 {attempt + 1}/{max_retries})")
                    if attempt < max_retries - 1:
                        time.sleep(2)
                    else:
                        print("CoinGecko认证失败，切换到离线模式")
                        self.offline_mode = True
                        return self._get_mock_data(url, params)
                    continue
                    
                if response.status_code == 429:
                    wait_time = (2 ** attempt) + random.uniform(0.1, 1.0)
                    print(f"CoinGecko速率限制，等待 {wait_time:.1f} 秒后重试...")
                    time.sleep(wait_time)
                    continue
                    
                response.raise_for_status()
                return response.json()
                
            except requests.exceptions.Timeout:
                print(f"CoinGecko请求超时 (尝试 {attempt + 1}/{max_retries})")
                if attempt < max_retries - 1:
                    time.sleep(2)
                continue
            except requests.exceptions.ConnectionError:
                print(f"CoinGecko连接错误 (尝试 {attempt + 1}/{max_retries})，切换到离线模式")
                self.offline_mode = True
                return self._get_mock_data(url, params)
            except requests.exceptions.RequestException as e:
                print(f"CoinGecko请求失败 (尝试 {attempt + 1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    time.sleep(2)
                else:
                    print(f"所有重试失败，切换到离线模式")
                    self.offline_mode = True
                    return self._get_mock_data(url, params)
        
        return None
    
    def _get_mock_data(self, url: str, params: Dict) -> Optional[Dict]:
        """生成模拟数据用于离线测试"""
        print("⚠️  CoinGecko使用模拟数据（离线模式）")
        
        if "coins/markets" in url:
            base_prices = {
                'bitcoin': 45000, 'ethereum': 3000, 'solana': 100, 
                'cardano': 0.5, 'polkadot': 7, 'matic-network': 0.8,
                'dogecoin': 0.15, 'uniswap': 8, 'aave': 90
            }
            
            mock_coins = []
            coin_list = [
                ('bitcoin', 'Bitcoin'), ('ethereum', 'Ethereum'), 
                ('solana', 'Solana'), ('cardano', 'Cardano')
            ]
            
            for coin_id, coin_name in coin_list:
                base_price = base_prices.get(coin_id, 100)
                current_price = base_price * (1 + random.uniform(-0.05, 0.05))
                change_1h = random.uniform(-2, 8)
                change_24h = random.uniform(-5, 15)
                
                mock_coins.append({
                    'id': coin_id,
                    'symbol': coin_id[:3],
                    'name': coin_name,
                    'current_price': current_price,
                    'market_cap': int(current_price * 1000000),
                    'market_cap_rank': len(mock_coins) + 1,
                    'price_change_percentage_1h_in_currency': change_1h,
                    'price_change_percentage_24h_in_currency': change_24h,
                    'price_change_percentage_7d_in_currency': random.uniform(-10, 25),
                    'total_volume': int(current_price * 50000),
                    'price_change_24h': current_price * (change_24h / 100)
                })
            
            per_page = params.get('per_page', 5)
            return mock_coins[:per_page]
        
        return None
    
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
            
            data = self._make_request(
                f"{API_BASE_URL}/coins/markets",
                params
            )
            
            if data:
                return data[:top_n]
            else:
                return []
            
        except Exception as e:
            print(f"CoinGecko获取{category}分类数据失败: {e}")
            return []
    
    def get_price_history(self, symbol: str, interval: str = '1h', limit: int = 24) -> pd.DataFrame:
        """获取价格历史数据"""
        try:
            # CoinGecko使用天数和间隔参数
            days_map = {'1h': 1, '4h': 7, '1d': 30}
            days = days_map.get(interval, 1)
            
            params = {
                'vs_currency': 'usd',
                'days': days,
                'interval': 'hourly' if days <= 7 else 'daily'
            }
            
            data = self._make_request(
                f"{API_BASE_URL}/coins/{symbol}/market_chart",
                params
            )
            
            if data and 'prices' in data:
                prices = data['prices']
                df = pd.DataFrame(prices, columns=['timestamp', 'close'])
                df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
                df.set_index('timestamp', inplace=True)
                # 添加其他OHLCV列以保持接口一致
                df['open'] = df['close']
                df['high'] = df['close']
                df['low'] = df['close']
                df['volume'] = 0  # CoinGecko不直接提供成交量
                return df
            else:
                return self._create_mock_history_data()
            
        except Exception as e:
            print(f"CoinGecko获取{symbol}价格历史失败: {e}")
            return self._create_mock_history_data()
    
    def get_current_price(self, symbol: str) -> Optional[float]:
        """获取当前价格"""
        try:
            params = {
                'ids': symbol,
                'vs_currencies': 'usd'
            }
            
            data = self._make_request(
                f"{API_BASE_URL}/simple/price",
                params
            )
            
            if data and symbol in data:
                return data[symbol].get('usd')
            else:
                return None
                
        except Exception as e:
            print(f"CoinGecko获取{symbol}当前价格失败: {e}")
            return None