"""
板块轮动管理器

实现板块强度计算、层级分类、权重分配和信号检测功能。
"""
from datetime import datetime
from typing import Dict, List, Optional
import pandas as pd
import numpy as np

from rotation_models import (
    RotationConfig, SectorStrength, CoinData, SectorData
)


class StrengthCalculator:
    """
    板块强度计算器
    
    计算各板块的综合强度评分，基于四个维度：
    - 动量评分 (momentum_score)
    - 成交量评分 (volume_score)
    - 相对强度评分 (relative_strength_score)
    - 龙头币评分 (leader_score)
    """
    
    def __init__(self, config: RotationConfig):
        """
        初始化强度计算器
        
        Args:
            config: 板块轮动配置
        """
        self.config = config
    
    def calculate_strength(
        self,
        sector: str,
        coins_data: List[CoinData],
        btc_data: Optional[pd.DataFrame],
        leader_coin: str
    ) -> SectorStrength:
        """
        计算单个板块的强度评分
        
        公式: score = w1*momentum + w2*volume + w3*relative_strength + w4*leader
        
        各维度评分范围: 0-100
        最终评分归一化到: 0-100
        
        Args:
            sector: 板块名称
            coins_data: 板块内币种数据列表
            btc_data: BTC参考数据 (DataFrame with 'close' column)
            leader_coin: 龙头币符号
            
        Returns:
            SectorStrength: 板块强度数据
        """
        timestamp = datetime.now()
        
        # 处理空数据情况
        if not coins_data:
            return SectorStrength(
                sector=sector,
                score=50.0,
                momentum_score=50.0,
                volume_score=50.0,
                relative_strength_score=50.0,
                leader_score=50.0,
                confidence="none",
                timestamp=timestamp
            )
        
        # 过滤有效数据的币种
        valid_coins = [c for c in coins_data if c.price_change_pct is not None]
        
        if not valid_coins:
            return SectorStrength(
                sector=sector,
                score=50.0,
                momentum_score=50.0,
                volume_score=50.0,
                relative_strength_score=50.0,
                leader_score=50.0,
                confidence="none",
                timestamp=timestamp
            )
        
        # 确定置信度
        confidence = "high" if len(valid_coins) >= 3 else "low"
        
        # 计算各维度评分
        momentum_score = self._calculate_momentum_score(valid_coins)
        volume_score = self._calculate_volume_score(valid_coins)
        relative_strength_score = self._calculate_relative_strength_score(
            valid_coins, btc_data
        )
        
        # 查找龙头币数据
        leader_data = None
        for coin in coins_data:
            if coin.symbol == leader_coin:
                leader_data = coin
                break
        leader_score = self._calculate_leader_score(leader_data)
        
        # 计算加权综合评分
        final_score = (
            self.config.momentum_weight * momentum_score +
            self.config.volume_weight * volume_score +
            self.config.relative_strength_weight * relative_strength_score +
            self.config.leader_weight * leader_score
        )
        
        # 确保评分在 0-100 范围内
        final_score = max(0.0, min(100.0, final_score))
        
        return SectorStrength(
            sector=sector,
            score=final_score,
            momentum_score=momentum_score,
            volume_score=volume_score,
            relative_strength_score=relative_strength_score,
            leader_score=leader_score,
            confidence=confidence,
            timestamp=timestamp
        )
    
    def _calculate_momentum_score(self, coins_data: List[CoinData]) -> float:
        """
        计算动量评分
        
        基于板块内所有币种的平均涨幅:
        - 涨幅 > 5%: 80-100分
        - 涨幅 2-5%: 60-80分
        - 涨幅 0-2%: 40-60分
        - 涨幅 -2-0%: 20-40分
        - 涨幅 < -2%: 0-20分
        
        Args:
            coins_data: 币种数据列表
            
        Returns:
            float: 动量评分 (0-100)
        """
        if not coins_data:
            return 50.0
        
        # 计算平均涨幅
        price_changes = [c.price_change_pct for c in coins_data 
                        if c.price_change_pct is not None]
        
        if not price_changes:
            return 50.0
        
        avg_change = sum(price_changes) / len(price_changes)
        
        # 根据涨幅区间映射到评分
        if avg_change > 5.0:
            # 涨幅 > 5%: 80-100分，线性插值
            score = 80.0 + min(20.0, (avg_change - 5.0) * 2.0)
        elif avg_change > 2.0:
            # 涨幅 2-5%: 60-80分
            score = 60.0 + (avg_change - 2.0) * (20.0 / 3.0)
        elif avg_change > 0.0:
            # 涨幅 0-2%: 40-60分
            score = 40.0 + avg_change * 10.0
        elif avg_change > -2.0:
            # 涨幅 -2-0%: 20-40分
            score = 20.0 + (avg_change + 2.0) * 10.0
        else:
            # 涨幅 < -2%: 0-20分
            score = max(0.0, 20.0 + (avg_change + 2.0) * 2.0)
        
        return max(0.0, min(100.0, score))
    
    def _calculate_volume_score(self, coins_data: List[CoinData]) -> float:
        """
        计算成交量评分
        
        基于成交量相对20周期均值的比率:
        - ratio > 2.0: 80-100分
        - ratio 1.5-2.0: 60-80分
        - ratio 1.0-1.5: 40-60分
        - ratio 0.5-1.0: 20-40分
        - ratio < 0.5: 0-20分
        
        Args:
            coins_data: 币种数据列表
            
        Returns:
            float: 成交量评分 (0-100)
        """
        if not coins_data:
            return 50.0
        
        # 计算平均成交量比率
        volume_ratios = [c.volume_ratio for c in coins_data 
                        if c.volume_ratio is not None and c.volume_ratio > 0]
        
        if not volume_ratios:
            return 50.0
        
        avg_ratio = sum(volume_ratios) / len(volume_ratios)
        
        # 根据比率区间映射到评分
        if avg_ratio > 2.0:
            # ratio > 2.0: 80-100分
            score = 80.0 + min(20.0, (avg_ratio - 2.0) * 10.0)
        elif avg_ratio > 1.5:
            # ratio 1.5-2.0: 60-80分
            score = 60.0 + (avg_ratio - 1.5) * 40.0
        elif avg_ratio > 1.0:
            # ratio 1.0-1.5: 40-60分
            score = 40.0 + (avg_ratio - 1.0) * 40.0
        elif avg_ratio > 0.5:
            # ratio 0.5-1.0: 20-40分
            score = 20.0 + (avg_ratio - 0.5) * 40.0
        else:
            # ratio < 0.5: 0-20分
            score = max(0.0, avg_ratio * 40.0)
        
        return max(0.0, min(100.0, score))
    
    def _calculate_relative_strength_score(
        self,
        coins_data: List[CoinData],
        btc_data: Optional[pd.DataFrame]
    ) -> float:
        """
        计算相对强度评分 (vs BTC)
        
        基于板块平均涨幅 - BTC涨幅 = 超额收益:
        - 超额收益 > 3%: 80-100分
        - 超额收益 1-3%: 60-80分
        - 超额收益 -1-1%: 40-60分
        - 超额收益 -3--1%: 20-40分
        - 超额收益 < -3%: 0-20分
        
        Args:
            coins_data: 币种数据列表
            btc_data: BTC参考数据
            
        Returns:
            float: 相对强度评分 (0-100)
        """
        if not coins_data:
            return 50.0
        
        # 计算板块平均涨幅
        price_changes = [c.price_change_pct for c in coins_data 
                        if c.price_change_pct is not None]
        
        if not price_changes:
            return 50.0
        
        avg_sector_change = sum(price_changes) / len(price_changes)
        
        # 获取BTC涨幅
        btc_change = 0.0
        if btc_data is not None and len(btc_data) >= 2:
            try:
                if 'close' in btc_data.columns:
                    first_price = btc_data['close'].iloc[0]
                    last_price = btc_data['close'].iloc[-1]
                    if first_price > 0:
                        btc_change = ((last_price - first_price) / first_price) * 100.0
            except (KeyError, IndexError):
                btc_change = 0.0
        
        # 计算超额收益
        excess_return = avg_sector_change - btc_change
        
        # 根据超额收益区间映射到评分
        if excess_return > 3.0:
            # 超额收益 > 3%: 80-100分
            score = 80.0 + min(20.0, (excess_return - 3.0) * 4.0)
        elif excess_return > 1.0:
            # 超额收益 1-3%: 60-80分
            score = 60.0 + (excess_return - 1.0) * 10.0
        elif excess_return > -1.0:
            # 超额收益 -1-1%: 40-60分
            score = 40.0 + (excess_return + 1.0) * 10.0
        elif excess_return > -3.0:
            # 超额收益 -3--1%: 20-40分
            score = 20.0 + (excess_return + 3.0) * 10.0
        else:
            # 超额收益 < -3%: 0-20分
            score = max(0.0, 20.0 + (excess_return + 3.0) * 4.0)
        
        return max(0.0, min(100.0, score))
    
    def _calculate_leader_score(self, leader_data: Optional[CoinData]) -> float:
        """
        计算龙头币评分
        
        基于龙头币涨幅和成交量的综合评估:
        - 龙头币表现强劲通常预示板块即将启动
        
        评分规则:
        - 涨幅评分 (60%权重): 同动量评分逻辑
        - 成交量评分 (40%权重): 同成交量评分逻辑
        
        Args:
            leader_data: 龙头币数据
            
        Returns:
            float: 龙头币评分 (0-100)
        """
        if leader_data is None:
            return 50.0
        
        # 计算涨幅评分
        price_change = leader_data.price_change_pct or 0.0
        
        if price_change > 5.0:
            price_score = 80.0 + min(20.0, (price_change - 5.0) * 2.0)
        elif price_change > 2.0:
            price_score = 60.0 + (price_change - 2.0) * (20.0 / 3.0)
        elif price_change > 0.0:
            price_score = 40.0 + price_change * 10.0
        elif price_change > -2.0:
            price_score = 20.0 + (price_change + 2.0) * 10.0
        else:
            price_score = max(0.0, 20.0 + (price_change + 2.0) * 2.0)
        
        # 计算成交量评分
        volume_ratio = leader_data.volume_ratio or 1.0
        
        if volume_ratio > 2.0:
            volume_score = 80.0 + min(20.0, (volume_ratio - 2.0) * 10.0)
        elif volume_ratio > 1.5:
            volume_score = 60.0 + (volume_ratio - 1.5) * 40.0
        elif volume_ratio > 1.0:
            volume_score = 40.0 + (volume_ratio - 1.0) * 40.0
        elif volume_ratio > 0.5:
            volume_score = 20.0 + (volume_ratio - 0.5) * 40.0
        else:
            volume_score = max(0.0, volume_ratio * 40.0)
        
        # 综合评分: 涨幅60% + 成交量40%
        final_score = price_score * 0.6 + volume_score * 0.4
        
        return max(0.0, min(100.0, final_score))


