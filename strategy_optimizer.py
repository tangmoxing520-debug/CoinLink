"""
策略优化器 (Strategy Optimizer)
协调各组件，提供统一的策略参数接口
Requirements: 5.1, 5.2, 5.3, 5.4, 5.5
"""
from dataclasses import dataclass
from typing import Optional, Tuple
from datetime import datetime, timedelta

from market_regime_detector import MarketRegimeDetector, MarketRegimeType
from stop_loss_controller import StopLossController
from sector_weight_manager import SectorWeightManager
from signal_calibrator import SignalCalibrator


@dataclass
class TradingParameters:
    """交易参数"""
    max_positions: int
    min_signal_score: float
    position_size_multiplier: float
    stop_loss_threshold: float
    is_trading_paused: bool
    pause_reason: Optional[str] = None
    pause_until: Optional[datetime] = None


@dataclass
class PerformanceMetrics:
    """表现指标"""
    consecutive_losses: int
    current_drawdown_pct: float
    total_trades: int
    win_rate: float


class StrategyOptimizer:
    """
    策略优化器 - 协调各组件
    
    功能:
    1. 熊市参数调整: max_positions 4→2, min_score 70→85
    2. 连续亏损暂停: ≥5次暂停24小时
    3. 回撤仓位缩减: >30%时仓位×0.5
    """
    
    NORMAL_MAX_POSITIONS = 4
    BEARISH_MAX_POSITIONS = 2
    NORMAL_MIN_SCORE = 70
    BEARISH_MIN_SCORE = 85
    CONSECUTIVE_LOSS_PAUSE_THRESHOLD = 5
    PAUSE_DURATION_HOURS = 24
    DRAWDOWN_REDUCTION_THRESHOLD = 30.0
    DRAWDOWN_POSITION_MULTIPLIER = 0.5
    
    def __init__(
        self,
        regime_detector: MarketRegimeDetector,
        stop_loss_controller: StopLossController,
        sector_weight_manager: SectorWeightManager,
        signal_calibrator: SignalCalibrator
    ):
        self.regime_detector = regime_detector
        self.stop_loss_controller = stop_loss_controller
        self.sector_weight_manager = sector_weight_manager
        self.signal_calibrator = signal_calibrator
        self._consecutive_losses = 0
        self._trading_paused_until: Optional[datetime] = None
        self._current_drawdown_pct = 0.0
    
    def get_trading_parameters(
        self,
        market_regime: MarketRegimeType,
        current_drawdown: float = 0.0,
        sector: str = None,
        current_time: datetime = None
    ) -> TradingParameters:
        """获取当前交易参数"""
        # 检查是否暂停
        is_paused = False
        pause_reason = None
        if current_time:
            allowed, reason = self.is_trading_allowed(current_time)
            is_paused = not allowed
            pause_reason = reason
        
        # 熊市参数调整
        if market_regime == MarketRegimeType.BEARISH:
            max_positions = self.BEARISH_MAX_POSITIONS
            min_signal_score = self.BEARISH_MIN_SCORE
        else:
            max_positions = self.NORMAL_MAX_POSITIONS
            min_signal_score = self.NORMAL_MIN_SCORE
        
        # 回撤仓位缩减
        if current_drawdown > self.DRAWDOWN_REDUCTION_THRESHOLD:
            position_size_multiplier = self.DRAWDOWN_POSITION_MULTIPLIER
        else:
            position_size_multiplier = 1.0
        
        # 获取止损阈值
        stop_loss_threshold = 10.0  # 默认值
        if sector:
            stop_loss_result = self.stop_loss_controller.get_stop_loss_threshold(sector, market_regime)
            stop_loss_threshold = stop_loss_result.final_threshold
        
        return TradingParameters(
            max_positions=max_positions,
            min_signal_score=min_signal_score,
            position_size_multiplier=position_size_multiplier,
            stop_loss_threshold=stop_loss_threshold,
            is_trading_paused=is_paused,
            pause_reason=pause_reason,
            pause_until=self._trading_paused_until
        )
    
    def record_trade_result(self, is_win: bool, current_time: datetime, current_drawdown_pct: float = 0.0) -> None:
        """记录交易结果"""
        self._current_drawdown_pct = current_drawdown_pct
        if is_win:
            self._consecutive_losses = 0
        else:
            self._consecutive_losses += 1
            if self._consecutive_losses >= self.CONSECUTIVE_LOSS_PAUSE_THRESHOLD:
                self._trading_paused_until = current_time + timedelta(hours=self.PAUSE_DURATION_HOURS)
    
    def is_trading_allowed(self, current_time: datetime) -> Tuple[bool, Optional[str]]:
        """检查是否允许交易"""
        if self._trading_paused_until and current_time < self._trading_paused_until:
            return False, f"连续亏损{self._consecutive_losses}次，暂停至{self._trading_paused_until}"
        if self._trading_paused_until and current_time >= self._trading_paused_until:
            self._trading_paused_until = None
            self._consecutive_losses = 0
        return True, None
    
    def get_consecutive_losses(self) -> int:
        return self._consecutive_losses
    
    def reset(self) -> None:
        self._consecutive_losses = 0
        self._trading_paused_until = None
        self._current_drawdown_pct = 0.0
