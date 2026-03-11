"""
增强版交易器 V2 - 同步回测优化逻辑 (V6高收益版)
包含:
1. 信号评分系统 (最低50分 - V6优化)
2. 动态止损/保本止损/移动止损 (1.5%/2.5% - V6优化)
3. 时间止损 (1.5小时/8小时 - V6优化)
4. 板块轮动权重
5. 黑名单过滤 (5次触发/8h时长 - V6优化)
6. 杠杆交易支持 (15x)
7. V6高收益参数: 止损4%, 止盈8%
8. 实盘交易支持 - 完整的币安API集成和安全检查

安全特性:
- API密钥验证
- 余额检查
- 订单确认
- 交易限额保护
- 错误处理和重试机制
"""
import requests
import urllib3
import logging
import time

import uuid
import random
import numpy as np
import pandas as pd
from typing import Dict, Optional, List, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from enum import Enum

from config import (
    API_BASE_URL, MONITOR_CONFIG, EXCHANGE,
    BINANCE_FUTURES_API_URL,
    VERIFY_SSL, PROXY_ENABLED, PROXY_URL, REQUEST_TIMEOUT,
    CRYPTO_CATEGORIES,
    CATEGORY_BLACKLIST, SYMBOL_BLACKLIST, CATEGORY_WEIGHT_ADJUSTMENTS,
    CATEGORY_STOP_LOSS, ROTATION_CONFIG,
    V2_TAKE_PROFIT, V2_STOP_LOSS, V2_TRAILING_STOP_PCT, V2_TRAILING_STOP_ACTIVATION,
    V2_MAX_POSITIONS, V2_BASE_TRADE_AMOUNT, V2_MAX_TRADE_AMOUNT,
    LEVERAGE, SIGNAL_MIN_SCORE, SIGNAL_CALIBRATOR_CONFIG,
    STOP_LOSS_CONFIG, SIGNAL_SCORE_CONFIG,
    SHORT_TIME_STOP_ENABLED, SHORT_TIME_STOP_HOURS, SHORT_TIME_STOP_MIN_PROFIT,
    LONG_TIME_STOP_ENABLED, LONG_TIME_STOP_HOURS, LONG_TIME_STOP_MIN_PROFIT,
    BLACKLIST_CONSECUTIVE_LOSSES, BLACKLIST_DURATION_HOURS,
    BLACKLIST_EARLY_RELEASE_ENABLED, BLACKLIST_EARLY_RELEASE_WINS,
    PERIODIC_RESET_ENABLED, PERIODIC_RESET_INTERVAL_DAYS,
    TRADE_MODE, BINANCE_API_KEY, BINANCE_SECRET_KEY,
    SAFE_MODE_ON_EXTERNAL_POSITIONS, MANAGE_EXTERNAL_POSITIONS,
    MAX_SINGLE_TRADE_AMOUNT, MAX_DAILY_TRADE_AMOUNT,
    PARTIAL_TP_ENABLED, PARTIAL_TP_LEVELS, PARTIAL_TP_RATIOS,
    MAX_DRAWDOWN_THRESHOLD, MAX_DRAWDOWN_ACTION, MAX_DRAWDOWN_SEVERE_THRESHOLD,
    MAX_DAILY_LOSS, MAX_DAILY_LOSS_ACTION, MAX_DAILY_LOSS_SEVERE
)

# 回测侧的策略优化组件（用于尽可能复刻高收益回测行为）
from market_regime_detector import MarketRegimeDetector, MarketRegimeType
from stop_loss_controller import StopLossController
from signal_calibrator import SignalCalibrator
from sector_weight_manager import SectorWeightManager
from strategy_optimizer import StrategyOptimizer

# 导入币安API客户端（如果可用）
try:
    from binance_api import BinanceAPIClient, BinanceAPIError
    BINANCE_API_AVAILABLE = True
except ImportError:
    BINANCE_API_AVAILABLE = False
    BinanceAPIClient = None
    BinanceAPIError = Exception


class StopLossType(Enum):
    """止损类型"""
    FIXED = "fixed"
    DYNAMIC = "dynamic"
    SIGNAL = "signal"
    BREAKEVEN = "breakeven"
    TRAILING = "trailing"
    TIME_2H = "time_2h"
    TIME_24H = "time_24h"


@dataclass
class TradePosition:
    """交易持仓"""
    symbol: str
    category: str
    entry_price: float
    quantity: float
    margin: float  # 保证金
    position_value: float  # 仓位价值
    leverage: int
    entry_time: datetime
    order_id: str
    
    # 止损相关
    initial_stop_loss_pct: float = 0.0
    current_stop_loss_pct: float = 0.0
    stop_loss_type: str = ""
    
    # 移动止损
    trailing_stop: float = 0.0
    highest_price: float = 0.0
    trailing_activated: bool = False
    
    # 保本止损
    breakeven_stop: float = 0.0
    breakeven_activated: bool = False
    
    # 信号评分
    signal_score: float = 0.0
    
    # 当前状态
    current_price: float = 0.0
    unrealized_pnl: float = 0.0
    unrealized_pnl_pct: float = 0.0
    
    # 平仓信息
    exit_price: float = 0.0
    exit_time: Optional[datetime] = None
    exit_reason: str = ""
    realized_pnl: float = 0.0
    status: str = "open"
    # 外部持仓标记：交易所已有但不是本程序创建（或程序重启后恢复）
    is_external: bool = False
    
    # 分批止盈相关
    initial_quantity: float = 0.0  # 初始数量（用于分批止盈计算）
    initial_margin: float = 0.0  # 初始保证金（用于分批止盈计算）
    tp_level: int = 0  # 已触发的止盈级别（0=未触发，1=第一级，2=第二级，3=第三级）


@dataclass 
class TradeResult:
    """交易结果"""
    symbol: str
    entry_price: float
    exit_price: float
    quantity: float
    margin: float
    leverage: int
    pnl: float
    pnl_pct: float
    exit_reason: str
    holding_hours: float
    signal_score: float


# P0优化：使用统一信号评分器（与回测一致）
try:
    from unified_signal_scorer import UnifiedSignalScorer, ScoreBreakdown
    UNIFIED_SCORER_AVAILABLE = True
except ImportError:
    UNIFIED_SCORER_AVAILABLE = False
    logging.warning("统一信号评分器不可用，使用简化版")

class SignalScorerLive:
    """实时信号评分器 - P0优化：使用统一评分器确保与回测一致"""
    
    def __init__(self):
        self.config = SIGNAL_SCORE_CONFIG
        self.min_score = SIGNAL_MIN_SCORE
        
        # P0优化：优先使用统一评分器
        if UNIFIED_SCORER_AVAILABLE:
            self.unified_scorer = UnifiedSignalScorer(self.config)
            self.use_unified = True
        else:
            self.use_unified = False
            logging.warning("统一评分器不可用，使用简化版评分逻辑")
    
    def calculate_score(
        self,
        df: pd.DataFrame,
        trigger_change: float = 0.0,
        coin_change: float = 0.0,
        category: str = "",
        trigger_df: pd.DataFrame = None,
        sector_tier = None
    ) -> Tuple[float, Dict]:
        """
        计算信号评分
        
        P0优化：使用统一评分器确保与回测一致
        """
        # 使用统一评分器
        if self.use_unified:
            try:
                score, breakdown = self.unified_scorer.calculate_score(
                    df=df,
                    idx=None,  # 实盘使用最后一条数据
                    trigger_change=trigger_change,
                    coin_change=coin_change,
                    trigger_df=trigger_df,
                    category=category,
                    sector_tier=sector_tier
                )
                # 转换为Dict格式（兼容旧接口）
                details = {
                    'trend': breakdown.trend_score,
                    'volume': breakdown.volume_score,
                    'momentum': breakdown.momentum_score,
                    'volatility': breakdown.volatility_score,
                    'correlation': breakdown.correlation_score,
                    'final_score': breakdown.final_score,
                    **breakdown.trend_details,
                    **breakdown.volume_details,
                    **breakdown.momentum_details,
                    **breakdown.volatility_details,
                    **breakdown.correlation_details
                }
                return score, details
            except Exception as e:
                logging.warning(f"统一评分器计算失败，回退到简化版: {e}")
                # 回退到简化版
                return self._calculate_score_simple(df, trigger_change, coin_change, category)
        else:
            # 回退到简化版
            return self._calculate_score_simple(df, trigger_change, coin_change, category)
    
    def _calculate_score_simple(
        self,
        df: pd.DataFrame,
        trigger_change: float,
        coin_change: float,
        category: str
    ) -> Tuple[float, Dict]:
        """简化版评分（兼容旧逻辑）"""
        score = 50.0  # 基础分
        details = {}
        
        try:
            if df is None or len(df) < 20:
                return score, details
            
            # 1. 趋势评分 (0-30)
            trend_score = self._calc_trend_score(df)
            score += trend_score
            details['trend'] = trend_score
            
            # 2. 成交量评分 (0-25)
            volume_score = self._calc_volume_score(df)
            score += volume_score
            details['volume'] = volume_score
            
            # 3. 动量评分 (0-25)
            momentum_score = self._calc_momentum_score(df, trigger_change, coin_change)
            score += momentum_score
            details['momentum'] = momentum_score
            
            # 4. 分类权重加成
            weight = CATEGORY_WEIGHT_ADJUSTMENTS.get(category, 1.0)
            if weight > 1.0:
                bonus = (weight - 1.0) * 20  # 最多+10分
                score += bonus
                details['category_bonus'] = bonus
            
            score = max(0, min(100, score))
            
        except Exception as e:
            details['error'] = str(e)
        
        return score, details
    
    def _calc_trend_score(self, df: pd.DataFrame) -> float:
        """趋势评分"""
        try:
            close = df['close'].values
            ma5 = np.mean(close[-5:])
            ma10 = np.mean(close[-10:])
            ma20 = np.mean(close[-20:])
            current = close[-1]
            
            score = 0
            if current > ma5:
                score += 10
            if ma5 > ma10:
                score += 10
            if ma10 > ma20:
                score += 10
            
            return score
        except:
            return 0
    
    def _calc_volume_score(self, df: pd.DataFrame) -> float:
        """成交量评分"""
        try:
            vol = df['volume'].values
            current_vol = vol[-1]
            avg_vol = np.mean(vol[-20:])
            
            if avg_vol <= 0:
                return 0
            
            vol_ratio = current_vol / avg_vol
            
            if vol_ratio > 2.0:
                return 25
            elif vol_ratio > 1.5:
                return 20
            elif vol_ratio > 1.0:
                return 10
            else:
                return 0
        except:
            return 0
    
    def _calc_momentum_score(self, df: pd.DataFrame, trigger_change: float, coin_change: float) -> float:
        """动量评分"""
        try:
            score = 0
            
            # 触发币涨幅越大，分数越高
            if trigger_change > 5:
                score += 15
            elif trigger_change > 3:
                score += 10
            
            # 跟涨币涨幅适中更好 (有上涨空间)
            if 0 < coin_change < trigger_change * 0.5:
                score += 10
            elif coin_change < 0:
                score += 5  # 还没涨，有机会
            
            return score
        except:
            return 0


