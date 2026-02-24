"""
交易频率监控器 (Trade Frequency Monitor)
监控交易频率，在低频期间自动调整阈值

Requirements: 5.1, 5.2, 5.3, 5.4, 5.5
"""
from dataclasses import dataclass
from typing import List, Optional, Tuple
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)


@dataclass
class FrequencyAdjustment:
    """频率调整结果"""
    timestamp: datetime
    hours_since_last_trade: float
    category_threshold_reduction: float
    signal_threshold_reduction: float
    is_quiet_period: bool


class TradeFrequencyMonitor:
    """
    交易频率监控器
    
    功能:
    1. 追踪每日和每周交易数量
    2. 48小时无交易: 降低分类阈值20%
    3. 72小时无交易: 额外降低信号阈值10分
    4. 交易恢复后24小时内逐步恢复阈值
    5. 记录所有阈值调整
    
    Properties:
    - Property 12: Quiet Period Threshold Reduction
    """
    
    QUIET_PERIOD_48H = 48        # 48小时无交易
    QUIET_PERIOD_72H = 72        # 72小时无交易
    CATEGORY_REDUCTION_48H = 0.20   # 48h降低分类阈值20%
    SIGNAL_REDUCTION_72H = 10.0     # 72h降低信号阈值10分
    RESTORATION_HOURS = 24          # 恢复期24小时
    
    def __init__(self):
        """初始化交易频率监控器"""
        self._last_trade_time: Optional[datetime] = None
        self._quiet_period_start: Optional[datetime] = None
        self._is_restoring = False
        self._restoration_start: Optional[datetime] = None
        self._adjustment_history: List[FrequencyAdjustment] = []
        self._daily_trade_count: int = 0
        self._weekly_trade_count: int = 0
        self._last_count_reset: Optional[datetime] = None
    
    def update(
        self,
        trade_history: List[dict],
        current_time: datetime
    ) -> FrequencyAdjustment:
        """
        更新频率监控状态
        
        Property 12: Quiet Period Threshold Reduction
        - After 48 hours, category thresholds SHALL be reduced by 20%
        - After 72 hours, signal threshold SHALL additionally be reduced by 10 points
        
        Args:
            trade_history: 交易历史
            current_time: 当前时间
            
        Returns:
            FrequencyAdjustment: 调整结果
        """
        # 更新最后交易时间
        self._update_last_trade_time(trade_history)
        
        # 计算距离上次交易的小时数
        hours_since_last = self._calculate_hours_since_last_trade(current_time)
        
        # 计算阈值调整
        category_reduction, signal_reduction = self._calculate_adjustments(
            hours_since_last, current_time
        )
        
        # 判断是否为静默期
        is_quiet = hours_since_last >= self.QUIET_PERIOD_48H
        
        adjustment = FrequencyAdjustment(
            timestamp=current_time,
            hours_since_last_trade=hours_since_last,
            category_threshold_reduction=category_reduction,
            signal_threshold_reduction=signal_reduction,
            is_quiet_period=is_quiet
        )
        
        self._adjustment_history.append(adjustment)
        
        if is_quiet:
            logger.info(
                f"静默期检测: {hours_since_last:.1f}小时无交易, "
                f"分类阈值降低{category_reduction:.0%}, 信号阈值降低{signal_reduction}分"
            )
        
        return adjustment
    
    def get_threshold_adjustments(
        self,
        current_time: datetime
    ) -> Tuple[float, float]:
        """
        获取阈值调整
        
        Returns:
            (category_reduction, signal_reduction): 调整值
            - category_reduction: 分类阈值降低比例 (0-1)
            - signal_reduction: 信号阈值降低分数
        """
        hours_since_last = self._calculate_hours_since_last_trade(current_time)
        return self._calculate_adjustments(hours_since_last, current_time)
    
    def record_trade(self, timestamp: datetime) -> None:
        """
        记录交易发生
        
        Args:
            timestamp: 交易时间
        """
        # 检查是否从静默期恢复 (在更新最后交易时间之前检查)
        if self._last_trade_time is not None:
            hours_since_last = (timestamp - self._last_trade_time).total_seconds() / 3600
            if hours_since_last >= self.QUIET_PERIOD_48H:
                self._is_restoring = True
                self._restoration_start = timestamp
                logger.info(f"交易恢复: 从{hours_since_last:.1f}小时静默期恢复，开始24小时恢复期")
        
        # 更新最后交易时间
        if self._last_trade_time is None or timestamp > self._last_trade_time:
            self._last_trade_time = timestamp
        
        # 更新交易计数
        self._daily_trade_count += 1
        self._weekly_trade_count += 1
    
    def get_daily_trade_count(self) -> int:
        """获取当日交易数量"""
        return self._daily_trade_count
    
    def get_weekly_trade_count(self) -> int:
        """获取本周交易数量"""
        return self._weekly_trade_count
    
    def get_adjustment_history(self) -> List[FrequencyAdjustment]:
        """获取调整历史"""
        return self._adjustment_history.copy()
    
    def reset(self) -> None:
        """重置监控器状态"""
        self._last_trade_time = None
        self._quiet_period_start = None
        self._is_restoring = False
        self._restoration_start = None
        self._adjustment_history.clear()
        self._daily_trade_count = 0
        self._weekly_trade_count = 0
        self._last_count_reset = None
    
    def reset_daily_count(self) -> None:
        """重置每日计数"""
        self._daily_trade_count = 0
    
    def reset_weekly_count(self) -> None:
        """重置每周计数"""
        self._weekly_trade_count = 0
    
    def _update_last_trade_time(self, trade_history: List[dict]) -> None:
        """从交易历史更新最后交易时间"""
        if not trade_history:
            return
        
        for trade in trade_history:
            trade_time = None
            for time_field in ['timestamp', 'entry_time', 'time', 'date', 'exit_time']:
                if time_field in trade and trade[time_field] is not None:
                    trade_time = trade[time_field]
                    break
            
            if trade_time is None:
                continue
            
            # 处理字符串格式
            if isinstance(trade_time, str):
                try:
                    trade_time = datetime.fromisoformat(trade_time.replace('Z', '+00:00'))
                except ValueError:
                    continue
            
            if isinstance(trade_time, datetime):
                if self._last_trade_time is None or trade_time > self._last_trade_time:
                    self._last_trade_time = trade_time
    
    def _calculate_hours_since_last_trade(
        self,
        current_time: datetime
    ) -> float:
        """
        计算距离上次交易的小时数
        
        Args:
            current_time: 当前时间
            
        Returns:
            float: 小时数，无交易记录返回无穷大
        """
        if self._last_trade_time is None:
            return float('inf')
        
        delta = current_time - self._last_trade_time
        return delta.total_seconds() / 3600
    
    def _calculate_adjustments(
        self,
        hours_since_last: float,
        current_time: datetime
    ) -> Tuple[float, float]:
        """
        计算阈值调整
        
        Property 12: Quiet Period Threshold Reduction
        
        Args:
            hours_since_last: 距离上次交易的小时数
            current_time: 当前时间
            
        Returns:
            (category_reduction, signal_reduction): 调整值
        """
        category_reduction = 0.0
        signal_reduction = 0.0
        
        # 检查是否在恢复期
        restoration_factor = self._get_restoration_factor(current_time)
        
        if restoration_factor < 1.0:
            # 恢复期内，逐步减少调整
            if hours_since_last >= self.QUIET_PERIOD_72H:
                category_reduction = self.CATEGORY_REDUCTION_48H * restoration_factor
                signal_reduction = self.SIGNAL_REDUCTION_72H * restoration_factor
            elif hours_since_last >= self.QUIET_PERIOD_48H:
                category_reduction = self.CATEGORY_REDUCTION_48H * restoration_factor
        else:
            # 非恢复期，正常计算
            if hours_since_last >= self.QUIET_PERIOD_72H:
                category_reduction = self.CATEGORY_REDUCTION_48H
                signal_reduction = self.SIGNAL_REDUCTION_72H
            elif hours_since_last >= self.QUIET_PERIOD_48H:
                category_reduction = self.CATEGORY_REDUCTION_48H
        
        return category_reduction, signal_reduction
    
    def _get_restoration_factor(
        self,
        current_time: datetime
    ) -> float:
        """
        获取恢复因子 (0-1)
        
        0 = 完全恢复 (不需要调整)
        1 = 未恢复 (需要完整调整)
        
        Args:
            current_time: 当前时间
            
        Returns:
            float: 恢复因子
        """
        if not self._is_restoring or self._restoration_start is None:
            return 1.0
        
        hours_since_restoration = (current_time - self._restoration_start).total_seconds() / 3600
        
        if hours_since_restoration >= self.RESTORATION_HOURS:
            # 恢复期结束
            self._is_restoring = False
            self._restoration_start = None
            return 1.0
        
        # 线性恢复: 从1逐渐降到0
        return 1.0 - (hours_since_restoration / self.RESTORATION_HOURS)
