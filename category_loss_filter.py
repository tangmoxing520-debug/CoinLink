"""
分类亏损过滤器 (Category Loss Filter)
追踪和过滤持续亏损的分类

功能:
1. 追踪每个分类的累计盈亏、交易次数、胜率
2. 自动识别持续亏损分类
3. 对表现差的分类采取措施（黑名单、降权、暂停）
4. 生成分类表现报告

Requirements: 1.1-1.5, 2.1-2.4, 3.1-3.4, 5.1-5.4, 6.1-6.4
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)


@dataclass
class CategoryLossFilterConfig:
    """
    分类亏损过滤器配置
    
    Requirements: 6.1, 6.2
    """
    # 累计亏损阈值 (USDT) - 低于此值标记为 poor_performing
    cumulative_pnl_threshold: float = -2000.0
    
    # 胜率阈值 (百分比) - 低于此值标记为 low_win_rate
    win_rate_threshold: float = 40.0
    
    # 连续亏损阈值 - 达到此值标记为 loss_streak
    consecutive_loss_threshold: int = 5
    
    # 最小交易数 (触发过滤的最小交易数)
    min_trades_for_filter: int = 10
    
    # 权重降低比例 (百分比)
    weight_reduction_pct: float = 50.0
    
    # 暂停时长 (小时，回测时间)
    suspension_hours: float = 24.0
    
    # 是否启用自动过滤
    auto_filter_enabled: bool = True
    
    def validate(self) -> None:
        """
        验证配置参数
        
        Requirements: 6.3
        
        Raises:
            ValueError: 配置参数无效
        """
        if self.cumulative_pnl_threshold > 0:
            raise ValueError(f"cumulative_pnl_threshold must be <= 0, got {self.cumulative_pnl_threshold}")
        
        if not 0 <= self.win_rate_threshold <= 100:
            raise ValueError(f"win_rate_threshold must be between 0 and 100, got {self.win_rate_threshold}")
        
        if self.consecutive_loss_threshold < 1:
            raise ValueError(f"consecutive_loss_threshold must be >= 1, got {self.consecutive_loss_threshold}")
        
        if self.min_trades_for_filter < 1:
            raise ValueError(f"min_trades_for_filter must be >= 1, got {self.min_trades_for_filter}")
        
        if not 0 <= self.weight_reduction_pct <= 100:
            raise ValueError(f"weight_reduction_pct must be between 0 and 100, got {self.weight_reduction_pct}")
        
        if self.suspension_hours < 0:
            raise ValueError(f"suspension_hours must be >= 0, got {self.suspension_hours}")


@dataclass
class CategoryStats:
    """
    分类统计数据
    
    Requirements: 1.1, 1.2, 1.3, 1.4, 1.5
    """
    category: str
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    cumulative_pnl: float = 0.0
    consecutive_losses: int = 0
    last_trade_time: Optional[datetime] = None
    
    # 状态标志
    is_poor_performing: bool = False
    is_low_win_rate: bool = False
    is_loss_streak: bool = False
    
    # 过滤状态
    is_blacklisted: bool = False
    is_weight_reduced: bool = False
    is_suspended: bool = False
    suspension_until: Optional[datetime] = None
    weight_multiplier: float = 1.0
    
    @property
    def win_rate(self) -> float:
        """
        计算胜率
        
        Requirements: 1.5
        
        Returns:
            float: 胜率百分比 (0-100)
        """
        if self.total_trades == 0:
            return 0.0
        return round((self.wins / self.total_trades) * 100, 1)
    
    @property
    def status(self) -> str:
        """获取当前状态"""
        if self.is_blacklisted:
            return "blacklisted"
        if self.is_suspended:
            return "suspended"
        if self.is_weight_reduced:
            return "weight_reduced"
        return "active"
    
    @property
    def flags(self) -> List[str]:
        """获取所有标志"""
        result = []
        if self.is_poor_performing:
            result.append("poor_performing")
        if self.is_low_win_rate:
            result.append("low_win_rate")
        if self.is_loss_streak:
            result.append("loss_streak")
        return result


@dataclass
class CategoryPerformanceReport:
    """
    分类表现报告
    
    Requirements: 5.2
    """
    category: str
    total_trades: int
    wins: int
    losses: int
    win_rate: float
    cumulative_pnl: float
    status: str
    weight_multiplier: float
    flags: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict:
        """
        转换为字典，用于JSON序列化
        
        Requirements: 5.4
        """
        return {
            "category": self.category,
            "total_trades": self.total_trades,
            "wins": self.wins,
            "losses": self.losses,
            "win_rate": self.win_rate,
            "cumulative_pnl": self.cumulative_pnl,
            "status": self.status,
            "weight_multiplier": self.weight_multiplier,
            "flags": self.flags
        }


class CategoryLossFilter:
    """
    分类亏损过滤器
    
    追踪和过滤持续亏损的分类
    
    Requirements: 1.1-1.5, 2.1-2.4, 3.1-3.4, 5.1-5.4, 6.1-6.4
    """
    
    def __init__(self, config: CategoryLossFilterConfig = None):
        """
        初始化过滤器
        
        Requirements: 6.2
        
        Args:
            config: 过滤器配置，如果为None则使用默认配置
        """
        if config is None:
            config = CategoryLossFilterConfig()
        else:
            config.validate()
        
        self.config = config
        self._stats: Dict[str, CategoryStats] = {}
    
    def record_trade(
        self,
        category: str,
        pnl: float,
        is_win: bool,
        trade_time: datetime
    ) -> None:
        """
        记录交易结果
        
        Requirements: 1.1, 1.2, 1.3, 1.4
        
        Args:
            category: 分类名称
            pnl: 盈亏金额 (USDT)
            is_win: 是否盈利
            trade_time: 交易时间
        """
        # 获取或创建分类统计
        if category not in self._stats:
            self._stats[category] = CategoryStats(category=category)
        
        stats = self._stats[category]
        
        # 更新累计盈亏 (Requirement 1.1)
        stats.cumulative_pnl += pnl
        
        # 更新交易计数 (Requirement 1.2)
        stats.total_trades += 1
        
        # 更新胜负计数和连续亏损 (Requirements 1.3, 1.4)
        if is_win:
            stats.wins += 1
            stats.consecutive_losses = 0  # 重置连续亏损
        else:
            stats.losses += 1
            stats.consecutive_losses += 1
        
        stats.last_trade_time = trade_time
        
        # 更新标志和应用动作
        if self.config.auto_filter_enabled:
            self._update_flags(category)
            self._apply_actions(category, trade_time)
            self._check_recovery(category)
        
        logger.debug(
            f"记录交易: {category}, PnL={pnl:+.2f}, "
            f"累计={stats.cumulative_pnl:+.2f}, "
            f"胜率={stats.win_rate:.1f}%, "
            f"连续亏损={stats.consecutive_losses}"
        )
    
    def _update_flags(self, category: str) -> None:
        """
        更新分类标志
        
        Requirements: 2.1, 2.2, 2.3
        
        Args:
            category: 分类名称
        """
        if category not in self._stats:
            return
        
        stats = self._stats[category]
        
        # 检查累计亏损阈值 (Requirement 2.1)
        stats.is_poor_performing = stats.cumulative_pnl < self.config.cumulative_pnl_threshold
        
        # 检查胜率阈值 (Requirement 2.2)
        stats.is_low_win_rate = stats.win_rate < self.config.win_rate_threshold
        
        # 检查连续亏损阈值 (Requirement 2.3)
        stats.is_loss_streak = stats.consecutive_losses >= self.config.consecutive_loss_threshold
    
    def _apply_actions(self, category: str, current_time: datetime) -> None:
        """
        应用过滤动作
        
        Requirements: 3.1, 3.2, 3.3
        
        Args:
            category: 分类名称
            current_time: 当前时间
        """
        if category not in self._stats:
            return
        
        stats = self._stats[category]
        
        # 检查是否达到最小交易数
        has_enough_trades = stats.total_trades >= self.config.min_trades_for_filter
        
        # 黑名单触发 (Requirement 3.1)
        if stats.is_poor_performing and has_enough_trades:
            if not stats.is_blacklisted:
                stats.is_blacklisted = True
                logger.warning(
                    f"分类 {category} 加入黑名单: "
                    f"累计亏损 {stats.cumulative_pnl:+.2f} < {self.config.cumulative_pnl_threshold}"
                )
        
        # 权重降低触发 (Requirement 3.2)
        if stats.is_low_win_rate and has_enough_trades:
            if not stats.is_weight_reduced:
                stats.is_weight_reduced = True
                stats.weight_multiplier = 1.0 - (self.config.weight_reduction_pct / 100)
                logger.warning(
                    f"分类 {category} 权重降低: "
                    f"胜率 {stats.win_rate:.1f}% < {self.config.win_rate_threshold}%, "
                    f"权重乘数 {stats.weight_multiplier:.2f}"
                )
        
        # 暂停触发 (Requirement 3.3)
        if stats.is_loss_streak:
            if not stats.is_suspended:
                stats.is_suspended = True
                stats.suspension_until = current_time + timedelta(hours=self.config.suspension_hours)
                logger.warning(
                    f"分类 {category} 暂停交易: "
                    f"连续亏损 {stats.consecutive_losses} >= {self.config.consecutive_loss_threshold}, "
                    f"恢复时间 {stats.suspension_until}"
                )
    
    def _check_recovery(self, category: str) -> None:
        """
        检查黑名单恢复
        
        Requirements: 3.4
        
        Args:
            category: 分类名称
        """
        if category not in self._stats:
            return
        
        stats = self._stats[category]
        
        # 检查累计盈亏是否改善 (Requirement 3.4)
        if stats.is_blacklisted and stats.cumulative_pnl >= self.config.cumulative_pnl_threshold:
            stats.is_blacklisted = False
            logger.info(
                f"分类 {category} 移除黑名单: "
                f"累计盈亏改善至 {stats.cumulative_pnl:+.2f}"
            )
    
    def is_category_eligible(
        self,
        category: str,
        current_time: datetime
    ) -> Tuple[bool, str]:
        """
        检查分类是否可交易
        
        Requirements: 3.1, 3.3
        
        Args:
            category: 分类名称
            current_time: 当前时间
            
        Returns:
            Tuple[bool, str]: (是否可交易, 原因)
        """
        if category not in self._stats:
            return True, "active"
        
        stats = self._stats[category]
        
        # 检查黑名单
        if stats.is_blacklisted:
            return False, f"blacklisted (cumulative_pnl={stats.cumulative_pnl:+.2f})"
        
        # 检查暂停状态
        if stats.is_suspended:
            if stats.suspension_until and current_time >= stats.suspension_until:
                # 暂停到期，恢复交易
                stats.is_suspended = False
                stats.suspension_until = None
                stats.consecutive_losses = 0  # 重置连续亏损
                logger.info(f"分类 {category} 暂停到期，恢复交易")
                return True, "active (suspension expired)"
            else:
                return False, f"suspended until {stats.suspension_until}"
        
        return True, "active"
    
    def get_category_weight(self, category: str) -> float:
        """
        获取分类权重乘数
        
        Requirements: 3.2
        
        Args:
            category: 分类名称
            
        Returns:
            float: 权重乘数 (0.0-1.0)
        """
        if category not in self._stats:
            return 1.0
        
        return self._stats[category].weight_multiplier
    
    def get_flagged_categories(self) -> Dict[str, List[str]]:
        """
        获取所有被标记的分类及原因
        
        Requirements: 2.4
        
        Returns:
            Dict[str, List[str]]: {分类名称: [标志列表]}
        """
        result = {}
        for category, stats in self._stats.items():
            flags = stats.flags
            if flags:
                result[category] = flags
        return result
    
    def get_performance_summary(self) -> List[Dict]:
        """
        获取分类表现摘要
        
        Requirements: 5.1, 5.2, 5.3, 5.4
        
        Returns:
            List[Dict]: 按累计盈亏降序排列的分类表现列表
        """
        reports = []
        for category, stats in self._stats.items():
            report = CategoryPerformanceReport(
                category=category,
                total_trades=stats.total_trades,
                wins=stats.wins,
                losses=stats.losses,
                win_rate=stats.win_rate,
                cumulative_pnl=stats.cumulative_pnl,
                status=stats.status,
                weight_multiplier=stats.weight_multiplier,
                flags=stats.flags
            )
            reports.append(report.to_dict())
        
        # 按累计盈亏降序排列 (Requirement 5.3)
        reports.sort(key=lambda x: x["cumulative_pnl"], reverse=True)
        
        return reports
    
    def get_category_stats(self, category: str) -> Optional[CategoryStats]:
        """
        获取分类统计数据
        
        Args:
            category: 分类名称
            
        Returns:
            Optional[CategoryStats]: 分类统计，不存在则返回None
        """
        return self._stats.get(category)
    
    def reset(self) -> None:
        """
        重置过滤器状态
        
        Requirements: 4.1
        """
        self._stats.clear()
        logger.info("分类亏损过滤器已重置")
    
    def update_config(self, config: CategoryLossFilterConfig) -> None:
        """
        更新配置
        
        Requirements: 6.3, 6.4
        
        Args:
            config: 新配置
            
        Raises:
            ValueError: 配置参数无效
        """
        config.validate()
        self.config = config
        
        # 立即应用新参数 (Requirement 6.4)
        for category in self._stats:
            self._update_flags(category)
        
        logger.info("分类亏损过滤器配置已更新")
    
    def print_summary(self) -> None:
        """打印分类表现摘要"""
        summary = self.get_performance_summary()
        
        if not summary:
            print("📊 暂无分类统计数据")
            return
        
        print("\n" + "=" * 80)
        print("📊 分类表现摘要")
        print("=" * 80)
        print(f"{'分类':<15} {'交易数':>8} {'胜率':>8} {'累计盈亏':>12} {'状态':<15} {'标志'}")
        print("-" * 80)
        
        for item in summary:
            flags_str = ", ".join(item["flags"]) if item["flags"] else "-"
            print(
                f"{item['category']:<15} "
                f"{item['total_trades']:>8} "
                f"{item['win_rate']:>7.1f}% "
                f"{item['cumulative_pnl']:>+11.2f} "
                f"{item['status']:<15} "
                f"{flags_str}"
            )
        
        print("=" * 80)
        
        # 打印汇总
        total_trades = sum(item["total_trades"] for item in summary)
        total_pnl = sum(item["cumulative_pnl"] for item in summary)
        blacklisted = sum(1 for item in summary if item["status"] == "blacklisted")
        weight_reduced = sum(1 for item in summary if item["status"] == "weight_reduced")
        suspended = sum(1 for item in summary if item["status"] == "suspended")
        
        print(f"总交易数: {total_trades}, 总盈亏: {total_pnl:+.2f} USDT")
        print(f"黑名单: {blacklisted}, 降权: {weight_reduced}, 暂停: {suspended}")
        print("=" * 80)
