"""
Meme币风险控制器 (Meme Risk Controller)
专门管理高波动Meme币的风险，包括仓位控制、止损和暂停机制

Requirements: 2.1, 2.2, 2.3, 2.4, 2.5
"""
from dataclasses import dataclass
from typing import Dict, List, Optional, Set
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)


@dataclass
class MemeTradeResult:
    """Meme交易结果"""
    symbol: str
    profit_loss: float
    is_win: bool
    timestamp: datetime


@dataclass
class MemeRiskParams:
    """Meme风险参数"""
    position_multiplier: float
    stop_loss_pct: float
    min_signal_score: float
    is_paused: bool
    pause_until: Optional[datetime]


class MemeRiskController:
    """
    Meme币风险控制器
    
    功能:
    1. 仓位控制: Meme币使用0.5x仓位乘数 (降低风险敞口)
    2. 止损控制: 12%止损阈值 (收紧止损)
    3. 信号门槛: 最低85分信号要求
    4. 暂停机制: 连续2次亏损暂停4小时
    5. 胜率追踪: 根据胜率调整策略
    
    Properties:
    - Property 3: Meme Position Size Reduction
    - Property 4: Meme Stop-Loss Trigger
    - Property 5: Meme Entry Signal Requirement
    - Property 6: Meme Consecutive Loss Pause
    """
    
    MEME_SYMBOLS: Set[str] = {
        "WIFUSDT", "1000PEPEUSDT", "1000BONKUSDT", 
        "DOGEUSDT", "1000SHIBUSDT"
    }
    
    POSITION_MULTIPLIER = 0.5      # 仓位乘数 (从0.7降至0.5，降低风险敞口)
    MEME_STOP_LOSS = 12.0          # Meme专用止损 (从15%收紧至12%)
    MEME_MIN_SIGNAL = 85.0         # Meme最低信号分
    CONSECUTIVE_LOSS_PAUSE = 2     # 连续亏损暂停阈值
    PAUSE_DURATION_HOURS = 4       # 暂停时长
    
    def __init__(self):
        """初始化Meme风险控制器"""
        self._trade_history: List[MemeTradeResult] = []
        self._consecutive_losses = 0
        self._paused_until: Optional[datetime] = None
        self._meme_win_rate = 0.0
        self._total_wins = 0
        self._total_trades = 0
    
    def get_risk_params(
        self,
        symbol: str,
        current_time: datetime
    ) -> MemeRiskParams:
        """
        获取Meme币风险参数
        
        Property 3: Meme Position Size Reduction
        For any Meme category coin, the position size multiplier SHALL be 0.7
        
        Property 5: Meme Entry Signal Requirement
        For any Meme trade entry, the signal score SHALL be at least 85
        
        Args:
            symbol: 交易对
            current_time: 当前时间
            
        Returns:
            MemeRiskParams: 风险参数
        """
        # 检查是否在暂停期
        is_paused = self._is_paused(current_time)
        
        return MemeRiskParams(
            position_multiplier=self.POSITION_MULTIPLIER,
            stop_loss_pct=self.MEME_STOP_LOSS,
            min_signal_score=self.MEME_MIN_SIGNAL,
            is_paused=is_paused,
            pause_until=self._paused_until if is_paused else None
        )
    
    def record_trade(
        self,
        symbol: str,
        profit_loss: float,
        timestamp: datetime
    ) -> None:
        """
        记录Meme交易结果
        
        Property 6: Meme Consecutive Loss Pause
        When 2 consecutive trades result in losses, Meme trading SHALL be paused for 4 hours
        
        Args:
            symbol: 交易对
            profit_loss: 盈亏金额
            timestamp: 交易时间
        """
        if not self.is_meme_symbol(symbol):
            return
        
        is_win = profit_loss > 0
        
        result = MemeTradeResult(
            symbol=symbol,
            profit_loss=profit_loss,
            is_win=is_win,
            timestamp=timestamp
        )
        self._trade_history.append(result)
        
        # 更新统计
        self._total_trades += 1
        if is_win:
            self._total_wins += 1
        
        # 更新胜率
        self._calculate_win_rate()
        
        # 更新连续亏损计数
        self._update_consecutive_losses(is_win, timestamp)
        
        logger.info(
            f"Meme交易记录: {symbol}, 盈亏={profit_loss:.2f}, "
            f"连续亏损={self._consecutive_losses}, 胜率={self._meme_win_rate:.1%}"
        )
    
    def is_meme_symbol(self, symbol: str) -> bool:
        """
        判断是否为Meme币
        
        Args:
            symbol: 交易对
            
        Returns:
            bool: 是否为Meme币
        """
        return symbol in self.MEME_SYMBOLS
    
    def should_trigger_stop_loss(
        self,
        current_loss_pct: float
    ) -> bool:
        """
        判断是否触发Meme专用止损
        
        Property 4: Meme Stop-Loss Trigger
        For any Meme trade with current loss exceeding 15%, 
        the system SHALL trigger immediate stop-loss
        
        Args:
            current_loss_pct: 当前亏损百分比 (负数表示亏损)
            
        Returns:
            bool: 是否触发止损
        """
        # current_loss_pct 为负数时表示亏损
        # 例如 -15.5 表示亏损15.5%
        return current_loss_pct <= -self.MEME_STOP_LOSS
    
    def can_enter_trade(
        self,
        symbol: str,
        signal_score: float,
        current_time: datetime
    ) -> tuple:
        """
        检查是否可以入场Meme交易
        
        Args:
            symbol: 交易对
            signal_score: 信号评分
            current_time: 当前时间
            
        Returns:
            tuple: (can_enter, reason)
        """
        if not self.is_meme_symbol(symbol):
            return True, "非Meme币"
        
        # 检查暂停状态
        if self._is_paused(current_time):
            return False, f"Meme交易暂停中，恢复时间: {self._paused_until}"
        
        # 检查信号评分
        if signal_score < self.MEME_MIN_SIGNAL:
            return False, f"信号评分{signal_score:.1f}低于Meme最低要求{self.MEME_MIN_SIGNAL}"
        
        return True, "允许入场"
    
    def get_win_rate(self) -> float:
        """获取Meme币胜率"""
        return self._meme_win_rate
    
    def get_consecutive_losses(self) -> int:
        """获取当前连续亏损次数"""
        return self._consecutive_losses
    
    def get_trade_history(self) -> List[MemeTradeResult]:
        """获取交易历史"""
        return self._trade_history.copy()
    
    def reset(self) -> None:
        """重置控制器状态"""
        self._trade_history.clear()
        self._consecutive_losses = 0
        self._paused_until = None
        self._meme_win_rate = 0.0
        self._total_wins = 0
        self._total_trades = 0
    
    def _is_paused(self, current_time: datetime) -> bool:
        """检查是否在暂停期"""
        if self._paused_until is None:
            return False
        return current_time < self._paused_until
    
    def _update_consecutive_losses(
        self,
        is_win: bool,
        timestamp: datetime
    ) -> None:
        """
        更新连续亏损计数
        
        Property 6: Meme Consecutive Loss Pause
        When 2 consecutive trades result in losses, 
        Meme trading SHALL be paused for 4 hours
        """
        if is_win:
            # 盈利重置连续亏损计数
            self._consecutive_losses = 0
            # 如果之前在暂停期，盈利后可以提前解除
            # (保持原暂停时间，不提前解除)
        else:
            # 亏损增加计数
            self._consecutive_losses += 1
            
            # 检查是否触发暂停
            if self._consecutive_losses >= self.CONSECUTIVE_LOSS_PAUSE:
                self._paused_until = timestamp + timedelta(hours=self.PAUSE_DURATION_HOURS)
                logger.warning(
                    f"Meme交易暂停: 连续{self._consecutive_losses}次亏损，"
                    f"暂停至 {self._paused_until}"
                )
    
    def _calculate_win_rate(self) -> float:
        """计算Meme币胜率"""
        if self._total_trades == 0:
            self._meme_win_rate = 0.0
        else:
            self._meme_win_rate = self._total_wins / self._total_trades
        return self._meme_win_rate
