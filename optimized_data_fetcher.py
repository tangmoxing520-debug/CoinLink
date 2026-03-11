"""
P0优化：API请求优化模块
- 批量获取ticker价格
- 智能缓存策略（根据波动率调整TTL）
- 优化API请求频率
"""
import time
import json
import logging
from typing import Dict, List, Optional
from datetime import datetime, timedelta
import pandas as pd
import numpy as np
from collections import defaultdict

from config import BINANCE_FUTURES_API_URL, TICKER_CACHE_TTL_SECONDS
from gate_data_fetcher import GateDataFetcher

logger = logging.getLogger(__name__)


class SmartCache:
    """智能缓存 - 根据市场波动率动态调整TTL"""
    
    def __init__(self, base_ttl: int = 30):
        self.base_ttl = base_ttl
        self._cache: Dict[str, Dict] = {}
        self._volatility_cache: Dict[str, float] = {}  # 波动率缓存
        self._volatility_cache_time: Dict[str, float] = {}
    
    def get(self, key: str) -> Optional[any]:
        """获取缓存值"""
        if key not in self._cache:
            return None
        
        entry = self._cache[key]
        age = time.time() - entry['timestamp']
        
        # 动态TTL：根据波动率调整
        volatility = self._get_volatility(key)
        if volatility > 0.05:  # 高波动（>5%）
            ttl = self.base_ttl * 0.5  # 短缓存（15秒）
        elif volatility > 0.02:  # 中波动（2-5%）
            ttl = self.base_ttl * 0.75  # 中等缓存（22.5秒）
        else:  # 低波动（<2%）
            ttl = self.base_ttl * 1.5  # 长缓存（45秒）
        
        if age > ttl:
            del self._cache[key]
            return None
        
        return entry['value']
    
    def set(self, key: str, value: any):
        """设置缓存值"""
        self._cache[key] = {
            'value': value,
            'timestamp': time.time()
        }
    
    def _get_volatility(self, symbol: str) -> float:
        """获取币种波动率"""
        # 如果波动率缓存过期（5分钟），重新计算
        if symbol in self._volatility_cache:
            age = time.time() - self._volatility_cache_time.get(symbol, 0)
            if age < 300:  # 5分钟内有效
                return self._volatility_cache[symbol]
        
        # 默认波动率（中等）
        return 0.02
    
    def update_volatility(self, symbol: str, volatility: float):
        """更新波动率"""
        self._volatility_cache[symbol] = volatility
        self._volatility_cache_time[symbol] = time.time()
    
    def clear(self, pattern: str = None):
        """清理缓存"""
        if pattern:
            keys_to_delete = [k for k in self._cache.keys() if pattern in k]
            for key in keys_to_delete:
                del self._cache[key]
        else:
            self._cache.clear()


