"""
回测验证系统 V2 - 优化版策略 (永续合约版)
主要改进:
1. 趋势过滤 - 只在上涨趋势中交易
2. 成交量确认 - 放量突破更可靠
3. 动态止损 - 移动止损保护利润
4. 信号强度评分 - 多维度评估入场质量
5. 仓位管理 - 根据信号强度调整仓位
6. 冷却期 - 避免频繁交易
7. 最大持仓限制 - 控制风险敞口
8. 杠杆交易 - 支持永续合约杠杆倍数
"""
import pandas as pd
import numpy as np
import warnings
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum
import requests
import time

# 忽略 numpy 相关系数计算时的除零警告 (数据标准差为零时的正常边界情况)
warnings.filterwarnings('ignore', category=RuntimeWarning, message='invalid value encountered in divide')

from config import (
    CRYPTO_CATEGORIES, EXCHANGE, MONITOR_CONFIG, 
    BINANCE_FUTURES_API_URL, LEADER_COINS,
    CATEGORY_THRESHOLDS, THRESHOLD_DEFAULT,
    ROTATION_CONFIG,
    CATEGORY_BLACKLIST, SYMBOL_BLACKLIST, CATEGORY_WEIGHT_ADJUSTMENTS,
    STRATEGY_OPTIMIZATION_ENABLED,
    CATEGORY_STOP_LOSS, DAILY_LOSS_LIMIT_CONFIG
)

from rotation_models import RotationConfig, SectorData, CoinData, SectorTier
from rotation_manager import RotationManager

# 策略优化组件
from market_regime_detector import MarketRegimeDetector, MarketRegimeType
from stop_loss_controller import StopLossController
from sector_weight_manager import SectorWeightManager
from signal_calibrator import SignalCalibrator
from strategy_optimizer import StrategyOptimizer

# 数据缓存
from data_cache import get_cache, DataCache

# Q3/Q4 优化组件
try:
    from q3q4_optimizer import Q3Q4Optimizer, Q3Q4TradeDecision
    Q3Q4_OPTIMIZER_AVAILABLE = True
except ImportError:
    Q3Q4_OPTIMIZER_AVAILABLE = False

# 分类亏损过滤器
from category_loss_filter import CategoryLossFilter, CategoryLossFilterConfig


class StopLossType(Enum):
    """止损类型枚举"""
    FIXED = "fixed"              # 固定止损
    DYNAMIC_ATR = "dynamic"      # 动态ATR止损
    SIGNAL_BASED = "signal"      # 信号评分止损
    BREAKEVEN = "breakeven"      # 保本止损
    TRAILING = "trailing"        # 移动止损
    TIME_DECAY = "time_decay"    # 时间衰减止损
    LIQUIDATION = "liquidation"  # 强平


@dataclass
class StopLossConfig:
    """止损配置"""
    # 动态止损 (ATR)
    dynamic_sl_enabled: bool = True
    atr_multiplier: float = 2.0
    min_stop_loss: float = 5.0
    max_stop_loss: float = 15.0
    
    # 提前保本止损
    early_breakeven_enabled: bool = True
    early_breakeven_threshold: float = 5.0  # 盈利5%激活
    early_breakeven_buffer: float = 0.2     # 0.2%缓冲
    
    # 信号评分止损
    signal_based_sl_enabled: bool = True
    high_score_sl: float = 12.0   # 评分>=80
    medium_score_sl: float = 10.0 # 评分60-79
    low_score_sl: float = 8.0     # 评分<60
    
    # 时间衰减止损
    time_decay_sl_enabled: bool = True
    time_decay_factor_12h: float = 0.8
    time_decay_factor_24h: float = 0.6
    min_decayed_sl: float = 5.0
    
    # 短期时间止损 (2小时)
    short_time_stop_enabled: bool = True
    short_time_stop_hours: float = 2.0
    short_time_stop_min_profit: float = 3.0
    
    # 长期时间止损 (24小时)
    long_time_stop_enabled: bool = True
    long_time_stop_hours: float = 24.0
    long_time_stop_min_profit: float = 0.0


class MarketRegime(Enum):
    """市场状态枚举"""
    UPTREND = "uptrend"      # 上涨趋势
    DOWNTREND = "downtrend"  # 下跌趋势
    RANGING = "ranging"      # 震荡市


@dataclass
class SignalScoreConfig:
    """信号评分配置"""
    enabled: bool = True
    
    # 各维度权重 (自动归一化)
    trend_weight: float = 0.25
    volume_weight: float = 0.20
    momentum_weight: float = 0.20
    volatility_weight: float = 0.15
    correlation_weight: float = 0.20
    
    # 最低入场评分
    min_signal_score: float = 30.0
    
    # 趋势评分参数
    adx_strong_threshold: float = 25.0
    
    # 成交量评分参数
    volume_high_ratio: float = 2.0      # 高成交量阈值 (相对平均)
    volume_abnormal_ratio: float = 5.0  # 异常成交量阈值
    
    # 波动率评分参数
    volatility_high_threshold: float = 5.0  # ATR > 5% of price 为高波动
    volatility_low_threshold: float = 1.0   # ATR < 1% of price 为低波动
    
    # 相关性评分参数
    correlation_high_threshold: float = 0.7  # 高相关性阈值
    correlation_lookback: int = 20           # 相关性计算周期
    
    # 市场状态自适应
    regime_adaptation_enabled: bool = True


@dataclass
class ScoreBreakdown:
    """评分明细，用于调试和分析"""
    trend_score: float = 0.0
    volume_score: float = 0.0
    momentum_score: float = 0.0
    volatility_score: float = 0.0
    correlation_score: float = 0.0
    
    # 各维度详情
    trend_details: Dict[str, any] = field(default_factory=dict)
    volume_details: Dict[str, any] = field(default_factory=dict)
    momentum_details: Dict[str, any] = field(default_factory=dict)
    volatility_details: Dict[str, any] = field(default_factory=dict)
    correlation_details: Dict[str, any] = field(default_factory=dict)
    
    # 市场状态和最终评分
    market_regime: str = ''
    final_score: float = 0.0
    
    # 权重 (可能因市场状态调整)
    applied_weights: Dict[str, float] = field(default_factory=dict)


@dataclass
class SignalScoreStats:
    """评分统计"""
    total_trades: int = 0
    # 按评分区间统计
    trades_by_score_range: Dict[str, int] = field(default_factory=dict)
    win_rate_by_score_range: Dict[str, float] = field(default_factory=dict)
    avg_profit_by_score_range: Dict[str, float] = field(default_factory=dict)
    # 评分与结果相关性
    score_outcome_correlation: float = 0.0
    # 最具预测性的维度
    most_predictive_dimension: str = ''
    dimension_correlations: Dict[str, float] = field(default_factory=dict)


@dataclass
class BacktestTradeV2:
    """回测交易记录 V2 - 永续合约版"""
    symbol: str
    category: str
    entry_time: datetime
    entry_price: float
    exit_time: Optional[datetime] = None
    exit_price: Optional[float] = None
    quantity: float = 0.0
    margin: float = 0.0  # 保证金 (实际占用资金)
    position_value: float = 0.0  # 仓位价值 (保证金 * 杠杆)
    leverage: int = 1  # 杠杆倍数
    profit_loss: float = 0.0
    profit_loss_pct: float = 0.0  # 基于保证金的收益率
    status: str = 'open'
    trigger_coin: str = ''
    trigger_change: float = 0.0
    exit_reason: str = ''
    signal_score: float = 0.0
    trailing_stop: float = 0.0
    highest_price: float = 0.0
    liquidation_price: float = 0.0  # 强平价格
    # 分批止盈相关字段
    initial_quantity: float = 0.0  # 初始数量
    initial_margin: float = 0.0  # 初始保证金
    tp_level: int = 0  # 已触发的止盈级别 (0=未触发, 1=10%, 2=20%, 3=30%)
    realized_pnl: float = 0.0  # 已实现盈亏 (分批止盈累计)
    breakeven_stop: float = 0.0  # 保本止损价格
    # 止损优化相关字段
    initial_stop_loss_pct: float = 0.0    # 初始止损百分比
    current_stop_loss_pct: float = 0.0    # 当前止损百分比
    stop_loss_type: str = ''              # 止损类型
    atr_at_entry: float = 0.0             # 入场时ATR值
    early_breakeven_activated: bool = False  # 提前保本是否激活
    time_decay_applied: bool = False      # 时间衰减是否应用


@dataclass
class StopLossStats:
    """止损统计"""
    total_stops: int = 0
    stops_by_type: Dict[str, int] = field(default_factory=dict)
    avg_loss_by_type: Dict[str, float] = field(default_factory=dict)
    breakeven_win_rate: float = 0.0
    efficiency: float = 0.0  # 止损效率


@dataclass
class BacktestResultV2:
    """回测结果 V2"""
    start_date: datetime
    end_date: datetime
    initial_balance: float
    final_balance: float
    total_trades: int
    winning_trades: int
    losing_trades: int
    total_profit_loss: float
    win_rate: float
    max_drawdown: float
    max_drawdown_pct: float
    sharpe_ratio: float
    profit_factor: float
    avg_profit_per_trade: float
    avg_holding_time: float
    avg_win: float
    avg_loss: float
    leverage: int = 1  # 杠杆倍数
    liquidations: int = 0  # 强平次数
    trades: List[BacktestTradeV2] = field(default_factory=list)
    equity_curve: List[Tuple[datetime, float]] = field(default_factory=list)
    stop_loss_stats: Optional[StopLossStats] = None  # 止损统计
    signal_score_stats: Optional[SignalScoreStats] = None  # 评分统计
    category_performance: Optional[List[Dict]] = None  # V7: 分类表现统计


class StopLossManager:
    """止损管理器 - 负责所有止损逻辑的计算和判断"""
    
    def __init__(self, config: StopLossConfig):
        self.config = config
    
    def calculate_dynamic_stop_loss(
        self,
        entry_price: float,
        atr: float
    ) -> float:
        """
        基于ATR计算动态止损百分比
        公式: stop_loss_pct = (atr * multiplier / entry_price) * 100
        结果会被限制在 min_stop_loss 和 max_stop_loss 之间
        """
        if atr <= 0 or entry_price <= 0:
            return self.config.medium_score_sl
        
        stop_loss_pct = (atr * self.config.atr_multiplier / entry_price) * 100
        
        # 应用 min/max 限制
        stop_loss_pct = max(self.config.min_stop_loss, stop_loss_pct)
        stop_loss_pct = min(self.config.max_stop_loss, stop_loss_pct)
        
        return stop_loss_pct
    
    def calculate_signal_based_stop_loss(
        self,
        signal_score: float
    ) -> float:
        """
        基于信号评分计算止损百分比
        - score >= 80: 使用 high_score_sl (更宽松)
        - 60 <= score < 80: 使用 medium_score_sl
        - score < 60: 使用 low_score_sl (更严格)
        """
        if signal_score >= 80:
            return self.config.high_score_sl
        elif signal_score >= 60:
            return self.config.medium_score_sl
        else:
            return self.config.low_score_sl
    
    def calculate_initial_stop_loss(
        self,
        entry_price: float,
        atr: float,
        signal_score: float,
        leverage: int = 1
    ) -> Tuple[float, str]:
        """
        计算初始止损百分比
        综合动态止损和信号止损，取较大值
        返回: (stop_loss_pct, stop_type)
        """
        dynamic_sl = 0.0
        signal_sl = 0.0
        stop_type = StopLossType.FIXED.value
        
        # 计算动态止损
        if self.config.dynamic_sl_enabled and atr > 0:
            dynamic_sl = self.calculate_dynamic_stop_loss(entry_price, atr)
        
        # 计算信号评分止损
        if self.config.signal_based_sl_enabled:
            signal_sl = self.calculate_signal_based_stop_loss(signal_score)
        
        # 取较大值
        if dynamic_sl > 0 and signal_sl > 0:
            if dynamic_sl >= signal_sl:
                return dynamic_sl, StopLossType.DYNAMIC_ATR.value
            else:
                return signal_sl, StopLossType.SIGNAL_BASED.value
        elif dynamic_sl > 0:
            return dynamic_sl, StopLossType.DYNAMIC_ATR.value
        elif signal_sl > 0:
            return signal_sl, StopLossType.SIGNAL_BASED.value
        else:
            # 都未启用，使用默认中等止损
            return self.config.medium_score_sl, StopLossType.FIXED.value
    
    def apply_time_decay(
        self,
        base_stop_loss: float,
        holding_hours: float,
        current_profit_pct: float
    ) -> Tuple[float, bool]:
        """
        应用时间衰减止损
        - 持仓 > 12h 且盈利 < 5%: 止损 * 0.85
        - 持仓 > 24h 且盈利 < 8%: 止损 * 0.7
        返回: (adjusted_stop_loss, decay_applied)
        """
        if not self.config.time_decay_sl_enabled:
            return base_stop_loss, False
        
        decay_applied = False
        adjusted_sl = base_stop_loss
        
        # 24小时衰减 (优先级更高)
        if holding_hours > 24 and current_profit_pct < 8:
            adjusted_sl = base_stop_loss * self.config.time_decay_factor_24h
            decay_applied = True
        # 12小时衰减
        elif holding_hours > 12 and current_profit_pct < 5:
            adjusted_sl = base_stop_loss * self.config.time_decay_factor_12h
            decay_applied = True
        
        # 不低于最小衰减止损
        if decay_applied:
            adjusted_sl = max(adjusted_sl, self.config.min_decayed_sl)
        
        return adjusted_sl, decay_applied
    
    def check_early_breakeven(
        self,
        trade: BacktestTradeV2,
        current_price: float,
        leverage: int = 1
    ) -> Tuple[bool, float]:
        """
        检查是否应激活提前保本止损
        返回: (should_activate, breakeven_price)
        """
        if not self.config.early_breakeven_enabled:
            return False, 0.0
        
        # 如果已经激活，不重复处理
        if trade.early_breakeven_activated:
            return False, trade.breakeven_stop
        
        # 计算当前盈利百分比 (基于价格变化，杠杆放大)
        price_change_pct = ((current_price - trade.entry_price) / trade.entry_price) * 100
        leveraged_profit_pct = price_change_pct * leverage
        
        # 检查是否达到激活阈值
        if leveraged_profit_pct >= self.config.early_breakeven_threshold:
            # 计算保本止损价 = 入场价 * (1 + buffer/100)
            breakeven_price = trade.entry_price * (1 + self.config.early_breakeven_buffer / 100)
            
            # 不覆盖已有的更高保本止损价
            if trade.breakeven_stop > 0 and breakeven_price < trade.breakeven_stop:
                return False, trade.breakeven_stop
            
            return True, breakeven_price
        
        return False, 0.0
    
    def get_effective_stop_loss(
        self,
        trade: BacktestTradeV2,
        current_price: float,
        current_time: datetime,
        leverage: int = 1
    ) -> Tuple[float, str]:
        """
        获取当前有效止损价和类型
        综合考虑: 初始止损、时间衰减、保本止损、移动止损
        返回: (stop_price, stop_type)
        """
        # 计算持仓时间
        holding_hours = (current_time - trade.entry_time).total_seconds() / 3600
        
        # 计算当前盈利
        price_change_pct = ((current_price - trade.entry_price) / trade.entry_price) * 100
        leveraged_profit_pct = price_change_pct * leverage
        
        # 获取基础止损百分比
        base_sl_pct = trade.current_stop_loss_pct if trade.current_stop_loss_pct > 0 else trade.initial_stop_loss_pct
        
        # 应用时间衰减
        adjusted_sl_pct, decay_applied = self.apply_time_decay(base_sl_pct, holding_hours, leveraged_profit_pct)
        
        # 计算止损价格 (基于杠杆后的止损百分比)
        stop_price = trade.entry_price * (1 - adjusted_sl_pct / 100 / leverage)
        stop_type = StopLossType.TIME_DECAY.value if decay_applied else trade.stop_loss_type
        
        # 检查保本止损 (优先级更高)
        if trade.breakeven_stop > 0 and trade.breakeven_stop > stop_price:
            stop_price = trade.breakeven_stop
            stop_type = StopLossType.BREAKEVEN.value
        
        # 检查移动止损 (优先级最高)
        if trade.trailing_stop > 0 and trade.trailing_stop > stop_price:
            stop_price = trade.trailing_stop
            stop_type = StopLossType.TRAILING.value
        
        return stop_price, stop_type


