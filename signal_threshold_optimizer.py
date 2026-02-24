"""
信号阈值优化器 (Signal Threshold Optimizer)
根据交易频率动态调整信号阈值，在低频期间降低门槛以捕捉更多机会

Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 6.1, 6.3, 6.4
"""
from dataclasses import dataclass, field
from typing import List, Optional
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)


@dataclass
class ThresholdAdjustment:
    """阈值调整记录"""
    timestamp: datetime
    old_threshold: float
    new_threshold: float
    reason: str
    trade_count_7d: int


@dataclass
class TimePeriodParams:
    """时段参数"""
    signal_threshold_adjustment: float  # 信号阈值调整
    max_positions_multiplier: float     # 最大持仓乘数
    period_name: str                    # 时段名称


class SignalThresholdOptimizer:
    """
    信号阈值优化器
    
    根据近7天交易数量动态调整入场信号阈值:
    - 交易数 < 5: 降低阈值10分 (增加交易机会)
    - 交易数 > 20: 提高阈值5分 (提高入场质量)
    - 阈值范围限制在 [60, 85]
    
    时段调整:
    - 亚洲时段 (00:00-08:00 UTC): 信号阈值+5
    - 周末: 最大持仓减半
    - BTC 4小时涨跌超5%: 暂停2小时
    
    Properties:
    - Property 1: Signal Threshold Trade Count Adjustment
    - Property 2: Signal Threshold Bounds
    - Property 13: Time-Based Parameter Selection
    - Property 14: Major Event Trading Pause
    """
    
    MIN_THRESHOLD = 60.0
    MAX_THRESHOLD = 85.0
    DEFAULT_THRESHOLD = 75.0
    
    LOW_TRADE_COUNT = 5      # 7天内少于5笔触发降低
    HIGH_TRADE_COUNT = 20    # 7天内超过20笔触发提高
    LOW_ADJUSTMENT = -10.0   # 低频时降低10分
    HIGH_ADJUSTMENT = 5.0    # 高频时提高5分
    
    # 时段参数
    ASIAN_HOURS_START = 0    # 00:00 UTC
    ASIAN_HOURS_END = 8      # 08:00 UTC
    ASIAN_THRESHOLD_ADJUSTMENT = 5.0  # 亚洲时段阈值+5
    WEEKEND_POSITION_MULTIPLIER = 0.5  # 周末持仓减半
    
    # 重大事件参数
    BTC_MAJOR_MOVE_THRESHOLD = 5.0  # BTC 4小时涨跌5%
    MAJOR_EVENT_PAUSE_HOURS = 2     # 暂停2小时
    
    def __init__(self, base_threshold: float = 75.0):
        """
        初始化信号阈值优化器
        
        Args:
            base_threshold: 基础阈值，默认75分
        """
        self.base_threshold = self._clamp_threshold(base_threshold)
        self._current_threshold = self.base_threshold
        self._adjustment_history: List[ThresholdAdjustment] = []
        self._major_event_pause_until: Optional[datetime] = None
        self._last_btc_price: Optional[float] = None
        self._btc_price_4h_ago: Optional[float] = None
        self._btc_price_timestamp: Optional[datetime] = None
    
    def update_threshold(
        self,
        trade_history: List[dict],
        current_time: datetime
    ) -> ThresholdAdjustment:
        """
        根据近7天交易数量更新阈值
        
        Property 1: Signal Threshold Trade Count Adjustment
        - When 7-day trade count < 5, threshold SHALL decrease by 10 points from base
        - When 7-day trade count > 20, threshold SHALL increase by 5 points from base
        - Otherwise, threshold SHALL equal base threshold
        
        Args:
            trade_history: 交易历史记录，每条记录需包含 'timestamp' 或 'entry_time' 字段
            current_time: 当前时间
            
        Returns:
            ThresholdAdjustment: 调整结果
        """
        old_threshold = self._current_threshold
        trade_count = self._count_recent_trades(trade_history, current_time, days=7)
        
        # 根据交易数量计算新阈值
        if trade_count < self.LOW_TRADE_COUNT:
            new_threshold = self.base_threshold + self.LOW_ADJUSTMENT
            reason = f"低交易频率: 7天内仅{trade_count}笔交易 (< {self.LOW_TRADE_COUNT})，降低阈值{abs(self.LOW_ADJUSTMENT)}分"
        elif trade_count > self.HIGH_TRADE_COUNT:
            new_threshold = self.base_threshold + self.HIGH_ADJUSTMENT
            reason = f"高交易频率: 7天内{trade_count}笔交易 (> {self.HIGH_TRADE_COUNT})，提高阈值{self.HIGH_ADJUSTMENT}分"
        else:
            new_threshold = self.base_threshold
            reason = f"正常交易频率: 7天内{trade_count}笔交易，使用基础阈值"
        
        # Property 2: Signal Threshold Bounds
        # 限制阈值在有效范围内
        new_threshold = self._clamp_threshold(new_threshold)
        self._current_threshold = new_threshold
        
        # 记录调整
        adjustment = ThresholdAdjustment(
            timestamp=current_time,
            old_threshold=old_threshold,
            new_threshold=new_threshold,
            reason=reason,
            trade_count_7d=trade_count
        )
        self._adjustment_history.append(adjustment)
        
        # 记录日志
        if old_threshold != new_threshold:
            logger.info(f"信号阈值调整: {old_threshold:.1f} -> {new_threshold:.1f}, {reason}")
        
        return adjustment
    
    def get_current_threshold(self) -> float:
        """
        获取当前阈值
        
        Returns:
            float: 当前信号阈值
        """
        return self._current_threshold
    
    def get_adjustment_history(self) -> List[ThresholdAdjustment]:
        """
        获取调整历史
        
        Returns:
            List[ThresholdAdjustment]: 调整历史记录
        """
        return self._adjustment_history.copy()
    
    def reset(self) -> None:
        """重置为基础阈值"""
        self._current_threshold = self.base_threshold
        self._adjustment_history.clear()
    
    def _count_recent_trades(
        self,
        trade_history: List[dict],
        current_time: datetime,
        days: int = 7
    ) -> int:
        """
        计算近N天的交易数量
        
        Args:
            trade_history: 交易历史记录
            current_time: 当前时间
            days: 统计天数，默认7天
            
        Returns:
            int: 交易数量
        """
        if not trade_history:
            return 0
        
        cutoff_time = current_time - timedelta(days=days)
        count = 0
        
        for trade in trade_history:
            # 支持多种时间字段名
            trade_time = None
            for time_field in ['timestamp', 'entry_time', 'time', 'date']:
                if time_field in trade:
                    trade_time = trade[time_field]
                    break
            
            if trade_time is None:
                continue
            
            # 处理字符串格式的时间
            if isinstance(trade_time, str):
                try:
                    trade_time = datetime.fromisoformat(trade_time.replace('Z', '+00:00'))
                except ValueError:
                    continue
            
            # 检查是否在统计范围内
            if isinstance(trade_time, datetime) and trade_time >= cutoff_time:
                count += 1
        
        return count
    
    def _clamp_threshold(self, threshold: float) -> float:
        """
        限制阈值在有效范围内
        
        Property 2: Signal Threshold Bounds
        For any threshold calculation, the final threshold SHALL be clamped to [60, 85]
        
        Args:
            threshold: 原始阈值
            
        Returns:
            float: 限制后的阈值
        """
        return max(self.MIN_THRESHOLD, min(self.MAX_THRESHOLD, threshold))
    
    # ============== 时段调整方法 (Task 8) ==============
    
    def get_time_period_params(self, current_time: datetime) -> TimePeriodParams:
        """
        获取当前时段参数
        
        Property 13: Time-Based Parameter Selection
        - During Asian hours (00:00-08:00 UTC), signal threshold SHALL increase by 5
        - During weekend, maximum positions SHALL be reduced by 50%
        
        Args:
            current_time: 当前时间 (UTC)
            
        Returns:
            TimePeriodParams: 时段参数
        """
        hour = current_time.hour
        weekday = current_time.weekday()  # 0=Monday, 6=Sunday
        
        # 判断时段
        is_asian = self.ASIAN_HOURS_START <= hour < self.ASIAN_HOURS_END
        is_weekend = weekday >= 5  # Saturday or Sunday
        
        # 计算调整
        threshold_adj = self.ASIAN_THRESHOLD_ADJUSTMENT if is_asian else 0.0
        position_mult = self.WEEKEND_POSITION_MULTIPLIER if is_weekend else 1.0
        
        # 确定时段名称
        if is_weekend:
            period_name = "weekend"
        elif is_asian:
            period_name = "asian"
        else:
            period_name = "standard"
        
        return TimePeriodParams(
            signal_threshold_adjustment=threshold_adj,
            max_positions_multiplier=position_mult,
            period_name=period_name
        )
    
    def get_adjusted_threshold(self, current_time: datetime) -> float:
        """
        获取时段调整后的阈值
        
        Args:
            current_time: 当前时间 (UTC)
            
        Returns:
            float: 调整后的阈值
        """
        base = self._current_threshold
        time_params = self.get_time_period_params(current_time)
        adjusted = base + time_params.signal_threshold_adjustment
        return self._clamp_threshold(adjusted)
    
    def update_btc_price(self, price: float, timestamp: datetime) -> None:
        """
        更新BTC价格用于重大事件检测
        
        Args:
            price: 当前BTC价格
            timestamp: 时间戳
        """
        # 保存4小时前的价格
        if self._btc_price_timestamp is not None:
            hours_diff = (timestamp - self._btc_price_timestamp).total_seconds() / 3600
            if hours_diff >= 4:
                self._btc_price_4h_ago = self._last_btc_price
                self._btc_price_timestamp = timestamp
        else:
            self._btc_price_timestamp = timestamp
        
        self._last_btc_price = price
    
    def check_major_event(self, current_time: datetime) -> tuple:
        """
        检查是否发生重大市场事件
        
        Property 14: Major Event Trading Pause
        For any 4-hour period where BTC moves more than 5%, 
        new entries SHALL be paused for 2 hours
        
        Args:
            current_time: 当前时间
            
        Returns:
            tuple: (is_paused, reason)
        """
        # 检查是否在暂停期
        if self._major_event_pause_until is not None:
            if current_time < self._major_event_pause_until:
                return True, f"重大事件暂停中，恢复时间: {self._major_event_pause_until}"
            else:
                self._major_event_pause_until = None
        
        # 检查BTC价格变动
        if self._last_btc_price is not None and self._btc_price_4h_ago is not None:
            if self._btc_price_4h_ago > 0:
                change_pct = abs(
                    (self._last_btc_price - self._btc_price_4h_ago) / self._btc_price_4h_ago * 100
                )
                
                if change_pct >= self.BTC_MAJOR_MOVE_THRESHOLD:
                    self._major_event_pause_until = current_time + timedelta(
                        hours=self.MAJOR_EVENT_PAUSE_HOURS
                    )
                    # 清除价格数据，避免重复触发
                    self._btc_price_4h_ago = None
                    logger.warning(
                        f"重大事件检测: BTC 4小时变动{change_pct:.1f}%，"
                        f"暂停交易至 {self._major_event_pause_until}"
                    )
                    return True, f"BTC 4小时变动{change_pct:.1f}%，暂停2小时"
        
        return False, ""
    
    def trigger_major_event_pause(self, current_time: datetime, reason: str = "") -> None:
        """
        手动触发重大事件暂停
        
        Args:
            current_time: 当前时间
            reason: 暂停原因
        """
        self._major_event_pause_until = current_time + timedelta(
            hours=self.MAJOR_EVENT_PAUSE_HOURS
        )
        logger.warning(f"手动触发重大事件暂停: {reason}，暂停至 {self._major_event_pause_until}")
    
    def is_trading_paused(self, current_time: datetime) -> bool:
        """
        检查交易是否暂停
        
        Args:
            current_time: 当前时间
            
        Returns:
            bool: 是否暂停
        """
        is_paused, _ = self.check_major_event(current_time)
        return is_paused