import math
from rotation_models import SectorTier, SectorClassification


class TierClassifier:
    """
    板块层级分类器
    
    根据强度评分对板块进行分类:
    - Hot: 评分排名前25%
    - Warm: 评分排名25-50%
    - Neutral: 评分排名50-75%
    - Cold: 评分排名后25%
    """
    
    def classify_sectors(
        self,
        strengths: List[SectorStrength],
        previous_classifications: Optional[Dict[str, SectorClassification]] = None
    ) -> List[SectorClassification]:
        """
        根据强度评分对板块进行分类
        
        分类规则:
        - Hot: 评分排名前25% (rank <= ceil(N * 0.25))
        - Warm: 评分排名25-50% (rank in (ceil(N * 0.25), ceil(N * 0.50)])
        - Neutral: 评分排名50-75% (rank in (ceil(N * 0.50), ceil(N * 0.75)])
        - Cold: 评分排名后25% (rank > ceil(N * 0.75))
        
        Args:
            strengths: 板块强度数据列表
            previous_classifications: 上一次的分类结果 (用于检测动量转换)
            
        Returns:
            List[SectorClassification]: 板块分类结果列表
        """
        if not strengths:
            return []
        
        n = len(strengths)
        
        # 按评分降序排序
        sorted_strengths = sorted(strengths, key=lambda x: x.score, reverse=True)
        
        # 计算各层级的边界排名
        hot_boundary = math.ceil(n * 0.25)
        warm_boundary = math.ceil(n * 0.50)
        neutral_boundary = math.ceil(n * 0.75)
        
        classifications = []
        
        for rank, strength in enumerate(sorted_strengths, start=1):
            # 确定层级
            if rank <= hot_boundary:
                tier = SectorTier.HOT
            elif rank <= warm_boundary:
                tier = SectorTier.WARM
            elif rank <= neutral_boundary:
                tier = SectorTier.NEUTRAL
            else:
                tier = SectorTier.COLD
            
            # 获取上一次的层级
            prev_tier = None
            momentum_shift = False
            
            if previous_classifications and strength.sector in previous_classifications:
                prev_classification = previous_classifications[strength.sector]
                prev_tier = prev_classification.tier
                
                # 检测动量转换 (需要上一次的评分)
                # 这里我们通过层级变化来近似判断
                # 实际的动量转换检测在 detect_momentum_shift 方法中
            
            classifications.append(SectorClassification(
                sector=strength.sector,
                tier=tier,
                rank=rank,
                score=strength.score,
                prev_tier=prev_tier,
                momentum_shift=momentum_shift
            ))
        
        return classifications
    
    def detect_momentum_shift(
        self,
        current: SectorStrength,
        previous: SectorStrength
    ) -> bool:
        """
        检测动量转换
        
        当评分变化超过20点时，标记为动量转换
        
        Args:
            current: 当前强度数据
            previous: 上一次强度数据
            
        Returns:
            bool: 是否发生动量转换
        """
        if current is None or previous is None:
            return False
        
        score_diff = abs(current.score - previous.score)
        return score_diff > 20.0
    
    def update_momentum_shifts(
        self,
        classifications: List[SectorClassification],
        current_strengths: Dict[str, SectorStrength],
        previous_strengths: Dict[str, SectorStrength]
    ) -> List[SectorClassification]:
        """
        更新分类结果中的动量转换标记
        
        Args:
            classifications: 分类结果列表
            current_strengths: 当前强度数据字典
            previous_strengths: 上一次强度数据字典
            
        Returns:
            List[SectorClassification]: 更新后的分类结果列表
        """
        updated = []
        
        for classification in classifications:
            sector = classification.sector
            momentum_shift = False
            
            if sector in current_strengths and sector in previous_strengths:
                momentum_shift = self.detect_momentum_shift(
                    current_strengths[sector],
                    previous_strengths[sector]
                )
            
            updated.append(SectorClassification(
                sector=classification.sector,
                tier=classification.tier,
                rank=classification.rank,
                score=classification.score,
                prev_tier=classification.prev_tier,
                momentum_shift=momentum_shift
            ))
        
        return updated