class TechnicalIndicators:
    """技术指标计算工具类"""
    
    @staticmethod
    def calculate_adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
        """
        计算ADX (Average Directional Index) - 趋势强度指标
        ADX > 25 表示强趋势，ADX < 20 表示弱趋势或震荡
        """
        high = df['high']
        low = df['low']
        close = df['close']
        
        # 计算 +DM 和 -DM
        plus_dm = high.diff()
        minus_dm = -low.diff()
        
        plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0)
        minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0)
        
        # 计算 TR (True Range)
        tr1 = high - low
        tr2 = abs(high - close.shift())
        tr3 = abs(low - close.shift())
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        
        # 平滑 TR, +DM, -DM
        atr = tr.rolling(window=period).mean()
        plus_di = 100 * (plus_dm.rolling(window=period).mean() / atr)
        minus_di = 100 * (minus_dm.rolling(window=period).mean() / atr)
        
        # 计算 DX 和 ADX
        dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di + 1e-10)
        adx = dx.rolling(window=period).mean()
        
        return adx
    
    @staticmethod
    def calculate_macd(
        df: pd.DataFrame,
        fast: int = 12,
        slow: int = 26,
        signal: int = 9
    ) -> Tuple[pd.Series, pd.Series, pd.Series]:
        """
        计算MACD (Moving Average Convergence Divergence)
        返回: (macd_line, signal_line, histogram)
        """
        close = df['close']
        
        # 计算快速和慢速EMA
        ema_fast = close.ewm(span=fast, adjust=False).mean()
        ema_slow = close.ewm(span=slow, adjust=False).mean()
        
        # MACD线 = 快速EMA - 慢速EMA
        macd_line = ema_fast - ema_slow
        
        # 信号线 = MACD线的EMA
        signal_line = macd_line.ewm(span=signal, adjust=False).mean()
        
        # 柱状图 = MACD线 - 信号线
        histogram = macd_line - signal_line
        
        return macd_line, signal_line, histogram
    
    @staticmethod
    def calculate_bollinger_bands(
        df: pd.DataFrame,
        period: int = 20,
        std_dev: float = 2.0
    ) -> Tuple[pd.Series, pd.Series, pd.Series, pd.Series]:
        """
        计算布林带
        返回: (upper_band, middle_band, lower_band, band_width)
        """
        close = df['close']
        
        # 中轨 = SMA
        middle_band = close.rolling(window=period).mean()
        
        # 标准差
        std = close.rolling(window=period).std()
        
        # 上轨和下轨
        upper_band = middle_band + (std_dev * std)
        lower_band = middle_band - (std_dev * std)
        
        # 带宽 = (上轨 - 下轨) / 中轨 * 100
        band_width = ((upper_band - lower_band) / middle_band) * 100
        
        return upper_band, middle_band, lower_band, band_width
    
    @staticmethod
    def calculate_roc(df: pd.DataFrame, period: int = 10) -> pd.Series:
        """
        计算ROC (Rate of Change) - 变化率
        ROC = (当前价格 - N周期前价格) / N周期前价格 * 100
        """
        close = df['close']
        roc = ((close - close.shift(period)) / close.shift(period)) * 100
        return roc
    
    @staticmethod
    def calculate_correlation(
        series1: pd.Series,
        series2: pd.Series,
        window: int = 20
    ) -> pd.Series:
        """
        计算滚动相关系数
        返回: 滚动相关系数序列 (-1 到 1)
        """
        return series1.rolling(window=window).corr(series2)
    
    @staticmethod
    def calculate_ma50(df: pd.DataFrame) -> pd.Series:
        """计算50周期移动平均线"""
        return df['close'].rolling(window=50).mean()
    
    @staticmethod
    def calculate_vol_ma20(df: pd.DataFrame) -> pd.Series:
        """计算20周期成交量移动平均"""
        return df['volume'].rolling(window=20).mean()


class SignalScorer:
    """信号评分器 - 多维度评估入场信号质量"""
    
    def __init__(self, config: SignalScoreConfig):
        self.config = config
        self._normalize_weights()
        # Hot 板块评分加成倍数 (默认 1.2，即加成 20%)
        self.hot_sector_boost: float = 1.2
    
    def _normalize_weights(self) -> None:
        """归一化权重，确保总和为1"""
        total = (self.config.trend_weight + self.config.volume_weight + 
                 self.config.momentum_weight + self.config.volatility_weight + 
                 self.config.correlation_weight)
        
        if total > 0 and abs(total - 1.0) > 0.001:
            self.config.trend_weight /= total
            self.config.volume_weight /= total
            self.config.momentum_weight /= total
            self.config.volatility_weight /= total
            self.config.correlation_weight /= total
    
    def set_hot_sector_boost(self, boost: float) -> None:
        """
        设置 Hot 板块评分加成倍数
        
        Args:
            boost: 加成倍数 (例如 1.2 表示加成 20%)
        """
        self.hot_sector_boost = max(1.0, boost)
    
    def calculate_score(
        self,
        df: pd.DataFrame,
        idx: int,
        trigger_df: pd.DataFrame = None,
        trigger_change: float = 0.0,
        coin_change: float = 0.0,
        btc_df: pd.DataFrame = None,
        sector_tier: SectorTier = None
    ) -> Tuple[float, ScoreBreakdown]:
        """
        计算综合信号评分，支持 Hot 板块评分加成
        
        Args:
            df: 币种K线数据
            idx: 当前K线索引
            trigger_df: 触发币种K线数据
            trigger_change: 触发币种涨幅
            coin_change: 当前币种涨幅
            btc_df: BTC K线数据
            sector_tier: 板块层级 (用于 Hot 板块加成)
            
        Returns:
            (final_score, breakdown): 最终评分和评分明细
        """
        breakdown = ScoreBreakdown()
        
        if not self.config.enabled:
            breakdown.final_score = 50.0
            return 50.0, breakdown
        
        try:
            # 检测市场状态
            if btc_df is not None and self.config.regime_adaptation_enabled:
                breakdown.market_regime = self.detect_market_regime(btc_df, min(idx, len(btc_df)-1))
                weights = self.adjust_weights_for_regime(breakdown.market_regime)
            else:
                breakdown.market_regime = MarketRegime.RANGING.value
                weights = {
                    'trend': self.config.trend_weight,
                    'volume': self.config.volume_weight,
                    'momentum': self.config.momentum_weight,
                    'volatility': self.config.volatility_weight,
                    'correlation': self.config.correlation_weight
                }
            
            breakdown.applied_weights = weights
            
            # 计算各维度评分
            breakdown.trend_score, breakdown.trend_details = self.calculate_trend_score(df, idx)
            breakdown.volume_score, breakdown.volume_details = self.calculate_volume_score(df, idx)
            breakdown.momentum_score, breakdown.momentum_details = self.calculate_momentum_score(df, idx)
            breakdown.volatility_score, breakdown.volatility_details = self.calculate_volatility_score(df, idx)
            
            if trigger_df is not None:
                breakdown.correlation_score, breakdown.correlation_details = self.calculate_correlation_score(
                    df, trigger_df, idx, trigger_change, coin_change
                )
            else:
                breakdown.correlation_score = 50.0
                breakdown.correlation_details = {'note': 'no trigger data'}
            
            # 加权汇总
            final_score = (
                breakdown.trend_score * weights['trend'] +
                breakdown.volume_score * weights['volume'] +
                breakdown.momentum_score * weights['momentum'] +
                breakdown.volatility_score * weights['volatility'] +
                breakdown.correlation_score * weights['correlation']
            )
            
            # 归一化到 0-100
            final_score = max(0.0, min(100.0, final_score))
            
            # 应用 Hot 板块评分加成
            # Property 16: Hot Sector Score Boost
            # *For any* trade signal in a HOT sector, the signal score SHALL receive a boost multiplier >= 1.0
            if sector_tier == SectorTier.HOT and self.hot_sector_boost > 1.0:
                boosted_score = final_score * self.hot_sector_boost
                # 加成后仍然限制在 0-100 范围内
                final_score = min(100.0, boosted_score)
                breakdown.trend_details['hot_sector_boost'] = self.hot_sector_boost
                breakdown.trend_details['pre_boost_score'] = final_score / self.hot_sector_boost
            
            breakdown.final_score = final_score
            
            return final_score, breakdown
            
        except Exception as e:
            breakdown.final_score = 50.0
            return 50.0, breakdown
    
    def calculate_trend_score(self, df: pd.DataFrame, idx: int) -> Tuple[float, Dict]:
        """
        计算趋势评分 (0-100)
        - MA多时间框架对齐 (MA5 > MA10 > MA20 > MA50)
        - ADX趋势强度
        - 价格相对MA位置
        """
        score = 0.0
        details = {}
        
        try:
            row = df.iloc[idx]
            close = row['close']
            
            # 获取或计算MA值
            ma5 = row.get('ma5', df['close'].rolling(5).mean().iloc[idx])
            ma10 = row.get('ma10', df['close'].rolling(10).mean().iloc[idx])
            ma20 = row.get('ma20', df['close'].rolling(20).mean().iloc[idx])
            
            # 计算MA50
            if 'ma50' in df.columns:
                ma50 = row['ma50']
            else:
                ma50 = df['close'].rolling(50).mean().iloc[idx] if idx >= 49 else ma20
            
            # 计算ADX
            if 'adx' in df.columns:
                adx = row['adx']
            else:
                adx_series = TechnicalIndicators.calculate_adx(df.iloc[:idx+1])
                adx = adx_series.iloc[-1] if len(adx_series) > 0 and pd.notna(adx_series.iloc[-1]) else 20
            
            details['ma5'] = ma5
            details['ma10'] = ma10
            details['ma20'] = ma20
            details['ma50'] = ma50
            details['adx'] = adx
            
            # 1. MA对齐评分 (最高40分)
            alignment_score = 0
            if pd.notna(ma5) and pd.notna(ma10) and ma5 > ma10:
                alignment_score += 10
            if pd.notna(ma10) and pd.notna(ma20) and ma10 > ma20:
                alignment_score += 10
            if pd.notna(ma20) and pd.notna(ma50) and ma20 > ma50:
                alignment_score += 10
            if pd.notna(ma5) and pd.notna(ma50) and ma5 > ma50:
                alignment_score += 10
            
            details['alignment_score'] = alignment_score
            score += alignment_score
            
            # 2. 价格位置评分 (最高30分)
            price_position_score = 0
            if pd.notna(ma5) and close > ma5:
                price_position_score += 10
            if pd.notna(ma20) and close > ma20:
                price_position_score += 10
            if pd.notna(ma50) and close > ma50:
                price_position_score += 10
            
            details['price_position_score'] = price_position_score
            score += price_position_score
            
            # 3. ADX强度评分 (最高30分)
            adx_score = 0
            if pd.notna(adx):
                if adx > 40:
                    adx_score = 30
                elif adx > self.config.adx_strong_threshold:
                    adx_score = 25
                elif adx > 20:
                    adx_score = 15
                else:
                    adx_score = 5
            
            details['adx_score'] = adx_score
            score += adx_score
            
        except Exception as e:
            details['error'] = str(e)
            score = 50.0
        
        return min(100.0, score), details
    
    def calculate_volume_score(self, df: pd.DataFrame, idx: int) -> Tuple[float, Dict]:
        """
        计算成交量评分 (0-100)
        - 成交量比率 (相对平均)
        - 连续放量检测
        - 量价背离检测
        - 异常放量检测
        """
        score = 50.0  # 基础分
        details = {}
        
        try:
            row = df.iloc[idx]
            volume = row['volume']
            close = row['close']
            
            # 计算成交量均值
            if 'vol_ma20' in df.columns:
                vol_ma20 = row['vol_ma20']
            else:
                vol_ma20 = df['volume'].rolling(20).mean().iloc[idx]
            
            vol_ratio = volume / vol_ma20 if vol_ma20 > 0 else 1.0
            details['vol_ratio'] = vol_ratio
            details['vol_ma20'] = vol_ma20
            
            # 1. 成交量比率评分 (最高30分)
            if vol_ratio > self.config.volume_high_ratio:
                score += 30
                details['high_volume'] = True
            elif vol_ratio > 1.5:
                score += 20
            elif vol_ratio > 1.0:
                score += 10
            elif vol_ratio < 0.5:
                score -= 15
            
            # 2. 连续放量检测 (最高15分)
            if idx >= 2:
                vol_increasing = True
                for i in range(1, 3):
                    if df.iloc[idx-i]['volume'] >= df.iloc[idx-i+1]['volume']:
                        vol_increasing = False
                        break
                if vol_increasing and volume > df.iloc[idx-1]['volume']:
                    score += 15
                    details['consecutive_increase'] = True
            
            # 3. 量价背离检测 (扣分)
            if idx >= 1:
                prev_close = df.iloc[idx-1]['close']
                prev_volume = df.iloc[idx-1]['volume']
                price_up = close > prev_close
                volume_down = volume < prev_volume
                
                if price_up and volume_down:
                    score -= 20
                    details['bearish_divergence'] = True
            
            # 4. 异常放量检测
            if vol_ratio > self.config.volume_abnormal_ratio:
                price_change = abs((close - df.iloc[idx-1]['close']) / df.iloc[idx-1]['close'] * 100) if idx > 0 else 0
                if price_change < 1.0:  # 异常放量但价格变化小
                    score -= 15
                    details['abnormal_volume_no_move'] = True
                else:
                    details['abnormal_volume'] = True
            
        except Exception as e:
            details['error'] = str(e)
            score = 50.0
        
        return max(0.0, min(100.0, score)), details
    
    def calculate_momentum_score(self, df: pd.DataFrame, idx: int) -> Tuple[float, Dict]:
        """
        计算动量评分 (0-100)
        - MACD柱状图方向和金叉
        - ROC动量
        - RSI位置
        """
        score = 50.0
        details = {}
        
        try:
            row = df.iloc[idx]
            
            # 计算MACD
            if idx >= 26:
                macd_line, signal_line, histogram = TechnicalIndicators.calculate_macd(df.iloc[:idx+1])
                macd = macd_line.iloc[-1] if len(macd_line) > 0 else 0
                signal = signal_line.iloc[-1] if len(signal_line) > 0 else 0
                hist = histogram.iloc[-1] if len(histogram) > 0 else 0
                prev_hist = histogram.iloc[-2] if len(histogram) > 1 else 0
            else:
                macd, signal, hist, prev_hist = 0, 0, 0, 0
            
            details['macd'] = macd
            details['signal'] = signal
            details['histogram'] = hist
            
            # 1. MACD柱状图评分 (最高25分)
            if hist > 0:
                score += 15
                if hist > prev_hist:  # 柱状图增加
                    score += 10
                    details['histogram_increasing'] = True
            elif hist < 0:
                score -= 10
            
            # 2. MACD金叉检测 (最高15分)
            if macd > signal and idx > 0:
                prev_macd = macd_line.iloc[-2] if len(macd_line) > 1 else 0
                prev_signal = signal_line.iloc[-2] if len(signal_line) > 1 else 0
                if prev_macd <= prev_signal:
                    score += 15
                    details['macd_crossover'] = True
            
            # 3. ROC评分 (最高20分)
            if idx >= 10:
                roc = TechnicalIndicators.calculate_roc(df.iloc[:idx+1], 10).iloc[-1]
                details['roc'] = roc
                if pd.notna(roc):
                    if roc > 5:
                        score += 20
                    elif roc > 2:
                        score += 15
                    elif roc > 0:
                        score += 10
                    elif roc < -5:
                        score -= 15
            
            # 4. RSI评分 (最高15分)
            rsi = row.get('rsi', 50)
            details['rsi'] = rsi
            if pd.notna(rsi):
                if 40 <= rsi <= 60:  # 中性区域，早期动量
                    score += 10
                    details['early_momentum'] = True
                elif 30 <= rsi < 40:  # 超卖反弹
                    score += 15
                elif 60 < rsi <= 70:
                    score += 5
                elif rsi > 70:  # 超买
                    score -= 10
                elif rsi < 30:  # 深度超卖
                    score += 5
            
        except Exception as e:
            details['error'] = str(e)
            score = 50.0
        
        return max(0.0, min(100.0, score)), details
    
    def calculate_volatility_score(self, df: pd.DataFrame, idx: int) -> Tuple[float, Dict]:
        """
        计算波动率评分 (0-100)
        - ATR相对价格比率
        - 波动率扩张/收缩
        - 布林带宽度
        """
        score = 50.0
        details = {}
        
        try:
            row = df.iloc[idx]
            close = row['close']
            atr = row.get('atr', 0)
            
            # ATR相对价格比率
            atr_pct = (atr / close * 100) if close > 0 else 0
            details['atr'] = atr
            details['atr_pct'] = atr_pct
            
            # 1. ATR比率评分 (最高30分)
            if atr_pct > self.config.volatility_high_threshold:
                score -= 15  # 波动太高，风险大
                details['high_volatility'] = True
            elif atr_pct < self.config.volatility_low_threshold:
                score -= 10  # 波动太低，机会少
                details['low_volatility'] = True
            elif 2.0 <= atr_pct <= 4.0:
                score += 20  # 适中波动
                details['optimal_volatility'] = True
            else:
                score += 10
            
            # 2. 波动率扩张检测 (最高20分)
            if idx >= 5:
                prev_atr = df.iloc[idx-5].get('atr', atr)
                if atr > prev_atr * 1.2:
                    score += 20
                    details['volatility_expansion'] = True
                elif atr < prev_atr * 0.8:
                    details['volatility_contraction'] = True
            
            # 3. 布林带宽度评分 (最高20分)
            if idx >= 20:
                upper, middle, lower, band_width = TechnicalIndicators.calculate_bollinger_bands(df.iloc[:idx+1])
                bw = band_width.iloc[-1] if len(band_width) > 0 else 0
                details['band_width'] = bw
                
                if pd.notna(bw):
                    # 检测布林带收缩 (潜在突破)
                    if idx >= 25:
                        prev_bw = band_width.iloc[-5] if len(band_width) > 5 else bw
                        if bw < prev_bw * 0.8:
                            score += 15
                            details['bb_squeeze'] = True
                    
                    # 价格位置
                    if close > middle.iloc[-1]:
                        score += 5
            
        except Exception as e:
            details['error'] = str(e)
            score = 50.0
        
        return max(0.0, min(100.0, score)), details
    
    def calculate_correlation_score(
        self,
        df: pd.DataFrame,
        trigger_df: pd.DataFrame,
        idx: int,
        trigger_change: float = 0.0,
        coin_change: float = 0.0
    ) -> Tuple[float, Dict]:
        """
        计算相关性评分 (0-100)
        - 滚动相关系数
        - 跟涨差距
        - 历史跟随准确率
        """
        score = 50.0
        details = {}
        
        try:
            # 1. 滚动相关系数 (最高30分)
            lookback = min(self.config.correlation_lookback, idx, len(trigger_df)-1)
            if lookback >= 10:
                coin_returns = df['close'].pct_change().iloc[idx-lookback:idx+1]
                trigger_returns = trigger_df['close'].pct_change().iloc[idx-lookback:idx+1]
                
                if len(coin_returns) == len(trigger_returns) and len(coin_returns) > 5:
                    correlation = coin_returns.corr(trigger_returns)
                    details['correlation'] = correlation
                    
                    if pd.notna(correlation):
                        if correlation > self.config.correlation_high_threshold:
                            score += 30
                            details['high_correlation'] = True
                        elif correlation > 0.5:
                            score += 20
                        elif correlation > 0.3:
                            score += 10
                        elif correlation < 0:
                            score -= 20
                            details['negative_correlation'] = True
            
            # 2. 跟涨差距评分 (最高25分)
            if trigger_change > 0:
                gap = trigger_change - coin_change
                gap_ratio = gap / trigger_change if trigger_change != 0 else 0
                details['gap_ratio'] = gap_ratio
                
                if gap_ratio > 0.5:  # 跟涨不足50%，补涨空间大
                    score += 25
                    details['large_gap'] = True
                elif gap_ratio > 0.3:
                    score += 15
                elif gap_ratio > 0.1:
                    score += 10
                elif gap_ratio < 0:  # 已经涨过头
                    score -= 10
            
            # 3. 滞后相关性 (最高15分)
            if lookback >= 15:
                # 检查1-3周期滞后的相关性
                for lag in [1, 2, 3]:
                    if idx > lag and len(trigger_df) > idx:
                        lagged_trigger = trigger_df['close'].pct_change().iloc[idx-lookback-lag:idx-lag+1]
                        if len(lagged_trigger) == len(coin_returns):
                            lag_corr = coin_returns.corr(lagged_trigger)
                            if pd.notna(lag_corr) and lag_corr > 0.6:
                                score += 5
                                details[f'lag_{lag}_correlation'] = lag_corr
                                break
            
        except Exception as e:
            details['error'] = str(e)
            score = 50.0
        
        return max(0.0, min(100.0, score)), details
    
    def detect_market_regime(self, btc_df: pd.DataFrame, idx: int) -> str:
        """
        检测市场状态
        基于BTC趋势判断整体市场方向
        返回: 'uptrend', 'downtrend', 'ranging'
        """
        try:
            if idx < 20:
                return MarketRegime.RANGING.value
            
            row = btc_df.iloc[idx]
            close = row['close']
            
            # 获取MA值
            ma20 = btc_df['close'].rolling(20).mean().iloc[idx]
            ma50 = btc_df['close'].rolling(50).mean().iloc[idx] if idx >= 49 else ma20
            
            # 计算ADX
            adx_series = TechnicalIndicators.calculate_adx(btc_df.iloc[:idx+1])
            adx = adx_series.iloc[-1] if len(adx_series) > 0 and pd.notna(adx_series.iloc[-1]) else 20
            
            # 判断趋势
            if adx < 20:
                return MarketRegime.RANGING.value
            
            if close > ma20 and ma20 > ma50:
                return MarketRegime.UPTREND.value
            elif close < ma20 and ma20 < ma50:
                return MarketRegime.DOWNTREND.value
            else:
                return MarketRegime.RANGING.value
                
        except Exception:
            return MarketRegime.RANGING.value
    
    def adjust_weights_for_regime(self, regime: str) -> Dict[str, float]:
        """
        根据市场状态调整权重
        - 上涨趋势: 增加动量权重
        - 下跌趋势: 增加波动率权重
        - 震荡市: 均衡权重
        """
        base_weights = {
            'trend': self.config.trend_weight,
            'volume': self.config.volume_weight,
            'momentum': self.config.momentum_weight,
            'volatility': self.config.volatility_weight,
            'correlation': self.config.correlation_weight
        }
        
        if regime == MarketRegime.UPTREND.value:
            # 上涨趋势：增加动量和趋势权重
            base_weights['momentum'] *= 1.3
            base_weights['trend'] *= 1.2
            base_weights['volatility'] *= 0.7
        elif regime == MarketRegime.DOWNTREND.value:
            # 下跌趋势：增加波动率权重，降低动量
            base_weights['volatility'] *= 1.3
            base_weights['momentum'] *= 0.7
            base_weights['correlation'] *= 1.2
        # 震荡市保持原权重
        
        # 归一化
        total = sum(base_weights.values())
        if total > 0:
            for key in base_weights:
                base_weights[key] /= total
        
        return base_weights


