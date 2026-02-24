"""
板块权重管理器 (Sector Weight Manager)
基于历史表现动态调整板块权重，并管理板块黑名单

Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 6.1, 6.2, 6.3, 6.4, 6.5
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from datetime import datetime, timedelta


@dataclass
class SectorPerformance:
    """板块表现统计"""
    sector: str
    total_trades: int
    winning_trades: int
    win_rate: float
    profit_factor: float
    consecutive_losses: int
    last_trade_time: Optional[datetime] = None


@dataclass
class SectorWeightResult:
    """板块权重计算结果"""
    sector: str
    base_weight: float
    performance_adjustment: float
    final_weight: float
    reason: str  # "insufficient_history", "low_win_rate", "high_win_rate", "normal"


@dataclass
class BlacklistEntry:
    """黑名单条目"""
    sector: str
    blacklist_time: datetime
    reason: str
    consecutive_losses: int


@dataclass
class TradeRecord:
    """交易记录"""
    sector: str
    profit_loss: float
    timestamp: datetime
    is_win: bool


class SectorWeightManager:
    """
    板块权重管理器
    
    功能:
    1. 基于历史表现动态调整板块权重
       - 胜率 < 40%: 权重减半 (×0.5)
       - 胜率 > 55%: 权重增加 (×1.25)
       - 权重边界: [0.1, 2.0]
    2. 板块黑名单机制
       - 连续亏损 N 次加入黑名单 (可配置)
       - M 小时后自动移除 (可配置)
       - 连续盈利可提前解除黑名单
    """
    
    MIN_WEIGHT = 0.1
    MAX_WEIGHT = 2.0
    DEFAULT_WEIGHT = 1.0
    MIN_TRADES_FOR_ADJUSTMENT = 10
    LOOKBACK_TRADES = 20
    
    LOW_WIN_RATE_THRESHOLD = 0.40
    HIGH_WIN_RATE_THRESHOLD = 0.55
    LOW_WIN_RATE_PENALTY = 0.5
    HIGH_WIN_RATE_BONUS = 1.25
    
    # 默认黑名单配置
    BLACKLIST_CONSECUTIVE_LOSSES = 5
    BLACKLIST_DURATION_HOURS = 48
    
    # V5 优化: 提前解除黑名单配置
    EARLY_RELEASE_ENABLED = False
    EARLY_RELEASE_CONSECUTIVE_WINS = 3  # 连续盈利3次可提前解除
    
    def __init__(
        self,
        blacklist_consecutive_losses: int = None,
        blacklist_duration_hours: float = None,
        early_release_enabled: bool = None,
        early_release_consecutive_wins: int = None
    ):
        """
        初始化板块权重管理器
        
        Args:
            blacklist_consecutive_losses: 连续亏损多少次加入黑名单 (默认5)
            blacklist_duration_hours: 黑名单持续时间 (小时, 默认48)
            early_release_enabled: 是否启用提前解除黑名单 (默认False)
            early_release_consecutive_wins: 连续盈利多少次可提前解除 (默认3)
        """
        self._sector_trades: Dict[str, List[TradeRecord]] = {}
        self._sector_weights: Dict[str, float] = {}
        self._blacklist: Dict[str, BlacklistEntry] = {}
        self._weight_history: List[dict] = []
        self._blacklist_logs: List[dict] = []
        
        # 可配置的黑名单参数
        if blacklist_consecutive_losses is not None:
            self.BLACKLIST_CONSECUTIVE_LOSSES = blacklist_consecutive_losses
        if blacklist_duration_hours is not None:
            self.BLACKLIST_DURATION_HOURS = blacklist_duration_hours
        if early_release_enabled is not None:
            self.EARLY_RELEASE_ENABLED = early_release_enabled
        if early_release_consecutive_wins is not None:
            self.EARLY_RELEASE_CONSECUTIVE_WINS = early_release_consecutive_wins
        
        # 记录其他板块的连续盈利次数 (用于提前解除黑名单)
        self._sector_consecutive_wins: Dict[str, int] = {}
    
    def record_trade(
        self,
        sector: str,
        profit_loss: float,
        timestamp: datetime
    ) -> None:
        """
        记录交易结果
        
        Args:
            sector: 板块名称
            profit_loss: 盈亏金额
            timestamp: 交易时间
        """
        if sector not in self._sector_trades:
            self._sector_trades[sector] = []
        
        is_win = profit_loss > 0
        
        record = TradeRecord(
            sector=sector,
            profit_loss=profit_loss,
            timestamp=timestamp,
            is_win=is_win
        )
        
        self._sector_trades[sector].append(record)
        
        # 更新连续盈利计数 (用于提前解除黑名单)
        if is_win:
            self._sector_consecutive_wins[sector] = self._sector_consecutive_wins.get(sector, 0) + 1
        else:
            self._sector_consecutive_wins[sector] = 0
        
        # 检查是否需要加入黑名单
        self._check_and_add_to_blacklist(sector, timestamp)
        
        # 检查是否可以提前解除其他板块的黑名单
        if self.EARLY_RELEASE_ENABLED and is_win:
            self._check_early_release(sector, timestamp)
        
        # 更新权重
        self._update_sector_weight(sector)
    
    def get_sector_weight(self, sector: str) -> SectorWeightResult:
        """
        获取板块权重
        
        Args:
            sector: 板块名称
            
        Returns:
            SectorWeightResult: 权重计算结果
        """
        performance = self.get_sector_performance(sector)
        return self._calculate_weight(performance)
    
    def get_sector_performance(self, sector: str) -> SectorPerformance:
        """
        获取板块表现统计
        
        Args:
            sector: 板块名称
            
        Returns:
            SectorPerformance: 表现统计
        """
        trades = self._sector_trades.get(sector, [])
        
        # 只看最近 LOOKBACK_TRADES 笔交易
        recent_trades = trades[-self.LOOKBACK_TRADES:] if trades else []
        
        total_trades = len(recent_trades)
        winning_trades = sum(1 for t in recent_trades if t.is_win)
        win_rate = winning_trades / total_trades if total_trades > 0 else 0.0
        
        # 计算盈亏因子
        total_profit = sum(t.profit_loss for t in recent_trades if t.profit_loss > 0)
        total_loss = abs(sum(t.profit_loss for t in recent_trades if t.profit_loss < 0))
        profit_factor = total_profit / total_loss if total_loss > 0 else float('inf') if total_profit > 0 else 0.0
        
        # 计算连续亏损次数
        consecutive_losses = self._count_consecutive_losses(sector)
        
        last_trade_time = trades[-1].timestamp if trades else None
        
        return SectorPerformance(
            sector=sector,
            total_trades=total_trades,
            winning_trades=winning_trades,
            win_rate=win_rate,
            profit_factor=profit_factor,
            consecutive_losses=consecutive_losses,
            last_trade_time=last_trade_time
        )
    
    def is_sector_blacklisted(self, sector: str) -> bool:
        """
        检查板块是否在黑名单中
        
        Args:
            sector: 板块名称
            
        Returns:
            bool: 是否在黑名单中
        """
        return sector in self._blacklist
    
    def update_blacklist(self, current_time: datetime) -> List[str]:
        """
        更新黑名单状态，移除过期条目
        
        Args:
            current_time: 当前时间
            
        Returns:
            List[str]: 被移除的板块列表
        """
        removed = []
        duration = timedelta(hours=self.BLACKLIST_DURATION_HOURS)
        
        for sector in list(self._blacklist.keys()):
            entry = self._blacklist[sector]
            if current_time >= entry.blacklist_time + duration:
                del self._blacklist[sector]
                removed.append(sector)
                
                # 记录移除日志
                self._blacklist_logs.append({
                    'action': 'remove',
                    'sector': sector,
                    'timestamp': current_time,
                    'reason': f'{self.BLACKLIST_DURATION_HOURS}小时已过 (加入时间: {entry.blacklist_time})'
                })
                
                print(f"✅ 板块 {sector} 已从黑名单移除 ({self.BLACKLIST_DURATION_HOURS}小时已过)")
        
        return removed
    
    def _check_and_add_to_blacklist(
        self,
        sector: str,
        timestamp: datetime
    ) -> bool:
        """
        检查是否需要加入黑名单
        
        Args:
            sector: 板块名称
            timestamp: 当前时间
            
        Returns:
            bool: 是否加入了黑名单
        """
        # 已在黑名单中则跳过
        if sector in self._blacklist:
            return False
        
        consecutive_losses = self._count_consecutive_losses(sector)
        
        if consecutive_losses >= self.BLACKLIST_CONSECUTIVE_LOSSES:
            entry = BlacklistEntry(
                sector=sector,
                blacklist_time=timestamp,
                reason=f"连续亏损 {consecutive_losses} 次",
                consecutive_losses=consecutive_losses
            )
            
            self._blacklist[sector] = entry
            
            # 记录添加日志
            self._blacklist_logs.append({
                'action': 'add',
                'sector': sector,
                'timestamp': timestamp,
                'reason': entry.reason,
                'consecutive_losses': consecutive_losses
            })
            
            print(f"⛔ 板块 {sector} 已加入黑名单 (连续亏损 {consecutive_losses} 次)")
            return True
        
        return False
    
    def _count_consecutive_losses(self, sector: str) -> int:
        """
        计算连续亏损次数
        
        Args:
            sector: 板块名称
            
        Returns:
            int: 连续亏损次数
        """
        trades = self._sector_trades.get(sector, [])
        if not trades:
            return 0
        
        count = 0
        for trade in reversed(trades):
            if trade.is_win:
                break
            count += 1
        
        return count
    
    def _calculate_weight(self, performance: SectorPerformance) -> SectorWeightResult:
        """
        计算板块权重
        
        Args:
            performance: 板块表现
            
        Returns:
            SectorWeightResult: 权重结果
        """
        sector = performance.sector
        base_weight = self.DEFAULT_WEIGHT
        
        # 交易不足时使用默认权重
        if performance.total_trades < self.MIN_TRADES_FOR_ADJUSTMENT:
            return SectorWeightResult(
                sector=sector,
                base_weight=base_weight,
                performance_adjustment=1.0,
                final_weight=base_weight,
                reason="insufficient_history"
            )
        
        # 根据胜率调整权重
        if performance.win_rate < self.LOW_WIN_RATE_THRESHOLD:
            adjustment = self.LOW_WIN_RATE_PENALTY
            reason = "low_win_rate"
        elif performance.win_rate > self.HIGH_WIN_RATE_THRESHOLD:
            adjustment = self.HIGH_WIN_RATE_BONUS
            reason = "high_win_rate"
        else:
            adjustment = 1.0
            reason = "normal"
        
        # 计算最终权重并限制边界
        final_weight = base_weight * adjustment
        final_weight = max(self.MIN_WEIGHT, min(self.MAX_WEIGHT, final_weight))
        
        return SectorWeightResult(
            sector=sector,
            base_weight=base_weight,
            performance_adjustment=adjustment,
            final_weight=final_weight,
            reason=reason
        )
    
    def _update_sector_weight(self, sector: str) -> None:
        """更新板块权重缓存"""
        result = self.get_sector_weight(sector)
        self._sector_weights[sector] = result.final_weight
        
        # 记录权重历史
        self._weight_history.append({
            'sector': sector,
            'weight': result.final_weight,
            'reason': result.reason,
            'timestamp': datetime.now()
        })
    
    def get_all_weights(self) -> Dict[str, float]:
        """获取所有板块权重"""
        return self._sector_weights.copy()
    
    def get_weight_history(self) -> List[dict]:
        """获取权重历史"""
        return self._weight_history.copy()
    
    def get_blacklist_logs(self) -> List[dict]:
        """获取黑名单日志"""
        return self._blacklist_logs.copy()
    
    def get_blacklisted_sectors(self) -> List[str]:
        """获取当前黑名单中的板块"""
        return list(self._blacklist.keys())
    
    def _check_early_release(self, winning_sector: str, current_time: datetime) -> List[str]:
        """
        检查是否可以提前解除黑名单
        当某个板块连续盈利达到阈值时，可以提前解除其他板块的黑名单
        
        Args:
            winning_sector: 刚刚盈利的板块
            current_time: 当前时间
            
        Returns:
            List[str]: 被提前解除的板块列表
        """
        if not self.EARLY_RELEASE_ENABLED:
            return []
        
        released = []
        consecutive_wins = self._sector_consecutive_wins.get(winning_sector, 0)
        
        # 检查是否达到提前解除条件
        if consecutive_wins >= self.EARLY_RELEASE_CONSECUTIVE_WINS:
            # 提前解除所有黑名单板块
            for sector in list(self._blacklist.keys()):
                entry = self._blacklist[sector]
                del self._blacklist[sector]
                released.append(sector)
                
                # 记录提前解除日志
                self._blacklist_logs.append({
                    'action': 'early_release',
                    'sector': sector,
                    'timestamp': current_time,
                    'reason': f'板块 {winning_sector} 连续盈利 {consecutive_wins} 次，提前解除',
                    'trigger_sector': winning_sector,
                    'consecutive_wins': consecutive_wins
                })
                
                print(f"✅ 板块 {sector} 提前解除黑名单 ({winning_sector} 连续盈利 {consecutive_wins} 次)")
            
            # 重置连续盈利计数
            self._sector_consecutive_wins[winning_sector] = 0
        
        return released
    
    def get_blacklist_config(self) -> Dict[str, any]:
        """获取当前黑名单配置"""
        return {
            'consecutive_losses': self.BLACKLIST_CONSECUTIVE_LOSSES,
            'duration_hours': self.BLACKLIST_DURATION_HOURS,
            'early_release_enabled': self.EARLY_RELEASE_ENABLED,
            'early_release_consecutive_wins': self.EARLY_RELEASE_CONSECUTIVE_WINS
        }
    
    def clear_all(self) -> None:
        """清空所有数据"""
        self._sector_trades.clear()
        self._sector_weights.clear()
        self._blacklist.clear()
        self._weight_history.clear()
        self._blacklist_logs.clear()
        self._sector_consecutive_wins.clear()