from rotation_models import SectorWeight


class WeightAllocator:
    """
    权重分配器
    
    根据板块层级分配仓位权重:
    - Hot: 1.5x - 2.0x 基础权重
    - Warm: 1.0x - 1.5x 基础权重
    - Neutral: 0.5x - 1.0x 基础权重
    - Cold: 0.25x - 0.5x 基础权重
    """
    
    def __init__(self, config: RotationConfig):
        """
        初始化权重分配器
        
        Args:
            config: 板块轮动配置
        """
        self.config = config
        self.tier_multipliers = {
            SectorTier.HOT: (1.5, 2.0),
            SectorTier.WARM: (1.0, 1.5),
            SectorTier.NEUTRAL: (0.5, 1.0),
            SectorTier.COLD: (0.25, 0.5)
        }
    
    def allocate_weights(
        self,
        classifications: List[SectorClassification]
    ) -> Dict[str, SectorWeight]:
        """
        分配板块权重
        
        算法:
        1. 根据层级确定倍数范围
        2. 在范围内根据评分线性插值
        3. 应用最小权重下限
        4. 归一化确保总和为100%
        
        Args:
            classifications: 板块分类结果列表
            
        Returns:
            Dict[str, SectorWeight]: 板块名称 -> 权重数据
        """
        if not classifications:
            return {}
        
        # 按层级分组，计算每个层级内的评分范围
        tier_scores: Dict[SectorTier, List[float]] = {
            SectorTier.HOT: [],
            SectorTier.WARM: [],
            SectorTier.NEUTRAL: [],
            SectorTier.COLD: []
        }
        
        for c in classifications:
            tier_scores[c.tier].append(c.score)
        
        # 计算每个板块的倍数
        raw_weights: Dict[str, float] = {}
        multipliers: Dict[str, float] = {}
        tiers: Dict[str, SectorTier] = {}
        
        for classification in classifications:
            multiplier = self._calculate_multiplier(
                classification.tier,
                classification.score,
                tier_scores[classification.tier]
            )
            multipliers[classification.sector] = multiplier
            tiers[classification.sector] = classification.tier
            raw_weights[classification.sector] = multiplier
        
        # 应用最小权重下限
        floored_weights = self._apply_floor(raw_weights, self.config.min_sector_weight)
        
        # 归一化权重
        normalized_weights = self._normalize_weights(floored_weights)
        
        # 构建结果
        result: Dict[str, SectorWeight] = {}
        for sector, weight in normalized_weights.items():
            result[sector] = SectorWeight(
                sector=sector,
                weight=weight,
                multiplier=multipliers[sector],
                tier=tiers[sector]
            )
        
        return result
    
    def _calculate_multiplier(
        self,
        tier: SectorTier,
        score: float,
        tier_scores: List[float]
    ) -> float:
        """
        计算具体倍数 (在层级范围内插值)
        
        Args:
            tier: 板块层级
            score: 板块评分
            tier_scores: 该层级内所有板块的评分列表
            
        Returns:
            float: 权重倍数
        """
        min_mult, max_mult = self.tier_multipliers[tier]
        
        if not tier_scores or len(tier_scores) == 1:
            # 只有一个板块，使用中间值
            return (min_mult + max_mult) / 2
        
        # 在层级内根据评分排名进行插值
        min_score = min(tier_scores)
        max_score = max(tier_scores)
        
        if max_score == min_score:
            # 所有评分相同，使用中间值
            return (min_mult + max_mult) / 2
        
        # 线性插值: 评分越高，倍数越大
        ratio = (score - min_score) / (max_score - min_score)
        multiplier = min_mult + ratio * (max_mult - min_mult)
        
        return multiplier
    
    def _apply_floor(
        self,
        weights: Dict[str, float],
        floor: float
    ) -> Dict[str, float]:
        """
        应用最小权重下限
        
        确保每个板块的权重不低于最小下限
        
        Args:
            weights: 原始权重字典
            floor: 最小权重下限
            
        Returns:
            Dict[str, float]: 应用下限后的权重字典
        """
        if not weights:
            return {}
        
        # 先归一化到总和为1
        total = sum(weights.values())
        if total <= 0:
            # 如果总和为0，使用等权分配
            n = len(weights)
            return {k: 1.0 / n for k in weights}
        
        normalized = {k: v / total for k, v in weights.items()}
        
        # 应用下限
        floored = {}
        for sector, weight in normalized.items():
            floored[sector] = max(weight, floor)
        
        return floored
    
    def _normalize_weights(
        self,
        weights: Dict[str, float]
    ) -> Dict[str, float]:
        """
        归一化权重使总和为1.0
        
        Args:
            weights: 权重字典
            
        Returns:
            Dict[str, float]: 归一化后的权重字典
        """
        if not weights:
            return {}
        
        total = sum(weights.values())
        
        if total <= 0:
            # 如果总和为0，使用等权分配
            n = len(weights)
            return {k: 1.0 / n for k in weights}
        
        return {k: v / total for k, v in weights.items()}