class HistoricalDataFetcherV2:
    """历史数据获取器 V2 - 增加技术指标计算"""
    
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0',
            'Accept': 'application/json'
        })
        self.cache = {}
        
    def _get_interval_ms(self, interval: str) -> int:
        """获取K线间隔的毫秒数"""
        interval_map = {
            '1m': 60 * 1000,
            '3m': 3 * 60 * 1000,
            '5m': 5 * 60 * 1000,
            '15m': 15 * 60 * 1000,
            '30m': 30 * 60 * 1000,
            '1h': 60 * 60 * 1000,
            '2h': 2 * 60 * 60 * 1000,
            '4h': 4 * 60 * 60 * 1000,
            '6h': 6 * 60 * 60 * 1000,
            '8h': 8 * 60 * 60 * 1000,
            '12h': 12 * 60 * 60 * 1000,
            '1d': 24 * 60 * 60 * 1000,
            '3d': 3 * 24 * 60 * 60 * 1000,
            '1w': 7 * 24 * 60 * 60 * 1000,
        }
        return interval_map.get(interval, 15 * 60 * 1000)

    def get_historical_klines(
        self, 
        symbol: str, 
        interval: str = '15m',
        start_time: datetime = None,
        end_time: datetime = None,
        limit: int = 1000
    ) -> pd.DataFrame:
        """获取历史K线数据并计算技术指标 - 支持分批获取长时间数据"""
        
        cache_key = f"{symbol}_{interval}_{start_time}_{end_time}"
        if cache_key in self.cache:
            return self.cache[cache_key]
        
        try:
            url = f"{BINANCE_FUTURES_API_URL}/klines"
            all_data = []
            
            # 计算需要获取的时间范围
            if start_time and end_time:
                interval_ms = self._get_interval_ms(interval)
                current_start = int(start_time.timestamp() * 1000)
                end_ms = int(end_time.timestamp() * 1000)
                
                print(f"📊 获取 {symbol} 历史数据 ({interval})...")
                
                # 分批获取数据
                batch_count = 0
                while current_start < end_ms:
                    params = {
                        'symbol': symbol.upper().replace('_', ''),
                        'interval': interval,
                        'startTime': current_start,
                        'endTime': end_ms,
                        'limit': 1000
                    }
                    
                    response = self.session.get(url, params=params, timeout=30)
                    response.raise_for_status()
                    data = response.json()
                    
                    if not data:
                        break
                    
                    all_data.extend(data)
                    batch_count += 1
                    
                    # 更新下一批的起始时间
                    last_close_time = data[-1][6]  # close_time
                    current_start = last_close_time + 1
                    
                    # 如果返回数据少于1000条，说明已经获取完毕
                    if len(data) < 1000:
                        break
                    
                    time.sleep(0.1)  # 避免请求过快
                
                if batch_count > 1:
                    print(f"   分 {batch_count} 批获取完成")
            else:
                # 没有指定时间范围，使用原来的逻辑
                params = {
                    'symbol': symbol.upper().replace('_', ''),
                    'interval': interval,
                    'limit': limit
                }
                
                if start_time:
                    params['startTime'] = int(start_time.timestamp() * 1000)
                if end_time:
                    params['endTime'] = int(end_time.timestamp() * 1000)
                
                print(f"📊 获取 {symbol} 历史数据 ({interval})...")
                
                response = self.session.get(url, params=params, timeout=30)
                response.raise_for_status()
                all_data = response.json()
            
            if not all_data:
                return pd.DataFrame()
            
            df = pd.DataFrame(all_data, columns=[
                'open_time', 'open', 'high', 'low', 'close', 'volume',
                'close_time', 'quote_volume', 'trades', 'taker_buy_base',
                'taker_buy_quote', 'ignore'
            ])
            
            # 去重（分批获取可能有重复）
            df = df.drop_duplicates(subset=['open_time'])
            
            df['timestamp'] = pd.to_datetime(df['open_time'], unit='ms')
            df.set_index('timestamp', inplace=True)
            df = df.sort_index()
            
            for col in ['open', 'high', 'low', 'close', 'volume', 'quote_volume']:
                df[col] = pd.to_numeric(df[col], errors='coerce')
            
            # 计算技术指标
            df = self._calculate_indicators(df)
            
            self.cache[cache_key] = df
            print(f"✅ 获取 {len(df)} 条历史数据")
            
            time.sleep(0.2)
            return df
            
        except Exception as e:
            print(f"❌ 获取历史数据失败: {e}")
            return pd.DataFrame()
    
    def _calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """计算技术指标"""
        # 价格变化
        df['price_change'] = df['close'].pct_change() * 100
        
        # 移动平均线
        df['ma5'] = df['close'].rolling(window=5).mean()
        df['ma10'] = df['close'].rolling(window=10).mean()
        df['ma20'] = df['close'].rolling(window=20).mean()
        df['ma50'] = df['close'].rolling(window=50).mean()  # 新增MA50
        
        # 成交量移动平均
        df['vol_ma5'] = df['volume'].rolling(window=5).mean()
        df['vol_ma10'] = df['volume'].rolling(window=10).mean()
        df['vol_ma20'] = df['volume'].rolling(window=20).mean()  # 新增vol_ma20
        
        # 成交量比率 (当前成交量 / 平均成交量)
        df['vol_ratio'] = df['volume'] / df['vol_ma5']
        
        # RSI
        df['rsi'] = self._calculate_rsi(df['close'], 14)
        
        # 波动率 (ATR)
        df['atr'] = self._calculate_atr(df, 14)
        
        # 趋势方向 (MA5 > MA20 为上涨趋势)
        df['trend'] = np.where(df['ma5'] > df['ma20'], 1, -1)
        
        # 动量
        df['momentum'] = df['close'] - df['close'].shift(5)
        
        # 新增: ADX (趋势强度)
        df['adx'] = TechnicalIndicators.calculate_adx(df, 14)
        
        # 新增: MACD
        macd_line, signal_line, histogram = TechnicalIndicators.calculate_macd(df)
        df['macd'] = macd_line
        df['macd_signal'] = signal_line
        df['macd_hist'] = histogram
        
        # 新增: 布林带
        upper, middle, lower, band_width = TechnicalIndicators.calculate_bollinger_bands(df)
        df['bb_upper'] = upper
        df['bb_middle'] = middle
        df['bb_lower'] = lower
        df['bb_width'] = band_width
        
        # 新增: ROC (变化率)
        df['roc'] = TechnicalIndicators.calculate_roc(df, 10)
        
        return df
    
    def _calculate_rsi(self, prices: pd.Series, period: int = 14) -> pd.Series:
        """计算RSI"""
        delta = prices.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss
        return 100 - (100 / (1 + rs))
    
    def _calculate_atr(self, df: pd.DataFrame, period: int = 14) -> pd.Series:
        """计算ATR"""
        high_low = df['high'] - df['low']
        high_close = np.abs(df['high'] - df['close'].shift())
        low_close = np.abs(df['low'] - df['close'].shift())
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        return tr.rolling(window=period).mean()
    
    def get_category_historical_data_by_date(
        self,
        category: str,
        interval: str = '15m',
        start_time: datetime = None,
        end_time: datetime = None
    ) -> Dict[str, pd.DataFrame]:
        """获取分类下所有币种的历史数据"""
        symbols = CRYPTO_CATEGORIES.get(category, {}).get(EXCHANGE, [])
        result = {}
        
        if end_time is None:
            end_time = datetime.now()
        if start_time is None:
            start_time = end_time - timedelta(days=7)
        
        for symbol in symbols:
            df = self.get_historical_klines(symbol, interval, start_time, end_time)
            if not df.empty:
                result[symbol] = df
        
        return result


