"""
P0优化：统一信号评分器
统一回测和实盘的信号评分逻辑，确保一致性
"""
import pandas as pd
import numpy as np
from typing import Dict, Tuple, Optional
from dataclasses import dataclass
from datetime import datetime
import logging

from config import SIGNAL_SCORE_CONFIG, CATEGORY_WEIGHT_ADJUSTMENTS, ROTATION_CONFIG
from market_regime_detector import MarketRegimeDetector, MarketRegimeType
from rotation_models import SectorTier

logger = logging.getLogger(__name__)


@dataclass
class ScoreBreakdown:
    """评分明细"""
    final_score: float = 0.0
    trend_score: float = 0.0
    volume_score: float = 0.0
    momentum_score: float = 0.0
    volatility_score: float = 0.0
    correlation_score: float = 0.0
    trend_details: Dict = None
    volume_details: Dict = None
    momentum_details: Dict = None
    volatility_details: Dict = None
    correlation_details: Dict = None
    
    def __post_init__(self):
        if self.trend_details is None:
            self.trend_details = {}
        if self.volume_details is None:
            self.volume_details = {}
        if self.momentum_details is None:
            self.momentum_details = {}
        if self.volatility_details is None:
            self.volatility_details = {}
        if self.correlation_details is None:
            self.correlation_details = {}