from rotation_models import RotationSignalType, RotationSignal, RotationSnapshot


class SignalDetector:
    """
    轮动信号检测器
    
    检测以下类型的信号:
    - SECTOR_BREAKOUT: 板块突破 (Cold -> Hot within 24h)
    - SECTOR_BREAKDOWN: 板块崩溃 (Hot -> Cold within 24h)
    - BROAD_RALLY: 广泛上涨 (>=3板块同步上涨)
    - BROAD_SELLOFF: 广泛下跌 (>=3板块同步下跌)
    - MOMENTUM_SHIFT: 动量转换
    """
    
    def __init__(self, strength_change_threshold: float = 10.0):
        """
        初始化信号检测器
        
        Args:
            strength_change_threshold: 同步运动的强度变化阈值
        """
        self.strength_change_threshold = strength_change_threshold
    
    def detect_signals(
        self,
        current_classifications: List[SectorClassification],
        history: List[RotationSnapshot],
        lookback_hours: int = 24
    ) -> List[RotationSignal]:
        """
        检测所有轮动信号
        
        Args:
            current_classifications: 当前板块分类结果
            history: 历史轮动快照列表
            lookback_hours: 回溯时间窗口 (小时)
            
        Returns:
            List[RotationSignal]: 检测到的信号列表
        """
        signals = []
        current_time = datetime.now()
        
        if not current_classifications:
            return signals
        
        # 获取历史分类数据
        historical_classifications = self._get_historical_classifications(
            history, lookback_hours
        )
        
        # 检测层级转换信号
        tier_signals = self._detect_tier_transitions(
            current_classifications, historical_classifications
        )
        signals.extend(tier_signals)
        
        # 获取历史强度数据用于同步运动检测
        historical_strengths = self._get_historical_strengths(history, lookback_hours)
        
        # 检测同步运动信号
        sync_signals = self._detect_synchronized_movements(
            current_classifications, historical_strengths
        )
        signals.extend(sync_signals)
        
        return signals
    
    def _get_historical_classifications(
        self,
        history: List[RotationSnapshot],
        lookback_hours: int
    ) -> List[SectorClassification]:
        """
        获取指定时间窗口内的历史分类数据
        
        Args:
            history: 历史快照列表
            lookback_hours: 回溯时间窗口
            
        Returns:
            List[SectorClassification]: 历史分类数据
        """
        if not history:
            return []
        
        cutoff_time = datetime.now() - pd.Timedelta(hours=lookback_hours)
        
        # 查找最早的符合条件的快照
        for snapshot in reversed(history):
            if snapshot.timestamp <= cutoff_time:
                return list(snapshot.classifications.values())
        
        # 如果没有足够早的数据，返回最早的快照
        if history:
            return list(history[0].classifications.values())
        
        return []
    
    def _get_historical_strengths(
        self,
        history: List[RotationSnapshot],
        lookback_hours: int
    ) -> Dict[str, SectorStrength]:
        """
        获取指定时间窗口内的历史强度数据
        
        Args:
            history: 历史快照列表
            lookback_hours: 回溯时间窗口
            
        Returns:
            Dict[str, SectorStrength]: 历史强度数据
        """
        if not history:
            return {}
        
        cutoff_time = datetime.now() - pd.Timedelta(hours=lookback_hours)
        
        # 查找最早的符合条件的快照
        for snapshot in reversed(history):
            if snapshot.timestamp <= cutoff_time:
                return snapshot.strengths
        
        # 如果没有足够早的数据，返回最早的快照
        if history:
            return history[0].strengths
        
        return {}
    
    def _detect_tier_transitions(
        self,
        current: List[SectorClassification],
        historical: List[SectorClassification]
    ) -> List[RotationSignal]:
        """
        检测层级转换信号
        
        - Cold -> Hot: SECTOR_BREAKOUT
        - Hot -> Cold: SECTOR_BREAKDOWN
        
        Args:
            current: 当前分类结果
            historical: 历史分类结果
            
        Returns:
            List[RotationSignal]: 层级转换信号列表
        """
        signals = []
        current_time = datetime.now()
        
        if not historical:
            return signals
        
        # 构建历史分类字典
        hist_dict = {c.sector: c for c in historical}
        
        for curr_class in current:
            sector = curr_class.sector
            
            if sector not in hist_dict:
                continue
            
            hist_class = hist_dict[sector]
            
            # Cold -> Hot: Breakout
            if hist_class.tier == SectorTier.COLD and curr_class.tier == SectorTier.HOT:
                signals.append(RotationSignal(
                    signal_type=RotationSignalType.SECTOR_BREAKOUT,
                    sectors=[sector],
                    timestamp=current_time,
                    details={
                        "prev_tier": hist_class.tier.value,
                        "curr_tier": curr_class.tier.value,
                        "prev_score": hist_class.score,
                        "curr_score": curr_class.score
                    }
                ))
            
            # Hot -> Cold: Breakdown
            elif hist_class.tier == SectorTier.HOT and curr_class.tier == SectorTier.COLD:
                signals.append(RotationSignal(
                    signal_type=RotationSignalType.SECTOR_BREAKDOWN,
                    sectors=[sector],
                    timestamp=current_time,
                    details={
                        "prev_tier": hist_class.tier.value,
                        "curr_tier": curr_class.tier.value,
                        "prev_score": hist_class.score,
                        "curr_score": curr_class.score
                    }
                ))
        
        return signals
    
    def _detect_synchronized_movements(
        self,
        current: List[SectorClassification],
        historical_strengths: Dict[str, SectorStrength],
        threshold: int = 3
    ) -> List[RotationSignal]:
        """
        检测同步运动信号
        
        - >=3 板块同步上涨 (强度增加 > 10): BROAD_RALLY
        - >=3 板块同步下跌 (强度减少 > 10): BROAD_SELLOFF
        
        Args:
            current: 当前分类结果
            historical_strengths: 历史强度数据
            threshold: 触发信号的最小板块数量
            
        Returns:
            List[RotationSignal]: 同步运动信号列表
        """
        signals = []
        current_time = datetime.now()
        
        if not historical_strengths:
            return signals
        
        increasing_sectors = []
        decreasing_sectors = []
        
        for curr_class in current:
            sector = curr_class.sector
            
            if sector not in historical_strengths:
                continue
            
            hist_strength = historical_strengths[sector]
            score_change = curr_class.score - hist_strength.score
            
            if score_change > self.strength_change_threshold:
                increasing_sectors.append(sector)
            elif score_change < -self.strength_change_threshold:
                decreasing_sectors.append(sector)
        
        # 检测广泛上涨
        if len(increasing_sectors) >= threshold:
            signals.append(RotationSignal(
                signal_type=RotationSignalType.BROAD_RALLY,
                sectors=increasing_sectors,
                timestamp=current_time,
                details={
                    "sector_count": len(increasing_sectors),
                    "threshold": self.strength_change_threshold
                }
            ))
        
        # 检测广泛下跌
        if len(decreasing_sectors) >= threshold:
            signals.append(RotationSignal(
                signal_type=RotationSignalType.BROAD_SELLOFF,
                sectors=decreasing_sectors,
                timestamp=current_time,
                details={
                    "sector_count": len(decreasing_sectors),
                    "threshold": self.strength_change_threshold
                }
            ))
        
        return signals