class BacktestEngineV2:
    """回测引擎 V2 - 永续合约版"""
    
    def __init__(
        self,
        initial_balance: float = 10000,
        base_trade_amount: float = 500,  # 基础保证金
        max_trade_amount: float = 1500,  # 最大保证金
        take_profit: float = 8,  # 止盈百分比 (单次止盈模式)
        stop_loss: float = 4,  # 止损百分比
        trailing_stop_pct: float = 3,  # 移动止损回撤百分比
        trailing_stop_activation: float = 5,  # 移动止损激活阈值
        max_positions: int = 5,  # 最大持仓数
        cooldown_periods: int = 3,  # 信号冷却期(K线数)
        leverage: int = 5,  # 杠杆倍数
        futures_mode: bool = True,  # 永续合约模式
        liquidation_buffer: float = 2.0,  # 强平缓冲
        category_thresholds: Dict[str, float] = None,
        # 分批止盈参数
        partial_tp_enabled: bool = False,  # 是否启用分批止盈
        partial_tp_levels: List[float] = None,  # 分批止盈级别 [10, 20, 30]
        partial_tp_ratios: List[float] = None,  # 每级止盈比例 [0.33, 0.33, 0.34]
        # 止损优化参数
        stop_loss_config: StopLossConfig = None,  # 止损配置
        # 信号评分参数
        signal_score_config: SignalScoreConfig = None,  # 信号评分配置
        # 板块轮动参数
        rotation_config: RotationConfig = None,  # 板块轮动配置
        # 黑名单配置参数 (V5 新增)
        blacklist_consecutive_losses: int = None,  # 连续亏损多少次加入黑名单
        blacklist_duration_hours: float = None,  # 黑名单持续时间 (小时)
        blacklist_early_release_enabled: bool = None,  # 是否启用提前解除黑名单
        blacklist_early_release_wins: int = None  # 连续盈利多少次可提前解除
    ):
        self.initial_balance = initial_balance
        self.balance = initial_balance
        self.base_trade_amount = base_trade_amount
        self.max_trade_amount = max_trade_amount
        self.take_profit = take_profit
        self.stop_loss = stop_loss
        self.trailing_stop_pct = trailing_stop_pct
        self.trailing_stop_activation = trailing_stop_activation
        self.max_positions = max_positions
        self.cooldown_periods = cooldown_periods
        
        # 永续合约参数
        self.leverage = leverage
        self.futures_mode = futures_mode
        self.liquidation_buffer = liquidation_buffer
        self.liquidations = 0  # 强平次数
        
        # 分批止盈参数
        self.partial_tp_enabled = partial_tp_enabled
        self.partial_tp_levels = partial_tp_levels or [10, 20, 30]  # 默认10%, 20%, 30%
        self.partial_tp_ratios = partial_tp_ratios or [0.33, 0.33, 0.34]  # 每级止盈1/3
        
        self.category_thresholds = category_thresholds or CATEGORY_THRESHOLDS
        self.threshold_default = THRESHOLD_DEFAULT
        
        self.trades: List[BacktestTradeV2] = []
        self.active_trades: Dict[str, BacktestTradeV2] = {}
        self.equity_curve: List[Tuple[datetime, float]] = []
        self.max_balance = initial_balance
        self.max_drawdown = 0
        
        # 冷却期追踪
        self.last_signal_time: Dict[str, datetime] = {}
        
        self.data_fetcher = HistoricalDataFetcherV2()
        
        # 止损管理器
        self.stop_loss_config = stop_loss_config or StopLossConfig()
        self.stop_loss_manager = StopLossManager(self.stop_loss_config)
        
        # 信号评分器
        self.signal_score_config = signal_score_config or SignalScoreConfig()
        self.signal_scorer = SignalScorer(self.signal_score_config)
        
        # 板块轮动管理器
        self.rotation_config = rotation_config or RotationConfig.from_dict(ROTATION_CONFIG)
        self.rotation_manager = RotationManager(self.rotation_config) if self.rotation_config.enabled else None
        
        # 板块权重缓存
        self.sector_weights: Dict[str, float] = {}
        # 板块分类缓存 (用于 Hot 板块评分加成)
        self.sector_classifications: Dict[str, any] = {}
        
        # BTC数据缓存 (用于市场状态检测)
        self.btc_data_cache: pd.DataFrame = None
        
        # 策略优化器组件
        self.regime_detector = MarketRegimeDetector()
        self.dynamic_stop_loss_controller = StopLossController()
        self.sector_weight_manager = SectorWeightManager(
            blacklist_consecutive_losses=blacklist_consecutive_losses,
            blacklist_duration_hours=blacklist_duration_hours,
            early_release_enabled=blacklist_early_release_enabled,
            early_release_consecutive_wins=blacklist_early_release_wins
        )
        self.signal_calibrator = SignalCalibrator()
        self.strategy_optimizer = StrategyOptimizer(
            self.regime_detector,
            self.dynamic_stop_loss_controller,
            self.sector_weight_manager,
            self.signal_calibrator
        )
        # 当前市场状态缓存
        self._current_market_regime: MarketRegimeType = MarketRegimeType.SIDEWAYS
        # 策略优化启用标志
        self.strategy_optimization_enabled: bool = True
        # 交易对黑名单 (静态配置)
        self.symbol_blacklist: set = set()
        # 分类权重调整 (静态配置)
        self.category_weight_adjustments: Dict[str, float] = {}
        
        # Q3/Q4 优化器
        self.q3q4_optimizer: Optional['Q3Q4Optimizer'] = None
        self.q3q4_optimization_enabled: bool = False
        
        # V6: 分类止损配置
        self.category_stop_loss: Dict[str, float] = CATEGORY_STOP_LOSS.copy()
        
        # V6: 单日最大亏损限制
        self.daily_loss_limit_enabled: bool = DAILY_LOSS_LIMIT_CONFIG.get('enabled', False)
        self.daily_loss_limit_pct: float = DAILY_LOSS_LIMIT_CONFIG.get('max_daily_loss_pct', 10.0)
        self.daily_loss_limit_cooldown_hours: float = DAILY_LOSS_LIMIT_CONFIG.get('cooldown_hours', 24.0)
        self.daily_loss_triggered: bool = False
        self.daily_loss_trigger_time: Optional[datetime] = None
        self.daily_pnl: float = 0.0  # 当日盈亏
        self.daily_pnl_reset_date: Optional[datetime] = None  # 上次重置日期
        
        # V7: 分类亏损过滤器
        self.category_loss_filter: Optional[CategoryLossFilter] = None
        self.category_filter_enabled: bool = False
        
        # V7: 定期重置机制 (模拟独立季度模式优势)
        from config import PERIODIC_RESET_ENABLED, PERIODIC_RESET_INTERVAL_DAYS
        self.periodic_reset_enabled: bool = PERIODIC_RESET_ENABLED
        self.reset_interval_days: int = PERIODIC_RESET_INTERVAL_DAYS
        self.last_reset_time: Optional[datetime] = None  # 上次重置时间
        self.period_pnl: float = 0.0  # 当前周期盈亏
        self.period_trades: int = 0  # 当前周期交易数
        self.period_history: List[Dict] = []  # 历史周期记录
    
    def calculate_liquidation_price(self, entry_price: float, leverage: int, is_long: bool = True) -> float:
        """
        计算强平价格 (简化版，假设维持保证金率为0.5%)
        做多: 强平价 = 入场价 * (1 - 1/杠杆 + 维持保证金率)
        做空: 强平价 = 入场价 * (1 + 1/杠杆 - 维持保证金率)
        """
        maintenance_margin_rate = 0.005  # 0.5% 维持保证金率
        
        if is_long:
            # 做多强平价格
            liquidation_price = entry_price * (1 - 1/leverage + maintenance_margin_rate)
        else:
            # 做空强平价格
            liquidation_price = entry_price * (1 + 1/leverage - maintenance_margin_rate)
        
        return liquidation_price
    
    def get_category_threshold(self, category: str) -> float:
        """获取分类的阈值"""
        return self.category_thresholds.get(category, self.threshold_default)
    
    def enable_q3q4_optimization(
        self,
        base_threshold: float = 75.0,
        base_stop_loss: float = 10.0
    ) -> None:
        """
        启用Q3/Q4优化
        
        Args:
            base_threshold: 基础信号阈值
            base_stop_loss: 基础止损百分比
        """
        if Q3Q4_OPTIMIZER_AVAILABLE:
            self.q3q4_optimizer = Q3Q4Optimizer(
                base_threshold=base_threshold,
                base_stop_loss=base_stop_loss,
                enabled=True
            )
            self.q3q4_optimization_enabled = True
            print("✅ Q3/Q4优化已启用")
        else:
            print("⚠️ Q3/Q4优化组件不可用")
    
    def disable_q3q4_optimization(self) -> None:
        """禁用Q3/Q4优化"""
        self.q3q4_optimization_enabled = False
        if self.q3q4_optimizer:
            self.q3q4_optimizer.enabled = False
        print("❌ Q3/Q4优化已禁用")
    
    def enable_category_loss_filter(
        self,
        config: CategoryLossFilterConfig = None,
        cumulative_pnl_threshold: float = -2000.0,
        win_rate_threshold: float = 40.0,
        consecutive_loss_threshold: int = 5,
        min_trades_for_filter: int = 10,
        weight_reduction_pct: float = 50.0,
        suspension_hours: float = 24.0
    ) -> None:
        """
        启用分类亏损过滤器
        
        Args:
            config: 过滤器配置对象，如果提供则忽略其他参数
            cumulative_pnl_threshold: 累计亏损阈值 (USDT)
            win_rate_threshold: 胜率阈值 (百分比)
            consecutive_loss_threshold: 连续亏损阈值
            min_trades_for_filter: 最小交易数
            weight_reduction_pct: 权重降低比例 (百分比)
            suspension_hours: 暂停时长 (小时)
        """
        if config is None:
            config = CategoryLossFilterConfig(
                cumulative_pnl_threshold=cumulative_pnl_threshold,
                win_rate_threshold=win_rate_threshold,
                consecutive_loss_threshold=consecutive_loss_threshold,
                min_trades_for_filter=min_trades_for_filter,
                weight_reduction_pct=weight_reduction_pct,
                suspension_hours=suspension_hours
            )
        
        self.category_loss_filter = CategoryLossFilter(config)
        self.category_filter_enabled = True
        print(f"✅ 分类亏损过滤器已启用: 累计亏损阈值={config.cumulative_pnl_threshold}, "
              f"胜率阈值={config.win_rate_threshold}%, 连续亏损阈值={config.consecutive_loss_threshold}")
    
    def disable_category_loss_filter(self) -> None:
        """禁用分类亏损过滤器"""
        self.category_filter_enabled = False
        print("❌ 分类亏损过滤器已禁用")
    
    # ========== V7: 定期重置机制 (模拟独立季度模式优势) ==========
    
    def check_periodic_reset(self, current_time: datetime) -> bool:
        """
        检查是否需要定期重置 - V7新增
        模拟独立季度模式的优势：定期清空动态黑名单和亏损计数
        
        Args:
            current_time: 当前回测时间点
            
        Returns:
            bool: 是否执行了重置
        """
        if not self.periodic_reset_enabled:
            return False
        
        # 初始化上次重置时间
        if self.last_reset_time is None:
            self.last_reset_time = current_time
            return False
        
        days_since_reset = (current_time - self.last_reset_time).days
        
        if days_since_reset >= self.reset_interval_days:
            self._perform_periodic_reset(current_time)
            return True
        
        return False
    
    def _perform_periodic_reset(self, current_time: datetime):
        """
        执行定期重置 - V7新增
        重置动态黑名单和亏损计数，但保留资金和持仓
        
        Args:
            current_time: 当前回测时间点
        """
        # 记录当前周期统计
        blacklist_count = len(self.sector_weight_manager._blacklist) if self.sector_weight_manager else 0
        period_record = {
            'start_time': self.last_reset_time,
            'end_time': current_time,
            'pnl': self.period_pnl,
            'trades': self.period_trades,
            'final_balance': self.balance,
            'dynamic_blacklist_count': blacklist_count
        }
        self.period_history.append(period_record)
        
        print(f"\n{'='*60}")
        print(f"🔄 定期重置 - 周期结束 (V7)")
        print(f"{'='*60}")
        print(f"   周期: {self.last_reset_time.strftime('%Y-%m-%d')} ~ {current_time.strftime('%Y-%m-%d')}")
        print(f"   周期盈亏: {self.period_pnl:+,.2f} USDT")
        print(f"   周期交易: {self.period_trades} 次")
        print(f"   当前余额: {self.balance:,.2f} USDT")
        
        # 重置动态黑名单 (核心优化点!)
        if self.sector_weight_manager:
            # 使用 clear_all() 方法清空所有状态
            self.sector_weight_manager.clear_all()
            print(f"   清空动态黑名单: {blacklist_count} 个分类")
        
        # 重置周期统计
        self.last_reset_time = current_time
        self.period_pnl = 0.0
        self.period_trades = 0
        
        print(f"✅ 重置完成，开始新周期")
        print(f"{'='*60}\n")
    
    def set_periodic_reset(self, enabled: bool = True, interval_days: int = None):
        """
        设置定期重置参数 - V7新增
        
        Args:
            enabled: 是否启用定期重置
            interval_days: 重置间隔天数 (建议: 7=每周, 30=每月, 90=每季度)
        """
        self.periodic_reset_enabled = enabled
        if interval_days is not None:
            self.reset_interval_days = interval_days
        
        status = "启用" if enabled else "禁用"
        print(f"🔄 定期重置已{status} (间隔: {self.reset_interval_days}天)")
    
    def get_period_summary(self) -> Dict:
        """
        获取周期摘要 - V7新增
        
        Returns:
            周期统计信息字典
        """
        return {
            'periodic_reset_enabled': self.periodic_reset_enabled,
            'reset_interval_days': self.reset_interval_days,
            'last_reset_time': self.last_reset_time,
            'period_pnl': self.period_pnl,
            'period_trades': self.period_trades,
            'total_periods': len(self.period_history),
            'period_history': self.period_history
        }
    
    # ========== 结束 V7 定期重置机制 ==========

    def calculate_price_change(self, df: pd.DataFrame, idx: int, periods: int = 1) -> float:
        """计算价格变化百分比"""
        if idx < periods:
            return 0.0
        
        current_price = df.iloc[idx]['close']
        prev_price = df.iloc[idx - periods]['close']
        
        if prev_price == 0:
            return 0.0
        
        return ((current_price - prev_price) / prev_price) * 100
    
    def calculate_signal_score(
        self,
        df: pd.DataFrame,
        idx: int,
        trigger_change: float,
        coin_change: float,
        trigger_df: pd.DataFrame = None,
        category: str = None
    ) -> Tuple[float, ScoreBreakdown]:
        """
        计算信号强度评分 (0-100)
        使用新的 SignalScorer 进行多维度评估，支持 Hot 板块加成
        
        Args:
            df: 币种K线数据
            idx: 当前K线索引
            trigger_change: 触发币种涨幅
            coin_change: 当前币种涨幅
            trigger_df: 触发币种K线数据
            category: 板块名称 (用于获取板块层级)
            
        Returns:
            (score, breakdown): 评分和评分明细
        """
        try:
            # 获取板块层级 (用于 Hot 板块加成)
            sector_tier = None
            if category and self.rotation_manager and hasattr(self, 'sector_classifications'):
                classification = self.sector_classifications.get(category)
                if classification:
                    sector_tier = classification.tier
            
            # 使用新的信号评分器
            score, breakdown = self.signal_scorer.calculate_score(
                df=df,
                idx=idx,
                trigger_df=trigger_df,
                trigger_change=trigger_change,
                coin_change=coin_change,
                btc_df=self.btc_data_cache,
                sector_tier=sector_tier
            )
            return score, breakdown
        except Exception as e:
            # 回退到简单评分
            return 50.0, ScoreBreakdown(final_score=50.0)
    
    def check_trend_filter(self, df: pd.DataFrame, idx: int) -> bool:
        """趋势过滤 - 只在上涨趋势中交易"""
        if idx < 20:
            return True  # 数据不足，不过滤
        
        try:
            row = df.iloc[idx]
            
            # 条件1: MA5 > MA10 (短期趋势向上)
            if pd.notna(row.get('ma5')) and pd.notna(row.get('ma10')):
                if row['ma5'] < row['ma10']:
                    return False
            
            # 条件2: 价格在MA20上方 (中期趋势向上)
            if pd.notna(row.get('ma20')):
                if row['close'] < row['ma20'] * 0.98:  # 允许2%的容差
                    return False
            
            return True
            
        except:
            return True
    
    def check_volume_confirmation(self, df: pd.DataFrame, idx: int) -> bool:
        """成交量确认 - 放量突破更可靠"""
        try:
            row = df.iloc[idx]
            vol_ratio = row.get('vol_ratio', 1)
            
            # 成交量至少是平均的80%
            if pd.notna(vol_ratio) and vol_ratio < 0.8:
                return False
            
            return True
        except:
            return True
    
    def is_in_cooldown(self, category: str, current_time: datetime, interval_minutes: int = 15) -> bool:
        """检查是否在冷却期"""
        if category not in self.last_signal_time:
            return False
        
        last_time = self.last_signal_time[category]
        cooldown_duration = timedelta(minutes=interval_minutes * self.cooldown_periods)
        
        return current_time < last_time + cooldown_duration
    
    def calculate_position_size(self, signal_score: float, category: str = None) -> float:
        """
        根据信号强度和板块权重计算仓位大小
        
        Args:
            signal_score: 信号评分 (0-100)
            category: 板块名称 (用于应用板块权重)
            
        Returns:
            float: 保证金金额
        """
        # 基础仓位计算: 信号评分 0-100 映射到 base_amount - max_amount
        if signal_score >= 80:
            base_margin = self.max_trade_amount
        elif signal_score >= 60:
            base_margin = self.base_trade_amount + (self.max_trade_amount - self.base_trade_amount) * 0.6
        elif signal_score >= 40:
            base_margin = self.base_trade_amount + (self.max_trade_amount - self.base_trade_amount) * 0.3
        else:
            base_margin = self.base_trade_amount
        
        # 应用板块权重
        if category and self.rotation_manager and self.sector_weights:
            sector_weight = self.sector_weights.get(category, 1.0 / len(self.sector_weights) if self.sector_weights else 1.0)
            n_sectors = len(self.sector_weights) if self.sector_weights else 1
            base_weight = 1.0 / n_sectors
            
            # 计算权重倍数 (相对于等权分配)
            weight_multiplier = sector_weight / base_weight if base_weight > 0 else 1.0
            
            # 应用权重倍数，但限制在合理范围内
            weight_multiplier = max(0.5, min(2.0, weight_multiplier))
            base_margin *= weight_multiplier
        
        # 确保不超过最大保证金
        return min(base_margin, self.max_trade_amount)
    
    def update_sector_weights(
        self,
        all_category_data: Dict[str, Dict[str, pd.DataFrame]],
        current_time: datetime
    ) -> None:
        """
        更新板块权重
        
        Args:
            all_category_data: 所有分类的历史数据
            current_time: 当前时间
        """
        if not self.rotation_manager:
            return
        
        # 构建板块数据
        sector_data: Dict[str, SectorData] = {}
        
        for category, category_data in all_category_data.items():
            coins = []
            for symbol, df in category_data.items():
                # 获取当前时间点的数据
                mask = df.index <= current_time
                if not mask.any():
                    continue
                
                current_idx = mask.sum() - 1
                if current_idx < 1:
                    continue
                
                row = df.iloc[current_idx]
                prev_row = df.iloc[current_idx - 1] if current_idx > 0 else row
                
                # 计算价格变化
                price_change_pct = ((row['close'] - prev_row['close']) / prev_row['close'] * 100) if prev_row['close'] > 0 else 0
                
                # 获取成交量比率
                vol_ratio = row.get('vol_ratio', 1.0)
                if pd.isna(vol_ratio):
                    vol_ratio = 1.0
                
                coins.append(CoinData(
                    symbol=symbol,
                    prices=None,
                    current_price=row['close'],
                    price_change_pct=price_change_pct,
                    volume_ratio=vol_ratio
                ))
            
            if coins:
                leader_coin = LEADER_COINS.get(category, "")
                avg_change = sum(c.price_change_pct for c in coins) / len(coins)
                avg_vol = sum(c.volume_ratio for c in coins) / len(coins)
                
                sector_data[category] = SectorData(
                    sector=category,
                    coins=coins,
                    leader_coin=leader_coin,
                    avg_price_change=avg_change,
                    avg_volume_ratio=avg_vol
                )
        
        if not sector_data:
            return
        
        # 计算板块权重
        self.sector_weights = self.rotation_manager.calculate_sector_weights(
            sector_data=sector_data,
            btc_data=self.btc_data_cache,
            current_time=current_time,
            leader_coins=LEADER_COINS
        )
        
        # 更新板块分类缓存 (用于 Hot 板块评分加成)
        self.sector_classifications = self.rotation_manager.get_all_classifications()
    
    def detect_surge(
        self,
        symbol: str,
        df: pd.DataFrame,
        idx: int,
        category: str
    ) -> Tuple[bool, float]:
        """检测是否为龙头币暴涨"""
        leader = LEADER_COINS.get(category)
        threshold = self.get_category_threshold(category)
        
        change = self.calculate_price_change(df, idx)
        
        if symbol != leader:
            return False, 0.0
        
        # 基本条件: 涨幅超过阈值
        if change < threshold:
            return False, 0.0
        
        # 趋势过滤
        if not self.check_trend_filter(df, idx):
            return False, 0.0
        
        # 成交量确认
        if not self.check_volume_confirmation(df, idx):
            return False, 0.0
        
        print(f"  🚀 触发信号! {symbol} [{category}] 涨幅 {change:+.2f}% >= {threshold}%")
        return True, change
    
    def find_follow_targets(
        self,
        category_data: Dict[str, pd.DataFrame],
        trigger_symbol: str,
        trigger_change: float,
        current_time: datetime,
        category: str = None
    ) -> List[Tuple[str, float, float, float, float]]:
        """
        找出跟涨不足的币种
        
        Args:
            category_data: 板块内所有币种的K线数据
            trigger_symbol: 触发信号的龙头币
            trigger_change: 龙头币涨幅
            current_time: 当前时间
            category: 板块名称 (用于 Hot 板块评分加成)
            
        Returns:
            List[(symbol, follow_pct, price, signal_score, atr)]
        """
        targets = []
        
        # 策略优化: 检查板块是否在黑名单中
        if self.strategy_optimization_enabled and category:
            # 先更新黑名单状态（移除过期条目）
            self.sector_weight_manager.update_blacklist(current_time)
            if self.sector_weight_manager.is_sector_blacklisted(category):
                return targets  # 黑名单板块不开仓
        
        # 策略优化: 检查是否允许交易 (连续亏损暂停)
        if self.strategy_optimization_enabled:
            if not self.strategy_optimizer.is_trading_allowed(current_time):
                return targets  # 交易暂停期间不开仓
        
        # 获取触发币的数据用于相关性计算
        trigger_df = category_data.get(trigger_symbol)
        
        # V6: 龙头币不参与交易，只作为信号触发器
        # 只处理跟涨币种（非龙头币）
        for symbol, df in category_data.items():
            if symbol == trigger_symbol:
                continue  # 跳过龙头币
            
            # 已有持仓则跳过
            if symbol in self.active_trades:
                continue
            
            # 策略优化: 检查交易对是否在黑名单中
            if self.strategy_optimization_enabled and hasattr(self, 'symbol_blacklist'):
                if symbol in self.symbol_blacklist:
                    continue
            
            mask = df.index <= current_time
            if not mask.any():
                continue
            
            idx = mask.sum() - 1
            if idx < 1:
                continue
            
            coin_change = self.calculate_price_change(df, idx)
            price = df.iloc[idx]['close']
            
            # 获取 ATR 值用于动态止损
            atr = df.iloc[idx].get('atr', 0.0)
            if pd.isna(atr):
                atr = 0.0
            
            # 获取成交量比率用于信号校准
            vol_ratio = df.iloc[idx].get('vol_ratio', 1.0)
            if pd.isna(vol_ratio):
                vol_ratio = 1.0
            
            # 条件1: 涨幅低于龙头
            if coin_change >= trigger_change:
                continue
            
            # 条件2: 趋势过滤
            if not self.check_trend_filter(df, idx):
                continue
            
            # 条件3: 不能是下跌的币 (至少要有正涨幅或小幅下跌)
            if coin_change < -1.0:  # 下跌超过1%不买
                continue
            
            # 计算信号评分 (使用新的多维度评分器，支持 Hot 板块加成)
            signal_score, breakdown = self.calculate_signal_score(
                df, idx, trigger_change, coin_change, trigger_df, category
            )
            
            # 策略优化: 使用信号校准器调整评分
            if self.strategy_optimization_enabled:
                # 计算波动率比率 (ATR / price * 100)
                volatility_ratio = (atr / price * 100) if price > 0 else 1.0
                
                # 校准信号评分
                calibration_result = self.signal_calibrator.calibrate_signal(
                    raw_score=signal_score,
                    volume_ratio=vol_ratio,
                    atr_ratio=volatility_ratio,
                    market_regime=self._current_market_regime
                )
                signal_score = calibration_result.final_score
                
                # 检查是否应该跳过交易
                should_skip, _ = self.signal_calibrator.should_skip_trade(
                    score=signal_score,
                    market_regime=self._current_market_regime
                )
                if should_skip:
                    continue
            
            # 条件4: 信号评分至少达到最低阈值
            min_score = self.signal_score_config.min_signal_score
            
            # 策略优化: 熊市提高信号阈值
            if self.strategy_optimization_enabled and self._current_market_regime == MarketRegimeType.BEARISH:
                min_score = max(min_score, 85.0)  # 熊市至少85分
            
            if signal_score < min_score:
                continue
            
            follow_pct = (coin_change / trigger_change * 100) if trigger_change != 0 else 0
            targets.append((symbol, follow_pct, price, signal_score, atr))
        
        # 按信号评分排序，选择评分最高的
        targets.sort(key=lambda x: x[3], reverse=True)
        
        return targets
    
    def open_trade(
        self,
        symbol: str,
        category: str,
        entry_time: datetime,
        entry_price: float,
        trigger_coin: str,
        trigger_change: float,
        signal_score: float,
        atr_value: float = 0.0,  # ATR值用于动态止损
        price_data: pd.DataFrame = None,  # K线数据用于Q3Q4优化
        trade_history: List[dict] = None  # 交易历史用于Q3Q4优化
    ) -> bool:
        """开仓 - 永续合约版 (支持板块轮动权重和策略优化)"""
        if symbol in self.active_trades:
            return False
        
        # V6: 检查每日亏损限制
        if self.daily_loss_limit_enabled and self.daily_loss_triggered:
            return False
        
        # V7: 分类亏损过滤器检查
        if self.category_filter_enabled and self.category_loss_filter and category:
            is_eligible, reason = self.category_loss_filter.is_category_eligible(category, entry_time)
            if not is_eligible:
                print(f"    ⛔ 分类过滤: {symbol} ({category}) - {reason}")
                return False
        
        # Q3/Q4 优化检查
        q3q4_decision = None
        if self.q3q4_optimization_enabled and self.q3q4_optimizer:
            q3q4_decision = self.q3q4_optimizer.evaluate_trade(
                symbol=symbol,
                category=category,
                signal_score=signal_score,
                price_data=price_data if price_data is not None else pd.DataFrame(),
                current_price=entry_price,
                current_time=entry_time,
                trade_history=trade_history or []
            )
            
            if not q3q4_decision.can_trade:
                # 打印拒绝原因
                reasons_str = ", ".join(q3q4_decision.reasons[:2])
                print(f"    ⛔ Q3Q4拒绝: {symbol} - {reasons_str}")
                return False
        
        # 策略优化: 获取动态最大持仓数
        effective_max_positions = self.max_positions
        if self.strategy_optimization_enabled:
            # 计算当前回撤
            current_equity = self.balance + sum(t.margin for t in self.active_trades.values())
            current_drawdown = ((self.max_balance - current_equity) / self.max_balance * 100) if self.max_balance > 0 else 0
            
            trading_params = self.strategy_optimizer.get_trading_parameters(
                market_regime=self._current_market_regime,
                current_drawdown=current_drawdown
            )
            effective_max_positions = trading_params.max_positions
        
        # 检查最大持仓数
        if len(self.active_trades) >= effective_max_positions:
            return False
        
        # 计算保证金大小 (应用板块权重)
        margin = self.calculate_position_size(signal_score, category)
        
        # 策略优化: 应用静态分类权重调整
        if self.strategy_optimization_enabled and category and self.category_weight_adjustments:
            static_weight = self.category_weight_adjustments.get(category, 1.0)
            margin = margin * static_weight
        
        # 策略优化: 应用动态板块权重调整
        if self.strategy_optimization_enabled and category:
            sector_weight = self.sector_weight_manager.get_sector_weight(category)
            margin = margin * sector_weight.final_weight
            # 确保保证金在合理范围内
            margin = max(self.base_trade_amount * 0.5, min(margin, self.max_trade_amount))
        
        # V7: 应用分类亏损过滤器权重
        if self.category_filter_enabled and self.category_loss_filter and category:
            filter_weight = self.category_loss_filter.get_category_weight(category)
            if filter_weight < 1.0:
                margin = margin * filter_weight
                margin = max(self.base_trade_amount * 0.3, margin)  # 最低30%基础仓位
        
        # 策略优化: 回撤时减少仓位
        if self.strategy_optimization_enabled:
            current_equity = self.balance + sum(t.margin for t in self.active_trades.values())
            current_drawdown = ((self.max_balance - current_equity) / self.max_balance * 100) if self.max_balance > 0 else 0
            
            trading_params = self.strategy_optimizer.get_trading_parameters(
                market_regime=self._current_market_regime,
                current_drawdown=current_drawdown
            )
            margin = margin * trading_params.position_size_multiplier
        
        if self.balance < margin:
            return False
        
        # 永续合约: 仓位价值 = 保证金 * 杠杆
        position_value = margin * self.leverage if self.futures_mode else margin
        quantity = position_value / entry_price
        
        # 计算强平价格
        liquidation_price = self.calculate_liquidation_price(entry_price, self.leverage) if self.futures_mode else 0
        
        # 使用 StopLossManager 计算初始止损
        initial_sl_pct, sl_type = self.stop_loss_manager.calculate_initial_stop_loss(
            entry_price, atr_value, signal_score, self.leverage
        )
        
        # V6: 应用分类止损限制
        if category and category in self.category_stop_loss:
            category_sl = self.category_stop_loss[category]
            if initial_sl_pct > category_sl:
                initial_sl_pct = category_sl
                sl_type = "category"
        
        # 策略优化: 应用动态止损调整
        if self.strategy_optimization_enabled and category:
            stop_loss_result = self.dynamic_stop_loss_controller.get_stop_loss_threshold(
                sector=category,
                market_regime=self._current_market_regime
            )
            # V6: 取分类止损和动态止损的较小值
            if category in self.category_stop_loss:
                initial_sl_pct = min(stop_loss_result.final_threshold, self.category_stop_loss[category])
            else:
                initial_sl_pct = stop_loss_result.final_threshold
        
        # Q3/Q4 优化: 应用仓位乘数和止损
        if q3q4_decision:
            margin = margin * q3q4_decision.position_multiplier
            margin = max(self.base_trade_amount * 0.3, min(margin, self.max_trade_amount))
            initial_sl_pct = q3q4_decision.stop_loss_pct
            sl_type = "q3q4_adaptive"
        
        # 获取板块层级信息
        sector_tier = ""
        if self.rotation_manager:
            tier = self.rotation_manager.get_sector_tier(category)
            sector_tier = tier.value if tier else ""
        
        self.balance -= margin
        
        trade = BacktestTradeV2(
            symbol=symbol,
            category=category,
            entry_time=entry_time,
            entry_price=entry_price,
            quantity=quantity,
            margin=margin,
            position_value=position_value,
            leverage=self.leverage if self.futures_mode else 1,
            trigger_coin=trigger_coin,
            trigger_change=trigger_change,
            signal_score=signal_score,
            highest_price=entry_price,
            trailing_stop=0,
            liquidation_price=liquidation_price,
            # 分批止盈初始化
            initial_quantity=quantity,
            initial_margin=margin,
            tp_level=0,
            realized_pnl=0,
            breakeven_stop=0,
            # 止损优化字段
            initial_stop_loss_pct=initial_sl_pct,
            current_stop_loss_pct=initial_sl_pct,
            stop_loss_type=sl_type,
            atr_at_entry=atr_value,
            early_breakeven_activated=False,
            time_decay_applied=False
        )
        
        self.active_trades[symbol] = trade
        
        # 打印开仓信息 (包含板块层级)
        tier_str = f" [{sector_tier.upper()}]" if sector_tier else ""
        opt_str = " [OPT]" if self.strategy_optimization_enabled else ""
        if self.futures_mode:
            print(f"    💰 开仓{opt_str}: {symbol}{tier_str} @ {entry_price:.4f}, 保证金: {margin:.0f}, 仓位: {position_value:.0f} ({self.leverage}x), 评分: {signal_score:.0f}, 止损: {initial_sl_pct:.1f}% ({sl_type})")
        else:
            print(f"    💰 开仓{opt_str}: {symbol}{tier_str} @ {entry_price:.4f}, 金额: {margin:.0f}, 评分: {signal_score:.0f}, 止损: {initial_sl_pct:.1f}%")
        return True
    
    def update_trailing_stop(self, trade: BacktestTradeV2, current_price: float):
        """更新移动止损"""
        # 更新最高价
        if current_price > trade.highest_price:
            trade.highest_price = current_price
        
        # 计算当前盈利百分比 (基于价格变化，杠杆会放大收益)
        price_change_pct = ((current_price - trade.entry_price) / trade.entry_price) * 100
        
        # 激活移动止损 (基于价格变化，不是杠杆后的收益)
        if price_change_pct >= self.trailing_stop_activation:
            # 移动止损价 = 最高价 * (1 - 回撤百分比)
            new_trailing_stop = trade.highest_price * (1 - self.trailing_stop_pct / 100)
            
            # 只能上移，不能下移
            if new_trailing_stop > trade.trailing_stop:
                trade.trailing_stop = new_trailing_stop
    
    def check_partial_take_profit(
        self,
        trade: BacktestTradeV2,
        current_price: float,
        leveraged_pnl_pct: float
    ) -> Optional[Tuple[bool, str]]:
        """
        检查分批止盈条件
        - 10%止盈1/3，设置保本止损
        - 20%止盈1/3
        - 30%止盈剩余全部
        返回: None表示不平仓，(True, reason)表示全部平仓
        """
        # 检查每个止盈级别
        for level_idx, tp_level in enumerate(self.partial_tp_levels):
            # 已经触发过这个级别，跳过
            if trade.tp_level > level_idx:
                continue
            
            # 检查是否达到这个止盈级别
            if leveraged_pnl_pct >= tp_level:
                trade.tp_level = level_idx + 1
                tp_ratio = self.partial_tp_ratios[level_idx]
                
                # 计算本次止盈的数量和保证金
                close_quantity = trade.initial_quantity * tp_ratio
                close_margin = trade.initial_margin * tp_ratio
                
                # 计算本次止盈的盈亏
                price_change = current_price - trade.entry_price
                partial_pnl = price_change * close_quantity
                
                # 累计已实现盈亏
                trade.realized_pnl += partial_pnl
                
                # 减少持仓
                trade.quantity -= close_quantity
                trade.margin -= close_margin
                trade.position_value = trade.margin * trade.leverage
                
                # 返还部分保证金 + 盈亏到余额
                self.balance += close_margin + partial_pnl
                
                # 第一次止盈后设置保本止损
                if level_idx == 0:
                    # 保本止损价 = 入场价 * (1 + 2%缓冲)，给更多空间
                    trade.breakeven_stop = trade.entry_price * 1.005  # 0.5%缓冲
                
                level_name = f"TP{level_idx + 1}"
                print(f"    📈 分批止盈 {level_name}: {trade.symbol} @ {current_price:.4f}, 止盈{tp_ratio*100:.0f}%仓位, 盈亏: +{partial_pnl:.2f} USDT")
                
                # 如果是最后一级，全部平仓
                if level_idx == len(self.partial_tp_levels) - 1:
                    return True, f"分批止盈完成 ({leveraged_pnl_pct:+.2f}%)"
                
                # 检查剩余仓位是否太小
                if trade.quantity < trade.initial_quantity * 0.1:
                    return True, f"分批止盈完成 ({leveraged_pnl_pct:+.2f}%)"
        
        return None
    
    def check_exit_conditions(
        self,
        trade: BacktestTradeV2,
        current_price: float,
        current_time: datetime
    ) -> Tuple[bool, str]:
        """检查平仓条件 - 永续合约版 (支持分批止盈和优化止损)"""
        # 价格变化百分比
        price_change_pct = ((current_price - trade.entry_price) / trade.entry_price) * 100
        
        # 杠杆后的收益率 (基于保证金)
        leveraged_pnl_pct = price_change_pct * trade.leverage
        
        # 计算持仓时间
        holding_hours = (current_time - trade.entry_time).total_seconds() / 3600
        
        # 更新移动止损
        self.update_trailing_stop(trade, current_price)
        
        # 0. 强平检查 (永续合约特有)
        if self.futures_mode and trade.liquidation_price > 0:
            if current_price <= trade.liquidation_price:
                self.liquidations += 1
                return True, f"强平 ({leveraged_pnl_pct:+.2f}%)"
        
        # 1. 检查提前保本止损激活
        if not trade.early_breakeven_activated:
            should_activate, be_price = self.stop_loss_manager.check_early_breakeven(
                trade, current_price, trade.leverage
            )
            if should_activate:
                trade.early_breakeven_activated = True
                trade.breakeven_stop = be_price
                print(f"    🛡️ 提前保本激活: {trade.symbol} @ {be_price:.4f}")
        
        # 2. 保本止损检查
        if trade.breakeven_stop > 0 and current_price <= trade.breakeven_stop:
            return True, f"保本止损 ({leveraged_pnl_pct:+.2f}%)"
        
        # 3. 移动止损触发
        if trade.trailing_stop > 0 and current_price <= trade.trailing_stop:
            return True, f"移动止损 ({leveraged_pnl_pct:+.2f}%)"
        
        # 4. 分批止盈检查
        if self.partial_tp_enabled:
            partial_result = self.check_partial_take_profit(trade, current_price, leveraged_pnl_pct)
            if partial_result:
                return partial_result
        else:
            # 原有的固定止盈逻辑
            if leveraged_pnl_pct >= self.take_profit:
                return True, f"止盈 ({leveraged_pnl_pct:+.2f}%)"
        
        # 5. 应用时间衰减止损
        effective_sl_pct = trade.current_stop_loss_pct
        if self.stop_loss_config.time_decay_sl_enabled:
            decayed_sl, decay_applied = self.stop_loss_manager.apply_time_decay(
                trade.initial_stop_loss_pct, holding_hours, leveraged_pnl_pct
            )
            if decay_applied and not trade.time_decay_applied:
                trade.time_decay_applied = True
                trade.current_stop_loss_pct = decayed_sl
                effective_sl_pct = decayed_sl
        
        # 6. 动态止损检查 (基于杠杆后收益)
        if effective_sl_pct > 0 and leveraged_pnl_pct <= -effective_sl_pct:
            sl_type = trade.stop_loss_type
            if trade.time_decay_applied:
                sl_type = StopLossType.TIME_DECAY.value
            return True, f"止损[{sl_type}] ({leveraged_pnl_pct:+.2f}%)"
        
        # 7. 短期时间止损 (可配置，默认持仓超过2小时且盈利<3%则平仓)
        # 分析显示1-4h持仓亏损，提前止损减少损失
        if self.stop_loss_config.short_time_stop_enabled:
            if holding_hours > self.stop_loss_config.short_time_stop_hours and leveraged_pnl_pct < self.stop_loss_config.short_time_stop_min_profit:
                return True, f"时间止损{self.stop_loss_config.short_time_stop_hours:.0f}h ({leveraged_pnl_pct:+.2f}%)"
        
        # 8. 长期时间止损 (可配置，默认持仓超过24小时且亏损)
        if self.stop_loss_config.long_time_stop_enabled:
            if holding_hours > self.stop_loss_config.long_time_stop_hours and leveraged_pnl_pct < self.stop_loss_config.long_time_stop_min_profit:
                return True, f"时间止损{self.stop_loss_config.long_time_stop_hours:.0f}h ({leveraged_pnl_pct:+.2f}%)"
        
        return False, ""
    
    def close_trade(
        self,
        symbol: str,
        exit_time: datetime,
        exit_price: float,
        reason: str
    ):
        """平仓 - 支持分批止盈和策略优化记录"""
        if symbol not in self.active_trades:
            return
        
        trade = self.active_trades[symbol]
        trade.exit_time = exit_time
        trade.exit_price = exit_price
        trade.exit_reason = reason
        
        # 计算剩余仓位的盈亏 (永续合约版)
        price_change = exit_price - trade.entry_price
        remaining_pnl = price_change * trade.quantity
        
        # 总盈亏 = 已实现盈亏(分批止盈) + 剩余仓位盈亏
        trade.profit_loss = trade.realized_pnl + remaining_pnl
        
        # 收益率基于初始保证金计算 (杠杆放大)
        trade.profit_loss_pct = (trade.profit_loss / trade.initial_margin) * 100
        trade.status = 'closed'
        
        # 返还剩余保证金 + 剩余盈亏
        self.balance += trade.margin + remaining_pnl
        self.trades.append(trade)
        
        # V6: 更新每日盈亏
        self.daily_pnl += trade.profit_loss
        
        # V7: 更新周期统计
        self.period_pnl += trade.profit_loss
        self.period_trades += 1
        
        # V6: 检查是否触发每日亏损限制
        if self.daily_loss_limit_enabled and not self.daily_loss_triggered:
            daily_loss_pct = (self.daily_pnl / self.initial_balance) * 100
            if daily_loss_pct <= -self.daily_loss_limit_pct:
                self.daily_loss_triggered = True
                self.daily_loss_trigger_time = exit_time
                print(f"    ⚠️ V6每日亏损限制触发: 当日亏损 {daily_loss_pct:.2f}% (限制: -{self.daily_loss_limit_pct}%), 暂停开仓 {self.daily_loss_limit_cooldown_hours}h")
        
        # 策略优化: 记录交易结果到板块权重管理器
        if self.strategy_optimization_enabled and trade.category:
            self.sector_weight_manager.record_trade(
                sector=trade.category,
                profit_loss=trade.profit_loss,
                timestamp=exit_time
            )
            # 更新黑名单状态（移除过期条目）
            self.sector_weight_manager.update_blacklist(exit_time)
            
            # 记录连续亏损 (用于交易暂停)
            is_win = trade.profit_loss > 0
            self.strategy_optimizer.record_trade_result(is_win, exit_time)
        
        # Q3/Q4 优化: 记录交易结果
        if self.q3q4_optimization_enabled and self.q3q4_optimizer:
            self.q3q4_optimizer.record_trade_result(
                symbol=symbol,
                category=trade.category,
                profit_loss=trade.profit_loss,
                timestamp=exit_time
            )
        
        # V7: 分类亏损过滤器记录交易
        if self.category_filter_enabled and self.category_loss_filter and trade.category:
            is_win = trade.profit_loss > 0
            self.category_loss_filter.record_trade(
                category=trade.category,
                pnl=trade.profit_loss,
                is_win=is_win,
                trade_time=exit_time
            )
        
        del self.active_trades[symbol]
        
        emoji = "✅" if trade.profit_loss > 0 else "❌"
        if self.futures_mode:
            print(f"    {emoji} 平仓: {symbol} @ {exit_price:.4f}, 盈亏: {trade.profit_loss_pct:+.2f}% ({trade.leverage}x), {reason}")
        else:
            print(f"    {emoji} 平仓: {symbol} @ {exit_price:.4f}, 盈亏: {trade.profit_loss_pct:+.2f}%, {reason}")
    
    def update_equity(self, current_time: datetime, all_data: Dict[str, pd.DataFrame]):
        """更新权益曲线 - 永续合约版"""
        unrealized_pnl = 0
        for symbol, trade in self.active_trades.items():
            if symbol in all_data:
                df = all_data[symbol]
                mask = df.index <= current_time
                if mask.any():
                    current_price = df.loc[mask].iloc[-1]['close']
                    # 未实现盈亏 = (当前价 - 入场价) * 数量
                    price_change = current_price - trade.entry_price
                    unrealized_pnl += price_change * trade.quantity
        
        # 总权益 = 可用余额 + 持仓保证金 + 未实现盈亏
        total_margin = sum(t.margin for t in self.active_trades.values())
        total_equity = self.balance + total_margin + unrealized_pnl
        self.equity_curve.append((current_time, total_equity))
        
        if total_equity > self.max_balance:
            self.max_balance = total_equity
        
        drawdown = self.max_balance - total_equity
        if drawdown > self.max_drawdown:
            self.max_drawdown = drawdown
    
    def run_backtest(
        self,
        categories: List[str] = None,
        start_date: datetime = None,
        end_date: datetime = None,
        days: int = 7,
        interval: str = '15m',
        segment_days: int = 0
    ) -> BacktestResultV2:
        """
        运行回测 V2
        
        Args:
            categories: 分类列表
            start_date: 开始日期
            end_date: 结束日期
            days: 回测天数
            interval: K线间隔
            segment_days: 分段天数 (0=不分段, 90=按季度分段模拟--mode full效果)
                         分段回测的核心优势:
                         1. 每段开始时技术指标重新计算 (冷启动效应)
                         2. 资金和持仓状态保持连续
                         3. 避免长期趋势的"惯性"影响
        """
        # 如果启用分段回测，调用分段回测方法
        if segment_days > 0 and start_date and end_date:
            return self._run_segmented_backtest(
                categories=categories,
                start_date=start_date,
                end_date=end_date,
                interval=interval,
                segment_days=segment_days
            )
        
        if categories is None:
            categories = list(CRYPTO_CATEGORIES.keys())[:3]
        
        if end_date is None:
            end_date = datetime.now()
        if start_date is None:
            start_date = end_date - timedelta(days=days)
        
        actual_days = (end_date - start_date).days
        
        mode_str = "永续合约" if self.futures_mode else "现货"
        print(f"\n{'='*60}")
        print(f"🚀 开始回测 V2 ({mode_str})")
        print(f"📅 开始日期: {start_date.strftime('%Y-%m-%d %H:%M')}")
        print(f"📅 结束日期: {end_date.strftime('%Y-%m-%d %H:%M')}")
        print(f"📅 回测周期: {actual_days} 天")
        print(f"📊 时间间隔: {interval}")
        print(f"📂 测试分类: {', '.join(categories)}")
        print(f"💰 初始资金: {self.initial_balance:,.2f} USDT")
        print(f"\n📈 V2 策略参数:")
        print(f"   交易模式: {mode_str}")
        if self.futures_mode:
            print(f"   杠杆倍数: {self.leverage}x")
        print(f"   基础保证金: {self.base_trade_amount} USDT")
        print(f"   最大保证金: {self.max_trade_amount} USDT")
        print(f"   止盈: {self.take_profit}%")
        print(f"   止损: {self.stop_loss}%")
        print(f"   移动止损: {self.trailing_stop_pct}% (激活阈值: {self.trailing_stop_activation}%)")
        print(f"   最大持仓: {self.max_positions}")
        print(f"   冷却期: {self.cooldown_periods} 根K线")
        if self.rotation_manager:
            print(f"\n📊 板块轮动配置:")
            print(f"   轮动启用: {self.rotation_config.enabled}")
            print(f"   回溯周期: {self.rotation_config.lookback_periods}")
            print(f"   再平衡间隔: {self.rotation_config.rebalance_interval}")
        print(f"\n📈 分类阈值配置:")
        for cat in categories:
            threshold = self.get_category_threshold(cat)
            print(f"   {cat}: {threshold}%")
        # V7: 打印定期重置配置
        if self.periodic_reset_enabled:
            print(f"\n🔄 V7 定期重置配置:")
            print(f"   定期重置: 启用 (每{self.reset_interval_days}天)")
        print(f"{'='*60}\n")
        
        # 获取数据缓存
        cache = get_cache()
        cache_stats = cache.get_stats()
        print(f"📦 数据缓存: {cache_stats['total_entries']} 条记录, {cache_stats['total_size_mb']:.1f} MB")
        
        # 获取所有分类的历史数据 (优先使用缓存)
        all_category_data = {}
        all_data_flat = {}  # 扁平化数据用于权益计算
        
        for category in categories:
            # 尝试从缓存获取
            cached_data = cache.get_category_data(category, interval, start_date, end_date)
            if cached_data:
                print(f"📦 从缓存加载 {category} 分类数据 ({len(cached_data)} 个币种)")
                all_category_data[category] = cached_data
                all_data_flat.update(cached_data)
            else:
                print(f"📥 从API加载 {category} 分类数据...")
                data = self.data_fetcher.get_category_historical_data_by_date(
                    category, interval, start_date, end_date
                )
                if data:
                    all_category_data[category] = data
                    all_data_flat.update(data)
                    # 保存到缓存
                    cache.set_category_data(category, interval, start_date, end_date, data)
                    print(f"   ✅ 已缓存 {len(data)} 个币种数据")
        
        if not all_category_data:
            print("❌ 没有获取到历史数据")
            return None
        
        # 加载 BTC 数据用于市场状态检测 (优先使用缓存)
        print(f"\n📥 加载 BTC 数据用于市场状态检测...")
        btc_cached = cache.get('BTCUSDT', interval, start_date, end_date)
        if btc_cached is not None and not btc_cached.empty:
            self.btc_data_cache = btc_cached
            print(f"   📦 从缓存加载 BTC 数据 ({len(btc_cached)} 条)")
        else:
            btc_df = self.data_fetcher.get_historical_klines('BTCUSDT', interval, start_date, end_date)
            if not btc_df.empty:
                self.btc_data_cache = btc_df
                cache.set('BTCUSDT', interval, start_date, end_date, btc_df)
                print(f"   ✅ BTC 数据加载成功 ({len(btc_df)} 条), 已缓存")
            else:
                self.btc_data_cache = None
                print(f"   ⚠️ BTC 数据加载失败，市场状态检测将使用默认值")
        
        # 获取时间范围
        all_timestamps = set()
        for category, data in all_category_data.items():
            for symbol, df in data.items():
                all_timestamps.update(df.index.tolist())
        
        sorted_timestamps = sorted(all_timestamps)
        
        print(f"\n📈 开始模拟交易 ({len(sorted_timestamps)} 个时间点)...")
        print(f"   策略优化: {'启用' if self.strategy_optimization_enabled else '禁用'}")
        
        # 板块轮动再平衡间隔计数器
        rebalance_counter = 0
        rebalance_interval = self.rotation_config.rebalance_interval if self.rotation_manager else 0
        
        # 市场状态检测间隔 (每100个时间点检测一次)
        regime_check_interval = 100
        
        # 遍历每个时间点
        for i, current_time in enumerate(sorted_timestamps):
            if i % 100 == 0:
                progress = (i / len(sorted_timestamps)) * 100
                active_count = len(self.active_trades)
                regime_str = self._current_market_regime.value if self.strategy_optimization_enabled else "N/A"
                print(f"  进度: {progress:.1f}% - {current_time} | 持仓: {active_count} | 市场: {regime_str}")
            
            # V6: 每日亏损限制 - 检查是否需要重置每日盈亏
            if self.daily_loss_limit_enabled:
                current_date = current_time.date() if hasattr(current_time, 'date') else current_time
                if self.daily_pnl_reset_date is None or current_date != self.daily_pnl_reset_date:
                    # 新的一天，重置每日盈亏
                    if self.daily_pnl_reset_date is not None and self.daily_pnl != 0:
                        daily_pct = (self.daily_pnl / self.initial_balance) * 100
                        print(f"  📊 日结: {self.daily_pnl_reset_date} 盈亏: {self.daily_pnl:+.2f} ({daily_pct:+.2f}%)")
                    self.daily_pnl = 0.0
                    self.daily_pnl_reset_date = current_date
                    # 检查冷却期是否结束
                    if self.daily_loss_triggered and self.daily_loss_trigger_time:
                        hours_since_trigger = (current_time - self.daily_loss_trigger_time).total_seconds() / 3600
                        if hours_since_trigger >= self.daily_loss_limit_cooldown_hours:
                            self.daily_loss_triggered = False
                            self.daily_loss_trigger_time = None
                            print(f"  ✅ V6每日亏损限制冷却结束，恢复交易")
            
            # V7: 定期重置检查 (模拟独立季度模式优势)
            self.check_periodic_reset(current_time)
            
            # 策略优化: 定期检测市场状态
            if self.strategy_optimization_enabled and i % regime_check_interval == 0:
                if self.btc_data_cache is not None and not self.btc_data_cache.empty:
                    # 获取当前时间点之前的BTC数据
                    btc_mask = self.btc_data_cache.index <= current_time
                    if btc_mask.any():
                        btc_data_slice = self.btc_data_cache.loc[btc_mask]
                        if len(btc_data_slice) >= 20:  # 至少需要20个数据点
                            regime_result = self.regime_detector.detect_regime(btc_data_slice)
                            self._current_market_regime = regime_result.regime
            
            # 定期更新板块权重
            if self.rotation_manager:
                rebalance_counter += 1
                if rebalance_counter >= rebalance_interval or i == 0:
                    self.update_sector_weights(all_category_data, current_time)
                    rebalance_counter = 0
            
            # 检查每个分类
            for category, category_data in all_category_data.items():
                leader = LEADER_COINS.get(category)
                
                if leader not in category_data:
                    continue
                
                leader_df = category_data[leader]
                
                # 找到当前时间点的索引
                mask = leader_df.index <= current_time
                if not mask.any():
                    continue
                
                idx = mask.sum() - 1
                
                # 检查冷却期
                interval_minutes = int(interval.replace('m', '').replace('h', '')) 
                if 'h' in interval:
                    interval_minutes *= 60
                
                if self.is_in_cooldown(category, current_time, interval_minutes):
                    continue
                
                # 检测龙头币暴涨
                is_surge, trigger_change = self.detect_surge(leader, leader_df, idx, category)
                
                if is_surge:
                    # 更新冷却期
                    self.last_signal_time[category] = current_time
                    
                    # 找出跟涨不足的币种 (传递 category 用于 Hot 板块评分加成)
                    targets = self.find_follow_targets(
                        category_data, leader, trigger_change, current_time, category
                    )
                    
                    # 开仓 (按信号评分排序，最多开到max_positions)
                    available_slots = self.max_positions - len(self.active_trades)
                    for symbol, follow_pct, price, signal_score, atr in targets[:available_slots]:
                        self.open_trade(
                            symbol, category, current_time, price,
                            leader, trigger_change, signal_score, atr
                        )
            
            # 检查持仓的止盈止损
            for symbol in list(self.active_trades.keys()):
                trade = self.active_trades[symbol]
                
                if symbol not in all_data_flat:
                    continue
                
                df = all_data_flat[symbol]
                mask = df.index <= current_time
                if not mask.any():
                    continue
                
                current_price = df.loc[mask].iloc[-1]['close']
                
                should_exit, reason = self.check_exit_conditions(
                    trade, current_price, current_time
                )
                
                if should_exit:
                    self.close_trade(symbol, current_time, current_price, reason)
            
            # 更新权益曲线（每10个时间点更新一次）
            if i % 10 == 0:
                self.update_equity(current_time, all_data_flat)
        
        # 强制平仓所有持仓
        print(f"\n📤 回测结束，强制平仓 {len(self.active_trades)} 个持仓...")
        for symbol in list(self.active_trades.keys()):
            if symbol in all_data_flat:
                df = all_data_flat[symbol]
                if not df.empty:
                    self.close_trade(
                        symbol, 
                        df.index[-1], 
                        df.iloc[-1]['close'],
                        "回测结束强制平仓"
                    )
        
        # 计算回测结果
        return self._calculate_results(
            sorted_timestamps[0] if sorted_timestamps else start_date,
            sorted_timestamps[-1] if sorted_timestamps else end_date
        )
    
    def _run_segmented_backtest(
        self,
        categories: List[str],
        start_date: datetime,
        end_date: datetime,
        interval: str = '15m',
        segment_days: int = 90
    ) -> BacktestResultV2:
        """
        分段回测 - 复刻 --mode full 的高收益机制
        
        核心优势:
        1. 每段开始时技术指标重新计算 (冷启动效应)
        2. 资金和持仓状态保持连续
        3. 避免长期趋势的"惯性"影响
        4. 结合定期重置机制，形成双重"新鲜开始"效果
        
        Args:
            categories: 分类列表
            start_date: 开始日期
            end_date: 结束日期
            interval: K线间隔
            segment_days: 每段天数 (默认90天=季度)
        """
        print(f"\n{'='*60}")
        print(f"📊 分段回测模式 (复刻 --mode full 高收益机制)")
        print(f"{'='*60}")
        print(f"时间范围: {start_date.date()} ~ {end_date.date()}")
        print(f"分段天数: {segment_days} 天")
        print(f"核心优势: 技术指标冷启动 + 资金状态累积")
        
        # 生成分段
        segments = []
        current_start = start_date
        segment_num = 1
        
        while current_start < end_date:
            current_end = min(current_start + timedelta(days=segment_days), end_date)
            segments.append((f"段{segment_num}", current_start, current_end))
            current_start = current_end + timedelta(days=1)
            segment_num += 1
        
        print(f"共 {len(segments)} 个分段")
        
        # 记录分段结果
        segment_results = []
        
        for name, seg_start, seg_end in segments:
            print(f"\n{'='*60}")
            print(f"📊 {name}: {seg_start.date()} ~ {seg_end.date()}")
            print(f"   起始余额: {self.balance:,.2f} USDT")
            print('='*60)
            
            # 记录段开始前的状态
            prev_balance = self.balance
            prev_trades_count = len(self.trades)
            
            # 运行单段回测 (不使用分段，让数据重新加载)
            # 这里的关键是：每段都会重新加载数据，技术指标重新计算
            result = self._run_single_segment(
                categories=categories,
                start_date=seg_start,
                end_date=seg_end,
                interval=interval
            )
            
            if result:
                # 计算本段的实际收益
                segment_pnl = self.balance - prev_balance
                segment_trades_count = len(self.trades) - prev_trades_count
                segment_trades = self.trades[prev_trades_count:]
                segment_wins = len([t for t in segment_trades if t.profit_loss > 0])
                segment_win_rate = (segment_wins / segment_trades_count * 100) if segment_trades_count > 0 else 0
                
                segment_results.append({
                    'name': name,
                    'pnl': segment_pnl,
                    'trades': segment_trades_count,
                    'win_rate': segment_win_rate,
                    'final_balance': self.balance
                })
                
                print(f"   收益: {segment_pnl:+,.2f} USDT")
                print(f"   交易数: {segment_trades_count}, 胜率: {segment_win_rate:.1f}%")
                print(f"   当前余额: {self.balance:,.2f} USDT")
        
        # 打印汇总
        print("\n" + "="*60)
        print("📊 分段回测汇总")
        print("="*60)
        
        total_pnl = self.balance - self.initial_balance
        total_pnl_pct = total_pnl / self.initial_balance * 100
        
        print(f"\n{'分段':<15} {'收益':<20} {'交易数':<10} {'胜率':<10}")
        print("-"*55)
        for data in segment_results:
            print(f"{data['name']:<15} {data['pnl']:>+15,.2f} {data['trades']:>10} {data['win_rate']:>8.1f}%")
        
        print("-"*55)
        print(f"{'合计':<15} {total_pnl:>+15,.2f}")
        print(f"\n💰 初始余额: {self.initial_balance:,.2f} USDT")
        print(f"💰 最终余额: {self.balance:,.2f} USDT")
        print(f"📈 总收益率: {total_pnl_pct:+.2f}%")
        print(f"📊 总交易数: {len(self.trades)}")
        
        # 返回最终结果
        return self._calculate_results(start_date, end_date)
    
    def _run_single_segment(
        self,
        categories: List[str],
        start_date: datetime,
        end_date: datetime,
        interval: str = '15m'
    ) -> bool:
        """
        运行单个分段的回测
        关键: 每段都重新加载数据，技术指标重新计算
        """
        # 获取数据缓存
        cache = get_cache()
        
        # 获取所有分类的历史数据 (每段重新加载，实现技术指标冷启动)
        all_category_data = {}
        all_data_flat = {}
        
        for category in categories:
            # 每段都重新从缓存或API获取数据
            # 关键: 这里的数据是该段时间范围内的，技术指标会重新计算
            cached_data = cache.get_category_data(category, interval, start_date, end_date)
            if cached_data:
                all_category_data[category] = cached_data
                all_data_flat.update(cached_data)
            else:
                data = self.data_fetcher.get_category_historical_data_by_date(
                    category, interval, start_date, end_date
                )
                if data:
                    all_category_data[category] = data
                    all_data_flat.update(data)
                    cache.set_category_data(category, interval, start_date, end_date, data)
        
        if not all_category_data:
            return False
        
        # 加载 BTC 数据 (每段重新加载)
        btc_cached = cache.get('BTCUSDT', interval, start_date, end_date)
        if btc_cached is not None and not btc_cached.empty:
            self.btc_data_cache = btc_cached
        else:
            btc_df = self.data_fetcher.get_historical_klines('BTCUSDT', interval, start_date, end_date)
            if not btc_df.empty:
                self.btc_data_cache = btc_df
                cache.set('BTCUSDT', interval, start_date, end_date, btc_df)
        
        # 获取时间范围
        all_timestamps = set()
        for category, data in all_category_data.items():
            for symbol, df in data.items():
                all_timestamps.update(df.index.tolist())
        
        sorted_timestamps = sorted(all_timestamps)
        
        # 板块轮动再平衡间隔计数器
        rebalance_counter = 0
        rebalance_interval = self.rotation_config.rebalance_interval if self.rotation_manager else 0
        regime_check_interval = 100
        
        # 遍历每个时间点
        for i, current_time in enumerate(sorted_timestamps):
            # V6: 每日亏损限制检查
            if self.daily_loss_limit_enabled:
                current_date = current_time.date() if hasattr(current_time, 'date') else current_time
                if self.daily_pnl_reset_date is None or current_date != self.daily_pnl_reset_date:
                    if self.daily_pnl_reset_date is not None and self.daily_pnl != 0:
                        daily_pct = (self.daily_pnl / self.initial_balance) * 100
                    self.daily_pnl = 0.0
                    self.daily_pnl_reset_date = current_date
                    if self.daily_loss_triggered and self.daily_loss_trigger_time:
                        hours_since_trigger = (current_time - self.daily_loss_trigger_time).total_seconds() / 3600
                        if hours_since_trigger >= self.daily_loss_limit_cooldown_hours:
                            self.daily_loss_triggered = False
                            self.daily_loss_trigger_time = None
            
            # V7: 定期重置检查
            self.check_periodic_reset(current_time)
            
            # 策略优化: 定期检测市场状态
            if self.strategy_optimization_enabled and i % regime_check_interval == 0:
                if self.btc_data_cache is not None and not self.btc_data_cache.empty:
                    btc_mask = self.btc_data_cache.index <= current_time
                    if btc_mask.any():
                        btc_data_slice = self.btc_data_cache.loc[btc_mask]
                        if len(btc_data_slice) >= 20:
                            regime_result = self.regime_detector.detect_regime(btc_data_slice)
                            self._current_market_regime = regime_result.regime
            
            # 定期更新板块权重
            if self.rotation_manager:
                rebalance_counter += 1
                if rebalance_counter >= rebalance_interval or i == 0:
                    self.update_sector_weights(all_category_data, current_time)
                    rebalance_counter = 0
            
            # 检查每个分类
            for category, category_data in all_category_data.items():
                leader = LEADER_COINS.get(category)
                
                if leader not in category_data:
                    continue
                
                leader_df = category_data[leader]
                mask = leader_df.index <= current_time
                if not mask.any():
                    continue
                
                idx = mask.sum() - 1
                
                interval_minutes = int(interval.replace('m', '').replace('h', '')) 
                if 'h' in interval:
                    interval_minutes *= 60
                
                if self.is_in_cooldown(category, current_time, interval_minutes):
                    continue
                
                is_surge, trigger_change = self.detect_surge(leader, leader_df, idx, category)
                
                if is_surge:
                    self.last_signal_time[category] = current_time
                    targets = self.find_follow_targets(
                        category_data, leader, trigger_change, current_time, category
                    )
                    
                    available_slots = self.max_positions - len(self.active_trades)
                    for symbol, follow_pct, price, signal_score, atr in targets[:available_slots]:
                        self.open_trade(
                            symbol, category, current_time, price,
                            leader, trigger_change, signal_score, atr
                        )
            
            # 检查持仓的止盈止损
            for symbol in list(self.active_trades.keys()):
                trade = self.active_trades[symbol]
                
                if symbol not in all_data_flat:
                    continue
                
                df = all_data_flat[symbol]
                mask = df.index <= current_time
                if not mask.any():
                    continue
                
                current_price = df.loc[mask].iloc[-1]['close']
                
                should_exit, reason = self.check_exit_conditions(
                    trade, current_price, current_time
                )
                
                if should_exit:
                    self.close_trade(symbol, current_time, current_price, reason)
            
            # 更新权益曲线
            if i % 10 == 0:
                self.update_equity(current_time, all_data_flat)
        
        # 强制平仓所有持仓
        for symbol in list(self.active_trades.keys()):
            if symbol in all_data_flat:
                df = all_data_flat[symbol]
                if not df.empty:
                    self.close_trade(
                        symbol, 
                        df.index[-1], 
                        df.iloc[-1]['close'],
                        "分段结束强制平仓"
                    )
        
        return True
    
    def _calculate_results(
        self, 
        start_date: datetime, 
        end_date: datetime
    ) -> BacktestResultV2:
        """计算回测结果 V2"""
        
        winning_trades = [t for t in self.trades if t.profit_loss > 0]
        losing_trades = [t for t in self.trades if t.profit_loss <= 0]
        
        total_pnl = sum(t.profit_loss for t in self.trades)
        
        # 计算胜率
        win_rate = len(winning_trades) / len(self.trades) * 100 if self.trades else 0
        
        # 计算平均持仓时间
        holding_times = []
        for t in self.trades:
            if t.exit_time and t.entry_time:
                hours = (t.exit_time - t.entry_time).total_seconds() / 3600
                holding_times.append(hours)
        avg_holding_time = np.mean(holding_times) if holding_times else 0
        
        # 计算最大回撤百分比
        max_dd_pct = (self.max_drawdown / self.max_balance * 100) if self.max_balance > 0 else 0
        
        # 计算夏普比率
        sharpe = 0
        if self.equity_curve:
            returns = []
            for i in range(1, len(self.equity_curve)):
                prev_eq = self.equity_curve[i-1][1]
                curr_eq = self.equity_curve[i][1]
                if prev_eq > 0:
                    returns.append((curr_eq - prev_eq) / prev_eq)
            
            if returns:
                avg_return = np.mean(returns)
                std_return = np.std(returns)
                sharpe = (avg_return / std_return * np.sqrt(252)) if std_return > 0 else 0
        
        # 计算盈亏比 (Profit Factor)
        total_wins = sum(t.profit_loss for t in winning_trades) if winning_trades else 0
        total_losses = abs(sum(t.profit_loss for t in losing_trades)) if losing_trades else 1
        profit_factor = total_wins / total_losses if total_losses > 0 else 0
        
        # 计算平均盈利和平均亏损
        avg_win = np.mean([t.profit_loss for t in winning_trades]) if winning_trades else 0
        avg_loss = np.mean([t.profit_loss for t in losing_trades]) if losing_trades else 0
        
        # 计算止损统计
        stop_loss_stats = self._calculate_stop_loss_stats()
        
        # 计算评分统计
        signal_score_stats = self._calculate_signal_score_stats()
        
        result = BacktestResultV2(
            start_date=start_date,
            end_date=end_date,
            initial_balance=self.initial_balance,
            final_balance=self.balance,
            total_trades=len(self.trades),
            winning_trades=len(winning_trades),
            losing_trades=len(losing_trades),
            total_profit_loss=total_pnl,
            win_rate=win_rate,
            max_drawdown=self.max_drawdown,
            max_drawdown_pct=max_dd_pct,
            sharpe_ratio=sharpe,
            profit_factor=profit_factor,
            avg_profit_per_trade=total_pnl / len(self.trades) if self.trades else 0,
            avg_holding_time=avg_holding_time,
            avg_win=avg_win,
            avg_loss=avg_loss,
            leverage=self.leverage if self.futures_mode else 1,
            liquidations=self.liquidations,
            trades=self.trades,
            equity_curve=self.equity_curve,
            stop_loss_stats=stop_loss_stats,
            signal_score_stats=signal_score_stats,
            category_performance=self.category_loss_filter.get_performance_summary() if self.category_filter_enabled and self.category_loss_filter else None
        )
        
        return result
    
    def _calculate_stop_loss_stats(self) -> StopLossStats:
        """计算止损统计"""
        stats = StopLossStats()
        
        # 统计各类型止损
        stops_by_type = {}
        loss_by_type = {}
        breakeven_trades = []
        
        for trade in self.trades:
            # 检查是否是止损退出
            if '止损' in trade.exit_reason:
                stats.total_stops += 1
                sl_type = trade.stop_loss_type if trade.stop_loss_type else 'fixed'
                
                if sl_type not in stops_by_type:
                    stops_by_type[sl_type] = 0
                    loss_by_type[sl_type] = []
                
                stops_by_type[sl_type] += 1
                loss_by_type[sl_type].append(trade.profit_loss)
            
            # 统计保本激活的交易
            if trade.early_breakeven_activated:
                breakeven_trades.append(trade)
        
        stats.stops_by_type = stops_by_type
        
        # 计算各类型平均亏损
        for sl_type, losses in loss_by_type.items():
            if losses:
                stats.avg_loss_by_type[sl_type] = np.mean(losses)
        
        # 计算保本激活后胜率
        if breakeven_trades:
            be_wins = sum(1 for t in breakeven_trades if t.profit_loss > 0)
            stats.breakeven_win_rate = be_wins / len(breakeven_trades) * 100
        
        # 计算止损效率 (止损次数 / 总亏损交易)
        losing_trades = [t for t in self.trades if t.profit_loss <= 0]
        if losing_trades:
            stats.efficiency = stats.total_stops / len(losing_trades) * 100
        
        return stats

    def _calculate_signal_score_stats(self) -> SignalScoreStats:
        """计算信号评分统计"""
        stats = SignalScoreStats()
        
        if not self.trades:
            return stats
        
        stats.total_trades = len(self.trades)
        
        # 定义评分区间
        score_ranges = {
            '0-40': (0, 40),
            '40-60': (40, 60),
            '60-80': (60, 80),
            '80-100': (80, 100)
        }
        
        # 按评分区间统计
        for range_name, (low, high) in score_ranges.items():
            trades_in_range = [t for t in self.trades if low <= t.signal_score < high]
            if range_name == '80-100':  # 包含100
                trades_in_range = [t for t in self.trades if low <= t.signal_score <= high]
            
            stats.trades_by_score_range[range_name] = len(trades_in_range)
            
            if trades_in_range:
                wins = sum(1 for t in trades_in_range if t.profit_loss > 0)
                stats.win_rate_by_score_range[range_name] = wins / len(trades_in_range) * 100
                stats.avg_profit_by_score_range[range_name] = np.mean([t.profit_loss for t in trades_in_range])
            else:
                stats.win_rate_by_score_range[range_name] = 0.0
                stats.avg_profit_by_score_range[range_name] = 0.0
        
        # 计算评分与结果相关性
        if len(self.trades) >= 3:
            scores = [t.signal_score for t in self.trades]
            profits = [t.profit_loss for t in self.trades]
            
            # 使用 numpy 计算相关系数
            if np.std(scores) > 0 and np.std(profits) > 0:
                correlation = np.corrcoef(scores, profits)[0, 1]
                stats.score_outcome_correlation = correlation if not np.isnan(correlation) else 0.0
        
        return stats