class UnifiedSignalScorer:
    """
    统一信号评分器
    回测和实盘共用，确保评分一致性
    """
    
    def __init__(self, config: Dict = None):
        """
        初始化评分器
        
        Args:
            config: 评分配置，如果为None则使用默认配置
        """
        self.config = config or SIGNAL_SCORE_CONFIG
        
        # 评分权重
        self.weights = {
            'trend': self.config.get('trend_weight', 0.25),
            'volume': self.config.get('volume_weight', 0.25),
            'momentum': self.config.get('momentum_weight', 0.20),
            'volatility': self.config.get('volatility_weight', 0.15),
            'correlation': self.config.get('correlation_weight', 0.15),
        }
        
        # Hot板块加成
        self.hot_sector_boost = float(ROTATION_CONFIG.get('hot_score_boost', 1.0))
        
        # 市场状态检测器
        self.regime_detector = MarketRegimeDetector()
    
    def calculate_score(
        self,
        df: pd.DataFrame,
        idx: int = None,
        trigger_change: float = 0.0,
        coin_change: float = 0.0,
        trigger_df: pd.DataFrame = None,
        category: str = "",
        sector_tier: SectorTier = None,
        btc_df: pd.DataFrame = None
    ) -> Tuple[float, ScoreBreakdown]:
        """
        计算信号评分（统一接口）
        
        Args:
            df: 币种K线数据
            idx: 当前K线索引（回测使用，实盘为None时使用最后一条）
            trigger_change: 触发币种涨幅
            coin_change: 当前币种涨幅
            trigger_df: 触发币种K线数据（用于相关性计算）
            category: 分类名称
            sector_tier: 板块层级（HOT/WARM/COLD）
            btc_df: BTC K线数据（用于市场状态检测）
            
        Returns:
            (score, breakdown): 评分和评分明细
        """
        breakdown = ScoreBreakdown()
        
        try:
            # 实盘兼容：如果没有idx，使用最后一条数据
            if idx is None:
                if df is None or len(df) < 20:
                    breakdown.final_score = 50.0
                    return 50.0, breakdown
                idx = len(df) - 1
            
            if df is None or len(df) < 20 or idx < 20:
                breakdown.final_score = 50.0
                return 50.0, breakdown
            
            # 1. 趋势评分
            breakdown.trend_score, breakdown.trend_details = self._calculate_trend_score(df, idx)
            
            # 2. 成交量评分
            breakdown.volume_score, breakdown.volume_details = self._calculate_volume_score(df, idx)
            
            # 3. 动量评分
            breakdown.momentum_score, breakdown.momentum_details = self._calculate_momentum_score(
                df, idx, trigger_change, coin_change
            )
            
            # 4. 波动率评分
            breakdown.volatility_score, breakdown.volatility_details = self._calculate_volatility_score(df, idx)
            
            # 5. 相关性评分（如果有触发币数据）
            if trigger_df is not None and len(trigger_df) > 0:
                breakdown.correlation_score, breakdown.correlation_details = self._calculate_correlation_score(
                    df, idx, trigger_df, trigger_change, coin_change
                )
            else:
                breakdown.correlation_score = 50.0  # 默认中等相关性
                breakdown.correlation_details = {'note': 'no trigger data'}
            
            # 加权汇总
            final_score = (
                breakdown.trend_score * self.weights['trend'] +
                breakdown.volume_score * self.weights['volume'] +
                breakdown.momentum_score * self.weights['momentum'] +
                breakdown.volatility_score * self.weights['volatility'] +
                breakdown.correlation_score * self.weights['correlation']
            )
            
            # 归一化到 0-100
            final_score = max(0.0, min(100.0, final_score))
            
            # 分类权重加成
            if category:
                weight = CATEGORY_WEIGHT_ADJUSTMENTS.get(category, 1.0)
                if weight > 1.0:
                    bonus = (weight - 1.0) * 20  # 最多+10分
                    final_score = min(100.0, final_score + bonus)
                    breakdown.trend_details['category_bonus'] = bonus
            
            # Hot板块评分加成
            if sector_tier == SectorTier.HOT and self.hot_sector_boost > 1.0:
                boosted_score = final_score * self.hot_sector_boost
                final_score = min(100.0, boosted_score)
                breakdown.trend_details['hot_sector_boost'] = self.hot_sector_boost
                breakdown.trend_details['pre_boost_score'] = final_score / self.hot_sector_boost
            
            breakdown.final_score = final_score
            
            return final_score, breakdown
            
        except Exception as e:
            logger.error(f"信号评分计算失败: {e}", exc_info=True)
            breakdown.final_score = 50.0
            return 50.0, breakdown
    
    def _calculate_trend_score(self, df: pd.DataFrame, idx: int) -> Tuple[float, Dict]:
        """计算趋势评分 (0-100)"""
        try:
            close = pd.to_numeric(df['close'], errors='coerce')
            if close.isna().all():
                return 50.0, {'error': 'no valid close data'}
            
            # MA指标
            ma5 = close.rolling(5).mean().iloc[idx]
            ma10 = close.rolling(10).mean().iloc[idx]
            ma20 = close.rolling(20).mean().iloc[idx]
            current_price = float(close.iloc[idx])
            
            score = 50.0  # 基础分
            details = {}
            
            # MA多头排列加分
            if pd.notna(ma5) and pd.notna(ma10) and pd.notna(ma20):
                if ma5 > ma10 > ma20:
                    score += 30  # 完美多头排列
                    details['ma_alignment'] = 'perfect_bullish'
                elif ma5 > ma10:
                    score += 15  # 部分多头
                    details['ma_alignment'] = 'partial_bullish'
                elif ma5 < ma10 < ma20:
                    score -= 20  # 空头排列
                    details['ma_alignment'] = 'bearish'
                
                # 价格相对MA位置
                if current_price > ma20:
                    score += 10
                    details['price_vs_ma20'] = 'above'
                elif current_price < ma20 * 0.95:
                    score -= 15
                    details['price_vs_ma20'] = 'below_5pct'
            
            # 趋势强度（价格变化率）
            if idx >= 5:
                price_change_5 = (current_price - float(close.iloc[idx-5])) / float(close.iloc[idx-5]) * 100
                if price_change_5 > 5:
                    score += 10
                    details['momentum_5'] = price_change_5
                elif price_change_5 < -5:
                    score -= 10
                    details['momentum_5'] = price_change_5
            
            score = max(0.0, min(100.0, score))
            return score, details
            
        except Exception as e:
            logger.debug(f"趋势评分计算失败: {e}")
            return 50.0, {'error': str(e)}
    
    def _calculate_volume_score(self, df: pd.DataFrame, idx: int) -> Tuple[float, Dict]:
        """计算成交量评分 (0-100)"""
        try:
            if 'volume' not in df.columns:
                return 50.0, {'error': 'no volume data'}
            
            volume = pd.to_numeric(df['volume'], errors='coerce')
            if volume.isna().all():
                return 50.0, {'error': 'no valid volume data'}
            
            score = 50.0
            details = {}
            
            # 当前成交量 vs 平均成交量
            if idx >= 20:
                current_vol = float(volume.iloc[idx])
                avg_vol = float(volume.iloc[idx-20:idx].mean())
                
                if avg_vol > 0:
                    vol_ratio = current_vol / avg_vol
                    details['volume_ratio'] = vol_ratio
                    
                    if vol_ratio > 2.0:
                        score += 30  # 成交量大幅放大
                    elif vol_ratio > 1.5:
                        score += 20  # 成交量明显放大
                    elif vol_ratio > 1.2:
                        score += 10  # 成交量适度放大
                    elif vol_ratio < 0.5:
                        score -= 20  # 成交量萎缩
                    elif vol_ratio < 0.8:
                        score -= 10  # 成交量略低
            
            score = max(0.0, min(100.0, score))
            return score, details
            
        except Exception as e:
            logger.debug(f"成交量评分计算失败: {e}")
            return 50.0, {'error': str(e)}
    
    def _calculate_momentum_score(
        self,
        df: pd.DataFrame,
        idx: int,
        trigger_change: float,
        coin_change: float
    ) -> Tuple[float, Dict]:
        """计算动量评分 (0-100)"""
        try:
            score = 50.0
            details = {}
            
            # 触发币涨幅
            if trigger_change > 0:
                if trigger_change > 5:
                    score += 20
                elif trigger_change > 3:
                    score += 15
                elif trigger_change > 1:
                    score += 10
                details['trigger_change'] = trigger_change
            
            # 当前币涨幅
            if coin_change > 0:
                if coin_change > 3:
                    score += 15
                elif coin_change > 1:
                    score += 10
                details['coin_change'] = coin_change
            
            # 跟涨比例（涨幅小于触发币，说明有跟涨空间）
            if trigger_change > 0 and coin_change < trigger_change:
                follow_ratio = coin_change / trigger_change
                if follow_ratio < 0.5:  # 跟涨不足50%，有较大空间
                    score += 15
                elif follow_ratio < 0.8:  # 跟涨50-80%
                    score += 10
                details['follow_ratio'] = follow_ratio
            
            score = max(0.0, min(100.0, score))
            return score, details
            
        except Exception as e:
            logger.debug(f"动量评分计算失败: {e}")
            return 50.0, {'error': str(e)}
    
    def _calculate_volatility_score(self, df: pd.DataFrame, idx: int) -> Tuple[float, Dict]:
        """计算波动率评分 (0-100)"""
        try:
            close = pd.to_numeric(df['close'], errors='coerce')
            if close.isna().all() or idx < 20:
                return 50.0, {'error': 'insufficient data'}
            
            score = 50.0
            details = {}
            
            # 计算ATR（平均真实波幅）
            if 'high' in df.columns and 'low' in df.columns:
                high = pd.to_numeric(df['high'], errors='coerce')
                low = pd.to_numeric(df['low'], errors='coerce')
                
                if idx >= 14:
                    # 计算最近14期的ATR
                    tr_list = []
                    for i in range(max(1, idx-13), idx+1):
                        if i > 0:
                            tr = max(
                                float(high.iloc[i]) - float(low.iloc[i]),
                                abs(float(high.iloc[i]) - float(close.iloc[i-1])),
                                abs(float(low.iloc[i]) - float(close.iloc[i-1]))
                            )
                            tr_list.append(tr)
                    
                    if tr_list:
                        atr = np.mean(tr_list)
                        current_price = float(close.iloc[idx])
                        atr_pct = (atr / current_price) * 100 if current_price > 0 else 0
                        
                        details['atr_pct'] = atr_pct
                        
                        # 适度的波动率是好的（2-5%），过高或过低都不好
                        if 2 <= atr_pct <= 5:
                            score += 20  # 理想波动率
                        elif 1 <= atr_pct < 2 or 5 < atr_pct <= 8:
                            score += 10  # 可接受波动率
                        elif atr_pct > 10:
                            score -= 15  # 波动率过高
                        elif atr_pct < 0.5:
                            score -= 10  # 波动率过低
            
            score = max(0.0, min(100.0, score))
            return score, details
            
        except Exception as e:
            logger.debug(f"波动率评分计算失败: {e}")
            return 50.0, {'error': str(e)}
    
    def _calculate_correlation_score(
        self,
        df: pd.DataFrame,
        idx: int,
        trigger_df: pd.DataFrame,
        trigger_change: float,
        coin_change: float
    ) -> Tuple[float, Dict]:
        """计算相关性评分 (0-100)"""
        try:
            score = 50.0
            details = {}
            
            # 简单的相关性评分：基于涨幅相关性
            if trigger_change > 0 and coin_change > 0:
                # 正相关：两个币都上涨
                correlation = min(coin_change / trigger_change, 1.0) if trigger_change > 0 else 0
                
                # 适度的相关性最好（0.3-0.7）
                if 0.3 <= correlation <= 0.7:
                    score += 20  # 理想相关性
                elif 0.1 <= correlation < 0.3 or 0.7 < correlation <= 0.9:
                    score += 10  # 可接受相关性
                elif correlation > 0.9:
                    score -= 10  # 相关性过高（可能同步上涨，没有优势）
                elif correlation < 0.1:
                    score -= 15  # 相关性过低（可能不跟涨）
                
                details['correlation_ratio'] = correlation
            
            # 如果触发币涨幅很大但当前币涨幅很小，说明有跟涨空间
            if trigger_change > 3 and coin_change < trigger_change * 0.5:
                score += 15
                details['follow_up_potential'] = True
            
            score = max(0.0, min(100.0, score))
            return score, details
            
        except Exception as e:
            logger.debug(f"相关性评分计算失败: {e}")
            return 50.0, {'error': str(e)}