class BatchPriceFetcher:
    """批量价格获取器 - 减少API请求"""
    
    def __init__(self, base_fetcher: GateDataFetcher):
        self.base_fetcher = base_fetcher
        self.cache = SmartCache(base_ttl=TICKER_CACHE_TTL_SECONDS)
        self.batch_size = 50  # Binance批量接口最多支持50个交易对
        
    def get_batch_prices(self, symbols: List[str]) -> Dict[str, float]:
        """
        批量获取价格
        
        Args:
            symbols: 交易对列表
            
        Returns:
            价格字典 {symbol: price}
        """
        # 去重并转换为大写
        symbols = list(set([s.upper().replace('_', '') for s in symbols]))
        
        # 检查缓存
        cached_prices = {}
        uncached_symbols = []
        
        for symbol in symbols:
            cached_price = self.cache.get(f"price:{symbol}")
            if cached_price is not None:
                cached_prices[symbol] = cached_price
            else:
                uncached_symbols.append(symbol)
        
        # 如果所有价格都在缓存中，直接返回
        if not uncached_symbols:
            return cached_prices
        
        # 批量获取未缓存的价格
        batch_prices = self._fetch_batch_prices(uncached_symbols)
        
        # 更新缓存
        for symbol, price in batch_prices.items():
            if price and price > 0:
                self.cache.set(f"price:{symbol}", price)
        
        # 合并结果
        result = {**cached_prices, **batch_prices}
        return result
    
    def _fetch_batch_prices(self, symbols: List[str]) -> Dict[str, float]:
        """从API批量获取价格"""
        if not symbols:
            return {}
        
        prices = {}
        
        # Binance批量ticker接口：/fapi/v1/ticker/24hr
        # 注意：Binance批量接口需要传递symbols数组，但实际API可能不支持
        # 这里使用逐个请求的优化版本（批量请求但合并处理）
        
        try:
            # 方案1：尝试使用Binance的批量ticker接口（如果支持）
            # 注意：Binance Futures API的/ticker/24hr不支持批量查询
            # 所以我们需要使用优化策略：并发请求或批量处理
            
            # 方案2：使用24hr ticker接口批量获取（需要逐个请求但可以优化）
            # 这里我们实现一个优化的批量请求：分组请求，减少等待时间
            
            # 将symbols分组，每组最多batch_size个
            for i in range(0, len(symbols), self.batch_size):
                batch = symbols[i:i + self.batch_size]
                
                # 并发请求这一批（使用线程池或异步）
                # 为了简化，这里先使用同步方式，但添加了请求优化
                for symbol in batch:
                    try:
                        # 使用base_fetcher的ticker接口
                        ticker_data = self._get_ticker_24hr(symbol)
                        if ticker_data and 'lastPrice' in ticker_data:
                            price = float(ticker_data['lastPrice'])
                            if price > 0:
                                prices[symbol] = price
                                
                                # 更新波动率（用于智能缓存）
                                if 'priceChangePercent' in ticker_data:
                                    volatility = abs(float(ticker_data['priceChangePercent'])) / 100
                                    self.cache.update_volatility(symbol, volatility)
                    except Exception as e:
                        logger.debug(f"获取 {symbol} 价格失败: {e}")
                        continue
                
                # 批次间添加小延迟，避免触发速率限制
                if i + self.batch_size < len(symbols):
                    time.sleep(0.1)
        
        except Exception as e:
            logger.error(f"批量获取价格失败: {e}")
        
        return prices
    
    def _get_ticker_24hr(self, symbol: str) -> Optional[Dict]:
        """获取24小时ticker数据"""
        try:
            url = f"{BINANCE_FUTURES_API_URL}/ticker/24hr"
            params = {'symbol': symbol}
            
            response = self.base_fetcher.session.get(
                url,
                params=params,
                timeout=self.base_fetcher.request_timeout,
                verify=self.base_fetcher.verify_ssl
            )
            
            if response.status_code == 200:
                return response.json()
            else:
                logger.debug(f"获取 {symbol} ticker失败: {response.status_code}")
                return None
                
        except Exception as e:
            logger.debug(f"获取 {symbol} ticker异常: {e}")
            return None
    
    def get_price(self, symbol: str) -> Optional[float]:
        """获取单个价格（使用批量接口优化）"""
        symbol = symbol.upper().replace('_', '')
        
        # 检查缓存
        cached_price = self.cache.get(f"price:{symbol}")
        if cached_price is not None:
            return cached_price
        
        # 批量获取（即使只有一个，也使用批量接口以利用缓存）
        prices = self.get_batch_prices([symbol])
        return prices.get(symbol)


class OptimizedDataFetcher(GateDataFetcher):
    """优化的数据获取器 - 继承GateDataFetcher并添加批量请求优化"""
    
    def __init__(self):
        super().__init__()
        self.batch_fetcher = BatchPriceFetcher(self)
        
        # K线数据智能缓存
        self.klines_cache = SmartCache(base_ttl=30)
        
    def get_current_price(self, symbol: str) -> Optional[float]:
        """获取当前价格 - 使用批量优化"""
        return self.batch_fetcher.get_price(symbol)
    
    def get_batch_prices(self, symbols: List[str]) -> Dict[str, float]:
        """批量获取价格"""
        return self.batch_fetcher.get_batch_prices(symbols)
    
    def get_klines(self, symbol: str, interval: str = '15m', limit: int = 50) -> Optional[pd.DataFrame]:
        """获取K线数据 - 使用智能缓存"""
        cache_key = f"klines:{symbol}:{interval}:{limit}"
        
        # 检查缓存
        cached_df = self.klines_cache.get(cache_key)
        if cached_df is not None:
            logger.debug(f"使用K线缓存: {symbol} {interval}")
            return cached_df
        
        # 获取数据（调用父类方法）
        df = super().get_price_history(symbol, interval)
        
        if df is not None and not df.empty:
            # 限制数据量
            if len(df) > limit:
                df = df.tail(limit)
            
            # 更新缓存
            self.klines_cache.set(cache_key, df)
            
            # 计算并更新波动率
            if 'close' in df.columns:
                returns = df['close'].pct_change().dropna()
                if len(returns) > 0:
                    volatility = float(returns.std())
                    self.klines_cache.update_volatility(symbol, volatility)
        
        return df
    
    def get_price_history(self, symbol: str, interval: str = '5m') -> pd.DataFrame:
        """获取价格历史 - 兼容父类接口"""
        return self.get_klines(symbol, interval, limit=50)
    
    def get_top_coins_by_category(self, category: str, top_n: int = 5) -> List[Dict]:
        """获取分类币种 - 优化批量价格获取"""
        coins = super().get_top_coins_by_category(category, top_n)
        
        if not coins:
            return coins
        
        # 批量获取价格（如果coins中没有价格信息）
        symbols = [coin.get('id') or coin.get('symbol', '') for coin in coins]
        symbols = [s.upper().replace('_', '') for s in symbols if s]
        
        if symbols:
            batch_prices = self.get_batch_prices(symbols)
            
            # 更新coins中的价格信息
            for coin in coins:
                symbol = (coin.get('id') or coin.get('symbol', '')).upper().replace('_', '')
                if symbol in batch_prices:
                    coin['current_price'] = batch_prices[symbol]
        
        return coins