def print_backtest_report_v2(result: BacktestResultV2):
    """打印回测报告 V2 - 永续合约版"""
    
    mode_str = "永续合约" if result.leverage > 1 else "现货"
    print(f"\n{'='*60}")
    print(f"📊 回测报告 V2 ({mode_str})")
    print(f"{'='*60}")
    
    print(f"\n📅 回测周期:")
    print(f"   开始: {result.start_date}")
    print(f"   结束: {result.end_date}")
    
    print(f"\n💰 资金情况:")
    print(f"   初始资金: {result.initial_balance:,.2f} USDT")
    print(f"   最终资金: {result.final_balance:,.2f} USDT")
    print(f"   总盈亏: {result.total_profit_loss:+,.2f} USDT")
    roi = (result.final_balance - result.initial_balance) / result.initial_balance * 100
    print(f"   收益率: {roi:+.2f}%")
    if result.leverage > 1:
        print(f"   杠杆倍数: {result.leverage}x")
    
    print(f"\n📈 交易统计:")
    print(f"   总交易次数: {result.total_trades}")
    print(f"   盈利交易: {result.winning_trades}")
    print(f"   亏损交易: {result.losing_trades}")
    if result.liquidations > 0:
        print(f"   强平次数: {result.liquidations}")
    print(f"   胜率: {result.win_rate:.1f}%")
    print(f"   盈亏比: {result.profit_factor:.2f}")
    print(f"   平均每笔盈亏: {result.avg_profit_per_trade:+.2f} USDT")
    print(f"   平均盈利: {result.avg_win:+.2f} USDT")
    print(f"   平均亏损: {result.avg_loss:+.2f} USDT")
    print(f"   平均持仓时间: {result.avg_holding_time:.1f} 小时")
    
    print(f"\n⚠️ 风险指标:")
    print(f"   最大回撤: {result.max_drawdown:,.2f} USDT ({result.max_drawdown_pct:.2f}%)")
    print(f"   夏普比率: {result.sharpe_ratio:.2f}")
    
    # 按退出原因统计 (增强版 - 区分止损类型)
    if result.trades:
        exit_reasons = {}
        stop_loss_stats = {
            'dynamic': {'count': 0, 'pnl': 0},
            'signal': {'count': 0, 'pnl': 0},
            'breakeven': {'count': 0, 'pnl': 0},
            'trailing': {'count': 0, 'pnl': 0},
            'time_decay': {'count': 0, 'pnl': 0},
            'fixed': {'count': 0, 'pnl': 0}
        }
        breakeven_trades = []
        
        for trade in result.trades:
            reason = trade.exit_reason.split(' ')[0]  # 取主要原因
            if reason not in exit_reasons:
                exit_reasons[reason] = {'count': 0, 'pnl': 0}
            exit_reasons[reason]['count'] += 1
            exit_reasons[reason]['pnl'] += trade.profit_loss
            
            # 统计止损类型
            if '止损' in trade.exit_reason:
                sl_type = trade.stop_loss_type if trade.stop_loss_type else 'fixed'
                if sl_type in stop_loss_stats:
                    stop_loss_stats[sl_type]['count'] += 1
                    stop_loss_stats[sl_type]['pnl'] += trade.profit_loss
            
            # 统计保本激活后的交易
            if trade.early_breakeven_activated:
                breakeven_trades.append(trade)
        
        print(f"\n📋 退出原因统计:")
        for reason, stats in sorted(exit_reasons.items(), key=lambda x: x[1]['count'], reverse=True):
            avg_pnl = stats['pnl'] / stats['count'] if stats['count'] > 0 else 0
            print(f"   {reason}: {stats['count']}笔, 盈亏: {stats['pnl']:+.2f} USDT, 平均: {avg_pnl:+.2f}")
        
        # 止损类型详细统计
        total_stops = sum(s['count'] for s in stop_loss_stats.values())
        if total_stops > 0:
            print(f"\n🛡️ 止损类型统计:")
            for sl_type, stats in stop_loss_stats.items():
                if stats['count'] > 0:
                    avg_loss = stats['pnl'] / stats['count']
                    type_name = {
                        'dynamic': '动态ATR',
                        'signal': '信号评分',
                        'breakeven': '保本止损',
                        'trailing': '移动止损',
                        'time_decay': '时间衰减',
                        'fixed': '固定止损'
                    }.get(sl_type, sl_type)
                    print(f"   {type_name}: {stats['count']}笔, 平均亏损: {avg_loss:+.2f} USDT")
        
        # 保本激活后胜率
        if breakeven_trades:
            be_wins = sum(1 for t in breakeven_trades if t.profit_loss > 0)
            be_win_rate = be_wins / len(breakeven_trades) * 100
            print(f"\n📈 保本止损效果:")
            print(f"   保本激活次数: {len(breakeven_trades)}")
            print(f"   激活后胜率: {be_win_rate:.1f}%")
    
    # 打印最近10笔交易
    if result.trades:
        leverage_str = f"({result.leverage}x)" if result.leverage > 1 else ""
        print(f"\n📋 最近交易记录 {leverage_str} (最多10笔):")
        print(f"   {'币种':<12} {'入场价':<12} {'出场价':<12} {'盈亏%':<10} {'评分':<6} {'止损类型':<8} {'原因'}")
        print(f"   {'-'*85}")
        for trade in result.trades[-10:]:
            exit_price = trade.exit_price or 0
            sl_type = trade.stop_loss_type[:6] if trade.stop_loss_type else '-'
            print(f"   {trade.symbol:<12} {trade.entry_price:<12.4f} {exit_price:<12.4f} {trade.profit_loss_pct:+8.2f}%  {trade.signal_score:>4.0f}  {sl_type:<8} {trade.exit_reason}")
    
    # 打印评分统计
    if result.signal_score_stats and result.signal_score_stats.total_trades > 0:
        stats = result.signal_score_stats
        print(f"\n📊 信号评分统计:")
        print(f"   {'评分区间':<12} {'交易数':<8} {'胜率':<10} {'平均盈亏'}")
        print(f"   {'-'*50}")
        
        for range_name in ['0-40', '40-60', '60-80', '80-100']:
            trades = stats.trades_by_score_range.get(range_name, 0)
            win_rate = stats.win_rate_by_score_range.get(range_name, 0)
            avg_profit = stats.avg_profit_by_score_range.get(range_name, 0)
            print(f"   {range_name:<12} {trades:<8} {win_rate:>6.1f}%    {avg_profit:+.2f} USDT")
        
        if stats.score_outcome_correlation != 0:
            corr_desc = "正相关" if stats.score_outcome_correlation > 0 else "负相关"
            print(f"\n   评分与盈亏相关性: {stats.score_outcome_correlation:+.3f} ({corr_desc})")
    
    # V7: 打印分类表现统计
    if result.category_performance:
        print(f"\n📊 分类表现统计 (V7):")
        print(f"   {'分类':<15} {'交易数':>8} {'胜率':>8} {'累计盈亏':>12} {'状态':<15} {'标志'}")
        print(f"   {'-'*75}")
        
        for item in result.category_performance:
            flags_str = ", ".join(item["flags"]) if item["flags"] else "-"
            print(
                f"   {item['category']:<15} "
                f"{item['total_trades']:>8} "
                f"{item['win_rate']:>7.1f}% "
                f"{item['cumulative_pnl']:>+11.2f} "
                f"{item['status']:<15} "
                f"{flags_str}"
            )
        
        # 汇总
        total_trades = sum(item["total_trades"] for item in result.category_performance)
        total_pnl = sum(item["cumulative_pnl"] for item in result.category_performance)
        blacklisted = sum(1 for item in result.category_performance if item["status"] == "blacklisted")
        weight_reduced = sum(1 for item in result.category_performance if item["status"] == "weight_reduced")
        suspended = sum(1 for item in result.category_performance if item["status"] == "suspended")
        
        print(f"   {'-'*75}")
        print(f"   总交易数: {total_trades}, 总盈亏: {total_pnl:+.2f} USDT")
        if blacklisted > 0 or weight_reduced > 0 or suspended > 0:
            print(f"   黑名单: {blacklisted}, 降权: {weight_reduced}, 暂停: {suspended}")
    
    print(f"\n{'='*60}")
