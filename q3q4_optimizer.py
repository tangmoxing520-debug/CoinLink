"""
Q3/Q4 优化器集成模块
整合所有Q3/Q4优化组件，提供统一的接口

Requirements: 7.1
"""
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
from datetime import datetime
import pandas as pd
import logging

from signal_threshold_optimizer import SignalThresholdOptimizer, ThresholdAdjustment, TimePeriodParams
from meme_risk_controller import MemeRiskController, MemeRiskParams
from category_performance_tracker import CategoryPerformanceTracker, CategoryParams
from volatility_adaptive_stop import VolatilityAdaptiveStop, AdaptiveStopLoss
from trade_frequency_monitor import TradeFrequencyMonitor, FrequencyAdjustment

logger = logging.getLogger(__name__)


@dataclass
class Q3Q4TradeDecision:
    """Q3/Q4优化交易决策"""
    can_trade: bool
    adjusted_signal_threshold: float
    position_multiplier: float
    stop_loss_pct: float
    reasons: List[str]
    is_meme: bool
    is_ai_agent: bool
    is_blacklisted: bool
    is_paused: bool


@dataclass
class Q3Q4OptimizationStats:
    """Q3/Q4优化统计"""
    threshold_adjustments: int
    meme_trades_blocked: int
    ai_agent_trades_blocked: int
    quiet_period_adjustments: int
    major_event_pauses: int