class RotationManager:
    """
    板块轮动管理器 - 核心控制类
    
    整合强度计算、层级分类、权重分配和信号检测功能，
    提供统一的接口供回测系统调用。
    """
    
    def __init__(self, config: RotationConfig):
        """
        初始化轮动管理器
        
        Args:
            config: 板块轮动配置
        """
        self.config = config
        self.strength_calculator = StrengthCalculator(config)
        self.tier_classifier = TierClassifier()
        self.weight_allocator = WeightAllocator(config)
        self.signal_detector = SignalDetector()
        self.history: List[RotationSnapshot] = []
        
        # 缓存当前状态
        self._current_strengths: Dict[str, SectorStrength] = {}
        self._current_classifications: Dict[str, SectorClassification] = {}
        self._current_weights: Dict[str, float] = {}
        self._last_rebalance_time: Optional[datetime] = None
    
    def calculate_sector_weights(
        self,
        sector_data: Dict[str, SectorData],
        btc_data: Optional[pd.DataFrame],
        current_time: datetime,
        leader_coins: Optional[Dict[str, str]] = None
    ) -> Dict[str, float]:
        """
        计算各板块的仓位权重
        
        Args:
            sector_data: 各板块的价格和成交量数据
            btc_data: BTC参考数据
            current_time: 当前时间
            leader_coins: 各板块的龙头币映射
            
        Returns:
            Dict[str, float]: 板块名称 -> 权重 (0-1)
        """
        if not self.config.enabled:
            # 轮动禁用时返回等权分配
            n = len(sector_data)
            if n == 0:
                return {}
            return {sector: 1.0 / n for sector in sector_data}
        
        # 计算各板块强度
        strengths: List[SectorStrength] = []
        for sector, data in sector_data.items():
            leader_coin = ""
            if leader_coins and sector in leader_coins:
                leader_coin = leader_coins[sector]
            elif data.leader_coin:
                leader_coin = data.leader_coin
            
            strength = self.strength_calculator.calculate_strength(
                sector=sector,
                coins_data=data.coins,
                btc_data=btc_data,
                leader_coin=leader_coin
            )
            strengths.append(strength)
        
        # 获取上一次的分类结果
        prev_classifications = self._current_classifications.copy()
        prev_strengths = self._current_strengths.copy()
        
        # 分类板块
        classifications = self.tier_classifier.classify_sectors(
            strengths, prev_classifications
        )
        
        # 更新动量转换标记
        current_strengths_dict = {s.sector: s for s in strengths}
        classifications = self.tier_classifier.update_momentum_shifts(
            classifications, current_strengths_dict, prev_strengths
        )
        
        # 分配权重
        weight_results = self.weight_allocator.allocate_weights(classifications)
        weights = {sector: w.weight for sector, w in weight_results.items()}
        
        # 检测信号
        signals = self.signal_detector.detect_signals(
            classifications, self.history, lookback_hours=24
        )
        
        # 更新缓存
        self._current_strengths = current_strengths_dict
        self._current_classifications = {c.sector: c for c in classifications}
        self._current_weights = weights
        
        # 保存快照
        snapshot = RotationSnapshot(
            timestamp=current_time,
            strengths=current_strengths_dict,
            classifications=self._current_classifications,
            weights=weights,
            signals=signals
        )
        self.history.append(snapshot)
        
        # 限制历史记录长度 (保留最近100个快照)
        if len(self.history) > 100:
            self.history = self.history[-100:]
        
        return weights
    
    def should_rebalance(
        self,
        current_weights: Dict[str, float],
        new_weights: Dict[str, float],
        btc_atr_pct: float
    ) -> bool:
        """
        判断是否需要再平衡
        
        触发条件:
        1. 任意板块权重变化超过阈值
        2. BTC ATR 未超过高波动阈值
        
        Args:
            current_weights: 当前权重
            new_weights: 新计算的权重
            btc_atr_pct: BTC ATR 百分比
            
        Returns:
            bool: 是否需要再平衡
        """
        # 高波动市场延迟再平衡
        if btc_atr_pct > self.config.high_volatility_atr_threshold:
            return False
        
        # 检查权重变化
        max_change = 0.0
        for sector in set(current_weights.keys()) | set(new_weights.keys()):
            curr = current_weights.get(sector, 0.0)
            new = new_weights.get(sector, 0.0)
            change = abs(new - curr)
            max_change = max(max_change, change)
        
        return max_change > self.config.rebalance_threshold
    
    def get_rotation_signals(self) -> List[RotationSignal]:
        """
        获取最近的板块轮动信号
        
        Returns:
            List[RotationSignal]: 信号列表
        """
        if not self.history:
            return []
        
        return self.history[-1].signals
    
    def get_sector_tier(self, sector: str) -> Optional[SectorTier]:
        """
        获取指定板块的当前层级
        
        Args:
            sector: 板块名称
            
        Returns:
            Optional[SectorTier]: 板块层级，如果不存在返回 None
        """
        if sector in self._current_classifications:
            return self._current_classifications[sector].tier
        return None
    
    def get_sector_strength(self, sector: str) -> Optional[SectorStrength]:
        """
        获取指定板块的当前强度数据
        
        Args:
            sector: 板块名称
            
        Returns:
            Optional[SectorStrength]: 强度数据，如果不存在返回 None
        """
        return self._current_strengths.get(sector)
    
    def get_all_classifications(self) -> Dict[str, SectorClassification]:
        """
        获取所有板块的当前分类结果
        
        Returns:
            Dict[str, SectorClassification]: 板块名称 -> 分类结果
        """
        return self._current_classifications.copy()
    
    def get_all_weights(self) -> Dict[str, float]:
        """
        获取所有板块的当前权重
        
        Returns:
            Dict[str, float]: 板块名称 -> 权重
        """
        return self._current_weights.copy()
    
    def is_position_protected(
        self,
        sector: str,
        unrealized_pnl: float
    ) -> bool:
        """
        判断持仓是否受保护 (不应在再平衡时关闭)
        
        保护条件:
        - 持仓盈利 (unrealized_pnl > 0)
        - 板块不是 Cold 层级
        
        Args:
            sector: 板块名称
            unrealized_pnl: 未实现盈亏
            
        Returns:
            bool: 是否受保护
        """
        if unrealized_pnl <= 0:
            return False
        
        tier = self.get_sector_tier(sector)
        if tier is None:
            return True  # 未知板块默认保护
        
        # Cold 层级的盈利持仓不受保护
        return tier != SectorTier.COLD
    
    def reset(self):
        """
        重置管理器状态
        
        清除所有历史数据和缓存
        """
        self.history = []
        self._current_strengths = {}
        self._current_classifications = {}
        self._current_weights = {}
        self._last_rebalance_time = None