class StopLossManagerLive:
    """实时止损管理器"""
    
    def __init__(self):
        self.config = STOP_LOSS_CONFIG
    
    def calculate_initial_stop_loss(self, signal_score: float) -> Tuple[float, str]:
        """计算初始止损"""
        if signal_score >= 80:
            return self.config.get('high_score_sl', 12.0), StopLossType.SIGNAL.value
        elif signal_score >= 60:
            return self.config.get('medium_score_sl', 10.0), StopLossType.SIGNAL.value
        else:
            return self.config.get('low_score_sl', 8.0), StopLossType.SIGNAL.value
    
    def check_breakeven(self, position: TradePosition, current_price: float) -> bool:
        """检查是否激活保本止损"""
        if position.breakeven_activated:
            return False
        
        threshold = self.config.get('early_breakeven_threshold', 5.0)
        buffer = self.config.get('early_breakeven_buffer', 0.5)
        
        price_change_pct = ((current_price - position.entry_price) / position.entry_price) * 100
        leveraged_pnl = price_change_pct * position.leverage
        
        if leveraged_pnl >= threshold:
            position.breakeven_activated = True
            position.breakeven_stop = position.entry_price * (1 + buffer / 100)
            return True
        
        return False
    
    def update_trailing_stop(self, position: TradePosition, current_price: float) -> bool:
        """更新移动止损"""
        activation_pct = V2_TRAILING_STOP_ACTIVATION
        trailing_pct = V2_TRAILING_STOP_PCT
        
        price_change_pct = ((current_price - position.entry_price) / position.entry_price) * 100
        leveraged_pnl = price_change_pct * position.leverage
        
        # 激活移动止损
        if not position.trailing_activated and leveraged_pnl >= activation_pct:
            position.trailing_activated = True
            position.highest_price = current_price
        
        # 更新最高价和移动止损
        if position.trailing_activated:
            if current_price > position.highest_price:
                position.highest_price = current_price
            
            # 移动止损价 = 最高价 * (1 - 回撤%)
            new_trailing = position.highest_price * (1 - trailing_pct / 100 / position.leverage)
            if new_trailing > position.trailing_stop:
                position.trailing_stop = new_trailing
                return True
        
        return False