class Q3Q4Optimizer:
    """
    Q3/Q4 优化器
    
    整合以下组件:
    1. SignalThresholdOptimizer - 动态信号阈值
    2. MemeRiskController - Meme币风险控制
    3. CategoryPerformanceTracker - 板块表现追踪
    4. VolatilityAdaptiveStop - 波动率自适应止损
    5. TradeFrequencyMonitor - 交易频率监控
    """
    
    def __init__(
        self,
        base_threshold: float = 75.0,
        base_stop_loss: float = 10.0,
        enabled: bool = True
    ):
        """
        初始化Q3/Q4优化器
        
        Args:
            base_threshold: 基础信号阈值
            base_stop_loss: 基础止损百分比
            enabled: 是否启用优化
        """
        self.enabled = enabled
        self.base_threshold = base_threshold
        self.base_stop_loss = base_stop_loss
        
        # 初始化各组件
        self.threshold_optimizer = SignalThresholdOptimizer(base_threshold)
        self.meme_controller = MemeRiskController()
        self.category_tracker = CategoryPerformanceTracker()
        self.volatility_stop = VolatilityAdaptiveStop(base_stop_loss)
        self.frequency_monitor = TradeFrequencyMonitor()
        
        # 统计
        self._stats = Q3Q4OptimizationStats(
            threshold_adjustments=0,
            meme_trades_blocked=0,
            ai_agent_trades_blocked=0,
            quiet_period_adjustments=0,
            major_event_pauses=0
        )
    
    def evaluate_trade(
        self,
        symbol: str,
        category: str,
        signal_score: float,
        price_data: pd.DataFrame,
        current_price: float,
        current_time: datetime,
        trade_history: List[dict]
    ) -> Q3Q4TradeDecision:
        """
        评估交易决策
        
        Args:
            symbol: 交易对
            category: 板块名称
            signal_score: 原始信号评分
            price_data: K线数据
            current_price: 当前价格
            current_time: 当前时间
            trade_history: 交易历史
            
        Returns:
            Q3Q4TradeDecision: 交易决策
        """
        if not self.enabled:
            return Q3Q4TradeDecision(
                can_trade=True,
                adjusted_signal_threshold=self.base_threshold,
                position_multiplier=1.0,
                stop_loss_pct=self.base_stop_loss,
                reasons=["Q3Q4优化未启用"],
                is_meme=False,
                is_ai_agent=False,
                is_blacklisted=False,
                is_paused=False
            )
        
        reasons = []
        can_trade = True
        position_multiplier = 1.0
        
        # 1. 检查重大事件暂停
        is_paused, pause_reason = self.threshold_optimizer.check_major_event(current_time)
        if is_paused:
            can_trade = False
            reasons.append(pause_reason)
            self._stats.major_event_pauses += 1
        
        # 2. 更新信号阈值
        self.threshold_optimizer.update_threshold(trade_history, current_time)
        base_threshold = self.threshold_optimizer.get_current_threshold()
        
        # 3. 应用时段调整
        time_params = self.threshold_optimizer.get_time_period_params(current_time)
        adjusted_threshold = base_threshold + time_params.signal_threshold_adjustment
        adjusted_threshold = max(60.0, min(85.0, adjusted_threshold))
        
        if time_params.signal_threshold_adjustment != 0:
            reasons.append(f"时段调整: {time_params.period_name}, 阈值+{time_params.signal_threshold_adjustment}")
        
        # 4. 应用频率监控调整
        freq_adjustment = self.frequency_monitor.update(trade_history, current_time)
        if freq_adjustment.is_quiet_period:
            # 静默期降低阈值
            adjusted_threshold -= freq_adjustment.signal_threshold_reduction
            adjusted_threshold = max(60.0, adjusted_threshold)
            reasons.append(f"静默期: {freq_adjustment.hours_since_last_trade:.0f}h无交易")
            self._stats.quiet_period_adjustments += 1
        
        # 5. 检查Meme币
        is_meme = self.meme_controller.is_meme_symbol(symbol)
        if is_meme:
            meme_can_enter, meme_reason = self.meme_controller.can_enter_trade(
                symbol, signal_score, current_time
            )
            if not meme_can_enter:
                can_trade = False
                reasons.append(f"Meme限制: {meme_reason}")
                self._stats.meme_trades_blocked += 1
            else:
                # 应用Meme仓位乘数
                meme_params = self.meme_controller.get_risk_params(symbol, current_time)
                position_multiplier *= meme_params.position_multiplier
                reasons.append(f"Meme币: 仓位x{meme_params.position_multiplier}")
        
        # 6. 检查AI Agent
        is_ai_agent = self.category_tracker.is_ai_agent_symbol(symbol)
        is_blacklisted = False
        if is_ai_agent or symbol in self.category_tracker.PERMANENT_BLACKLIST:
            # 检查永久黑名单
            is_blacklisted = self.category_tracker.is_coin_blacklisted(symbol, current_time)
            if is_blacklisted:
                can_trade = False
                if symbol in self.category_tracker.PERMANENT_BLACKLIST:
                    reasons.append(f"永久黑名单: {symbol}")
                else:
                    reasons.append(f"AI Agent黑名单: {symbol}")
                self._stats.ai_agent_trades_blocked += 1
            
            # 应用AI Agent权重 (仅对非黑名单的AI Agent币种)
            if is_ai_agent and not is_blacklisted:
                ai_params = self.category_tracker.get_category_params("AI Agent", current_time)
                position_multiplier *= ai_params.weight_multiplier
                if ai_params.weight_multiplier < 1.0:
                    reasons.append(f"AI Agent低胜率: 权重x{ai_params.weight_multiplier:.2f}")
        
        # 7. 检查信号评分
        if can_trade and signal_score < adjusted_threshold:
            can_trade = False
            reasons.append(f"信号不足: {signal_score:.1f} < {adjusted_threshold:.1f}")
        
        # 8. 计算止损
        stop_loss_result = self.volatility_stop.calculate_stop_loss(price_data, current_price)
        stop_loss_pct = stop_loss_result.final_stop_loss
        
        # AI Agent使用更严格止损
        if is_ai_agent and not is_blacklisted:
            ai_params = self.category_tracker.get_category_params("AI Agent", current_time)
            stop_loss_pct = min(stop_loss_pct, ai_params.stop_loss_pct)
            reasons.append(f"AI Agent止损: {ai_params.stop_loss_pct}%")
        
        # Meme使用专用止损
        if is_meme:
            meme_params = self.meme_controller.get_risk_params(symbol, current_time)
            stop_loss_pct = meme_params.stop_loss_pct
            reasons.append(f"Meme止损: {meme_params.stop_loss_pct}%")
        
        # 周末减仓
        if time_params.max_positions_multiplier < 1.0:
            position_multiplier *= time_params.max_positions_multiplier
            reasons.append(f"周末减仓: x{time_params.max_positions_multiplier}")
        
        return Q3Q4TradeDecision(
            can_trade=can_trade,
            adjusted_signal_threshold=adjusted_threshold,
            position_multiplier=position_multiplier,
            stop_loss_pct=stop_loss_pct,
            reasons=reasons,
            is_meme=is_meme,
            is_ai_agent=is_ai_agent,
            is_blacklisted=is_blacklisted,
            is_paused=is_paused
        )
    
    def record_trade_result(
        self,
        symbol: str,
        category: str,
        profit_loss: float,
        timestamp: datetime
    ) -> None:
        """
        记录交易结果
        
        Args:
            symbol: 交易对
            category: 板块名称
            profit_loss: 盈亏金额
            timestamp: 交易时间
        """
        if not self.enabled:
            return
        
        is_win = profit_loss > 0
        
        # 记录到Meme控制器
        if self.meme_controller.is_meme_symbol(symbol):
            self.meme_controller.record_trade(symbol, profit_loss, timestamp)
        
        # 记录到板块追踪器
        self.category_tracker.record_trade(symbol, category, is_win, timestamp)
        
        # 记录到频率监控器
        self.frequency_monitor.record_trade(timestamp)
    
    def update_btc_price(self, price: float, timestamp: datetime) -> None:
        """更新BTC价格用于重大事件检测"""
        if self.enabled:
            self.threshold_optimizer.update_btc_price(price, timestamp)
    
    def get_stats(self) -> Q3Q4OptimizationStats:
        """获取优化统计"""
        return self._stats
    
    def get_current_threshold(self) -> float:
        """获取当前信号阈值"""
        return self.threshold_optimizer.get_current_threshold()
    
    def get_meme_win_rate(self) -> float:
        """获取Meme币胜率"""
        return self.meme_controller.get_win_rate()
    
    def get_ai_agent_win_rate(self) -> float:
        """获取AI Agent胜率"""
        return self.category_tracker.get_ai_agent_win_rate()
    
    def reset(self) -> None:
        """重置所有组件"""
        self.threshold_optimizer.reset()
        self.meme_controller.reset()
        self.category_tracker.reset()
        self.frequency_monitor.reset()
        self._stats = Q3Q4OptimizationStats(
            threshold_adjustments=0,
            meme_trades_blocked=0,
            ai_agent_trades_blocked=0,
            quiet_period_adjustments=0,
            major_event_pauses=0
        )
