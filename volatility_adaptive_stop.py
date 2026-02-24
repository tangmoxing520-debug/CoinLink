"""
波动率自适应止损 (Volatility Adaptive Stop)
根据币种历史波动率动态调整止损水平

Requirements: 4.1, 4.2, 4.3, 4.4, 4.5
"""
from dataclasses import dataclass
from typing import Optional
import pandas as pd
import numpy as np
import logging

logger = logging.getLogger(__name__)


@dataclass
class AdaptiveStopLoss:
    """自适应止损结果"""
    base_stop_loss: float
    atr_ratio: float
    multiplier: float
    final_stop_loss: float
    reason: str


class VolatilityAdaptiveStop:
    """
    波动率自适应止损
    
    功能:
    1. 计算20周期ATR
    2. ATR > 5%: 放宽止损1.5x
    3. ATR < 2%: 收紧止损0.8x
    4. 止损范围限制在[3%, 15%]
    
    Properties:
    - Property 10: ATR-Based Stop-Loss Adjustment
    - Property 11: Stop-Loss Bounds
    """
    
    ATR_PERIOD = 20
    HIGH_ATR_THRESHOLD = 0.05    # ATR > 5% 视为高波动
    LOW_ATR_THRESHOLD = 0.02     # ATR < 2% 视为低波动
    HIGH_ATR_MULTIPLIER = 1.5    # 高波动放宽止损
    LOW_ATR_MULTIPLIER = 0.8     # 低波动收紧止损
    MIN_STOP_LOSS = 3.0          # 最小止损 3%
    MAX_STOP_LOSS = 15.0         # 最大止损 15%
    
    def __init__(self, base_stop_loss: float = 10.0):
        """
        初始化波动率自适应止损
        
        Args:
            base_stop_loss: 基础止损百分比，默认10%
        """
        self.base_stop_loss = base_stop_loss
    
    def calculate_stop_loss(
        self,
        price_data: pd.DataFrame,
        current_price: float
    ) -> AdaptiveStopLoss:
        """
        计算自适应止损
        
        Property 10: ATR-Based Stop-Loss Adjustment
        - When ATR > 5% of price, stop-loss SHALL be widened by 1.5x
        - When ATR < 2% of price, stop-loss SHALL be tightened by 0.8x
        
        Property 11: Stop-Loss Bounds
        For any stop-loss calculation, the final stop-loss SHALL be clamped to [3%, 15%]
        
        Args:
            price_data: K线数据 (需包含 high, low, close)
            current_price: 当前价格
            
        Returns:
            AdaptiveStopLoss: 止损计算结果
        """
        # 计算ATR
        atr = self._calculate_atr(price_data, self.ATR_PERIOD)
        
        # 处理无效ATR
        if atr <= 0 or current_price <= 0:
            return AdaptiveStopLoss(
                base_stop_loss=self.base_stop_loss,
                atr_ratio=0.0,
                multiplier=1.0,
                final_stop_loss=self._clamp_stop_loss(self.base_stop_loss),
                reason="ATR无效，使用基础止损"
            )
        
        # 计算ATR比率
        atr_ratio = atr / current_price
        
        # 获取乘数
        multiplier = self._get_multiplier(atr_ratio)
        
        # 计算调整后止损
        adjusted_stop_loss = self.base_stop_loss * multiplier
        
        # 限制在有效范围内
        final_stop_loss = self._clamp_stop_loss(adjusted_stop_loss)
        
        # 生成原因说明
        if atr_ratio > self.HIGH_ATR_THRESHOLD:
            reason = f"高波动(ATR={atr_ratio:.2%})，放宽止损{multiplier}x"
        elif atr_ratio < self.LOW_ATR_THRESHOLD:
            reason = f"低波动(ATR={atr_ratio:.2%})，收紧止损{multiplier}x"
        else:
            reason = f"正常波动(ATR={atr_ratio:.2%})，使用基础止损"
        
        return AdaptiveStopLoss(
            base_stop_loss=self.base_stop_loss,
            atr_ratio=atr_ratio,
            multiplier=multiplier,
            final_stop_loss=final_stop_loss,
            reason=reason
        )
    
    def _calculate_atr(
        self,
        price_data: pd.DataFrame,
        period: int = 20
    ) -> float:
        """
        计算ATR (Average True Range)
        
        Args:
            price_data: K线数据
            period: ATR周期
            
        Returns:
            float: ATR值
        """
        if price_data is None or len(price_data) < period:
            return 0.0
        
        try:
            high = price_data['high']
            low = price_data['low']
            close = price_data['close']
            
            # 计算True Range
            tr1 = high - low
            tr2 = abs(high - close.shift(1))
            tr3 = abs(low - close.shift(1))
            
            tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
            
            # 计算ATR
            atr = tr.rolling(window=period).mean()
            
            # 返回最新ATR值
            latest_atr = atr.iloc[-1]
            return float(latest_atr) if pd.notna(latest_atr) else 0.0
            
        except Exception as e:
            logger.warning(f"ATR计算错误: {e}")
            return 0.0
    
    def _get_multiplier(self, atr_ratio: float) -> float:
        """
        根据ATR比率获取乘数
        
        Property 10: ATR-Based Stop-Loss Adjustment
        
        Args:
            atr_ratio: ATR与价格的比率
            
        Returns:
            float: 止损乘数
        """
        if atr_ratio > self.HIGH_ATR_THRESHOLD:
            return self.HIGH_ATR_MULTIPLIER
        elif atr_ratio < self.LOW_ATR_THRESHOLD:
            return self.LOW_ATR_MULTIPLIER
        return 1.0
    
    def _clamp_stop_loss(self, stop_loss: float) -> float:
        """
        限制止损在有效范围内
        
        Property 11: Stop-Loss Bounds
        For any stop-loss calculation, the final stop-loss SHALL be clamped to [3%, 15%]
        
        Args:
            stop_loss: 原始止损百分比
            
        Returns:
            float: 限制后的止损百分比
        """
        return max(self.MIN_STOP_LOSS, min(self.MAX_STOP_LOSS, stop_loss))
    
    def get_atr_ratio(
        self,
        price_data: pd.DataFrame,
        current_price: float
    ) -> float:
        """
        获取ATR比率
        
        Args:
            price_data: K线数据
            current_price: 当前价格
            
        Returns:
            float: ATR比率
        """
        atr = self._calculate_atr(price_data, self.ATR_PERIOD)
        if current_price <= 0:
            return 0.0
        return atr / current_price