# ============================================================================
# RotationStats - 轮动统计类
# ============================================================================

from dataclasses import dataclass, field


@dataclass
class RotationStats:
    """
    轮动统计
    
    用于统计回测期间的板块轮动表现，包括：
    - 板块表现统计
    - 交易表现按层级统计
    - 轮动效率计算
    - 贡献分析
    
    Validates: Requirements 7.1, 7.2, 7.3
    """
    # 板块表现
    sector_avg_strength: Dict[str, float] = field(default_factory=dict)
    sector_time_in_tier: Dict[str, Dict[str, float]] = field(default_factory=dict)  # 各层级停留时间比例
    
    # 交易表现
    trades_by_tier: Dict[str, int] = field(default_factory=dict)
    win_rate_by_tier: Dict[str, float] = field(default_factory=dict)
    avg_profit_by_tier: Dict[str, float] = field(default_factory=dict)
    total_profit_by_tier: Dict[str, float] = field(default_factory=dict)
    
    # 轮动效率
    rotation_efficiency: float = 0.0  # Hot板块利润 / Cold板块利润
    rebalance_count: int = 0
    signals_generated: Dict[str, int] = field(default_factory=dict)
    
    # 贡献分析
    profit_contribution: Dict[str, float] = field(default_factory=dict)  # 各板块利润贡献
    top_contributors: List[str] = field(default_factory=list)  # 贡献最大的板块


