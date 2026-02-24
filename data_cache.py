"""
数据缓存管理器
缓存历史K线数据，避免重复API请求，加快回测速度
"""
import os
import json
import pickle
import hashlib
from datetime import datetime
from typing import Dict, Optional, Tuple
import pandas as pd


class DataCache:
    """
    数据缓存管理器
    
    功能:
    1. 缓存历史K线数据到本地文件
    2. 支持按日期范围查询缓存
    3. 自动管理缓存文件
    """
    
    CACHE_DIR = "backtest_cache"
    INDEX_FILE = "cache_index.json"
    
    def __init__(self, cache_dir: str = None):
        self.cache_dir = cache_dir or self.CACHE_DIR
        self._ensure_cache_dir()
        self._index = self._load_index()
    
    def _ensure_cache_dir(self) -> None:
        """确保缓存目录存在"""
        if not os.path.exists(self.cache_dir):
            os.makedirs(self.cache_dir)
    
    def _load_index(self) -> Dict:
        """加载缓存索引"""
        index_path = os.path.join(self.cache_dir, self.INDEX_FILE)
        if os.path.exists(index_path):
            try:
                with open(index_path, 'r') as f:
                    return json.load(f)
            except:
                return {}
        return {}
    
    def _save_index(self) -> None:
        """保存缓存索引"""
        index_path = os.path.join(self.cache_dir, self.INDEX_FILE)
        with open(index_path, 'w') as f:
            json.dump(self._index, f, indent=2, default=str)
    
    def _get_cache_key(
        self,
        symbol: str,
        interval: str,
        start_date: datetime,
        end_date: datetime
    ) -> str:
        """生成缓存键"""
        key_str = f"{symbol}_{interval}_{start_date.strftime('%Y%m%d')}_{end_date.strftime('%Y%m%d')}"
        return hashlib.md5(key_str.encode()).hexdigest()[:16]
    
    def _get_cache_path(self, cache_key: str) -> str:
        """获取缓存文件路径"""
        return os.path.join(self.cache_dir, f"{cache_key}.pkl")
    
    def get(
        self,
        symbol: str,
        interval: str,
        start_date: datetime,
        end_date: datetime
    ) -> Optional[pd.DataFrame]:
        """
        获取缓存数据
        
        Args:
            symbol: 交易对
            interval: 时间间隔
            start_date: 开始日期
            end_date: 结束日期
            
        Returns:
            缓存的DataFrame，如果不存在返回None
        """
        cache_key = self._get_cache_key(symbol, interval, start_date, end_date)
        
        if cache_key not in self._index:
            return None
        
        cache_path = self._get_cache_path(cache_key)
        if not os.path.exists(cache_path):
            # 索引存在但文件不存在，清理索引
            del self._index[cache_key]
            self._save_index()
            return None
        
        try:
            with open(cache_path, 'rb') as f:
                df = pickle.load(f)
            return df
        except Exception as e:
            print(f"⚠️ 读取缓存失败 {symbol}: {e}")
            return None
    
    def set(
        self,
        symbol: str,
        interval: str,
        start_date: datetime,
        end_date: datetime,
        data: pd.DataFrame
    ) -> bool:
        """
        设置缓存数据
        
        Args:
            symbol: 交易对
            interval: 时间间隔
            start_date: 开始日期
            end_date: 结束日期
            data: 要缓存的DataFrame
            
        Returns:
            是否成功
        """
        if data is None or data.empty:
            return False
        
        cache_key = self._get_cache_key(symbol, interval, start_date, end_date)
        cache_path = self._get_cache_path(cache_key)
        
        try:
            with open(cache_path, 'wb') as f:
                pickle.dump(data, f)
            
            # 更新索引
            self._index[cache_key] = {
                'symbol': symbol,
                'interval': interval,
                'start_date': start_date.isoformat(),
                'end_date': end_date.isoformat(),
                'rows': len(data),
                'cached_at': datetime.now().isoformat()
            }
            self._save_index()
            return True
        except Exception as e:
            print(f"⚠️ 写入缓存失败 {symbol}: {e}")
            return False
    
    def get_category_data(
        self,
        category: str,
        interval: str,
        start_date: datetime,
        end_date: datetime
    ) -> Optional[Dict[str, pd.DataFrame]]:
        """
        获取整个分类的缓存数据
        
        Args:
            category: 分类名称
            interval: 时间间隔
            start_date: 开始日期
            end_date: 结束日期
            
        Returns:
            {symbol: DataFrame} 字典，如果不存在返回None
        """
        cache_key = self._get_cache_key(f"category_{category}", interval, start_date, end_date)
        
        if cache_key not in self._index:
            return None
        
        cache_path = self._get_cache_path(cache_key)
        if not os.path.exists(cache_path):
            del self._index[cache_key]
            self._save_index()
            return None
        
        try:
            with open(cache_path, 'rb') as f:
                data = pickle.load(f)
            return data
        except Exception as e:
            print(f"⚠️ 读取分类缓存失败 {category}: {e}")
            return None
    
    def set_category_data(
        self,
        category: str,
        interval: str,
        start_date: datetime,
        end_date: datetime,
        data: Dict[str, pd.DataFrame]
    ) -> bool:
        """
        设置整个分类的缓存数据
        
        Args:
            category: 分类名称
            interval: 时间间隔
            start_date: 开始日期
            end_date: 结束日期
            data: {symbol: DataFrame} 字典
            
        Returns:
            是否成功
        """
        if not data:
            return False
        
        cache_key = self._get_cache_key(f"category_{category}", interval, start_date, end_date)
        cache_path = self._get_cache_path(cache_key)
        
        try:
            with open(cache_path, 'wb') as f:
                pickle.dump(data, f)
            
            # 更新索引
            self._index[cache_key] = {
                'category': category,
                'interval': interval,
                'start_date': start_date.isoformat(),
                'end_date': end_date.isoformat(),
                'symbols': list(data.keys()),
                'cached_at': datetime.now().isoformat()
            }
            self._save_index()
            return True
        except Exception as e:
            print(f"⚠️ 写入分类缓存失败 {category}: {e}")
            return False
    
    def clear(self) -> None:
        """清空所有缓存"""
        import shutil
        if os.path.exists(self.cache_dir):
            shutil.rmtree(self.cache_dir)
        self._ensure_cache_dir()
        self._index = {}
        self._save_index()
    
    def get_stats(self) -> Dict:
        """获取缓存统计信息"""
        total_size = 0
        for filename in os.listdir(self.cache_dir):
            filepath = os.path.join(self.cache_dir, filename)
            if os.path.isfile(filepath):
                total_size += os.path.getsize(filepath)
        
        return {
            'total_entries': len(self._index),
            'total_size_mb': total_size / (1024 * 1024),
            'cache_dir': self.cache_dir
        }


# 全局缓存实例
_global_cache: Optional[DataCache] = None


def get_cache() -> DataCache:
    """获取全局缓存实例"""
    global _global_cache
    if _global_cache is None:
        _global_cache = DataCache()
    return _global_cache