class TraderV2:
    """增强版交易器 V2 - 支持虚拟和实盘交易"""
    
    def __init__(self, initial_balance: float = 20000):
        # ========== 交易模式配置 ==========
        self.trade_mode = TRADE_MODE.lower()  # 'virtual' or 'real'
        self.is_real_trading = self.trade_mode == 'real'
        
        # 实盘交易安全检查
        if self.is_real_trading:
            if not BINANCE_API_AVAILABLE:
                raise RuntimeError("实盘交易模式需要binance_api模块，但导入失败")
            if not BINANCE_API_KEY or not BINANCE_SECRET_KEY:
                raise RuntimeError("实盘交易模式需要配置BINANCE_API_KEY和BINANCE_SECRET_KEY")
            if BINANCE_API_KEY == 'your_binance_api_key_here':
                raise RuntimeError("请先在config.env中配置真实的API密钥！")
        
        # 资金管理
        self.virtual_balance = initial_balance
        self.initial_balance = initial_balance
        self.positions: Dict[str, TradePosition] = {}
        self.trade_history: List[TradeResult] = []
        self.total_pnl = 0.0
        self._max_equity = float(initial_balance)  # 用于回撤估算（虚拟模式）
        
        # 优化：K线数据缓存（TTL=30秒）
        self._klines_cache: Dict[Tuple[str, str], Tuple[pd.DataFrame, float]] = {}
        self._klines_cache_ttl = 30.0  # 30秒缓存
        
        # 优化：信号评分缓存（TTL=60秒）
        self._signal_score_cache: Dict[Tuple[str, float, float, str], Tuple[float, Dict, float]] = {}
        self._signal_score_cache_ttl = 60.0  # 60秒缓存
        
        # 组件
        self.signal_scorer = SignalScorerLive()
        self.stop_loss_manager = StopLossManagerLive()

        # ========== 回测优势：市场状态/信号校准/动态止损/仓位门控 ==========
        self.regime_detector = MarketRegimeDetector()
        self.dynamic_stop_loss_controller = StopLossController()
        # 信号校准器：用于开仓前二次门控（可配置，便于“暴跌后反弹”等场景调参增开仓）
        try:
            cfg = SIGNAL_CALIBRATOR_CONFIG or {}
            self.signal_calibrator = SignalCalibrator(
                volume_bonus_threshold=float(cfg.get("volume_bonus_threshold", 1.5)),
                volume_bonus_points=float(cfg.get("volume_bonus_points", 10)),
                volatility_penalty_threshold=float(cfg.get("volatility_penalty_threshold", 2.0)),
                volatility_penalty_points=float(cfg.get("volatility_penalty_points", 15)),
                bullish_bonus_points=float(cfg.get("bullish_bonus_points", 10)),
                bearish_penalty_points=float(cfg.get("bearish_penalty_points", 10)),
                normal_min_score=float(cfg.get("normal_min_score", 70)),
                bearish_min_score=float(cfg.get("bearish_min_score", 80)),
            )
        except Exception:
            self.signal_calibrator = SignalCalibrator()
        self.sector_weight_manager = SectorWeightManager()  # 仅用于 StrategyOptimizer 依赖（可后续扩展到实盘）
        self.strategy_optimizer = StrategyOptimizer(
            self.regime_detector,
            self.dynamic_stop_loss_controller,
            self.sector_weight_manager,
            self.signal_calibrator
        )
        self._current_market_regime: MarketRegimeType = MarketRegimeType.SIDEWAYS

        # ========== 回测优势：板块轮动权重（由 LiveTraderV3 注入） ==========
        self._rotation_weight_multiplier: Dict[str, float] = {}  # category -> multiplier (1.0=等权)
        self._rotation_tier: Dict[str, str] = {}  # category -> hot/warm/neutral/cold
    
    def _get_sector_tier(self, category: str):
        """获取板块层级（用于Hot板块加成）- P0优化"""
        try:
            if hasattr(self, '_rotation_tier') and self._rotation_tier:
                tier_str = (self._rotation_tier.get(category) or "").lower()
                if tier_str == "hot":
                    try:
                        from rotation_models import SectorTier
                        return SectorTier.HOT
                    except ImportError:
                        return None
                elif tier_str == "warm":
                    try:
                        from rotation_models import SectorTier
                        return SectorTier.WARM
                    except ImportError:
                        return None
                elif tier_str == "cold":
                    try:
                        from rotation_models import SectorTier
                        return SectorTier.COLD
                    except ImportError:
                        return None
        except Exception:
            pass
        return None
        
        # 实盘API客户端
        self.binance_api = None
        if self.is_real_trading and BINANCE_API_AVAILABLE:
            try:
                self.binance_api = BinanceAPIClient()
                # 验证连接
                connected, msg = self.binance_api.check_api_connection()
                if not connected:
                    raise RuntimeError(f"币安API连接失败: {msg}")
                logging.info(f"✅ 币安API连接成功")
            except Exception as e:
                logging.error(f"❌ 币安API初始化失败: {e}")
                raise
        
        # 配置
        self.leverage = LEVERAGE
        self.take_profit = V2_TAKE_PROFIT
        self.stop_loss = V2_STOP_LOSS
        self.max_positions = V2_MAX_POSITIONS
        self.base_trade_amount = V2_BASE_TRADE_AMOUNT
        self.max_trade_amount = V2_MAX_TRADE_AMOUNT
        self.min_signal_score = SIGNAL_MIN_SCORE
        
        # 交易限额保护
        self.max_single_trade_amount = float(MAX_SINGLE_TRADE_AMOUNT)  # 单笔最大交易金额
        self.max_daily_trade_amount = float(MAX_DAILY_TRADE_AMOUNT)    # 单日最大交易金额
        self.daily_trade_amount = 0.0  # 今日已交易金额
        self.last_reset_date = datetime.now().date()

        # 外部持仓处理策略
        self.safe_mode_on_external_positions = bool(SAFE_MODE_ON_EXTERNAL_POSITIONS)
        self.manage_external_positions = bool(MANAGE_EXTERNAL_POSITIONS)
        
        # 黑名单
        self.category_blacklist = set(CATEGORY_BLACKLIST)
        self.symbol_blacklist = set(SYMBOL_BLACKLIST)
        
        # 动态黑名单 (连续亏损) - V6优化
        self.dynamic_blacklist: Dict[str, datetime] = {}
        self.category_loss_count: Dict[str, int] = {}
        self.category_win_count: Dict[str, int] = {}  # V6: 连续盈利计数
        self.blacklist_consecutive_losses = BLACKLIST_CONSECUTIVE_LOSSES  # V6: 5次
        self.blacklist_duration_hours = BLACKLIST_DURATION_HOURS          # V6: 8小时
        self.blacklist_early_release_enabled = BLACKLIST_EARLY_RELEASE_ENABLED  # V6: 启用
        self.blacklist_early_release_wins = BLACKLIST_EARLY_RELEASE_WINS  # V6: 2次盈利解除
        
        # ========== V7: 定期重置机制 (模拟独立季度模式) ==========
        self.periodic_reset_enabled = PERIODIC_RESET_ENABLED  # 从配置文件读取
        self.reset_interval_days = PERIODIC_RESET_INTERVAL_DAYS  # 从配置文件读取
        self.last_reset_time = datetime.now()  # 上次重置时间
        self.period_pnl = 0.0  # 当前周期盈亏
        self.period_trades = 0  # 当前周期交易数
        self.period_history: List[Dict] = []  # 历史周期记录
        
        # ========== P0优化：风险控制跟踪 ==========
        # 最大回撤跟踪
        self.max_drawdown_threshold = MAX_DRAWDOWN_THRESHOLD
        self.max_drawdown_action = MAX_DRAWDOWN_ACTION
        self.max_drawdown_severe_threshold = MAX_DRAWDOWN_SEVERE_THRESHOLD
        self._trading_paused_drawdown = False  # 是否因回撤暂停交易
        self._trading_stopped_drawdown = False  # 是否因回撤完全停止
        
        # 单日亏损跟踪
        self.max_daily_loss = MAX_DAILY_LOSS
        self.max_daily_loss_action = MAX_DAILY_LOSS_ACTION
        self.max_daily_loss_severe = MAX_DAILY_LOSS_SEVERE
        self.daily_pnl = 0.0  # 今日盈亏
        self.daily_pnl_reset_date = datetime.now().date()  # 上次重置日期
        self._trading_paused_daily_loss = False  # 是否因单日亏损暂停交易
        self._trading_stopped_daily_loss = False  # 是否因单日亏损完全停止
        
        # 分批止盈配置
        self.partial_tp_enabled = PARTIAL_TP_ENABLED
        self.partial_tp_levels = PARTIAL_TP_LEVELS  # 例如: [10.0, 20.0, 30.0]
        self.partial_tp_ratios = PARTIAL_TP_RATIOS  # 例如: [0.33, 0.33, 0.34]
        
        # API配置（仅用于价格查询等公开接口）
        self.verify_ssl = bool(VERIFY_SSL)
        self.proxy_enabled = bool(PROXY_ENABLED)
        self.proxy_url = PROXY_URL or ""
        self.request_timeout = int(REQUEST_TIMEOUT) if REQUEST_TIMEOUT else 30

        # 兼容旧逻辑：如果 MONITOR_CONFIG 显式提供了网络配置，则以其为准
        self.verify_ssl = bool(MONITOR_CONFIG.get("verify_ssl", self.verify_ssl))
        self.proxy_enabled = bool(MONITOR_CONFIG.get("proxy_enabled", self.proxy_enabled))
        self.proxy_url = MONITOR_CONFIG.get("proxy_url", self.proxy_url) or ""
        self.request_timeout = int(MONITOR_CONFIG.get("request_timeout", self.request_timeout))

        if not self.verify_ssl:
            # 仅当用户显式关闭 SSL 验证时才禁用告警
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

        self.session = requests.Session()
        if self.proxy_enabled and self.proxy_url:
            self.session.proxies = {
                "http": self.proxy_url,
                "https": self.proxy_url,
            }
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0',
            'Accept': 'application/json'
        })
        
        # 每日限额重置检查
        self._check_daily_reset()
        
        mode_str = "🔴 实盘交易" if self.is_real_trading else "🔵 虚拟交易"
        logging.info("TraderV2 初始化完成 (V6高收益版) - %s", mode_str)
        logging.info("  杠杆: %sx, 止盈: %s%%, 止损: %s%%", self.leverage, self.take_profit, self.stop_loss)
        logging.info("  移动止损: %s%% (激活: %s%%)", V2_TRAILING_STOP_PCT, V2_TRAILING_STOP_ACTIVATION)
        logging.info("  信号阈值: %s, 最大持仓: %s", self.min_signal_score, self.max_positions)
        logging.info("  黑名单: 连续亏损%s次触发, %sh时长", self.blacklist_consecutive_losses, self.blacklist_duration_hours)
        logging.info("  提前解除: %s (连续盈利%s次)", "启用" if self.blacklist_early_release_enabled else "禁用", self.blacklist_early_release_wins)
        logging.info("  定期重置: %s (每%s天)", "启用" if self.periodic_reset_enabled else "禁用", self.reset_interval_days)
        if self.is_real_trading:
            logging.warning("实盘交易模式已启用，请谨慎操作！")

    def _infer_category(self, symbol: str) -> str:
        """根据 CRYPTO_CATEGORIES 反推分类（找不到则返回空字符串）"""
        try:
            sym = str(symbol).upper().replace("_", "")
            for cat, mapping in CRYPTO_CATEGORIES.items():
                lst = mapping.get(EXCHANGE, []) if isinstance(mapping, dict) else []
                if sym in [str(x).upper().replace("_", "") for x in lst]:
                    return cat
        except Exception:
            pass
        return ""

    def sync_positions_from_exchange(self) -> int:
        """
        启动同步：把交易所现有仓位同步到本地（标记为 external）。
        Returns: 外部持仓数量
        """
        if not (self.is_real_trading and self.binance_api):
            return 0
        external_count = 0
        try:
            remote = self.binance_api.get_all_positions()
            remote_symbols = set()
            for pos in remote:
                sym = str(pos.get("symbol") or "").upper()
                if not sym:
                    continue
                remote_symbols.add(sym)

                if sym in self.positions:
                    # 已在本地（认为是程序已管理的仓位）
                    continue

                # 外部仓位：构建最小可用的持仓快照（默认不自动管理，避免误操作）
                amt = float(pos.get("positionAmt", 0) or 0)
                qty = abs(amt)
                entry = float(pos.get("entryPrice", 0) or 0)
                mark = float(pos.get("markPrice", entry) or entry)
                lev = int(float(pos.get("leverage", self.leverage) or self.leverage))
                margin = float(pos.get("isolatedMargin", 0) or pos.get("positionInitialMargin", 0) or 0)
                if margin <= 0 and mark > 0 and lev > 0:
                    margin = (qty * mark) / lev

                self.positions[sym] = TradePosition(
                    symbol=sym,
                    category=self._infer_category(sym),
                    entry_price=entry if entry > 0 else mark,
                    quantity=qty,
                    margin=margin,
                    position_value=qty * mark,
                    leverage=lev,
                    entry_time=datetime.now(),
                    order_id=f"EXTERNAL:{sym}",
                    initial_stop_loss_pct=0.0,
                    current_stop_loss_pct=0.0,
                    stop_loss_type="external",
                    signal_score=0.0,
                    highest_price=entry if entry > 0 else mark,
                    is_external=True,
                )
                external_count += 1

            # 本地存在但交易所不存在：移除“僵尸持仓”
            stale = [s for s in list(self.positions.keys()) if s not in remote_symbols and self.positions[s].is_external]
            for s in stale:
                del self.positions[s]

        except Exception as e:
            logging.error("同步交易所持仓失败: %s", e)
            return 0

        if external_count > 0:
            logging.error("检测到交易所外部持仓 %s 个（非本程序创建或重启遗留）", external_count)
            if not self.manage_external_positions:
                logging.warning("外部持仓默认不自动平仓/止盈止损（MANAGE_EXTERNAL_POSITIONS=false）")
        return external_count

    def reconcile_exchange_positions(self) -> int:
        """
        周期对账：检测外部仓位/手动平仓等变化。
        Returns: 外部仓位数量（当前）
        """
        if not (self.is_real_trading and self.binance_api):
            return 0
        # 复用同步逻辑（会补齐缺失 external，并清理已消失 external）
        return self.sync_positions_from_exchange()

    def set_rotation_context(self, weight_multiplier: Dict[str, float], tier_map: Dict[str, str]) -> None:
        """
        设置板块轮动上下文（由外部采样周期注入）
        - weight_multiplier: 以等权=1.0 为基准的倍数
        - tier_map: 板块层级（hot/warm/neutral/cold）
        """
        if isinstance(weight_multiplier, dict):
            self._rotation_weight_multiplier = weight_multiplier
        if isinstance(tier_map, dict):
            self._rotation_tier = tier_map

    def _get_current_drawdown_pct(self) -> float:
        """估算当前回撤（虚拟模式基于资金曲线；实盘返回0）"""
        if self.is_real_trading:
            return 0.0
        equity = float(self.virtual_balance) + sum(p.margin for p in self.positions.values())
        if equity > self._max_equity:
            self._max_equity = equity
        if self._max_equity <= 0:
            return 0.0
        return max(0.0, (self._max_equity - equity) / self._max_equity * 100.0)

    def _update_market_regime(self) -> None:
        """更新市场状态缓存（使用 BTC K线）"""
        try:
            btc_symbol = "BTCUSDT"  # 目前实盘/回测均以币安合约为主
            btc_df = self.get_klines(btc_symbol)
            if btc_df is None or btc_df.empty or 'close' not in btc_df.columns:
                self._current_market_regime = MarketRegimeType.SIDEWAYS
                return
            # MarketRegimeDetector 需要至少 ma_period(20) 条数据
            btc_close_df = btc_df[['close']].copy()
            result = self.regime_detector.detect_regime(btc_close_df)
            self._current_market_regime = result.regime
        except Exception:
            self._current_market_regime = MarketRegimeType.SIDEWAYS

    def _calc_volume_ratio(self, df: pd.DataFrame, lookback: int = 20) -> float:
        try:
            if df is None or df.empty or 'volume' not in df.columns:
                return 1.0
            vols = pd.to_numeric(df['volume'], errors='coerce').dropna()
            if len(vols) < 2:
                return 1.0
            current = float(vols.iloc[-1])
            avg = float(vols.iloc[-lookback:].mean()) if len(vols) >= 3 else float(vols.mean())
            if avg <= 0:
                return 1.0
            return max(0.1, current / avg)
        except Exception:
            return 1.0

    def _calc_atr_ratio(self, df: pd.DataFrame) -> float:
        """
        计算 ATR 比率（当前ATR / 近期均值ATR），用于信号校准
        """
        try:
            if df is None or df.empty:
                return 1.0
            for col in ['high', 'low', 'close']:
                if col not in df.columns:
                    return 1.0
            high = pd.to_numeric(df['high'], errors='coerce')
            low = pd.to_numeric(df['low'], errors='coerce')
            close = pd.to_numeric(df['close'], errors='coerce')
            prev_close = close.shift(1)
            tr = pd.concat([
                (high - low).abs(),
                (high - prev_close).abs(),
                (low - prev_close).abs(),
            ], axis=1).max(axis=1)
            atr14 = tr.rolling(14).mean().iloc[-1]
            atr50 = tr.rolling(50).mean().iloc[-1] if len(tr) >= 50 else tr.rolling(max(14, len(tr))).mean().iloc[-1]
            if pd.isna(atr14) or pd.isna(atr50) or atr50 <= 0:
                return 1.0
            return max(0.1, float(atr14) / float(atr50))
        except Exception:
            return 1.0
    
    def check_periodic_reset(self) -> bool:
        """
        检查是否需要定期重置 - V7新增
        模拟独立季度模式的优势：定期清空动态黑名单和亏损计数
        
        Returns:
            bool: 是否执行了重置
        """
        if not self.periodic_reset_enabled:
            return False
        
        now = datetime.now()
        days_since_reset = (now - self.last_reset_time).days
        
        if days_since_reset >= self.reset_interval_days:
            self._perform_periodic_reset()
            return True
        
        return False
    
    def _perform_periodic_reset(self):
        """
        执行定期重置 - V7新增
        重置动态黑名单和亏损计数，但保留资金和持仓
        """
        now = datetime.now()
        
        # 记录当前周期统计
        period_record = {
            'start_time': self.last_reset_time,
            'end_time': now,
            'pnl': self.period_pnl,
            'trades': self.period_trades,
            'final_balance': self.virtual_balance,
            'dynamic_blacklist': list(self.dynamic_blacklist.keys())
        }
        self.period_history.append(period_record)
        
        logging.info("=" * 60)
        logging.info("定期重置 - 周期结束")
        logging.info("=" * 60)
        logging.info("  周期: %s ~ %s", self.last_reset_time.strftime('%Y-%m-%d'), now.strftime('%Y-%m-%d'))
        logging.info("  周期盈亏: %+,.2f USDT", self.period_pnl)
        logging.info("  周期交易: %s 次", self.period_trades)
        logging.info("  当前余额(虚拟): %,.2f USDT", self.virtual_balance)
        
        # 重置动态黑名单 (核心优化点!)
        blacklist_count = len(self.dynamic_blacklist)
        self.dynamic_blacklist.clear()
        self.category_loss_count.clear()
        self.category_win_count.clear()
        
        logging.info("  清空动态黑名单: %s 个分类", blacklist_count)
        
        # 重置周期统计
        self.last_reset_time = now
        self.period_pnl = 0.0
        self.period_trades = 0
        
        logging.info("重置完成，开始新周期")
        logging.info("=" * 60)
    
    def set_reset_interval(self, days: int):
        """
        设置重置间隔 - V7新增
        
        Args:
            days: 重置间隔天数 (建议: 7=每周, 30=每月, 90=每季度)
        """
        self.reset_interval_days = days
        logging.info("重置间隔已设置为 %s 天", days)
    
    def enable_periodic_reset(self, enabled: bool = True, interval_days: int = None):
        """
        启用/禁用定期重置 - V7新增
        
        Args:
            enabled: 是否启用
            interval_days: 重置间隔天数
        """
        self.periodic_reset_enabled = enabled
        if interval_days:
            self.reset_interval_days = interval_days
        
        status = "启用" if enabled else "禁用"
        logging.info("定期重置已%s (间隔: %s天)", status, self.reset_interval_days)
    
    def force_reset(self):
        """
        强制执行重置 - V7新增
        用于手动触发重置，例如在月初或季度初
        """
        logging.warning("强制执行定期重置...")
        self._perform_periodic_reset()
    
    def get_period_summary(self) -> Dict:
        """
        获取当前周期摘要 - V7新增
        """
        now = datetime.now()
        days_in_period = (now - self.last_reset_time).days
        days_until_reset = max(0, self.reset_interval_days - days_in_period)
        
        return {
            'period_start': self.last_reset_time,
            'days_in_period': days_in_period,
            'days_until_reset': days_until_reset,
            'period_pnl': self.period_pnl,
            'period_trades': self.period_trades,
            'dynamic_blacklist_count': len(self.dynamic_blacklist),
            'total_periods': len(self.period_history)
        }

    def is_blacklisted(self, symbol: str, category: str) -> Tuple[bool, str]:
        """检查是否在黑名单"""
        # 分类黑名单
        if category in self.category_blacklist:
            return True, f"分类 {category} 在黑名单"
        
        # 交易对黑名单
        if symbol in self.symbol_blacklist:
            return True, f"交易对 {symbol} 在黑名单"
        
        # 动态黑名单 - V5优化: 缩短时间，支持提前解除
        if category in self.dynamic_blacklist:
            blacklist_time = self.dynamic_blacklist[category]
            if datetime.now() - blacklist_time < timedelta(hours=self.blacklist_duration_hours):
                return True, f"分类 {category} 动态黑名单中 (剩余 {self.blacklist_duration_hours - (datetime.now() - blacklist_time).total_seconds() / 3600:.1f}h)"
            else:
                del self.dynamic_blacklist[category]
                self.category_loss_count[category] = 0
                logging.info("分类 %s 已从动态黑名单移除 (时间到期)", category)
        
        return False, ""
    
    def add_to_dynamic_blacklist(self, category: str):
        """添加到动态黑名单 - V5优化"""
        self.category_loss_count[category] = self.category_loss_count.get(category, 0) + 1
        self.category_win_count[category] = 0  # 重置连续盈利计数
        
        if self.category_loss_count[category] >= self.blacklist_consecutive_losses:
            self.dynamic_blacklist[category] = datetime.now()
            logging.info(
                "分类 %s 加入动态黑名单 (连续亏损 %s 次, 时长 %sh)",
                category, self.category_loss_count[category], self.blacklist_duration_hours
            )
    
    def reset_loss_count(self, category: str):
        """重置亏损计数并检查提前解除 - V5优化"""
        self.category_loss_count[category] = 0
        self.category_win_count[category] = self.category_win_count.get(category, 0) + 1
        
        # V5: 提前解除黑名单
        if self.blacklist_early_release_enabled and category in self.dynamic_blacklist:
            if self.category_win_count[category] >= self.blacklist_early_release_wins:
                del self.dynamic_blacklist[category]
                self.category_win_count[category] = 0
                logging.info("分类 %s 提前解除黑名单 (连续盈利 %s 次)", category, self.blacklist_early_release_wins)
    
    def _check_daily_reset(self):
        """检查并重置每日限额和单日亏损"""
        today = datetime.now().date()
        if today != self.daily_pnl_reset_date:
            # 重置单日盈亏
            self.daily_pnl = 0.0
            self.daily_pnl_reset_date = today
            # 重置交易暂停状态（如果是因为单日亏损暂停的）
            if self._trading_paused_daily_loss:
                self._trading_paused_daily_loss = False
                logging.info("✅ 新的一天开始，单日亏损暂停已解除")
        if today != self.last_reset_date:
            self.daily_trade_amount = 0.0
            self.last_reset_date = today
            logging.info(f"📅 每日限额已重置")
    
    def get_current_price(self, symbol: str, max_retries: int = 3, use_klines: bool = True) -> Optional[float]:
        """
        获取当前价格（带重试机制）
        
        Args:
            symbol: 交易对
            max_retries: 最大重试次数
            use_klines: 是否优先使用K线数据的最新收盘价（更准确）
        """
        # 优化：优先使用K线数据的最新收盘价（与K线数据同步）
        if use_klines:
            try:
                df = self.get_klines(symbol, interval='1m', limit=1)
                if df is not None and len(df) > 0:
                    latest_close = float(df['close'].iloc[-1])
                    if latest_close > 0:
                        return latest_close
            except Exception:
                pass  # K线获取失败，回退到ticker
        
        # 重试机制
        for attempt in range(max_retries):
            try:
                # 优先使用币安API（如果可用）
                if self.is_real_trading and self.binance_api:
                    price = self.binance_api.get_ticker_price(symbol)
                    if price and price > 0:
                        return price
                
                # 回退到公开API
                if EXCHANGE == 'binance':
                    url = f"{BINANCE_FUTURES_API_URL}/ticker/price"
                    response = self.session.get(
                        url,
                        params={'symbol': symbol},
                        timeout=self.request_timeout,
                        verify=self.verify_ssl
                    )
                    if response.status_code == 200:
                        data = response.json()
                        price = float(data['price'])
                        if price > 0:
                            return price
                else:
                    # Gate.io
                    url = f"{API_BASE_URL}/spot/tickers"
                    response = self.session.get(
                        url,
                        params={'currency_pair': symbol},
                        timeout=self.request_timeout,
                        verify=self.verify_ssl
                    )
                    if response.status_code == 200:
                        data = response.json()
                        if data:
                            price = float(data[0]['last'])
                            if price > 0:
                                return price
                
                # 如果本次尝试失败，等待后重试
                if attempt < max_retries - 1:
                    time.sleep(1 * (attempt + 1))  # 递增等待时间
                    
            except Exception as e:
                if attempt < max_retries - 1:
                    logging.warning(f"⚠️ 获取价格失败 {symbol} (尝试 {attempt+1}/{max_retries}): {e}")
                    time.sleep(1 * (attempt + 1))
                else:
                    logging.error(f"❌ 获取价格失败 {symbol} (所有重试均失败): {e}")
        
        return None
    
    def get_klines(self, symbol: str, interval: str = '15m', limit: int = 50) -> Optional[pd.DataFrame]:
        """获取K线数据（带时效性检查和缓存）"""
        # 优化：检查缓存
        cache_key = (symbol, interval)
        if cache_key in self._klines_cache:
            df, cache_time = self._klines_cache[cache_key]
            age = time.time() - cache_time
            if age < self._klines_cache_ttl:
                logging.debug(f"📦 使用K线缓存: {symbol} {interval} (缓存{age:.1f}秒)")
                return df.copy()
            else:
                # 缓存过期，删除
                del self._klines_cache[cache_key]
        
        try:
            df = None
            # 优先使用币安API（如果可用）
            if self.is_real_trading and self.binance_api:
                try:
                    klines = self.binance_api.get_klines(symbol, interval, limit)
                    if klines:
                        # 币安API返回的K线数据格式：[open_time, open, high, low, close, volume, close_time, ...]
                        df = pd.DataFrame(klines, columns=[
                            'open_time', 'open', 'high', 'low', 'close', 'volume',
                            'close_time', 'quote_volume', 'trades', 'taker_buy_base',
                            'taker_buy_quote', 'ignore'
                        ])
                        # 转换时间戳（毫秒）为datetime
                        df['timestamp'] = pd.to_datetime(df['open_time'], unit='ms')
                        df['close'] = df['close'].astype(float)
                        df['high'] = df['high'].astype(float)
                        df['low'] = df['low'].astype(float)
                        df['open'] = df['open'].astype(float)
                        df['volume'] = df['volume'].astype(float)
                except Exception as e:
                    logging.warning(f"币安API获取K线失败，回退到公开API: {e}")
            
            # 回退到公开API
            if EXCHANGE == 'binance':
                url = f"{BINANCE_FUTURES_API_URL}/klines"
                params = {'symbol': symbol, 'interval': interval, 'limit': limit}
                response = self.session.get(
                    url,
                    params=params,
                    timeout=self.request_timeout,
                    verify=self.verify_ssl
                )
                
                if response.status_code == 200:
                    data = response.json()
                    # 公开API返回的K线数据格式：[open_time, open, high, low, close, volume, close_time, ...]
                    df = pd.DataFrame(data, columns=[
                        'open_time', 'open', 'high', 'low', 'close', 'volume',
                        'close_time', 'quote_volume', 'trades', 'taker_buy_base',
                        'taker_buy_quote', 'ignore'
                    ])
                    # 转换时间戳（毫秒）为datetime
                    df['timestamp'] = pd.to_datetime(df['open_time'], unit='ms')
                    df['close'] = df['close'].astype(float)
                    df['high'] = df['high'].astype(float)
                    df['low'] = df['low'].astype(float)
                    df['open'] = df['open'].astype(float)
                    df['volume'] = df['volume'].astype(float)
            
            # 优化：检查K线数据时效性
            if df is not None and len(df) > 0:
                # 检查最新K线的时间戳
                try:
                    latest_timestamp = None
                    if 'timestamp' in df.columns:
                        # timestamp列应该是datetime类型（已在上面转换）
                        latest_timestamp = df['timestamp'].iloc[-1]
                        # 确保是datetime类型
                        if not isinstance(latest_timestamp, (pd.Timestamp, datetime)):
                            try:
                                latest_timestamp = pd.to_datetime(latest_timestamp)
                            except Exception:
                                latest_timestamp = None
                    elif df.index.name == 'timestamp' or isinstance(df.index, pd.DatetimeIndex):
                        latest_timestamp = df.index[-1]
                    elif 'close_time' in df.columns:
                        # 如果没有timestamp列，使用close_time（毫秒时间戳）
                        try:
                            close_time_ms = df['close_time'].iloc[-1]
                            latest_timestamp = pd.to_datetime(close_time_ms, unit='ms')
                        except Exception:
                            pass
                    
                    if latest_timestamp and isinstance(latest_timestamp, (pd.Timestamp, datetime)):
                        age_minutes = (datetime.now() - latest_timestamp).total_seconds() / 60
                        # 根据K线间隔设置最大允许延迟（间隔的2倍，最少5分钟）
                        interval_minutes = self._interval_to_minutes(interval)
                        max_age = max(5.0, interval_minutes * 2)
                        
                        # 只记录合理的过期时间（避免时间戳错误导致的误报）
                        if age_minutes > max_age and age_minutes < 100000:  # 小于100000分钟（约69天）
                            logging.warning(f"⚠️ {symbol} K线数据过期 ({age_minutes:.1f}分钟，最大允许{max_age:.1f}分钟)")
                            return None
                        elif age_minutes >= 100000:
                            # 时间戳明显异常，可能是数据格式问题，记录debug但不返回None
                            logging.debug(f"⚠️ {symbol} K线时间戳异常 ({age_minutes:.1f}分钟)，可能是数据格式问题，继续使用")
                except Exception as e:
                    logging.debug(f"检查K线时效性失败 {symbol}: {e}")
                
                # 优化：缓存K线数据
                if df is not None and len(df) > 0:
                    self._klines_cache[cache_key] = (df.copy(), time.time())
                    # 清理过期缓存（每100次调用清理一次）
                    if len(self._klines_cache) > 100:
                        self._clean_expired_cache()
                
                return df
            
            return None
        except Exception as e:
            logging.error(f"❌ 获取K线失败 {symbol}: {e}")
            return None
    
    def _interval_to_minutes(self, interval: str) -> float:
        """将时间间隔转换为分钟数"""
        try:
            s = (interval or "").strip().lower()
            if s.endswith("m"):
                return float(s[:-1])
            if s.endswith("h"):
                return float(s[:-1]) * 60
            if s.endswith("d"):
                return float(s[:-1]) * 60 * 24
        except Exception:
            pass
        return 15.0  # 默认15分钟
    
    def _clean_expired_cache(self):
        """清理过期的缓存"""
        current_time = time.time()
        expired_keys = []
        for key, (_, cache_time) in self._klines_cache.items():
            if current_time - cache_time > self._klines_cache_ttl:
                expired_keys.append(key)
        for key in expired_keys:
            del self._klines_cache[key]
        
        # 清理信号评分缓存
        expired_score_keys = []
        for key, (_, _, cache_time) in self._signal_score_cache.items():
            if current_time - cache_time > self._signal_score_cache_ttl:
                expired_score_keys.append(key)
        for key in expired_score_keys:
            del self._signal_score_cache[key]
    
    def calculate_trade_amount(self, signal_score: float) -> float:
        """根据信号评分计算交易金额"""
        if signal_score >= 90:
            return self.max_trade_amount
        elif signal_score >= 80:
            return self.max_trade_amount * 0.8
        elif signal_score >= 70:
            return self.max_trade_amount * 0.6
        else:
            return self.base_trade_amount
    
    def open_position(
        self,
        symbol: str,
        category: str,
        trigger_change: float = 0.0,
        coin_change: float = 0.0
    ) -> Optional[TradePosition]:
        """开仓 - 支持虚拟和实盘交易"""
        try:
            now = datetime.now()
            
            # P0优化：检查风险限制
            allowed, reason = self.is_trading_allowed()
            if not allowed:
                logging.info(f"⏸️ 风险控制暂停交易: {reason}")
                return None
            
            # 回测优势：连续亏损暂停等全局门控
            allowed, pause_reason = self.strategy_optimizer.is_trading_allowed(now)
            if not allowed:
                logging.info(f"⏸️ 策略暂停交易: {pause_reason}")
                return None

            # 检查黑名单
            is_blocked, reason = self.is_blacklisted(symbol, category)
            if is_blocked:
                logging.info(f"⛔ 跳过 {symbol}: {reason}")
                return None
            
            # 检查持仓数量
            # 回测优势：熊市/回撤时动态最大持仓数
            self._update_market_regime()
            current_drawdown = self._get_current_drawdown_pct()
            trading_params = self.strategy_optimizer.get_trading_parameters(
                market_regime=self._current_market_regime,
                current_drawdown=current_drawdown,
                current_time=now
            )
            effective_max_positions = min(self.max_positions, trading_params.max_positions)
            if len(self.positions) >= effective_max_positions:
                logging.info(f"⛔ 已达最大持仓数 {effective_max_positions}")
                return None
            
            # 检查是否已有持仓
            if symbol in self.positions:
                logging.warning(f"⚠️ 已有 {symbol} 持仓")
                return None
            
            # 获取K线数据计算信号评分
            df = self.get_klines(symbol)
            if df is None or len(df) < 20:
                logging.warning(f"⚠️ {symbol} K线数据不足，无法计算信号评分")
                return None
            
            # 优化：检查信号评分缓存
            score_cache_key = (symbol, trigger_change, coin_change, category)
            if score_cache_key in self._signal_score_cache:
                cached_score, cached_details, cache_time = self._signal_score_cache[score_cache_key]
                age = time.time() - cache_time
                if age < self._signal_score_cache_ttl:
                    logging.debug(f"📦 使用信号评分缓存: {symbol} (缓存{age:.1f}秒)")
                    signal_score, score_details = cached_score, cached_details
                else:
                    # 缓存过期，重新计算
                    del self._signal_score_cache[score_cache_key]
                    # P0优化：传递更多参数给统一评分器（Hot板块加成已集成）
                    signal_score, score_details = self.signal_scorer.calculate_score(
                        df, trigger_change, coin_change, category,
                        trigger_df=None,  # 实盘暂时不传递trigger_df
                        sector_tier=self._get_sector_tier(category)
                    )
                    # 更新缓存
                    self._signal_score_cache[score_cache_key] = (signal_score, score_details, time.time())
            else:
                # 无缓存，计算并缓存
                # P0优化：传递更多参数给统一评分器（Hot板块加成已集成）
                signal_score, score_details = self.signal_scorer.calculate_score(
                    df, trigger_change, coin_change, category,
                    trigger_df=None,  # 实盘暂时不传递trigger_df
                    sector_tier=self._get_sector_tier(category)
                )
                self._signal_score_cache[score_cache_key] = (signal_score, score_details, time.time())

            # P0优化：Hot板块加成已集成到统一评分器中，这里保留作为兼容性检查
            # 统一评分器会自动处理Hot板块加成，无需重复处理

            # 回测优势：信号校准（成交量/波动率/市场环境）并可能跳过低质量信号
            volume_ratio = self._calc_volume_ratio(df)
            atr_ratio = self._calc_atr_ratio(df)
            calibration = self.signal_calibrator.calibrate_signal(
                raw_score=signal_score,
                volume_ratio=volume_ratio,
                atr_ratio=atr_ratio,
                market_regime=self._current_market_regime
            )
            if calibration.should_skip:
                logging.info(f"⏭️ 跳过 {symbol}: {calibration.skip_reason}")
                return None
            signal_score = calibration.final_score
            
            # 检查信号评分
            if signal_score < self.min_signal_score:
                logging.info(f"⛔ {symbol} 信号评分 {signal_score:.1f} < {self.min_signal_score}")
                return None
            
            # 获取当前价格
            current_price = self.get_current_price(symbol)
            if not current_price or current_price <= 0:
                logging.error(f"❌ 无法获取 {symbol} 有效价格")
                return None
            
            # 计算交易金额和数量
            trade_amount = self.calculate_trade_amount(signal_score)

            # 回测优势：回撤时减少仓位
            trade_amount = trade_amount * trading_params.position_size_multiplier
            
            # 应用分类权重
            weight = CATEGORY_WEIGHT_ADJUSTMENTS.get(category, 1.0)
            trade_amount = trade_amount * weight

            # 回测优势：应用板块轮动权重（外部注入，等权=1.0）
            rot_mult = self._rotation_weight_multiplier.get(category, 1.0)
            trade_amount = trade_amount * rot_mult
            
            # 交易限额检查
            self._check_daily_reset()
            if trade_amount > self.max_single_trade_amount:
                logging.warning(f"⚠️ 交易金额 {trade_amount:.2f} 超过单笔限额 {self.max_single_trade_amount:.2f}，已限制")
                trade_amount = self.max_single_trade_amount
            
            if self.daily_trade_amount + trade_amount > self.max_daily_trade_amount:
                logging.warning(f"⚠️ 今日交易金额已达上限")
                return None
            
            # 余额检查
            if self.is_real_trading:
                # 实盘：从交易所获取真实余额
                if self.binance_api:
                    real_balance = self.binance_api.get_balance()
                    if real_balance < trade_amount * 1.1:  # 10%缓冲
                        logging.error(f"❌ 实盘余额不足: 需要 {trade_amount:.2f}, 当前 {real_balance:.2f}")
                        return None
            else:
                # 虚拟：使用虚拟余额
                if self.virtual_balance < trade_amount:
                    logging.error(f"❌ 虚拟余额不足: 需要 {trade_amount:.2f}, 当前 {self.virtual_balance:.2f}")
                    return None
            
            # 计算止损
            # 先计算基础止损（信号评分）
            stop_loss_pct, stop_type = self.stop_loss_manager.calculate_initial_stop_loss(signal_score)

            # V6：分类止损上限（与回测一致）
            try:
                if category and category in CATEGORY_STOP_LOSS:
                    cap = float(CATEGORY_STOP_LOSS[category])
                    if stop_loss_pct > cap:
                        stop_loss_pct = cap
                        stop_type = "category"
            except Exception:
                pass

            # 回测优势：动态止损（市场环境/板块波动性）
            try:
                dyn = self.dynamic_stop_loss_controller.get_stop_loss_threshold(
                    sector=category, market_regime=self._current_market_regime
                ).final_threshold
                if category and category in CATEGORY_STOP_LOSS:
                    stop_loss_pct = min(float(dyn), float(CATEGORY_STOP_LOSS[category]))
                    stop_type = "dynamic_category"
                else:
                    stop_loss_pct = float(dyn)
                    stop_type = "dynamic"
            except Exception:
                pass
            
            # 计算数量（考虑最小数量精度）
            quantity = (trade_amount * self.leverage) / current_price
            # 实盘：按交易对 LOT_SIZE(stepSize/minQty) 规则向下取整，避免下单被拒
            if self.is_real_trading and self.binance_api:
                adj_qty, qty_reason = self.binance_api.adjust_quantity(symbol, quantity)
                quantity = adj_qty
                if quantity <= 0:
                    logging.error(f"❌ 数量不满足交易对规则: {symbol}, 原始={quantity}, 原因={qty_reason}")
                    return None
            else:
                # 虚拟：简化精度
                quantity = round(quantity, 3)
            if quantity <= 0:
                logging.error(f"❌ 计算数量无效: {quantity}")
                return None
            
            # ========== 实盘交易执行（带重试机制） ==========
            if self.is_real_trading and self.binance_api:
                max_order_retries = 3
                for order_attempt in range(max_order_retries):
                    try:
                        # 安全：本系统默认"只做多 + 不加仓"，若交易所已有该 symbol 持仓则拒绝再次开仓
                        try:
                            rp = self.binance_api.get_position(symbol)
                            if rp and abs(float(rp.get("positionAmt", 0))) > 0:
                                logging.error("❌ 交易所已存在持仓，禁止再次开仓以避免加仓/方向不一致: %s positionAmt=%s", symbol, rp.get("positionAmt"))
                                return None
                        except Exception:
                            # 获取持仓失败时保守拒绝开仓（避免误加仓）
                            logging.error(f"❌ 无法确认交易所持仓状态，保守拒绝开仓: {symbol}")
                            return None

                        client_order_id = f"CL_{uuid.uuid4().hex[:20]}"
                        # 1. 设置杠杆
                        if not self.binance_api.set_leverage(symbol, self.leverage):
                            logging.error(f"❌ 设置杠杆失败: {symbol}")
                            return None
                        
                        # 2. 设置保证金模式（逐仓）
                        self.binance_api.set_margin_type(symbol, 'ISOLATED')
                        
                        # 3. 下单（市价单）
                        order_result = self.binance_api.place_order(
                            symbol=symbol,
                            side='BUY',
                            order_type='MARKET',
                            quantity=quantity,
                            client_order_id=client_order_id
                        )
                        
                        # 4. 验证订单
                        if not order_result or 'orderId' not in order_result:
                            logging.error(f"❌ 下单失败: {symbol}, 响应: {order_result}")
                            return None
                        
                        order_id = order_result['orderId']
                        executed_price = float(order_result.get('avgPrice', current_price))
                        executed_qty = float(order_result.get('executedQty', quantity))
                        
                        # 5. 确认订单状态（增强版：轮询最多5秒）
                        max_wait_seconds = 5
                        poll_interval = 0.5
                        waited = 0
                        while waited < max_wait_seconds:
                            time.sleep(poll_interval)
                            waited += poll_interval
                            order_status = self.binance_api.get_order(symbol, order_id)
                            status = order_status.get('status', '')
                            if status == 'FILLED':
                                break
                            elif status in ['CANCELED', 'REJECTED', 'EXPIRED']:
                                logging.error(f"❌ 订单被取消/拒绝: {symbol}, 状态: {status}")
                                return None
                        
                        if order_status.get('status') != 'FILLED':
                            logging.warning(f"⚠️ 订单未完全成交: {symbol}, 状态: {order_status.get('status')}")
                            # 如果部分成交，使用实际成交数量
                            executed_qty = float(order_status.get('executedQty', executed_qty))

                        # 如果未成交（0），视为下单失败，避免创建"空持仓"
                        if executed_qty <= 0:
                            logging.error(f"❌ 订单未成交，放弃建仓: {symbol}, orderId={order_id}")
                            return None
                        
                        # 使用实际成交价格和数量
                        current_price = executed_price
                        quantity = executed_qty
                        trade_amount = (executed_qty * executed_price) / self.leverage  # 实际使用的保证金
                        
                        logging.info(f"✅ 实盘开仓成功: {symbol}, 订单ID: {order_id}")
                        break  # 成功，退出重试循环
                        
                    except BinanceAPIError as e:
                        # 优化：区分临时错误和永久错误
                        error_code = getattr(e, 'code', None)
                        error_message = getattr(e, 'message', str(e))
                        
                        # 临时错误：可以重试
                        retryable_codes = [1003, -1021, -1003]  # 网络问题、时间戳错误
                        if error_code in retryable_codes and order_attempt < max_order_retries - 1:
                            wait_time = 2 * (order_attempt + 1)
                            logging.warning(f"⚠️ 实盘下单临时错误 {symbol} (尝试 {order_attempt+1}/{max_order_retries}): {error_message}, {wait_time}秒后重试")
                            time.sleep(wait_time)
                            continue
                        
                        # 永久错误：不重试
                        permanent_codes = [-2010, -2011, -2019]  # 余额不足、订单被拒绝、杠杆设置失败
                        if error_code in permanent_codes:
                            logging.error(f"❌ 实盘下单永久错误 {symbol}: {error_message} (错误码: {error_code})")
                            return None
                        
                        # 其他错误：最后一次尝试失败则返回
                        if order_attempt >= max_order_retries - 1:
                            logging.error(f"❌ 实盘下单失败 {symbol} (所有重试均失败): {error_message}")
                            return None
                        else:
                            wait_time = 2 * (order_attempt + 1)
                            logging.warning(f"⚠️ 实盘下单错误 {symbol} (尝试 {order_attempt+1}/{max_order_retries}): {error_message}, {wait_time}秒后重试")
                            time.sleep(wait_time)
                            
                    except Exception as e:
                        if order_attempt >= max_order_retries - 1:
                            logging.error(f"❌ 实盘交易异常 {symbol} (所有重试均失败): {e}")
                            return None
                        else:
                            wait_time = 2 * (order_attempt + 1)
                            logging.warning(f"⚠️ 实盘交易异常 {symbol} (尝试 {order_attempt+1}/{max_order_retries}): {e}, {wait_time}秒后重试")
                            time.sleep(wait_time)
            
            # ========== 创建持仓记录 ==========
            position = TradePosition(
                symbol=symbol,
                category=category,
                entry_price=current_price,
                quantity=quantity,
                margin=trade_amount,
                position_value=trade_amount * self.leverage,
                leverage=self.leverage,
                entry_time=datetime.now(),
                order_id=str(order_id) if self.is_real_trading and self.binance_api else str(uuid.uuid4()),
                initial_stop_loss_pct=stop_loss_pct,
                current_stop_loss_pct=stop_loss_pct,
                stop_loss_type=stop_type,
                signal_score=signal_score,
                highest_price=current_price,
                # P0优化：分批止盈初始化
                initial_quantity=quantity,
                initial_margin=trade_amount,
                tp_level=0
            )
            
            # 更新余额和统计
            if self.is_real_trading:
                # 实盘：不修改虚拟余额，使用真实余额
                pass
            else:
                # 虚拟：扣除保证金
                self.virtual_balance -= trade_amount
            
            self.positions[symbol] = position
            self.daily_trade_amount += trade_amount
            
            mode_str = "🔴实盘" if self.is_real_trading else "🔵虚拟"
            logging.info(f"💰 [{mode_str}] 开仓: {symbol} [{category}] @ {current_price:.4f}")
            logging.info(f"   保证金: {trade_amount:.0f}, 仓位: {position.position_value:.0f} ({self.leverage}x)")
            logging.info(f"   评分: {signal_score:.0f}, 止损: {stop_loss_pct:.1f}% ({stop_type})")
            
            return position
            
        except Exception as e:
            logging.error(f"❌ 开仓异常 {symbol}: {e}")
            import traceback
            logging.error(traceback.format_exc())
            return None

    def check_position(self, position: TradePosition) -> Tuple[bool, str]:
        """
        检查持仓是否需要平仓
        返回: (是否平仓, 平仓原因)
        """
        # 优化：价格获取失败时的容错处理
        current_price = self.get_current_price(position.symbol, max_retries=3)
        if not current_price:
            # 如果价格获取失败，使用缓存价格（如果存在）
            if hasattr(position, '_last_price') and position._last_price:
                current_price = position._last_price
                # 记录失败次数
                if not hasattr(position, '_price_fail_count'):
                    position._price_fail_count = 0
                position._price_fail_count += 1
                
                # 连续失败超过5次，触发警告
                if position._price_fail_count >= 5:
                    logging.error(f"❌ {position.symbol} 价格获取连续失败 {position._price_fail_count} 次，使用缓存价格 {current_price}")
                    # 可以考虑触发紧急平仓（可选）
                    # return True, f"价格获取失败，紧急平仓"
            else:
                # 没有缓存价格，无法检查
                logging.warning(f"⚠️ {position.symbol} 价格获取失败且无缓存，跳过本次检查")
                return False, ""
        else:
            # 价格获取成功，更新缓存并重置失败计数
            position._last_price = current_price
            if hasattr(position, '_price_fail_count'):
                position._price_fail_count = 0
        
        # 更新持仓状态
        position.current_price = current_price
        
        # 价格变化百分比
        price_change_pct = ((current_price - position.entry_price) / position.entry_price) * 100
        
        # 杠杆后的收益率 (基于保证金)
        leveraged_pnl_pct = price_change_pct * position.leverage
        position.unrealized_pnl_pct = leveraged_pnl_pct
        position.unrealized_pnl = position.margin * (leveraged_pnl_pct / 100)
        
        # 计算持仓时间
        holding_hours = (datetime.now() - position.entry_time).total_seconds() / 3600
        
        # 优化：移动止损更新频率限制（每30秒最多更新一次）
        should_update_trailing = True
        if hasattr(position, '_last_trailing_update_time'):
            time_since_update = (datetime.now() - position._last_trailing_update_time).total_seconds()
            if time_since_update < 30:  # 30秒内不更新
                should_update_trailing = False
        
        if should_update_trailing:
            # 更新最高价和移动止损
            updated = self.stop_loss_manager.update_trailing_stop(position, current_price)
            if updated:
                position._last_trailing_update_time = datetime.now()
        elif not hasattr(position, '_last_trailing_update_time'):
            # 首次检查，初始化时间
            position._last_trailing_update_time = datetime.now()
            self.stop_loss_manager.update_trailing_stop(position, current_price)
        
        # 1. 检查提前保本止损激活
        self.stop_loss_manager.check_breakeven(position, current_price)
        
        # 2. 保本止损检查
        if position.breakeven_stop > 0 and current_price <= position.breakeven_stop:
            return True, f"保本止损 ({leveraged_pnl_pct:+.2f}%)"
        
        # 3. 移动止损触发
        if position.trailing_stop > 0 and current_price <= position.trailing_stop:
            return True, f"移动止损 ({leveraged_pnl_pct:+.2f}%)"
        
        # 4. P0优化：分批止盈检查（优先于固定止盈）
        if self.partial_tp_enabled and position.initial_quantity > 0:
            partial_result = self._check_partial_take_profit(position, current_price, leveraged_pnl_pct)
            if partial_result:
                should_close, reason = partial_result
                if should_close:
                    return True, reason
        
        # 5. 止盈检查 (V2_TAKE_PROFIT是价格变化百分比，不是杠杆后收益)
        # 例如: 10%价格变化 × 15x杠杆 = 150%保证金收益
        if price_change_pct >= self.take_profit:
            return True, f"止盈 ({leveraged_pnl_pct:+.2f}%)"
        
        # 6. 止损检查 (V2_STOP_LOSS是价格变化百分比)
        # 例如: 5%价格下跌 × 15x杠杆 = -75%保证金亏损
        effective_sl_pct = position.current_stop_loss_pct
        if effective_sl_pct > 0 and price_change_pct <= -effective_sl_pct:
            return True, f"止损[{position.stop_loss_type}] ({leveraged_pnl_pct:+.2f}%)"
        
        # 7. 短期时间止损 (可配置，默认持仓超过2小时且盈利<3%则平仓)
        if SHORT_TIME_STOP_ENABLED:
            if holding_hours > SHORT_TIME_STOP_HOURS and leveraged_pnl_pct < SHORT_TIME_STOP_MIN_PROFIT:
                return True, f"时间止损{SHORT_TIME_STOP_HOURS:.0f}h ({leveraged_pnl_pct:+.2f}%)"
        
        # 8. 长期时间止损 (可配置，默认持仓超过24小时且亏损)
        if LONG_TIME_STOP_ENABLED:
            if holding_hours > LONG_TIME_STOP_HOURS and leveraged_pnl_pct < LONG_TIME_STOP_MIN_PROFIT:
                return True, f"时间止损{LONG_TIME_STOP_HOURS:.0f}h ({leveraged_pnl_pct:+.2f}%)"
        
        return False, ""
    
    def _check_partial_take_profit(
        self, 
        position: TradePosition, 
        current_price: float, 
        leveraged_pnl_pct: float
    ) -> Optional[Tuple[bool, str]]:
        """
        P0优化：检查分批止盈条件
        返回: None表示不平仓，(True, reason)表示全部平仓
        """
        if not self.partial_tp_enabled or not self.partial_tp_levels or not self.partial_tp_ratios:
            return None
        
        if position.initial_quantity <= 0 or position.initial_margin <= 0:
            return None
        
        # 检查每个止盈级别
        for level_idx, tp_level in enumerate(self.partial_tp_levels):
            # 已经触发过这个级别，跳过
            if position.tp_level > level_idx:
                continue
            
            # 检查是否达到这个止盈级别（基于杠杆后收益率）
            if leveraged_pnl_pct >= tp_level:
                # 触发分批止盈
                tp_ratio = self.partial_tp_ratios[level_idx] if level_idx < len(self.partial_tp_ratios) else 0.0
                if tp_ratio <= 0:
                    continue
                
                # 执行部分平仓
                result = self._partial_close_position(position, current_price, tp_ratio, level_idx + 1)
                if result:
                    # 如果是最后一级或剩余仓位太小，全部平仓
                    if level_idx == len(self.partial_tp_levels) - 1 or position.quantity < position.initial_quantity * 0.1:
                        return True, f"分批止盈完成 ({leveraged_pnl_pct:+.2f}%)"
                    # 否则继续持有剩余仓位
                    position.tp_level = level_idx + 1
                    # 第一次止盈后设置保本止损
                    if level_idx == 0:
                        position.breakeven_stop = position.entry_price * 1.005  # 0.5%缓冲
                    return None  # 部分平仓，继续持有
        
        return None
    
    def _partial_close_position(
        self, 
        position: TradePosition, 
        current_price: float, 
        close_ratio: float, 
        tp_level: int
    ) -> bool:
        """
        P0优化：部分平仓（分批止盈）
        返回: True表示成功，False表示失败
        """
        try:
            # 计算本次平仓的数量和保证金
            close_quantity = position.initial_quantity * close_ratio
            close_margin = position.initial_margin * close_ratio
            
            # 确保不超过当前持仓
            close_quantity = min(close_quantity, position.quantity)
            close_margin = min(close_margin, position.margin)
            
            if close_quantity <= 0:
                return False
            
            # 计算本次止盈的盈亏
            price_change = current_price - position.entry_price
            partial_pnl = price_change * close_quantity
            
            # ========== 实盘交易执行 ==========
            if self.is_real_trading and self.binance_api:
                try:
                    # 调整数量精度
                    adj_qty, _ = self.binance_api.adjust_quantity(position.symbol, close_quantity)
                    if adj_qty <= 0:
                        logging.warning(f"⚠️ 分批止盈数量调整后无效: {position.symbol}")
                        return False
                    close_quantity = adj_qty
                    
                    # 部分平仓下单
                    client_order_id = f"TP{tp_level}_{uuid.uuid4().hex[:20]}"
                    order_result = self.binance_api.place_order(
                        symbol=position.symbol,
                        side='SELL',
                        order_type='MARKET',
                        quantity=close_quantity,
                        reduce_only=True,
                        client_order_id=client_order_id
                    )
                    
                    if not order_result or 'orderId' not in order_result:
                        logging.error(f"❌ 分批止盈下单失败: {position.symbol}")
                        return False
                    
                    executed_price = float(order_result.get('avgPrice', current_price))
                    executed_qty = float(order_result.get('executedQty', close_quantity))
                    
                    logging.info(f"✅ 分批止盈 TP{tp_level} 成功: {position.symbol}, 平仓 {executed_qty:.4f} ({close_ratio*100:.0f}%), 盈亏: {partial_pnl:+.2f} USDT")
                    
                except Exception as e:
                    logging.error(f"❌ 分批止盈执行失败 {position.symbol}: {e}")
                    return False
            else:
                # 虚拟交易：直接更新
                executed_price = current_price
                executed_qty = close_quantity
            
            # 更新持仓（减少数量和保证金）
            position.quantity -= executed_qty
            position.margin -= close_margin
            position.position_value = position.margin * position.leverage
            
            # 累计已实现盈亏
            position.realized_pnl += partial_pnl
            
            # 更新余额
            if not self.is_real_trading:
                # 虚拟：返还部分保证金 + 盈亏
                self.virtual_balance += close_margin + partial_pnl
            
            # 更新统计
            self.total_pnl += partial_pnl
            self.daily_pnl += partial_pnl
            
            level_name = f"TP{tp_level}"
            logging.info(f"📈 分批止盈 {level_name}: {position.symbol} @ {executed_price:.4f}, 止盈{close_ratio*100:.0f}%仓位, 盈亏: +{partial_pnl:.2f} USDT")
            
            return True
            
        except Exception as e:
            logging.error(f"❌ 分批止盈异常 {position.symbol}: {e}")
            return False
    
    def close_position(self, symbol: str, reason: str) -> Optional[TradeResult]:
        """平仓 - 支持虚拟和实盘交易"""
        if symbol not in self.positions:
            logging.warning(f"⚠️ 未找到持仓: {symbol}")
            return None
        
        position = self.positions[symbol]
        current_price = self.get_current_price(symbol)
        
        if not current_price or current_price <= 0:
            logging.error(f"❌ 无法获取 {symbol} 有效价格")
            return None
        
        # ========== 实盘交易执行 ==========
        executed_price = current_price
        executed_qty = position.quantity
        
        if self.is_real_trading and self.binance_api:
            try:
                # 1. 获取实际持仓
                real_position = self.binance_api.get_position(symbol)
                if real_position:
                    # 使用实际持仓数量
                    pos_amt = float(real_position.get('positionAmt', 0) or 0)
                    # 安全：若交易所是空仓（负仓位），本系统不应自动平仓（避免方向不一致造成加仓）
                    if pos_amt < 0:
                        logging.error("❌ 检测到交易所为空头仓位，本系统默认只做多，拒绝自动平仓: %s positionAmt=%s", symbol, pos_amt)
                        return None
                    real_qty = abs(pos_amt)
                    if real_qty > 0:
                        executed_qty = min(real_qty, position.quantity)
                    else:
                        logging.warning(f"⚠️ 实盘持仓已不存在: {symbol}")
                        # 持仓已不存在，可能是手动平仓了
                        executed_qty = 0
                
                # 2. 平仓下单（市价单，只减仓）
                if executed_qty > 0:
                    # 平仓数量同样需要按 LOT_SIZE 规则修正
                    adj_qty, _ = self.binance_api.adjust_quantity(symbol, executed_qty)
                    executed_qty = adj_qty
                    if executed_qty <= 0:
                        logging.error(f"❌ 平仓数量不满足交易对规则: {symbol}")
                        return None

                    client_order_id = f"CL_{uuid.uuid4().hex[:20]}"
                    order_result = self.binance_api.place_order(
                        symbol=symbol,
                        side='SELL',
                        order_type='MARKET',
                        quantity=executed_qty,
                        reduce_only=True,
                        client_order_id=client_order_id
                    )
                    
                    if not order_result or 'orderId' not in order_result:
                        logging.error(f"❌ 平仓下单失败: {symbol}, 响应: {order_result}")
                        return None
                    
                    order_id = order_result['orderId']
                    executed_price = float(order_result.get('avgPrice', current_price))
                    executed_qty = float(order_result.get('executedQty', executed_qty))
                    
                    # 3. 确认订单状态
                    time.sleep(0.5)
                    order_status = self.binance_api.get_order(symbol, order_id)
                    if order_status.get('status') != 'FILLED':
                        logging.warning(f"⚠️ 平仓订单未完全成交: {symbol}, 状态: {order_status.get('status')}")
                        executed_qty = float(order_status.get('executedQty', executed_qty))
                    
                    logging.info(f"✅ 实盘平仓成功: {symbol}, 订单ID: {order_id}")
                
            except BinanceAPIError as e:
                logging.error(f"❌ 实盘平仓失败 {symbol}: {e.message}")
                # 高风险：下单失败时不能移除本地持仓，否则可能“实盘还有仓但程序不管了”
                # 这里保守处理：再次确认交易所是否已无仓；若仍有仓则保留，等待下一轮重试
                try:
                    rp = self.binance_api.get_position(symbol)
                    if rp and abs(float(rp.get('positionAmt', 0))) > 0:
                        return None
                except Exception:
                    return None
            except Exception as e:
                logging.error(f"❌ 实盘平仓异常 {symbol}: {e}")
                try:
                    rp = self.binance_api.get_position(symbol)
                    if rp and abs(float(rp.get('positionAmt', 0))) > 0:
                        return None
                except Exception:
                    return None
        
        # 计算盈亏（使用实际成交价格和数量）
        price_change = executed_price - position.entry_price
        pnl = price_change * executed_qty
        # 如果已有部分止盈，需要加上已实现盈亏
        if position.realized_pnl != 0:
            pnl += position.realized_pnl
        pnl_pct = (pnl / position.margin) * 100 if position.margin > 0 else 0
        
        # 计算持仓时间
        holding_hours = (datetime.now() - position.entry_time).total_seconds() / 3600
        
        # 更新持仓状态
        position.exit_price = executed_price
        position.exit_time = datetime.now()
        position.exit_reason = reason
        position.realized_pnl = pnl
        position.status = 'closed'
        
        # 更新余额和统计
        if self.is_real_trading:
            # 实盘：不修改虚拟余额，盈亏由交易所自动结算
            pass
        else:
            # 虚拟：返还保证金 + 盈亏
            self.virtual_balance += position.margin + pnl
        
        self.total_pnl += pnl
        
        # P0优化：更新单日盈亏
        self.daily_pnl += pnl
        
        # V7: 更新周期统计
        self.period_pnl += pnl
        self.period_trades += 1
        
        # 创建交易结果
        result = TradeResult(
            symbol=symbol,
            entry_price=position.entry_price,
            exit_price=executed_price,
            quantity=executed_qty,
            margin=position.margin,
            leverage=position.leverage,
            pnl=pnl,
            pnl_pct=pnl_pct,
            exit_reason=reason,
            holding_hours=holding_hours,
            signal_score=position.signal_score
        )
        
        # 记录交易历史
        self.trade_history.append(result)

        # 回测优势：记录交易结果用于连续亏损暂停等
        try:
            self.strategy_optimizer.record_trade_result(is_win=(pnl > 0), current_time=datetime.now(),
                                                       current_drawdown_pct=self._get_current_drawdown_pct())
        except Exception:
            pass
        
        # 更新分类亏损计数
        if pnl < 0:
            self.add_to_dynamic_blacklist(position.category)
        else:
            self.reset_loss_count(position.category)
        
        # 移除持仓
        del self.positions[symbol]
        
        mode_str = "🔴实盘" if self.is_real_trading else "🔵虚拟"
        emoji = "✅" if pnl > 0 else "❌"
        balance_str = f"{self.binance_api.get_balance():.2f}" if (self.is_real_trading and self.binance_api) else f"{self.virtual_balance:.2f}"
        logging.info(f"{emoji} [{mode_str}] 平仓: {symbol} @ {executed_price:.4f}")
        logging.info(f"   盈亏: {pnl:+.2f} USDT ({pnl_pct:+.2f}%), 原因: {reason}")
        logging.info(f"   持仓时间: {holding_hours:.1f}h, 余额: {balance_str}")
        
        return result
    
    def monitor_positions(self) -> List[TradeResult]:
        """监控所有持仓，检查止盈止损"""
        # V7: 检查是否需要定期重置
        self.check_periodic_reset()
        
        # P0优化：检查每日重置（包括单日亏损重置）
        self._check_daily_reset()
        
        # P0优化：检查最大回撤和单日亏损限制
        self._check_risk_limits()
        
        closed_trades = []
        symbols_to_close = []
        
        for symbol, position in self.positions.items():
            # 外部持仓默认不自动管理（避免误操作）；需要时打开 MANAGE_EXTERNAL_POSITIONS
            if position.is_external and not self.manage_external_positions:
                continue
            should_close, reason = self.check_position(position)
            if should_close:
                symbols_to_close.append((symbol, reason))
        
        # 执行平仓
        for symbol, reason in symbols_to_close:
            result = self.close_position(symbol, reason)
            if result:
                closed_trades.append(result)
                # 注意：daily_pnl 已在 close_position() 中更新，无需重复更新
        
        # P0优化：再次检查风险限制（平仓后可能触发）
        self._check_risk_limits()
        
        return closed_trades
    
    def _check_risk_limits(self):
        """
        P0优化：检查最大回撤和单日亏损限制
        """
        # 更新当前权益和回撤
        current_equity = self._get_current_equity()
        current_drawdown = self._get_current_drawdown_pct()
        
        # 1. 检查最大回撤
        if not self._trading_stopped_drawdown:
            if current_drawdown >= self.max_drawdown_severe_threshold:
                # 严重回撤：完全停止交易并平仓所有持仓
                if not self._trading_stopped_drawdown:
                    self._trading_stopped_drawdown = True
                    logging.error("=" * 60)
                    logging.error(f"🚨 严重回撤触发！回撤 {current_drawdown:.2f}% >= {self.max_drawdown_severe_threshold:.2f}%")
                    logging.error("🚨 完全停止交易，准备平仓所有持仓")
                    logging.error("=" * 60)
                    # 平仓所有持仓
                    self._close_all_positions("严重回撤保护")
            elif current_drawdown >= self.max_drawdown_threshold:
                # 达到回撤阈值：暂停新开仓
                if not self._trading_paused_drawdown:
                    self._trading_paused_drawdown = True
                    logging.warning("=" * 60)
                    logging.warning(f"⚠️ 最大回撤触发！回撤 {current_drawdown:.2f}% >= {self.max_drawdown_threshold:.2f}%")
                    logging.warning(f"⚠️ 暂停新开仓，收紧止损到3%")
                    logging.warning("=" * 60)
                    # 收紧所有持仓的止损
                    for position in self.positions.values():
                        if position.current_stop_loss_pct > 3.0:
                            position.current_stop_loss_pct = 3.0
                            position.stop_loss_type = "drawdown_protection"
            else:
                # 回撤恢复：解除暂停
                if self._trading_paused_drawdown and current_drawdown < self.max_drawdown_threshold * 0.8:
                    self._trading_paused_drawdown = False
                    logging.info(f"✅ 回撤恢复，解除交易暂停（当前回撤: {current_drawdown:.2f}%）")
        
        # 2. 检查单日亏损
        if not self._trading_stopped_daily_loss:
            daily_loss_pct = (abs(self.daily_pnl) / self.initial_balance * 100) if self.daily_pnl < 0 else 0.0
            if daily_loss_pct >= self.max_daily_loss_severe:
                # 严重单日亏损：完全停止交易
                if not self._trading_stopped_daily_loss:
                    self._trading_stopped_daily_loss = True
                    logging.error("=" * 60)
                    logging.error(f"🚨 严重单日亏损触发！今日亏损 {daily_loss_pct:.2f}% >= {self.max_daily_loss_severe:.2f}%")
                    logging.error("🚨 完全停止交易，准备平仓所有持仓")
                    logging.error("=" * 60)
                    # 平仓所有持仓
                    self._close_all_positions("严重单日亏损保护")
            elif daily_loss_pct >= self.max_daily_loss:
                # 达到单日亏损阈值：暂停新开仓
                if not self._trading_paused_daily_loss:
                    self._trading_paused_daily_loss = True
                    logging.warning("=" * 60)
                    logging.warning(f"⚠️ 单日亏损限制触发！今日亏损 {daily_loss_pct:.2f}% >= {self.max_daily_loss:.2f}%")
                    logging.warning(f"⚠️ 暂停新开仓，收紧止损到3%")
                    logging.warning("=" * 60)
                    # 收紧所有持仓的止损
                    for position in self.positions.values():
                        if position.current_stop_loss_pct > 3.0:
                            position.current_stop_loss_pct = 3.0
                            position.stop_loss_type = "daily_loss_protection"
    
    def _close_all_positions(self, reason: str):
        """P0优化：平仓所有持仓（紧急情况）"""
        symbols_to_close = list(self.positions.keys())
        for symbol in symbols_to_close:
            try:
                self.close_position(symbol, reason)
            except Exception as e:
                logging.error(f"❌ 紧急平仓失败 {symbol}: {e}")
    
    def _get_current_equity(self) -> float:
        """获取当前权益（余额 + 未实现盈亏）"""
        if self.is_real_trading and self.binance_api:
            try:
                return self.binance_api.get_balance() + sum(
                    pos.unrealized_pnl for pos in self.positions.values()
                )
            except Exception:
                pass
        # 虚拟模式
        return self.virtual_balance + sum(
            pos.unrealized_pnl for pos in self.positions.values()
        )
    
    def _get_current_drawdown_pct(self) -> float:
        """获取当前回撤百分比"""
        current_equity = self._get_current_equity()
        if current_equity > self._max_equity:
            self._max_equity = current_equity
        if self._max_equity <= 0:
            return 0.0
        return ((self._max_equity - current_equity) / self._max_equity) * 100
    
    def is_trading_allowed(self) -> Tuple[bool, str]:
        """
        P0优化：检查是否允许交易（考虑回撤和单日亏损限制）
        返回: (是否允许, 原因)
        """
        if self._trading_stopped_drawdown:
            return False, f"交易已停止：严重回撤保护（回撤 >= {self.max_drawdown_severe_threshold}%）"
        if self._trading_stopped_daily_loss:
            return False, f"交易已停止：严重单日亏损保护（亏损 >= {self.max_daily_loss_severe}%）"
        if self._trading_paused_drawdown:
            return False, f"交易已暂停：最大回撤保护（回撤 >= {self.max_drawdown_threshold}%）"
        if self._trading_paused_daily_loss:
            return False, f"交易已暂停：单日亏损限制（亏损 >= {self.max_daily_loss}%）"
        return True, ""
    
    def update_positions_status(self):
        """更新所有持仓状态 (不平仓，仅更新)"""
        for symbol, position in self.positions.items():
            current_price = self.get_current_price(symbol)
            if current_price:
                position.current_price = current_price
                price_change_pct = ((current_price - position.entry_price) / position.entry_price) * 100
                position.unrealized_pnl_pct = price_change_pct * position.leverage
                position.unrealized_pnl = position.margin * (position.unrealized_pnl_pct / 100)
                
                # 更新最高价
                if current_price > position.highest_price:
                    position.highest_price = current_price
    
    def get_performance_summary(self) -> Dict:
        """获取交易表现摘要"""
        # 更新持仓状态
        self.update_positions_status()
        
        # 计算未实现盈亏
        unrealized_pnl = sum(p.unrealized_pnl for p in self.positions.values())
        
        # 统计交易结果
        total_trades = len(self.trade_history)
        winning_trades = [t for t in self.trade_history if t.pnl > 0]
        losing_trades = [t for t in self.trade_history if t.pnl <= 0]
        
        win_rate = (len(winning_trades) / total_trades * 100) if total_trades > 0 else 0
        
        avg_win = np.mean([t.pnl for t in winning_trades]) if winning_trades else 0
        avg_loss = np.mean([t.pnl for t in losing_trades]) if losing_trades else 0
        
        # 按平仓原因统计
        exit_reasons = {}
        for trade in self.trade_history:
            reason_type = trade.exit_reason.split(' ')[0]  # 取第一个词作为类型
            if reason_type not in exit_reasons:
                exit_reasons[reason_type] = {'count': 0, 'pnl': 0}
            exit_reasons[reason_type]['count'] += 1
            exit_reasons[reason_type]['pnl'] += trade.pnl
        
        return {
            'initial_balance': self.initial_balance,
            'current_balance': self.virtual_balance,
            'total_pnl': self.total_pnl,
            'unrealized_pnl': unrealized_pnl,
            'total_equity': self.virtual_balance + unrealized_pnl,
            'roi_percentage': ((self.virtual_balance + unrealized_pnl - self.initial_balance) / self.initial_balance) * 100,
            'total_trades': total_trades,
            'winning_trades': len(winning_trades),
            'losing_trades': len(losing_trades),
            'win_rate': win_rate,
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'active_positions': len(self.positions),
            'exit_reasons': exit_reasons,
            'dynamic_blacklist': list(self.dynamic_blacklist.keys())
        }
    
    def display_status(self):
        """显示当前状态"""
        summary = self.get_performance_summary()
        logging.info("=" * 60)
        logging.info("TraderV2 交易状态")
        logging.info("=" * 60)
        logging.info("初始资金: %,.2f USDT", summary['initial_balance'])
        logging.info("当前余额(虚拟): %,.2f USDT", summary['current_balance'])
        logging.info("已实现盈亏: %+,.2f USDT", summary['total_pnl'])
        logging.info("未实现盈亏: %+,.2f USDT", summary['unrealized_pnl'])
        logging.info("总权益(虚拟): %,.2f USDT", summary['total_equity'])
        logging.info("ROI: %+,.2f%%", summary['roi_percentage'])
        logging.info("-" * 60)
        logging.info("总交易: %s 次 | 盈利: %s | 亏损: %s | 胜率: %.1f%% | 活跃持仓: %s",
                     summary['total_trades'], summary['winning_trades'], summary['losing_trades'],
                     summary['win_rate'], summary['active_positions'])
        
        if summary['exit_reasons']:
            logging.info("-" * 60)
            logging.info("平仓原因统计:")
            for reason, data in summary['exit_reasons'].items():
                logging.info("  %s: %s次, 盈亏: %+,.2f", reason, data['count'], data['pnl'])
        
        if summary['dynamic_blacklist']:
            logging.info("-" * 60)
            logging.info("动态黑名单: %s", ", ".join(summary['dynamic_blacklist']))
        
        logging.info("=" * 60)
        
        # 显示活跃持仓
        if self.positions:
            logging.debug("活跃持仓:")
            for symbol, pos in self.positions.items():
                holding_hours = (datetime.now() - pos.entry_time).total_seconds() / 3600
                logging.debug("  %s [%s] 入场: %.4f 当前: %.4f 盈亏: %+,.2f (%+.2f%%) 持仓: %.1fh 评分: %.0f",
                              symbol, pos.category, pos.entry_price, pos.current_price,
                              pos.unrealized_pnl, pos.unrealized_pnl_pct, holding_hours, pos.signal_score)