class RotationStatsCalculator:
    """
    轮动统计计算器
    
    从回测交易记录和轮动历史中计算统计数据
    """
    
    def __init__(self):
        pass
    
    def calculate_stats(
        self,
        trades: List,  # List[BacktestTradeV2]
        rotation_history: List[RotationSnapshot],
        sector_tier_map: Dict[str, Dict[str, str]] = None  # {symbol: {time: tier}}
    ) -> RotationStats:
        """
        计算轮动统计
        
        Args:
            trades: 回测交易记录列表
            rotation_history: 轮动历史快照列表
            sector_tier_map: 交易时的板块层级映射
            
        Returns:
            RotationStats: 轮动统计数据
        """
        stats = RotationStats()
        
        # 计算板块平均强度
        stats.sector_avg_strength = self._calculate_sector_avg_strength(rotation_history)
        
        # 计算各层级停留时间比例
        stats.sector_time_in_tier = self._calculate_time_in_tier(rotation_history)
        
        # 计算交易表现按层级统计
        tier_stats = self._calculate_trades_by_tier(trades)
        stats.trades_by_tier = tier_stats['trades_by_tier']
        stats.win_rate_by_tier = tier_stats['win_rate_by_tier']
        stats.avg_profit_by_tier = tier_stats['avg_profit_by_tier']
        stats.total_profit_by_tier = tier_stats['total_profit_by_tier']
        
        # 计算轮动效率
        stats.rotation_efficiency = self._calculate_rotation_efficiency(
            stats.total_profit_by_tier
        )
        
        # 计算再平衡次数和信号统计
        stats.rebalance_count = self._count_rebalances(rotation_history)
        stats.signals_generated = self._count_signals(rotation_history)
        
        # 计算利润贡献
        contribution_stats = self._calculate_profit_contribution(trades)
        stats.profit_contribution = contribution_stats['profit_contribution']
        stats.top_contributors = contribution_stats['top_contributors']
        
        return stats
    
    def _calculate_sector_avg_strength(
        self,
        history: List[RotationSnapshot]
    ) -> Dict[str, float]:
        """
        计算各板块的平均强度评分
        
        Args:
            history: 轮动历史快照列表
            
        Returns:
            Dict[str, float]: 板块名称 -> 平均强度
        """
        if not history:
            return {}
        
        sector_scores: Dict[str, List[float]] = {}
        
        for snapshot in history:
            for sector, strength in snapshot.strengths.items():
                if sector not in sector_scores:
                    sector_scores[sector] = []
                sector_scores[sector].append(strength.score)
        
        return {
            sector: sum(scores) / len(scores) if scores else 0.0
            for sector, scores in sector_scores.items()
        }
    
    def _calculate_time_in_tier(
        self,
        history: List[RotationSnapshot]
    ) -> Dict[str, Dict[str, float]]:
        """
        计算各板块在各层级的停留时间比例
        
        Args:
            history: 轮动历史快照列表
            
        Returns:
            Dict[str, Dict[str, float]]: 板块名称 -> {层级: 时间比例}
        """
        if not history:
            return {}
        
        sector_tier_counts: Dict[str, Dict[str, int]] = {}
        
        for snapshot in history:
            for sector, classification in snapshot.classifications.items():
                if sector not in sector_tier_counts:
                    sector_tier_counts[sector] = {
                        SectorTier.HOT.value: 0,
                        SectorTier.WARM.value: 0,
                        SectorTier.NEUTRAL.value: 0,
                        SectorTier.COLD.value: 0
                    }
                sector_tier_counts[sector][classification.tier.value] += 1
        
        # 转换为比例
        result: Dict[str, Dict[str, float]] = {}
        for sector, tier_counts in sector_tier_counts.items():
            total = sum(tier_counts.values())
            if total > 0:
                result[sector] = {
                    tier: count / total
                    for tier, count in tier_counts.items()
                }
            else:
                result[sector] = {tier: 0.0 for tier in tier_counts}
        
        return result
    
    def _calculate_trades_by_tier(
        self,
        trades: List
    ) -> Dict[str, Dict]:
        """
        计算交易表现按层级统计
        
        Args:
            trades: 回测交易记录列表
            
        Returns:
            Dict containing trades_by_tier, win_rate_by_tier, avg_profit_by_tier, total_profit_by_tier
        """
        # 初始化统计
        trades_by_tier: Dict[str, int] = {
            SectorTier.HOT.value: 0,
            SectorTier.WARM.value: 0,
            SectorTier.NEUTRAL.value: 0,
            SectorTier.COLD.value: 0,
            'unknown': 0
        }
        
        wins_by_tier: Dict[str, int] = {
            SectorTier.HOT.value: 0,
            SectorTier.WARM.value: 0,
            SectorTier.NEUTRAL.value: 0,
            SectorTier.COLD.value: 0,
            'unknown': 0
        }
        
        profits_by_tier: Dict[str, List[float]] = {
            SectorTier.HOT.value: [],
            SectorTier.WARM.value: [],
            SectorTier.NEUTRAL.value: [],
            SectorTier.COLD.value: [],
            'unknown': []
        }
        
        for trade in trades:
            # 获取交易的板块层级
            tier = getattr(trade, 'sector_tier', None)
            if tier is None or tier == '':
                tier = 'unknown'
            elif hasattr(tier, 'value'):
                tier = tier.value
            
            if tier not in trades_by_tier:
                tier = 'unknown'
            
            trades_by_tier[tier] += 1
            
            # 统计盈亏
            profit = getattr(trade, 'profit_loss', 0.0) or 0.0
            realized_pnl = getattr(trade, 'realized_pnl', 0.0) or 0.0
            total_profit = profit + realized_pnl
            
            profits_by_tier[tier].append(total_profit)
            
            if total_profit > 0:
                wins_by_tier[tier] += 1
        
        # 计算胜率和平均利润
        win_rate_by_tier: Dict[str, float] = {}
        avg_profit_by_tier: Dict[str, float] = {}
        total_profit_by_tier: Dict[str, float] = {}
        
        for tier in trades_by_tier:
            count = trades_by_tier[tier]
            if count > 0:
                win_rate_by_tier[tier] = wins_by_tier[tier] / count * 100
                avg_profit_by_tier[tier] = sum(profits_by_tier[tier]) / count
            else:
                win_rate_by_tier[tier] = 0.0
                avg_profit_by_tier[tier] = 0.0
            
            total_profit_by_tier[tier] = sum(profits_by_tier[tier])
        
        return {
            'trades_by_tier': trades_by_tier,
            'win_rate_by_tier': win_rate_by_tier,
            'avg_profit_by_tier': avg_profit_by_tier,
            'total_profit_by_tier': total_profit_by_tier
        }
    
    def _calculate_rotation_efficiency(
        self,
        total_profit_by_tier: Dict[str, float]
    ) -> float:
        """
        计算轮动效率
        
        公式: rotation_efficiency = Hot板块利润 / Cold板块利润
        
        Property 15: Rotation Efficiency Calculation
        *For any* backtest result with trades, rotation_efficiency SHALL equal:
        - sum(profit for trades where sector_tier == HOT) / sum(profit for trades where sector_tier == COLD)
        - If Cold sector profit <= 0, efficiency = ∞ (represented as a large number)
        
        Validates: Requirements 7.3
        
        Args:
            total_profit_by_tier: 各层级总利润
            
        Returns:
            float: 轮动效率
        """
        hot_profit = total_profit_by_tier.get(SectorTier.HOT.value, 0.0)
        cold_profit = total_profit_by_tier.get(SectorTier.COLD.value, 0.0)
        
        if cold_profit <= 0:
            # Cold板块利润 <= 0，效率为无穷大（用大数表示）
            if hot_profit > 0:
                return 999999.0  # 表示无穷大
            else:
                return 0.0  # 两者都 <= 0
        
        return hot_profit / cold_profit
    
    def _count_rebalances(
        self,
        history: List[RotationSnapshot]
    ) -> int:
        """
        计算再平衡次数
        
        通过检测权重变化来统计再平衡次数
        
        Args:
            history: 轮动历史快照列表
            
        Returns:
            int: 再平衡次数
        """
        if len(history) < 2:
            return 0
        
        rebalance_count = 0
        threshold = 0.10  # 10% 权重变化阈值
        
        for i in range(1, len(history)):
            prev_weights = history[i-1].weights
            curr_weights = history[i].weights
            
            # 检查是否有显著权重变化
            max_change = 0.0
            for sector in set(prev_weights.keys()) | set(curr_weights.keys()):
                prev = prev_weights.get(sector, 0.0)
                curr = curr_weights.get(sector, 0.0)
                change = abs(curr - prev)
                max_change = max(max_change, change)
            
            if max_change > threshold:
                rebalance_count += 1
        
        return rebalance_count
    
    def _count_signals(
        self,
        history: List[RotationSnapshot]
    ) -> Dict[str, int]:
        """
        统计各类信号生成次数
        
        Args:
            history: 轮动历史快照列表
            
        Returns:
            Dict[str, int]: 信号类型 -> 次数
        """
        signal_counts: Dict[str, int] = {
            RotationSignalType.SECTOR_BREAKOUT.value: 0,
            RotationSignalType.SECTOR_BREAKDOWN.value: 0,
            RotationSignalType.BROAD_RALLY.value: 0,
            RotationSignalType.BROAD_SELLOFF.value: 0,
            RotationSignalType.MOMENTUM_SHIFT.value: 0
        }
        
        for snapshot in history:
            for signal in snapshot.signals:
                signal_type = signal.signal_type.value if hasattr(signal.signal_type, 'value') else str(signal.signal_type)
                if signal_type in signal_counts:
                    signal_counts[signal_type] += 1
        
        return signal_counts
    
    def _calculate_profit_contribution(
        self,
        trades: List
    ) -> Dict[str, any]:
        """
        计算各板块的利润贡献
        
        Validates: Requirements 7.2
        
        Args:
            trades: 回测交易记录列表
            
        Returns:
            Dict containing profit_contribution and top_contributors
        """
        sector_profits: Dict[str, float] = {}
        
        for trade in trades:
            category = getattr(trade, 'category', 'unknown')
            profit = getattr(trade, 'profit_loss', 0.0) or 0.0
            realized_pnl = getattr(trade, 'realized_pnl', 0.0) or 0.0
            total_profit = profit + realized_pnl
            
            if category not in sector_profits:
                sector_profits[category] = 0.0
            sector_profits[category] += total_profit
        
        # 计算总利润
        total_profit = sum(sector_profits.values())
        
        # 计算贡献比例
        profit_contribution: Dict[str, float] = {}
        if total_profit != 0:
            for sector, profit in sector_profits.items():
                profit_contribution[sector] = profit / abs(total_profit) * 100
        else:
            profit_contribution = {sector: 0.0 for sector in sector_profits}
        
        # 找出贡献最大的板块（按绝对利润排序）
        sorted_sectors = sorted(
            sector_profits.items(),
            key=lambda x: x[1],
            reverse=True
        )
        top_contributors = [sector for sector, _ in sorted_sectors[:5]]
        
        return {
            'profit_contribution': profit_contribution,
            'top_contributors': top_contributors
        }
    
    def format_stats_report(self, stats: RotationStats) -> str:
        """
        格式化统计报告为可读字符串
        
        Args:
            stats: 轮动统计数据
            
        Returns:
            str: 格式化的报告字符串
        """
        lines = []
        lines.append("\n" + "=" * 60)
        lines.append("📊 板块轮动统计报告")
        lines.append("=" * 60)
        
        # 板块平均强度
        if stats.sector_avg_strength:
            lines.append("\n📈 板块平均强度:")
            sorted_strength = sorted(
                stats.sector_avg_strength.items(),
                key=lambda x: x[1],
                reverse=True
            )
            for sector, strength in sorted_strength:
                lines.append(f"   {sector}: {strength:.1f}")
        
        # 交易表现按层级
        lines.append("\n📊 交易表现 (按层级):")
        for tier in [SectorTier.HOT.value, SectorTier.WARM.value, 
                     SectorTier.NEUTRAL.value, SectorTier.COLD.value]:
            trades = stats.trades_by_tier.get(tier, 0)
            win_rate = stats.win_rate_by_tier.get(tier, 0.0)
            avg_profit = stats.avg_profit_by_tier.get(tier, 0.0)
            total_profit = stats.total_profit_by_tier.get(tier, 0.0)
            
            tier_emoji = {
                SectorTier.HOT.value: "🔥",
                SectorTier.WARM.value: "🌡️",
                SectorTier.NEUTRAL.value: "⚖️",
                SectorTier.COLD.value: "❄️"
            }.get(tier, "")
            
            lines.append(f"   {tier_emoji} {tier.upper()}: {trades}笔, "
                        f"胜率 {win_rate:.1f}%, "
                        f"平均 {avg_profit:+.2f}, "
                        f"总计 {total_profit:+.2f}")
        
        # 轮动效率
        lines.append(f"\n⚡ 轮动效率: {stats.rotation_efficiency:.2f}")
        lines.append(f"   (Hot利润/Cold利润, >1表示轮动策略有效)")
        
        # 再平衡和信号统计
        lines.append(f"\n🔄 再平衡次数: {stats.rebalance_count}")
        
        if stats.signals_generated:
            lines.append("\n📡 信号统计:")
            for signal_type, count in stats.signals_generated.items():
                if count > 0:
                    lines.append(f"   {signal_type}: {count}次")
        
        # 利润贡献
        if stats.top_contributors:
            lines.append("\n🏆 利润贡献 Top 5:")
            for i, sector in enumerate(stats.top_contributors[:5], 1):
                contribution = stats.profit_contribution.get(sector, 0.0)
                lines.append(f"   {i}. {sector}: {contribution:+.1f}%")
        
        lines.append("\n" + "=" * 60)
        
        return "\n".join(lines)
