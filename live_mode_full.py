"""
实盘交易 Mode Full 增强模块

将 --mode full 回测的核心优势应用到实盘交易:
1. 技术指标冷启动 - 定期重新计算，避免历史数据污染
2. 状态完全重置 - 黑名单、冷却期、持仓状态定期清空
3. 新鲜开始效应 - 每周期都能捕捉新趋势
4. 指标预热期 - 跳过前N个信号等待指标稳定

核心配置 (config.py V8_CONFIG):
- periodic_reset.interval_days: 重置间隔（默认30天）
- cold_start.warmup_candles: 冷启动预热K线数（默认50）
- cold_start.skip_first_signals: 跳过前N个信号（默认3）
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set, Tuple
from dataclasses import dataclass, field
import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class ColdStartConfig:
    """冷启动配置"""
    warmup_candles: int = 50  # 预热K线数
    skip_first_signals: int = 3  # 跳过前N个信号
    indicator_reset_on_period: bool = True  # 周期重置时重置指标


@dataclass
class PeriodicResetConfig:
    """定期重置配置"""
    enabled: bool = True
    interval_days: int = 30  # 重置间隔（天）
    reset_blacklist: bool = True  # 重置黑名单
    reset_cooldown: bool = True  # 重置冷却期
    reset_price_cache: bool = True  # 重置价格缓存
    reset_indicators: bool = True  # 重置技术指标


@dataclass
class BlacklistConfig:
    """黑名单配置"""
    max_consecutive_losses: int = 3  # 连续亏损N次加入黑名单
    blacklist_duration_hours: int = 24  # 黑名单持续时间
    auto_remove_on_reset: bool = True  # 重置时自动移除


@dataclass
class PeriodStats:
    """周期统计"""
    start_time: datetime
    end_time: Optional[datetime] = None
    total_pnl: float = 0.0
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    signals_skipped: int = 0  # 冷启动跳过的信号数
    blacklist_count: int = 0  # 黑名单数量
    
    @property
    def win_rate(self) -> float:
        if self.total_trades == 0:
            return 0.0
        return (self.winning_trades / self.total_trades) * 100


class IndicatorColdStarter:
    """
    技术指标冷启动管理器
    
    核心功能:
    1. 管理指标预热状态
    2. 跳过预热期内的信号
    3. 周期重置时触发冷启动
    """
    
    def __init__(self, config: ColdStartConfig):
        self.config = config
        self._warmup_status: Dict[str, bool] = {}  # symbol -> is_warmed_up
        self._signal_count: Dict[str, int] = {}  # symbol -> signal_count
        self._candle_count: Dict[str, int] = {}  # symbol -> candle_count
        self._last_reset_time: datetime = datetime.now()
    
    def reset(self) -> None:
        """重置所有冷启动状态"""
        self._warmup_status.clear()
        self._signal_count.clear()
        self._candle_count.clear()
        self._last_reset_time = datetime.now()
        logger.info("[冷启动] 所有指标状态已重置，进入预热期")
    
    def update_candle_count(self, symbol: str, count: int) -> None:
        """更新K线计数"""
        self._candle_count[symbol] = count
        
        # 检查是否完成预热
        if count >= self.config.warmup_candles:
            if not self._warmup_status.get(symbol, False):
                self._warmup_status[symbol] = True
                logger.info(f"[冷启动] {symbol} 完成预热 ({count} K线)")
    
    def is_warmed_up(self, symbol: str) -> bool:
        """检查指标是否已预热"""
        return self._warmup_status.get(symbol, False)
    
    def should_skip_signal(self, symbol: str) -> Tuple[bool, str]:
        """
        检查是否应跳过信号
        
        Returns:
            (should_skip, reason)
        """
        # 检查K线预热
        if not self.is_warmed_up(symbol):
            candles = self._candle_count.get(symbol, 0)
            return True, f"指标预热中 ({candles}/{self.config.warmup_candles} K线)"
        
        # 检查信号计数
        signal_count = self._signal_count.get(symbol, 0)
        if signal_count < self.config.skip_first_signals:
            self._signal_count[symbol] = signal_count + 1
            return True, f"跳过早期信号 ({signal_count + 1}/{self.config.skip_first_signals})"
        
        return False, ""
    
    def record_signal(self, symbol: str) -> None:
        """记录信号（用于计数）"""
        self._signal_count[symbol] = self._signal_count.get(symbol, 0) + 1


class DynamicBlacklistManager:
    """
    动态黑名单管理器
    
    核心功能:
    1. 连续亏损自动加入黑名单
    2. 定期重置时清空黑名单
    3. 盈利时重置亏损计数
    """
    
    def __init__(self, config: BlacklistConfig):
        self.config = config
        self._blacklist: Dict[str, datetime] = {}  # symbol -> blacklist_time
        self._loss_count: Dict[str, int] = {}  # symbol -> consecutive_losses
    
    def reset(self) -> int:
        """
        重置黑名单
        
        Returns:
            清除的黑名单数量
        """
        count = len(self._blacklist)
        self._blacklist.clear()
        self._loss_count.clear()
        logger.info(f"[黑名单] 已清空 {count} 个交易对")
        return count
    
    def is_blacklisted(self, symbol: str) -> bool:
        """检查是否在黑名单中"""
        if symbol not in self._blacklist:
            return False
        
        # 检查是否过期
        blacklist_time = self._blacklist[symbol]
        duration = timedelta(hours=self.config.blacklist_duration_hours)
        
        if datetime.now() - blacklist_time > duration:
            # 已过期，移除
            del self._blacklist[symbol]
            logger.info(f"[黑名单] {symbol} 黑名单已过期，自动移除")
            return False
        
        return True
    
    def record_trade_result(self, symbol: str, is_win: bool) -> None:
        """
        记录交易结果
        
        Args:
            symbol: 交易对
            is_win: 是否盈利
        """
        if is_win:
            # 盈利，重置亏损计数
            self._loss_count[symbol] = 0
        else:
            # 亏损，增加计数
            self._loss_count[symbol] = self._loss_count.get(symbol, 0) + 1
            
            # 检查是否达到黑名单阈值
            if self._loss_count[symbol] >= self.config.max_consecutive_losses:
                self._blacklist[symbol] = datetime.now()
                logger.warning(
                    f"[黑名单] {symbol} 连续亏损 {self._loss_count[symbol]} 次，"
                    f"加入黑名单 {self.config.blacklist_duration_hours} 小时"
                )
    
    @property
    def blacklist_count(self) -> int:
        """当前黑名单数量"""
        return len(self._blacklist)
    
    @property
    def blacklisted_symbols(self) -> Set[str]:
        """当前黑名单交易对"""
        return set(self._blacklist.keys())


class LiveModeFullManager:
    """
    实盘 Mode Full 管理器
    
    整合所有 --mode full 优势到实盘交易:
    1. 定期重置机制
    2. 技术指标冷启动
    3. 动态黑名单管理
    4. 周期统计
    """
    
    def __init__(
        self,
        periodic_config: PeriodicResetConfig = None,
        cold_start_config: ColdStartConfig = None,
        blacklist_config: BlacklistConfig = None
    ):
        self.periodic_config = periodic_config or PeriodicResetConfig()
        self.cold_start_config = cold_start_config or ColdStartConfig()
        self.blacklist_config = blacklist_config or BlacklistConfig()
        
        # 初始化子管理器
        self.cold_starter = IndicatorColdStarter(self.cold_start_config)
        self.blacklist_manager = DynamicBlacklistManager(self.blacklist_config)
        
        # 周期管理
        self._last_reset_time: datetime = datetime.now()
        self._current_period: PeriodStats = PeriodStats(start_time=datetime.now())
        self._period_history: List[PeriodStats] = []
        
        # 价格缓存（用于重置）
        self._price_cache: Dict[str, pd.DataFrame] = {}
        
        # 冷却期管理
        self._cooldown: Dict[str, datetime] = {}  # symbol -> cooldown_until
        
        logger.info(f"[Mode Full] 初始化完成")
        logger.info(f"  - 重置间隔: {self.periodic_config.interval_days} 天")
        logger.info(f"  - 预热K线: {self.cold_start_config.warmup_candles}")
        logger.info(f"  - 跳过信号: {self.cold_start_config.skip_first_signals}")
        logger.info(f"  - 黑名单阈值: {self.blacklist_config.max_consecutive_losses} 次连续亏损")
    
    def check_and_perform_reset(self) -> bool:
        """
        检查并执行定期重置
        
        Returns:
            是否执行了重置
        """
        if not self.periodic_config.enabled:
            return False
        
        days_since_reset = (datetime.now() - self._last_reset_time).days
        
        if days_since_reset >= self.periodic_config.interval_days:
            self._perform_reset()
            return True
        
        return False
    
    def _perform_reset(self) -> None:
        """执行定期重置"""
        current_time = datetime.now()
        
        # 结束当前周期
        self._current_period.end_time = current_time
        self._current_period.blacklist_count = self.blacklist_manager.blacklist_count
        self._period_history.append(self._current_period)
        
        # 打印周期统计
        logger.info("=" * 60)
        logger.info(f"[Mode Full] 周期重置 - 周期结束")
        logger.info("=" * 60)
        logger.info(f"  周期: {self._current_period.start_time.strftime('%Y-%m-%d')} ~ "
                   f"{current_time.strftime('%Y-%m-%d')}")
        logger.info(f"  周期盈亏: {self._current_period.total_pnl:+,.2f} USDT")
        logger.info(f"  周期交易: {self._current_period.total_trades} 次")
        logger.info(f"  胜率: {self._current_period.win_rate:.1f}%")
        logger.info(f"  跳过信号: {self._current_period.signals_skipped} 个 (冷启动)")
        
        # 执行重置
        if self.periodic_config.reset_blacklist:
            cleared = self.blacklist_manager.reset()
            logger.info(f"  清空黑名单: {cleared} 个交易对")
        
        if self.periodic_config.reset_cooldown:
            self._cooldown.clear()
            logger.info(f"  清空冷却期")
        
        if self.periodic_config.reset_price_cache:
            self._price_cache.clear()
            logger.info(f"  清空价格缓存")
        
        if self.periodic_config.reset_indicators:
            self.cold_starter.reset()
            logger.info(f"  重置技术指标 (进入冷启动)")
        
        # 开始新周期
        self._last_reset_time = current_time
        self._current_period = PeriodStats(start_time=current_time)
        
        logger.info(f"[Mode Full] 新周期开始")
        logger.info("=" * 60)
    
    def can_trade(self, symbol: str) -> Tuple[bool, str]:
        """
        检查是否可以交易
        
        Returns:
            (can_trade, reason)
        """
        # 检查黑名单
        if self.blacklist_manager.is_blacklisted(symbol):
            return False, "在黑名单中"
        
        # 检查冷却期
        if symbol in self._cooldown:
            if datetime.now() < self._cooldown[symbol]:
                remaining = (self._cooldown[symbol] - datetime.now()).total_seconds() / 60
                return False, f"冷却中 ({remaining:.0f}分钟)"
            else:
                del self._cooldown[symbol]
        
        # 检查冷启动
        should_skip, reason = self.cold_starter.should_skip_signal(symbol)
        if should_skip:
            self._current_period.signals_skipped += 1
            return False, reason
        
        return True, ""
    
    def record_trade(self, symbol: str, pnl: float, is_win: bool) -> None:
        """
        记录交易结果
        
        Args:
            symbol: 交易对
            pnl: 盈亏金额
            is_win: 是否盈利
        """
        # 更新周期统计
        self._current_period.total_pnl += pnl
        self._current_period.total_trades += 1
        if is_win:
            self._current_period.winning_trades += 1
        else:
            self._current_period.losing_trades += 1
        
        # 更新黑名单
        self.blacklist_manager.record_trade_result(symbol, is_win)
    
    def set_cooldown(self, symbol: str, minutes: int = 30) -> None:
        """设置冷却期"""
        self._cooldown[symbol] = datetime.now() + timedelta(minutes=minutes)
    
    def update_indicator_data(self, symbol: str, df: pd.DataFrame) -> None:
        """
        更新指标数据（用于冷启动检测）
        
        Args:
            symbol: 交易对
            df: K线数据
        """
        self.cold_starter.update_candle_count(symbol, len(df))
        self._price_cache[symbol] = df
    
    def get_period_summary(self) -> Dict:
        """获取当前周期摘要"""
        return {
            'start_time': self._current_period.start_time,
            'days_elapsed': (datetime.now() - self._current_period.start_time).days,
            'days_until_reset': max(0, self.periodic_config.interval_days - 
                                   (datetime.now() - self._last_reset_time).days),
            'total_pnl': self._current_period.total_pnl,
            'total_trades': self._current_period.total_trades,
            'win_rate': self._current_period.win_rate,
            'signals_skipped': self._current_period.signals_skipped,
            'blacklist_count': self.blacklist_manager.blacklist_count,
            'blacklisted_symbols': list(self.blacklist_manager.blacklisted_symbols)
        }
    
    def get_history_summary(self) -> List[Dict]:
        """获取历史周期摘要"""
        return [
            {
                'period': f"{p.start_time.strftime('%Y-%m-%d')} ~ {p.end_time.strftime('%Y-%m-%d') if p.end_time else 'ongoing'}",
                'pnl': p.total_pnl,
                'trades': p.total_trades,
                'win_rate': p.win_rate,
                'signals_skipped': p.signals_skipped
            }
            for p in self._period_history
        ]


def create_live_mode_full_manager(config: Dict = None) -> LiveModeFullManager:
    """
    从配置创建 LiveModeFullManager
    
    Args:
        config: V8_CONFIG 配置字典，如果为 None 则使用默认值
    
    Returns:
        LiveModeFullManager 实例
    """
    if config is None:
        # 尝试从 config.py 导入
        try:
            from config import V8_CONFIG
            config = V8_CONFIG
        except ImportError:
            config = {}
    
    # 解析配置
    periodic_cfg = config.get('periodic_reset', {})
    cold_start_cfg = config.get('cold_start', {})
    blacklist_cfg = config.get('blacklist', {})
    
    return LiveModeFullManager(
        periodic_config=PeriodicResetConfig(
            enabled=periodic_cfg.get('enabled', True),
            interval_days=periodic_cfg.get('interval_days', 30),
            reset_blacklist=periodic_cfg.get('reset_blacklist', True),
            reset_cooldown=periodic_cfg.get('reset_cooldown', True),
            reset_price_cache=periodic_cfg.get('reset_price_cache', True),
            reset_indicators=periodic_cfg.get('reset_indicators', True),
        ),
        cold_start_config=ColdStartConfig(
            warmup_candles=cold_start_cfg.get('warmup_candles', 50),
            skip_first_signals=cold_start_cfg.get('skip_first_signals', 3),
            indicator_reset_on_period=cold_start_cfg.get('indicator_reset_on_period', True),
        ),
        blacklist_config=BlacklistConfig(
            max_consecutive_losses=blacklist_cfg.get('max_consecutive_losses', 3),
            blacklist_duration_hours=blacklist_cfg.get('blacklist_duration_hours', 24),
            auto_remove_on_reset=blacklist_cfg.get('auto_remove_on_reset', True),
        )
    )


# 便捷函数
def integrate_with_main(monitor_instance) -> None:
    """
    将 Mode Full 功能集成到 main.py 的 CryptoMonitor
    
    使用方法:
    ```python
    from live_mode_full import integrate_with_main, create_live_mode_full_manager
    
    monitor = CryptoMonitor()
    monitor.mode_full_manager = create_live_mode_full_manager()
    integrate_with_main(monitor)
    ```
    """
    if not hasattr(monitor_instance, 'mode_full_manager'):
        monitor_instance.mode_full_manager = create_live_mode_full_manager()
    
    manager = monitor_instance.mode_full_manager
    
    # 保存原始方法
    original_run_cycle = monitor_instance.run_monitoring_cycle
    original_execute_trade = monitor_instance._execute_trade
    original_close_trade = monitor_instance._close_trade
    
    def enhanced_run_cycle():
        """增强的监控周期"""
        # 检查定期重置
        manager.check_and_perform_reset()
        # 执行原始监控
        original_run_cycle()
    
    def enhanced_execute_trade(symbol: str, category: str) -> bool:
        """增强的交易执行"""
        # 检查是否可以交易
        can_trade, reason = manager.can_trade(symbol)
        if not can_trade:
            logger.info(f"[Mode Full] 跳过交易 {symbol}: {reason}")
            return False
        # 执行原始交易
        return original_execute_trade(symbol, category)
    
    def enhanced_close_trade(trade, reason: str) -> bool:
        """增强的平仓"""
        result = original_close_trade(trade, reason)
        if result:
            # 记录交易结果
            is_win = trade.profit_loss > 0
            manager.record_trade(trade.symbol, trade.profit_loss, is_win)
            # 设置冷却期
            if not is_win:
                manager.set_cooldown(trade.symbol, 30)
        return result
    
    # 替换方法
    monitor_instance.run_monitoring_cycle = enhanced_run_cycle
    monitor_instance._execute_trade = enhanced_execute_trade
    monitor_instance._close_trade = enhanced_close_trade
    
    logger.info("[Mode Full] 已集成到 CryptoMonitor")
