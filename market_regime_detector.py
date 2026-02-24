"""
市场环境检测器 (Market Regime Detector)
基于BTC技术指标检测市场状态（牛市/熊市/震荡市）

Requirements: 1.1, 1.2, 1.3, 1.4, 1.5
"""
from enum import Enum
from dataclasses import dataclass
from typing import Optional
import pandas as pd
import numpy as np


class MarketRegimeType(Enum):
    """市场状态枚举"""
    BULLISH = "bullish"    # 牛市: 价格 > MA20 且 MA 上升
    BEARISH = "bearish"    # 熊市: 价格 < MA20 且 MA 下降
    SIDEWAYS = "sideways"  # 震荡: 价格频繁穿越 MA20


@dataclass
class MarketRegimeResult:
    """市场状态检测结果"""
    regime: MarketRegimeType
    btc_price: float
    ma20: float
    ma_trend: str  # "rising", "falling", "flat"
    confidence: float  # 0.0 - 1.0
    crossover_count: int  # MA交叉次数 (用于判断震荡)


class MarketRegimeDetector:
    """
    市场环境检测器
    
    基于BTC的20日移动平均线检测市场状态:
    - 牛市: 价格 > MA20 且 MA20 上升
    - 熊市: 价格 < MA20 且 MA20 下降
    - 震荡: 价格频繁穿越 MA20
    """
    
    def __init__(
        self,
        ma_period: int = 20,
        crossover_lookback: int = 10,
        crossover_threshold: int = 3,
        trend_lookback: int = 5
    ):
        """
        初始化市场环境检测器
        
        Args:
            ma_period: 移动平均周期 (默认20)
            crossover_lookback: 交叉检测回溯周期 (默认10)
            crossover_threshold: 判定震荡市的交叉次数阈值 (默认3)
            trend_lookback: MA趋势判断回溯周期 (默认5)
        """
        self.ma_period = ma_period
        self.crossover_lookback = crossover_lookback
        self.crossover_threshold = crossover_threshold
        self.trend_lookback = trend_lookback
        self._current_regime: Optional[MarketRegimeResult] = None
    
    def detect_regime(self, btc_df: pd.DataFrame) -> MarketRegimeResult:
        """
        检测市场状态
        
        Args:
            btc_df: BTC K线数据，需包含 'close' 列
            
        Returns:
            MarketRegimeResult: 市场状态结果
        """
        # 数据验证
        if btc_df is None or btc_df.empty:
            return self._default_result()
        
        if 'close' not in btc_df.columns:
            return self._default_result()
        
        if len(btc_df) < self.ma_period:
            return self._default_result()
        
        try:
            # 计算20日移动平均线
            close_prices = btc_df['close'].astype(float)
            ma20 = close_prices.rolling(window=self.ma_period).mean()
            
            # 获取当前值
            current_price = float(close_prices.iloc[-1])
            current_ma20 = float(ma20.iloc[-1])
            
            if pd.isna(current_ma20):
                return self._default_result()
            
            # 计算MA趋势
            ma_trend = self._calculate_ma_trend(ma20, self.trend_lookback)
            
            # 计算交叉次数
            crossover_count = self._count_crossovers(
                close_prices, ma20, self.crossover_lookback
            )
            
            # 判断市场状态
            regime, confidence = self._classify_regime(
                current_price, current_ma20, ma_trend, crossover_count
            )
            
            result = MarketRegimeResult(
                regime=regime,
                btc_price=current_price,
                ma20=current_ma20,
                ma_trend=ma_trend,
                confidence=confidence,
                crossover_count=crossover_count
            )
            
            self._current_regime = result
            return result
            
        except Exception as e:
            print(f"⚠️ 市场状态检测异常: {e}")
            return self._default_result()
    
    def get_market_regime(self) -> MarketRegimeType:
        """
        获取当前市场状态
        
        Returns:
            MarketRegimeType: 当前市场状态
        """
        if self._current_regime is None:
            return MarketRegimeType.SIDEWAYS
        return self._current_regime.regime
    
    def _calculate_ma_trend(self, ma_series: pd.Series, lookback: int = 5) -> str:
        """
        计算MA趋势方向
        
        Args:
            ma_series: MA序列
            lookback: 回溯周期
            
        Returns:
            str: "rising", "falling", "flat"
        """
        if len(ma_series) < lookback + 1:
            return "flat"
        
        # 获取最近的MA值
        recent_ma = ma_series.iloc[-lookback:].dropna()
        if len(recent_ma) < 2:
            return "flat"
        
        # 计算变化率
        ma_start = float(recent_ma.iloc[0])
        ma_end = float(recent_ma.iloc[-1])
        
        if ma_start == 0:
            return "flat"
        
        change_pct = (ma_end - ma_start) / ma_start * 100
        
        # 阈值判断 (0.5% 作为显著变化阈值)
        if change_pct > 0.5:
            return "rising"
        elif change_pct < -0.5:
            return "falling"
        else:
            return "flat"
    
    def _count_crossovers(
        self, 
        price: pd.Series, 
        ma: pd.Series, 
        lookback: int
    ) -> int:
        """
        计算价格与MA的交叉次数
        
        Args:
            price: 价格序列
            ma: MA序列
            lookback: 回溯周期
            
        Returns:
            int: 交叉次数
        """
        if len(price) < lookback + 1 or len(ma) < lookback + 1:
            return 0
        
        # 获取最近的数据
        recent_price = price.iloc[-lookback:].values
        recent_ma = ma.iloc[-lookback:].values
        
        # 计算价格相对于MA的位置 (1: 上方, -1: 下方)
        position = np.sign(recent_price - recent_ma)
        
        # 计算位置变化 (交叉)
        crossovers = np.abs(np.diff(position))
        
        # 交叉次数 = 位置变化为2的次数 (从上到下或从下到上)
        return int(np.sum(crossovers == 2))
    
    def _classify_regime(
        self,
        price: float,
        ma20: float,
        ma_trend: str,
        crossover_count: int
    ) -> tuple:
        """
        根据条件分类市场状态
        
        Args:
            price: 当前价格
            ma20: 20日MA值
            ma_trend: MA趋势
            crossover_count: 交叉次数
            
        Returns:
            tuple: (MarketRegimeType, confidence)
        """
        # 优先判断震荡市 (交叉次数 >= 阈值)
        if crossover_count >= self.crossover_threshold:
            confidence = min(1.0, crossover_count / (self.crossover_threshold + 2))
            return MarketRegimeType.SIDEWAYS, confidence
        
        # 判断牛市: 价格 > MA20 且 MA 上升
        if price > ma20 and ma_trend == "rising":
            # 计算置信度: 价格偏离MA的程度
            deviation = (price - ma20) / ma20 * 100
            confidence = min(1.0, deviation / 5.0)  # 5%偏离为满置信度
            return MarketRegimeType.BULLISH, max(0.5, confidence)
        
        # 判断熊市: 价格 < MA20 且 MA 下降
        if price < ma20 and ma_trend == "falling":
            deviation = (ma20 - price) / ma20 * 100
            confidence = min(1.0, deviation / 5.0)
            return MarketRegimeType.BEARISH, max(0.5, confidence)
        
        # 其他情况视为震荡
        return MarketRegimeType.SIDEWAYS, 0.5
    
    def _default_result(self) -> MarketRegimeResult:
        """返回默认结果 (数据不足时)"""
        result = MarketRegimeResult(
            regime=MarketRegimeType.SIDEWAYS,
            btc_price=0.0,
            ma20=0.0,
            ma_trend="flat",
            confidence=0.0,
            crossover_count=0
        )
        self._current_regime = result
        return result
