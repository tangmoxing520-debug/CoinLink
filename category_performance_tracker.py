"""
板块表现追踪器 (Category Performance Tracker)
追踪各板块表现，专注于AI Agent板块优化

Requirements: 3.1, 3.2, 3.3, 3.4, 3.5
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)


@dataclass
class CoinPerformance:
    """币种表现数据"""
    symbol: str
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    win_rate: float = 0.0
    consecutive_losses: int = 0
    is_blacklisted: bool = False
    blacklist_until: Optional[datetime] = None


@dataclass
class CategoryParams:
    """板块参数"""
    stop_loss_pct: float
    weight_multiplier: float
    priority_order: List[str]


class CategoryPerformanceTracker:
    """
    板块表现追踪器
    
    功能:
    1. AI Agent止损: 8%止损 (比默认10%更严格)
    2. AIXBT黑名单: 连续3次亏损加入24小时黑名单
    3. 优先级排序: VIRTUALUSDT > FARTCOINUSDT > AIXBTUSDT
    4. 胜率权重: 胜率低于50%时权重降低30%
    5. 独立追踪: 每个币种独立追踪表现
    
    Properties:
    - Property 7: AI Agent Stop-Loss Tightening
    - Property 8: AIXBT Blacklist on Consecutive Losses
    - Property 9: AI Agent Weight Reduction on Low Win Rate
    """
    
    AI_AGENT_SYMBOLS: Set[str] = {
        "AIXBTUSDT", "VIRTUALUSDT", "FARTCOINUSDT",
        "UAIUSDT"
        # SWARMSUSDT 已移除 - 频繁触发止损，表现不佳
    }
    
    # 永久黑名单 - 表现极差的币种
    PERMANENT_BLACKLIST: Set[str] = {
        "SWARMSUSDT"  # 频繁触发止损，亏损严重
    }
    
    AI_AGENT_STOP_LOSS = 8.0           # AI Agent止损 (8%)
    DEFAULT_STOP_LOSS = 10.0           # 默认止损 (10%)
    BLACKLIST_CONSECUTIVE_LOSSES = 3   # 连续亏损黑名单阈值
    BLACKLIST_DURATION_HOURS = 24      # 黑名单时长
    LOW_WIN_RATE_THRESHOLD = 0.50      # 低胜率阈值
    WEIGHT_REDUCTION = 0.30            # 权重降低比例
    
    # 优先级顺序 (基于历史表现)
    PRIORITY_ORDER = ["VIRTUALUSDT", "FARTCOINUSDT", "AIXBTUSDT"]
    
    def __init__(self):
        """初始化板块表现追踪器"""
        self._coin_performance: Dict[str, CoinPerformance] = {}
        self._category_stats: Dict[str, Dict] = {}
        self._ai_agent_win_rate = 0.0
        self._ai_agent_total_trades = 0
        self._ai_agent_wins = 0
    
    def get_category_params(
        self,
        category: str,
        current_time: datetime
    ) -> CategoryParams:
        """
        获取板块参数
        
        Property 7: AI Agent Stop-Loss Tightening
        For any AI Agent category coin, the stop-loss SHALL be 8%
        
        Property 9: AI Agent Weight Reduction on Low Win Rate
        For any AI Agent category with win rate below 50%, 
        the category weight SHALL be reduced by 30%
        
        Args:
            category: 板块名称
            current_time: 当前时间
            
        Returns:
            CategoryParams: 板块参数
        """
        # 清理过期黑名单
        self._cleanup_expired_blacklists(current_time)
        
        # AI Agent板块特殊处理
        if category == "AI Agent":
            stop_loss = self.AI_AGENT_STOP_LOSS
            
            # 计算权重乘数
            weight_multiplier = 1.0
            if self._ai_agent_win_rate < self.LOW_WIN_RATE_THRESHOLD and self._ai_agent_total_trades >= 5:
                weight_multiplier = 1.0 - self.WEIGHT_REDUCTION  # 0.7
            
            return CategoryParams(
                stop_loss_pct=stop_loss,
                weight_multiplier=weight_multiplier,
                priority_order=self.PRIORITY_ORDER.copy()
            )
        
        # 其他板块使用默认参数
        return CategoryParams(
            stop_loss_pct=self.DEFAULT_STOP_LOSS,
            weight_multiplier=1.0,
            priority_order=[]
        )
    
    def record_trade(
        self,
        symbol: str,
        category: str,
        is_win: bool,
        timestamp: datetime
    ) -> None:
        """
        记录交易结果
        
        Property 8: AIXBT Blacklist on Consecutive Losses
        When AIXBTUSDT has 3 consecutive losses, 
        AIXBTUSDT SHALL be blacklisted for 24 hours
        
        Args:
            symbol: 交易对
            category: 板块名称
            is_win: 是否盈利
            timestamp: 交易时间
        """
        # 初始化币种表现记录
        if symbol not in self._coin_performance:
            self._coin_performance[symbol] = CoinPerformance(symbol=symbol)
        
        perf = self._coin_performance[symbol]
        perf.total_trades += 1
        
        if is_win:
            perf.wins += 1
            perf.consecutive_losses = 0
        else:
            perf.losses += 1
            perf.consecutive_losses += 1
        
        # 更新胜率
        perf.win_rate = perf.wins / perf.total_trades if perf.total_trades > 0 else 0.0
        
        # AI Agent板块统计
        if symbol in self.AI_AGENT_SYMBOLS:
            self._ai_agent_total_trades += 1
            if is_win:
                self._ai_agent_wins += 1
            self._ai_agent_win_rate = (
                self._ai_agent_wins / self._ai_agent_total_trades 
                if self._ai_agent_total_trades > 0 else 0.0
            )
        
        # 检查AIXBT黑名单
        if symbol == "AIXBTUSDT":
            self._update_blacklist(symbol, timestamp)
        
        logger.info(
            f"交易记录: {symbol}, 胜负={'胜' if is_win else '负'}, "
            f"连续亏损={perf.consecutive_losses}, 胜率={perf.win_rate:.1%}"
        )
    
    def is_coin_blacklisted(
        self,
        symbol: str,
        current_time: datetime
    ) -> bool:
        """
        检查币种是否在黑名单
        
        Args:
            symbol: 交易对
            current_time: 当前时间
            
        Returns:
            bool: 是否在黑名单
        """
        # 检查永久黑名单
        if symbol in self.PERMANENT_BLACKLIST:
            return True
        
        if symbol not in self._coin_performance:
            return False
        
        perf = self._coin_performance[symbol]
        
        if not perf.is_blacklisted:
            return False
        
        # 检查黑名单是否过期
        if perf.blacklist_until and current_time >= perf.blacklist_until:
            perf.is_blacklisted = False
            perf.blacklist_until = None
            logger.info(f"{symbol} 黑名单已过期，恢复交易")
            return False
        
        return True
    
    def get_priority_symbol(
        self,
        available_symbols: List[str],
        current_time: datetime
    ) -> Optional[str]:
        """
        获取优先交易的币种
        
        Args:
            available_symbols: 可用币种列表
            current_time: 当前时间
            
        Returns:
            Optional[str]: 优先币种，无可用则返回None
        """
        # 过滤黑名单币种
        valid_symbols = [
            s for s in available_symbols 
            if not self.is_coin_blacklisted(s, current_time)
        ]
        
        if not valid_symbols:
            return None
        
        # 按优先级排序
        for priority_symbol in self.PRIORITY_ORDER:
            if priority_symbol in valid_symbols:
                return priority_symbol
        
        # 返回第一个可用的
        return valid_symbols[0]
    
    def get_coin_performance(self, symbol: str) -> Optional[CoinPerformance]:
        """获取币种表现数据"""
        return self._coin_performance.get(symbol)
    
    def get_ai_agent_win_rate(self) -> float:
        """获取AI Agent板块胜率"""
        return self._ai_agent_win_rate
    
    def is_ai_agent_symbol(self, symbol: str) -> bool:
        """判断是否为AI Agent币种"""
        return symbol in self.AI_AGENT_SYMBOLS
    
    def reset(self) -> None:
        """重置追踪器状态"""
        self._coin_performance.clear()
        self._category_stats.clear()
        self._ai_agent_win_rate = 0.0
        self._ai_agent_total_trades = 0
        self._ai_agent_wins = 0
    
    def _update_blacklist(
        self,
        symbol: str,
        timestamp: datetime
    ) -> None:
        """
        更新黑名单状态
        
        Property 8: AIXBT Blacklist on Consecutive Losses
        """
        if symbol not in self._coin_performance:
            return
        
        perf = self._coin_performance[symbol]
        
        # 检查是否达到黑名单阈值
        if perf.consecutive_losses >= self.BLACKLIST_CONSECUTIVE_LOSSES:
            perf.is_blacklisted = True
            perf.blacklist_until = timestamp + timedelta(hours=self.BLACKLIST_DURATION_HOURS)
            logger.warning(
                f"{symbol} 加入黑名单: 连续{perf.consecutive_losses}次亏损，"
                f"解除时间: {perf.blacklist_until}"
            )
    
    def _cleanup_expired_blacklists(self, current_time: datetime) -> None:
        """清理过期的黑名单"""
        for symbol, perf in self._coin_performance.items():
            if perf.is_blacklisted and perf.blacklist_until:
                if current_time >= perf.blacklist_until:
                    perf.is_blacklisted = False
                    perf.blacklist_until = None
