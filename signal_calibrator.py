"""
信号校准器 (Signal Calibrator)
校准信号评分，整合成交量、波动率和市场环境因素

Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6
"""
from dataclasses import dataclass
from typing import Optional, Tuple

from market_regime_detector import MarketRegimeType


@dataclass
class CalibrationResult:
    """校准结果"""
    raw_score: float
    volume_adjustment: float
    volatility_adjustment: float
    regime_adjustment: float
    final_score: float
    should_skip: bool
    skip_reason: Optional[str] = None


class SignalCalibrator:
    """
    信号校准器
    
    功能:
    1. 成交量加成: volume_ratio > 1.5 时加 10 分
    2. 波动率惩罚: atr_ratio > 2.0 时减 15 分
    3. 市场环境调整: 牛市 +10, 熊市 -10
    4. 交易跳过建议:
       - 评分 < 70 跳过
       - 熊市且评分 < 80 跳过
    """
    
    # 成交量加成参数
    VOLUME_BONUS_THRESHOLD = 1.5
    VOLUME_BONUS_POINTS = 10
    
    # 波动率惩罚参数
    VOLATILITY_PENALTY_THRESHOLD = 2.0
    VOLATILITY_PENALTY_POINTS = 15
    
    # 市场环境调整参数
    BULLISH_BONUS_POINTS = 10
    BEARISH_PENALTY_POINTS = 10
    
    # 最低评分阈值
    NORMAL_MIN_SCORE = 70
    BEARISH_MIN_SCORE = 80
    
    def __init__(
        self,
        volume_bonus_threshold: float = 1.5,
        volume_bonus_points: float = 10,
        volatility_penalty_threshold: float = 2.0,
        volatility_penalty_points: float = 15,
        bullish_bonus_points: float = 10,
        bearish_penalty_points: float = 10,
        normal_min_score: float = 70,
        bearish_min_score: float = 80
    ):
        self.volume_bonus_threshold = volume_bonus_threshold
        self.volume_bonus_points = volume_bonus_points
        self.volatility_penalty_threshold = volatility_penalty_threshold
        self.volatility_penalty_points = volatility_penalty_points
        self.bullish_bonus_points = bullish_bonus_points
        self.bearish_penalty_points = bearish_penalty_points
        self.normal_min_score = normal_min_score
        self.bearish_min_score = bearish_min_score
    
    def calibrate_signal(
        self,
        raw_score: float,
        volume_ratio: float,
        atr_ratio: float,
        market_regime: MarketRegimeType
    ) -> CalibrationResult:
        """
        校准信号评分
        
        Args:
            raw_score: 原始信号评分 (0-100)
            volume_ratio: 成交量比率 (当前/平均)
            atr_ratio: ATR比率 (当前/平均)
            market_regime: 市场状态
            
        Returns:
            CalibrationResult: 校准结果
        """
        # 限制原始评分范围
        raw_score = max(0, min(100, raw_score))
        
        # 处理无效比率
        if volume_ratio <= 0:
            volume_ratio = 1.0
        if atr_ratio <= 0:
            atr_ratio = 1.0
        
        # 计算成交量调整
        volume_adjustment = 0.0
        if volume_ratio > self.volume_bonus_threshold:
            volume_adjustment = self.volume_bonus_points
        
        # 计算波动率调整
        volatility_adjustment = 0.0
        if atr_ratio > self.volatility_penalty_threshold:
            volatility_adjustment = -self.volatility_penalty_points
        
        # 计算市场环境调整
        regime_adjustment = 0.0
        if market_regime == MarketRegimeType.BULLISH:
            regime_adjustment = self.bullish_bonus_points
        elif market_regime == MarketRegimeType.BEARISH:
            regime_adjustment = -self.bearish_penalty_points
        # SIDEWAYS 不调整
        
        # 计算最终评分
        final_score = raw_score + volume_adjustment + volatility_adjustment + regime_adjustment
        
        # 限制最终评分范围
        final_score = max(0, min(100, final_score))
        
        # 判断是否跳过
        should_skip, skip_reason = self.should_skip_trade(final_score, market_regime)
        
        return CalibrationResult(
            raw_score=raw_score,
            volume_adjustment=volume_adjustment,
            volatility_adjustment=volatility_adjustment,
            regime_adjustment=regime_adjustment,
            final_score=final_score,
            should_skip=should_skip,
            skip_reason=skip_reason
        )
    
    def should_skip_trade(
        self,
        score: float,
        market_regime: MarketRegimeType
    ) -> Tuple[bool, Optional[str]]:
        """
        判断是否应跳过交易
        
        Args:
            score: 校准后评分
            market_regime: 市场状态
            
        Returns:
            Tuple[bool, Optional[str]]: (是否跳过, 跳过原因)
        """
        # 评分低于 70 跳过
        if score < self.normal_min_score:
            return True, f"评分 {score:.1f} 低于最低阈值 {self.normal_min_score}"
        
        # 熊市且评分低于 80 跳过
        if market_regime == MarketRegimeType.BEARISH and score < self.bearish_min_score:
            return True, f"熊市评分 {score:.1f} 低于熊市阈值 {self.bearish_min_score}"
        
        return False, None
    
    def get_adjustment_breakdown(
        self,
        volume_ratio: float,
        atr_ratio: float,
        market_regime: MarketRegimeType
    ) -> dict:
        """
        获取调整分解详情
        
        Args:
            volume_ratio: 成交量比率
            atr_ratio: ATR比率
            market_regime: 市场状态
            
        Returns:
            dict: 调整详情
        """
        breakdown = {
            'volume': {
                'ratio': volume_ratio,
                'threshold': self.volume_bonus_threshold,
                'adjustment': self.volume_bonus_points if volume_ratio > self.volume_bonus_threshold else 0,
                'triggered': volume_ratio > self.volume_bonus_threshold
            },
            'volatility': {
                'ratio': atr_ratio,
                'threshold': self.volatility_penalty_threshold,
                'adjustment': -self.volatility_penalty_points if atr_ratio > self.volatility_penalty_threshold else 0,
                'triggered': atr_ratio > self.volatility_penalty_threshold
            },
            'regime': {
                'type': market_regime.value,
                'adjustment': self.bullish_bonus_points if market_regime == MarketRegimeType.BULLISH 
                             else -self.bearish_penalty_points if market_regime == MarketRegimeType.BEARISH 
                             else 0
            }
        }
        
        breakdown['total_adjustment'] = (
            breakdown['volume']['adjustment'] + 
            breakdown['volatility']['adjustment'] + 
            breakdown['regime']['adjustment']
        )
        
        return breakdown
