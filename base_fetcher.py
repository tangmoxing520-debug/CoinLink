from abc import ABC, abstractmethod
from typing import Dict, List, Optional
import pandas as pd

class BaseDataFetcher(ABC):
    """数据获取器基类"""
    
    def __init__(self, offline_mode=False):
        self.offline_mode = offline_mode
    
    @abstractmethod
    def get_top_coins_by_category(self, category: str, top_n: int = 5) -> List[Dict]:
        """获取指定分类的龙头币种"""
        pass
    
    @abstractmethod
    def get_price_history(self, symbol: str, interval: str = '1h', limit: int = 24) -> pd.DataFrame:
        """获取价格历史数据"""
        pass
    
    @abstractmethod
    def get_current_price(self, symbol: str) -> Optional[float]:
        """获取当前价格"""
        pass
    
    def _create_mock_history_data(self, base_price: float = 45000) -> pd.DataFrame:
        """创建模拟历史数据（用于离线模式）"""
        import numpy as np
        from datetime import datetime, timedelta
        
        timestamps = [datetime.now() - timedelta(hours=i) for i in range(24, 0, -1)]
        # 添加随机波动
        prices = base_price + np.random.normal(0, base_price * 0.02, 24).cumsum()
        
        df = pd.DataFrame({
            'timestamp': timestamps,
            'open': prices,
            'high': prices * (1 + np.random.uniform(0, 0.05, 24)),
            'low': prices * (1 - np.random.uniform(0, 0.05, 24)),
            'close': prices,
            'volume': np.random.uniform(1000000, 50000000, 24)
        })
        df.set_index('timestamp', inplace=True)
        return df