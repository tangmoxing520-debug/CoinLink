"""
实时交易系统 V3 - 整合 TraderV2 优化策略 (V6高收益版)
同步回测中的所有优化逻辑:
1. 信号评分系统 (最低50分 - V6优化)
2. 动态止损/保本止损/移动止损
3. 时间止损 (1.5小时/8小时 - V6优化)
4. 板块轮动权重
5. 黑名单过滤 (静态+动态, 5次触发/8h时长 - V6优化)
6. 杠杆交易支持 (15x)
7. V6高收益参数: 止损4%, 止盈8%, 移动止损1.5%/2.5%
"""
import schedule
import time
import logging
import sys
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import traceback
import pandas as pd

from config import (
    CRYPTO_CATEGORIES, MONITOR_CONFIG, EXCHANGE, DINGTALK_WEBHOOK,
    CATEGORY_BLACKLIST, SYMBOL_BLACKLIST, CATEGORY_WEIGHT_ADJUSTMENTS,
    V2_TAKE_PROFIT, V2_STOP_LOSS, V2_TRAILING_STOP_PCT, V2_TRAILING_STOP_ACTIVATION,
    LEVERAGE, SIGNAL_MIN_SCORE, V2_MAX_POSITIONS, V2_BASE_TRADE_AMOUNT, V2_MAX_TRADE_AMOUNT,
    BLACKLIST_CONSECUTIVE_LOSSES, BLACKLIST_DURATION_HOURS,
    DAILY_LOSS_LIMIT_ENABLED, DAILY_LOSS_LIMIT_PCT,
    V8_CONFIG, TRADE_MODE, TRADE_ENABLED, BINANCE_API_KEY, BINANCE_SECRET_KEY,
    ROTATION_CONFIG,
    BACKTEST_INTERVAL, V2_COOLDOWN_PERIODS,
    LOG_LEVEL, STATUS_LOG_INTERVAL_MINUTES,
    MARKET_ANOMALY_ENABLED, FLASH_CRASH_THRESHOLD, FLASH_CRASH_WINDOW_MINUTES, LIQUIDITY_DROP_THRESHOLD, LIQUIDITY_MIN_VOLUME_THRESHOLD
)
from data_fetcher import create_data_fetcher
try:
    from adaptive_learning import AdaptiveLearningEngine, MarketAnalyzer, PerformanceAnalyzer
    ADAPTIVE_LEARNING_AVAILABLE = True
except ImportError:
    ADAPTIVE_LEARNING_AVAILABLE = False
    logging.warning("自适应学习模块不可用，将跳过学习分析功能")
from analyzer import CryptoAnalyzer, PriceAlert, TradeSignal
from notifier import DingTalkNotifier
from trader_v2 import TraderV2, TradePosition, TradeResult
from trade_recorder import TradeRecorder
from live_mode_full import create_live_mode_full_manager, LiveModeFullManager

from rotation_models import RotationConfig, SectorData, CoinData
from rotation_manager import RotationManager


class SafeStreamHandler(logging.StreamHandler):
    """安全的流处理器，处理编码问题"""
    
    def emit(self, record):
        try:
            msg = self.format(record)
            msg = self._safe_encode(msg)

            # 按当前控制台/流编码做“可写入”清洗，避免 UnicodeEncodeError 直接炸主循环
            stream = self.stream
            enc = getattr(stream, "encoding", None) or "utf-8"
            msg = msg.encode(enc, errors="replace").decode(enc, errors="replace")

            stream.write(msg + self.terminator)
            self.flush()
        except Exception:
            self.handleError(record)
    
    def _safe_encode(self, text):
        """安全编码处理"""
        emoji_map = {
            # 用 ASCII 标签替换 emoji，避免 Windows 控制台默认编码（cp1252/cp936）写入失败
            '🔍': '[SCAN]', '🚀': '[START]', '📊': '[DATA]', '✅': '[OK]',
            '❌': '[ERR]', '⚠️': '[WARN]', '🚨': '[ALERT]', '💼': '[TRADE]',
            '🎯': '[TARGET]', '📈': '[UP]', '📉': '[DOWN]', '💰': '[P&L]',
            '💸': '[LOSS]', '📦': '[ACTIVE]', '📋': '[TOTAL]', '📂': '[CAT]',
            '🐲': '[LEADER]', '🔮': '[VIRTUAL]', '⏹️': '[STOP]', '⏭️': '[SKIP]',
            '🔒': '[SSL]', '🔗': '[LINK]', '⏰': '[TIMEOUT]', '🏦': '[EXCHANGE]',
            '📢': '[NOTIFY]', '🚫': '[LIMIT]', '💳': '[BAL]', '🔄': '[RETRY]',
            '🌐': '[NET]', '🔑': '[KEY]', '📜': '[LOG]', '🔧': '[CFG]',
            '📡': '[MON]', '⚙️': '[SET]', '🖥️': '[SYS]', '🎉': '[DONE]',
            '🛑': '[STOP]', '⛔': '[BLOCK]', '💵': '[FUNDS]', '💎': '[EQUITY]'
        }
        
        for emoji, text_replacement in emoji_map.items():
            text = text.replace(emoji, text_replacement)
        return text


def setup_logging():
    """设置日志配置"""
    # 尽可能把控制台输出改成 UTF-8，彻底规避 charmap 编码崩溃（Windows 常见）
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    logger = logging.getLogger()
    level = getattr(logging, str(LOG_LEVEL).upper(), logging.INFO)
    logger.setLevel(level)
    
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
    
    file_handler = logging.FileHandler('crypto_monitor.log', encoding='utf-8')
    file_handler.setLevel(level)
    
    console_handler = SafeStreamHandler()
    console_handler.setLevel(level)
    
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)
    
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    return logger


class LiveTraderV3:
    """
    实时交易系统 V3
    整合 TraderV2 的所有优化策略
    支持虚拟和实盘交易模式
    """
    
    def __init__(self, initial_balance: float = 20000):
        # ========== 交易模式检查 ==========
        self.trade_mode = TRADE_MODE.lower()
        self.is_real_trading = self.trade_mode == 'real'
        self.trade_enabled = TRADE_ENABLED
        
        # 实盘交易安全检查
        if self.is_real_trading:
            self._validate_real_trading_config()
        
        # 数据获取
        self.fetcher = create_data_fetcher()
        self.analyzer = CryptoAnalyzer(MONITOR_CONFIG)
        
        # 通知
        self.notifier = DingTalkNotifier()
        
        # 交易器 V2 (核心)
        try:
            self.trader = TraderV2(initial_balance=initial_balance)
        except Exception as e:
            logging.error(f"❌ 交易器初始化失败: {e}")
            if self.is_real_trading:
                raise RuntimeError(f"实盘交易模式初始化失败，请检查配置: {e}")
            raise

        # P0：启动时与交易所持仓对账。发现外部持仓则进入安全模式（默认停开仓）
        if self.is_real_trading:
            try:
                external_cnt = self.trader.sync_positions_from_exchange()
                if external_cnt > 0 and getattr(self.trader, "safe_mode_on_external_positions", True):
                    self.trade_enabled = False
                    logging.error("已进入安全模式：检测到外部持仓，自动停开仓（SAFE_MODE_ON_EXTERNAL_POSITIONS=true）")
            except Exception as e:
                # 无法对账时也保守停开仓，避免失控
                self.trade_enabled = False
                logging.error("启动对账失败，保守停开仓: %s", e)
        
        # 交易记录
        self.recorder = TradeRecorder()
        
        # V8: Mode Full 管理器（把 --mode full 的冷启动/重置/黑名单优势落到实盘链路）
        self.mode_full_manager: LiveModeFullManager = create_live_mode_full_manager(V8_CONFIG)

        # 板块轮动管理器（轻量版：使用每周期抓取到的 top coins/ticker 数据来估算强度）
        self.rotation_manager: Optional[RotationManager] = None
        try:
            rotation_cfg = RotationConfig.from_dict(ROTATION_CONFIG)
            if rotation_cfg.enabled:
                self.rotation_manager = RotationManager(rotation_cfg)
        except Exception as e:
            logging.warning(f"⚠️ 板块轮动管理器初始化失败，将退化为静态权重: {e}")

        # 警报历史
        self.alert_history = []
        self.trade_signals_history = []

        # 回测对齐：分类冷却（按 K 线周期 * 冷却根数）
        self._category_last_signal_time: Dict[str, datetime] = {}
        
        # 配置
        self.enabled_categories = MONITOR_CONFIG.get('enabled_categories', [])
        self.monitor_interval = MONITOR_CONFIG.get('monitor_interval', 5)

        # 运维：状态汇总限频
        self._last_status_log_time: Optional[datetime] = None
        
        # 自适应学习模块
        self.learning_engine: Optional[AdaptiveLearningEngine] = None
        self._last_learning_analysis_time: Optional[datetime] = None
        self._learning_analysis_interval_minutes = int(os.getenv("LEARNING_ANALYSIS_INTERVAL_MINUTES", "60"))  # 默认每小时分析一次
        
        if ADAPTIVE_LEARNING_AVAILABLE:
            try:
                self.learning_engine = AdaptiveLearningEngine(
                    market_analyzer=MarketAnalyzer(),
                    performance_analyzer=PerformanceAnalyzer(),
                    min_trades_for_analysis=10
                )
                logging.info("✅ 自适应学习模块已启用")
            except Exception as e:
                logging.warning(f"⚠️ 自适应学习模块初始化失败: {e}")
        else:
            logging.info("ℹ️ 自适应学习模块未启用（模块不可用）")
        
        # 优化：性能统计和错误统计
        self._cycle_stats = {
            'total_cycles': 0,
            'total_time': 0.0,
            'avg_cycle_time': 0.0,
            'max_cycle_time': 0.0,
            'signals_generated': 0,
            'positions_opened': 0,
            'positions_closed': 0,
            'errors': {}
        }
        self._last_position_check_time: Optional[datetime] = None
        self._position_check_interval = timedelta(minutes=2)  # 每2分钟检查一次持仓
        
        # 优化：持仓数据与交易所同步（每小时同步一次）
        self._last_position_sync_time: Optional[datetime] = None
        self._position_sync_interval = timedelta(hours=1)
        
        # 优化：板块轮动上下文更新频率控制（每5分钟更新一次，不需要每个周期都更新）
        self._last_rotation_update_time: Optional[datetime] = None
        self._rotation_update_interval = timedelta(minutes=5)
        
        # P0优化：市场异常检测
        self.market_anomaly_enabled = MARKET_ANOMALY_ENABLED
        self.flash_crash_threshold = FLASH_CRASH_THRESHOLD
        self.flash_crash_window_minutes = FLASH_CRASH_WINDOW_MINUTES
        self.liquidity_drop_threshold = LIQUIDITY_DROP_THRESHOLD
        self.liquidity_min_volume_threshold = LIQUIDITY_MIN_VOLUME_THRESHOLD
        self._price_history: Dict[str, List[Tuple[datetime, float]]] = {}  # symbol -> [(time, price), ...]
        self._volume_history: Dict[str, List[Tuple[datetime, float]]] = {}  # symbol -> [(time, volume), ...]
        self._market_anomaly_paused = False  # 是否因市场异常暂停交易
        
        # 启动信息
        self._print_startup_info(initial_balance)

    @staticmethod
    def _interval_to_minutes(interval: str) -> int:
        """将 '15m'/'1h' 等 interval 解析为分钟数"""
        try:
            s = (interval or "").strip().lower()
            if s.endswith("m"):
                return max(1, int(float(s[:-1])))
            if s.endswith("h"):
                return max(1, int(float(s[:-1])) * 60)
            if s.endswith("d"):
                return max(1, int(float(s[:-1])) * 60 * 24)
        except Exception:
            pass
        return 15

    def _cooldown_minutes(self) -> int:
        """回测对齐：冷却分钟 = K线分钟数 * 冷却根数"""
        return max(1, self._interval_to_minutes(BACKTEST_INTERVAL) * int(V2_COOLDOWN_PERIODS))

    def _is_category_in_cooldown(self, category: str) -> bool:
        last_time = self._category_last_signal_time.get(category)
        if not last_time:
            return False
        return datetime.now() < last_time + timedelta(minutes=self._cooldown_minutes())
    
    def _validate_real_trading_config(self):
        """验证实盘交易配置"""
        errors = []
        
        if not BINANCE_API_KEY or BINANCE_API_KEY == 'your_binance_api_key_here':
            errors.append("BINANCE_API_KEY 未配置或使用默认值")
        
        if not BINANCE_SECRET_KEY or BINANCE_SECRET_KEY == 'your_binance_secret_key_here':
            errors.append("BINANCE_SECRET_KEY 未配置或使用默认值")
        
        if not TRADE_ENABLED:
            errors.append("TRADE_ENABLED 必须为 true")
        
        if errors:
            error_msg = "\n".join([f"  ❌ {e}" for e in errors])
            raise RuntimeError(f"实盘交易配置错误:\n{error_msg}\n\n请在 config.env 中正确配置！")
        
        logging.warning("=" * 60)
        logging.warning("⚠️  实盘交易模式已启用！")
        logging.warning("⚠️  系统将使用真实资金进行交易！")
        logging.warning("⚠️  请确保已充分测试并理解风险！")
        logging.warning("=" * 60)
    
    def _print_startup_info(self, initial_balance: float):
        """打印启动信息"""
        mode_str = "🔴 实盘交易" if self.is_real_trading else "🔵 虚拟交易"
        trade_status = "✅ 已启用" if self.trade_enabled else "❌ 已禁用"
        
        logging.info("=" * 60)
        logging.info(f"🚀 LiveTraderV3 实时交易系统启动 (V6高收益版)")
        logging.info("=" * 60)
        logging.info(f"📊 交易所: {EXCHANGE.upper()}")
        logging.info(f"💼 交易模式: {mode_str}")
        logging.info(f"🔧 交易功能: {trade_status}")
        logging.info(f"💰 初始资金: {initial_balance:,.0f} USDT")
        logging.info(f"⚙️ 杠杆: {LEVERAGE}x")
        logging.info(f"📈 止盈: {V2_TAKE_PROFIT}% (价格变化)")
        logging.info(f"📉 止损: {V2_STOP_LOSS}% (价格变化)")
        logging.info(f"🎯 信号阈值: {SIGNAL_MIN_SCORE}")
        logging.info(f"📦 最大持仓: {V2_MAX_POSITIONS}")
        logging.info(f"⛔ 黑名单分类: {CATEGORY_BLACKLIST}")
        logging.info(f"⛔ 黑名单交易对: {SYMBOL_BLACKLIST}")
        logging.info(f"📋 V6参数: 止盈8%, 止损4%, 移动止损1.5%/2.5%, 信号阈值50")
        logging.info("=" * 60)
        
        if self.is_real_trading:
            logging.warning("⚠️  实盘交易模式 - 请确保:")
            logging.warning("   1. API密钥权限已正确配置（仅交易权限，非提现权限）")
            logging.warning("   2. 已充分测试虚拟交易模式")
            logging.warning("   3. 已设置合理的交易限额")
            logging.warning("   4. 已配置钉钉通知以便及时了解交易情况")
            logging.warning("=" * 60)
    
    def run_monitoring_cycle(self):
        """执行监控周期（带性能监控）"""
        cycle_start = datetime.now()
        self._cycle_stats['total_cycles'] += 1
        
        try:
            logging.info(f"\n🔍 开始监控周期 - {cycle_start.strftime('%Y-%m-%d %H:%M:%S')}")

            # V8: 周期重置（Mode Full 机制）
            reset_start = datetime.now()
            self.mode_full_manager.check_and_perform_reset()
            reset_time = (datetime.now() - reset_start).total_seconds()

            # P0优化：市场异常检测
            if self.market_anomaly_enabled:
                self._check_market_anomalies()

            # P0：每周期与交易所持仓对账（手动开/平仓、进程重启等场景）
            if self.is_real_trading:
                try:
                    external_cnt = self.trader.reconcile_exchange_positions()
                    if external_cnt > 0 and getattr(self.trader, "safe_mode_on_external_positions", True):
                        self.trade_enabled = False
                except Exception as e:
                    self._record_error('reconcile_positions', str(e))
                    self.trade_enabled = False
            
            # 优化：定期同步持仓数据（每小时一次）
            if self.is_real_trading and self._should_sync_positions():
                try:
                    sync_start = datetime.now()
                    # 使用现有的 sync_positions_from_exchange 方法
                    external_cnt = self.trader.sync_positions_from_exchange()
                    sync_time = (datetime.now() - sync_start).total_seconds()
                    logging.info(f"✅ 持仓数据同步完成 (耗时 {sync_time:.2f}秒, 外部持仓: {external_cnt})")
                    self._last_position_sync_time = datetime.now()
                except Exception as e:
                    self._record_error('sync_positions', str(e))
                    logging.warning(f"⚠️ 持仓数据同步失败: {e}")
            
            # 1. 优化：持仓检查频率控制（每2分钟检查一次）
            should_check_positions = True
            if self._last_position_check_time:
                if datetime.now() - self._last_position_check_time < self._position_check_interval:
                    should_check_positions = False
            
            if should_check_positions:
                monitor_start = datetime.now()
                self._monitor_positions()
                monitor_time = (datetime.now() - monitor_start).total_seconds()
                self._last_position_check_time = datetime.now()
            else:
                monitor_time = 0.0
            
            # 2. 扫描新的交易机会
            scan_start = datetime.now()
            signals_before = len(self.trade_signals_history)
            self._scan_opportunities()
            signals_after = len(self.trade_signals_history)
            signals_generated = signals_after - signals_before
            self._cycle_stats['signals_generated'] += signals_generated
            scan_time = (datetime.now() - scan_start).total_seconds()
            
            # 3. 自适应学习分析（定期执行）
            # 优化：在扫描后检查耗时，如果已经过长则跳过学习分析
            scan_elapsed = (datetime.now() - cycle_start).total_seconds()
            self._current_cycle_time = scan_elapsed  # 用于学习分析判断
            
            learning_start = datetime.now()
            self._run_adaptive_learning()
            learning_time = (datetime.now() - learning_start).total_seconds()
            
            # 4. 显示状态
            display_start = datetime.now()
            self._display_status()
            display_time = (datetime.now() - display_start).total_seconds()
            
            # 优化：记录性能统计
            cycle_time = (datetime.now() - cycle_start).total_seconds()
            self._cycle_stats['total_time'] += cycle_time
            self._cycle_stats['avg_cycle_time'] = self._cycle_stats['total_time'] / self._cycle_stats['total_cycles']
            if cycle_time > self._cycle_stats['max_cycle_time']:
                self._cycle_stats['max_cycle_time'] = cycle_time
            
            # 如果周期耗时超过监控间隔的50%，发出警告并给出优化建议
            monitor_interval_seconds = self.monitor_interval * 60
            if cycle_time > monitor_interval_seconds * 0.5:
                logging.warning(f"⚠️ 监控周期耗时 {cycle_time:.2f}秒，超过监控间隔的50% ({monitor_interval_seconds * 0.5:.2f}秒)")
                logging.warning(f"   各步骤耗时: 重置={reset_time:.2f}s, 持仓={monitor_time:.2f}s, 扫描={scan_time:.2f}s, 学习={learning_time:.2f}s, 显示={display_time:.2f}s")
                
                # 性能优化建议
                if scan_time > monitor_interval_seconds * 0.3:
                    logging.warning(f"   💡 扫描耗时过长 ({scan_time:.2f}s)，建议：")
                    logging.warning(f"      - 减少监控分类数量")
                    logging.warning(f"      - 减少每个分类的币种数量 (top_n)")
                    logging.warning(f"      - 减少监控时间窗口数量")
                
                if learning_time > 5.0:
                    logging.warning(f"   💡 学习分析耗时过长 ({learning_time:.2f}s)，建议增加 LEARNING_ANALYSIS_INTERVAL_MINUTES")
                
                if monitor_time > 10.0:
                    logging.warning(f"   💡 持仓检查耗时过长 ({monitor_time:.2f}s)，建议检查持仓数量或网络延迟")
            
            # 每10个周期输出一次性能统计
            if self._cycle_stats['total_cycles'] % 10 == 0:
                logging.info(f"📊 性能统计 (最近{self._cycle_stats['total_cycles']}个周期):")
                logging.info(f"   平均周期耗时: {self._cycle_stats['avg_cycle_time']:.2f}秒")
                logging.info(f"   最大周期耗时: {self._cycle_stats['max_cycle_time']:.2f}秒")
                logging.info(f"   信号生成: {self._cycle_stats['signals_generated']} 个")
                logging.info(f"   开仓: {self._cycle_stats['positions_opened']} 次")
                logging.info(f"   平仓: {self._cycle_stats['positions_closed']} 次")
            
        except Exception as e:
            logging.error(f"❌ 监控周期执行失败: {e}")
            logging.error(traceback.format_exc())
    
    def _monitor_positions(self):
        """监控现有持仓"""
        if not self.trader.positions:
            return
        
        logging.info(f"📦 监控 {len(self.trader.positions)} 个活跃持仓...")
        
        # 检查止盈止损
        closed_trades = self.trader.monitor_positions()
        
        # 处理平仓结果
        for result in closed_trades:
            self._handle_trade_closed(result)
    
    def _handle_trade_closed(self, result: TradeResult):
        """处理平仓结果"""
        # V8 Mode Full：记录交易结果，用于动态黑名单/周期统计
        try:
            is_win = result.pnl > 0
            self.mode_full_manager.record_trade(result.symbol, result.pnl, is_win)
            # 亏损后设置短冷却，避免连续追单（与 main.py 旧链路保持一致）
            if not is_win:
                self.mode_full_manager.set_cooldown(result.symbol, self._cooldown_minutes())
        except Exception:
            # Mode Full 统计不应影响主流程
            pass

        # 记录到Excel
        self.recorder.add_trade_record(
            symbol=result.symbol,
            entry_price=result.entry_price,
            quantity=result.quantity,
            amount=result.margin,
            category="",  # 可以从position获取
            entry_time=datetime.now() - timedelta(hours=result.holding_hours)
        )
        
        self.recorder.update_trade_record(
            symbol=result.symbol,
            exit_price=result.exit_price,
            exit_time=datetime.now(),
            profit_loss=result.pnl,
            profit_loss_percentage=result.pnl_pct,
            status='closed',
            close_reason=result.exit_reason
        )
        
        # 发送通知
        self.notifier.send_trade_result(
            result.symbol,
            result.entry_price,
            result.exit_price,
            result.quantity,
            result.pnl,
            result.exit_reason,
            "V3"
        )
        
        emoji = "✅" if result.pnl > 0 else "❌"
        logging.info(f"{emoji} 平仓完成: {result.symbol}")
        logging.info(f"   盈亏: {result.pnl:+.2f} USDT ({result.pnl_pct:+.2f}%)")
        logging.info(f"   原因: {result.exit_reason}")
    
    def _scan_opportunities(self):
        """扫描交易机会"""
        # 检查是否还能开仓
        if len(self.trader.positions) >= self.trader.max_positions:
            logging.info(f"⛔ 已达最大持仓数 {self.trader.max_positions}，跳过扫描")
            return
        
        trade_signals = []
        category_snapshots: Dict[str, List[Dict]] = {}
        
        for category in self.enabled_categories:
            if category not in CRYPTO_CATEGORIES:
                continue
            
            # 检查分类黑名单
            if category in CATEGORY_BLACKLIST:
                continue

            category_in_cooldown = self._is_category_in_cooldown(category)
            if category_in_cooldown:
                # 对齐回测：冷却期内仍可采样行情/更新轮动，但不生成该分类的新交易信号
                logging.debug(f"⏭️ 分类冷却中: {category} (冷却 {self._cooldown_minutes()} 分钟)")
            
            # 默认 INFO 只保留关键交易事件；分类扫描属于高频噪声，降到 DEBUG
            logging.debug(f"[分类] 扫描分类: {category}")
            
            # 优化：减少每个分类的币种数量（从20降到10，减少API请求）
            # 获取币种数据
            top_n = min(MONITOR_CONFIG.get('top_n', 20), 10)  # 最多10个币种
            coins = self.fetcher.get_top_coins_by_category(
                category, 
                top_n
            )
            
            if not coins:
                continue
            
            category_coins = coins.copy()
            category_snapshots[category] = category_coins
            
            # 优化：检测价格警报（优先检测龙头币，然后检测前3个币种，减少API请求）
            # 确保龙头币一定会被检测到，避免漏掉交易信号
            leader_coin = MONITOR_CONFIG.get("leader_coins", {}).get(category)
            coins_to_check = []
            
            # 1. 优先添加龙头币（如果存在）
            if leader_coin:
                for coin in coins:
                    if coin.get('id') == leader_coin:
                        coins_to_check.append(coin)
                        break
            
            # 2. 添加前3个币种（如果还没有添加）
            for coin in coins[:3]:
                if coin not in coins_to_check:
                    coins_to_check.append(coin)
            
            # 如果还是没有币种，使用所有币种（兜底）
            if not coins_to_check:
                coins_to_check = coins
            
            # 检测价格警报
            for coin in coins_to_check:
                coin_id = coin.get('id')
                if not coin_id:
                    continue
                
                alerts = self.analyzer.detect_price_alerts(coin, category, self.fetcher)
                
                for alert in alerts:
                    if self._is_duplicate_alert(alert):
                        continue
                    
                    # 记录警报
                    self.alert_history.append(alert)
                    
                    # 发送警报通知
                    if self.notifier.send_alert(alert):
                        alert_type = "暴涨" if alert.alert_type == 'surge' else "暴跌"
                        logging.info(f"🚨 {alert_type}警报: {alert.coin_name} {alert.change_percentage:+.2f}%")
                    
                    # 检查是否为龙头币触发的交易信号
                    if (alert.alert_type == 'surge' and 
                        alert.time_window == MONITOR_CONFIG.get('signal_trigger_interval', BACKTEST_INTERVAL) and
                        self.analyzer.is_leader_coin(alert.coin_id, category)):
                        
                        logging.info(f"🐲 龙头币 {alert.coin_name} 触发，生成交易信号...")

                        # 回测对齐：龙头触发需要趋势/成交量确认（减少噪声信号）
                        try:
                            leader_df = self.trader.get_klines(alert.coin_id, interval=BACKTEST_INTERVAL)
                            if leader_df is None or leader_df.empty or len(leader_df) < 20:
                                logging.debug(
                                    "跳过龙头触发确认: %s [%s] K线不足 (len=%s, interval=%s)",
                                    alert.coin_id, category, 0 if leader_df is None else len(leader_df), BACKTEST_INTERVAL
                                )
                                continue
                            close = pd.to_numeric(leader_df.get("close"), errors="coerce")
                            volume = pd.to_numeric(leader_df.get("volume"), errors="coerce")
                            if close.isna().all():
                                logging.debug(
                                    "跳过龙头触发确认: %s [%s] close 全为 NaN (interval=%s)",
                                    alert.coin_id, category, BACKTEST_INTERVAL
                                )
                                continue
                            ma5 = close.rolling(5).mean().iloc[-1]
                            ma10 = close.rolling(10).mean().iloc[-1]
                            ma20 = close.rolling(20).mean().iloc[-1]
                            last_close = float(close.iloc[-1])
                            trend_ok = True
                            # 优化：放宽趋势确认条件
                            # 允许 ma5 < ma10 但 last_close > ma20 * 0.95（从0.98放宽到0.95）
                            if pd.notna(ma5) and pd.notna(ma10) and ma5 < ma10:
                                # 如果 ma5 < ma10，但价格仍在 ma20 上方，仍认为趋势OK
                                if pd.notna(ma20) and last_close < float(ma20) * 0.95:
                                    trend_ok = False
                            elif pd.notna(ma20) and last_close < float(ma20) * 0.95:
                                trend_ok = False

                            vol_ok = True
                            vol_ratio = None
                            if volume is not None and not volume.isna().all():
                                current_vol = float(volume.iloc[-1])
                                avg_vol = float(volume.iloc[-20:].mean()) if len(volume) >= 20 else float(volume.mean())
                                if avg_vol > 0:
                                    vol_ratio = current_vol / avg_vol
                                    # 优化：降低成交量要求从0.8到0.6
                                    if vol_ratio < 0.6:
                                        vol_ok = False

                            if not (trend_ok and vol_ok):
                                logging.debug(
                                    "跳过龙头触发确认: %s [%s] trend_ok=%s (ma5=%s ma10=%s ma20=%s last=%s) vol_ok=%s (vol_ratio=%s)",
                                    alert.coin_id, category,
                                    trend_ok,
                                    None if pd.isna(ma5) else float(ma5),
                                    None if pd.isna(ma10) else float(ma10),
                                    None if pd.isna(ma20) else float(ma20),
                                    last_close,
                                    vol_ok,
                                    None if vol_ratio is None else float(vol_ratio),
                                )
                                continue
                        except Exception:
                            # 触发确认失败则保守跳过（避免误触发偏离回测）
                            logging.debug(
                                "跳过龙头触发确认: %s [%s] 确认过程异常",
                                alert.coin_id, category,
                                exc_info=True
                            )
                            continue

                        # 回测对齐：分类冷却（按K线周期*冷却根数）——冷却期内不生成新信号
                        if category_in_cooldown:
                            logging.debug(
                                "跳过生成交易信号: 分类冷却中 %s (冷却 %s 分钟)",
                                category, self._cooldown_minutes()
                            )
                            continue

                        # 记录本次分类触发时间（回测 last_signal_time 逻辑）
                        self._category_last_signal_time[category] = datetime.now()
                        
                        trade_signal = self.analyzer.generate_trade_signal(
                            alert, category_coins, self.fetcher
                        )
                        
                        if trade_signal.target_coins:
                            trade_signals.append(trade_signal)
                            self.trade_signals_history.append(trade_signal)
                        else:
                            # 常见原因：同板块币种跟涨"太一致"而没有滞涨目标（FOLLOW_THRESHOLD已优化为100，与回测对齐）
                            logging.debug(
                                "未生成可交易目标: %s [%s] trigger=%.2f%% FOLLOW_THRESHOLD=%.1f (目标为空，可能所有币种跟涨都超过阈值)",
                                alert.coin_id, category, float(alert.change_percentage), float(MONITOR_CONFIG.get("follow_threshold", 100))
                            )
        
        # 优化：板块轮动上下文更新频率控制（每5分钟更新一次）
        should_update_rotation = True
        if self._last_rotation_update_time:
            if datetime.now() - self._last_rotation_update_time < self._rotation_update_interval:
                should_update_rotation = False
        
        if should_update_rotation:
            # 先更新板块轮动上下文，再处理交易信号（使开仓金额/评分加成更贴近回测）
            self._update_rotation_context(category_snapshots)
            self._last_rotation_update_time = datetime.now()

        # P0优化：如果市场异常暂停，跳过交易信号处理
        if self._market_anomaly_paused:
            logging.warning("⚠️ 市场异常检测暂停交易，跳过信号处理")
            return

        # 处理交易信号
        if trade_signals:
            self._process_trade_signals(trade_signals)

    def _update_rotation_context(self, category_snapshots: Dict[str, List[Dict]]) -> None:
        """更新板块轮动权重/层级，并注入到 TraderV2"""
        if not self.rotation_manager or not category_snapshots:
            return
        try:
            # 构建 BTC 参考数据（用 ticker 近似生成两点 close 序列）
            btc_df = None
            try:
                btc_coin = None
                # 使用 Layer1 龙头 BTCUSDT（fetcher 已配置）
                btc_list = self.fetcher.get_top_coins_by_category("Layer1", 1)
                if btc_list:
                    btc_coin = btc_list[0]
                if btc_coin and btc_coin.get("current_price"):
                    current = float(btc_coin["current_price"])
                    pct = float(btc_coin.get("price_change_percentage_24h_in_currency", 0.0))
                    first = current / (1.0 + pct / 100.0) if (1.0 + pct / 100.0) != 0 else current
                    btc_df = pd.DataFrame({"close": [first, current]})
            except Exception:
                btc_df = None

            sector_data: Dict[str, SectorData] = {}
            leader_map = MONITOR_CONFIG.get("leader_coins", {})

            for category, coins in category_snapshots.items():
                if not coins:
                    continue
                # 成交量基准：用当前采样的均值做 proxy
                vols = [float(c.get("total_volume", 0) or 0) for c in coins]
                avg_vol = (sum(vols) / len(vols)) if vols else 0.0

                coin_objs: List[CoinData] = []
                for c in coins:
                    sym = c.get("symbol") or c.get("id") or ""
                    if not sym:
                        continue
                    # GateDataFetcher 返回 'symbol' 形如 BTCUSDT
                    try:
                        price = float(c.get("current_price", 0) or 0)
                        pct = float(c.get("price_change_percentage_24h_in_currency", 0) or 0)
                        vol = float(c.get("total_volume", 0) or 0)
                        vol_ratio = (vol / avg_vol) if avg_vol > 0 else 1.0
                        coin_objs.append(CoinData(
                            symbol=str(sym).upper(),
                            prices=None,
                            current_price=price,
                            price_change_pct=pct,
                            volume_ratio=max(0.1, vol_ratio)
                        ))
                    except Exception:
                        continue

                if not coin_objs:
                    continue

                leader = leader_map.get(category, "")
                if leader:
                    leader = str(leader).upper()
                else:
                    leader = coin_objs[0].symbol

                sector_data[category] = SectorData(
                    sector=category,
                    coins=coin_objs,
                    leader_coin=leader
                )

            if not sector_data:
                return

            # 计算权重（0-1）
            weights = self.rotation_manager.calculate_sector_weights(
                sector_data=sector_data,
                btc_data=btc_df,
                current_time=datetime.now(),
                leader_coins=leader_map
            )

            # 转换为“等权=1.0”的倍数，并提取层级
            n = len(weights) if weights else 0
            base = (1.0 / n) if n > 0 else 0.0
            multipliers: Dict[str, float] = {}
            tiers: Dict[str, str] = {}
            for cat, w in weights.items():
                if base > 0:
                    multipliers[cat] = max(0.2, float(w) / base)
                tier = self.rotation_manager.get_sector_tier(cat)
                if tier:
                    tiers[cat] = tier.value

            # 注入 TraderV2（开仓金额/评分加成使用）
            self.trader.set_rotation_context(multipliers, tiers)

        except Exception as e:
            logging.warning(f"⚠️ 更新板块轮动上下文失败: {e}")
    
    def _process_trade_signals(self, trade_signals: List[TradeSignal]):
        """处理交易信号"""
        # 检查交易功能是否启用
        if not self.trade_enabled:
            logging.info("⏸️ 交易功能已禁用，跳过交易信号处理")
            return
        
        for signal in trade_signals:
            try:
                logging.info(f"💼 处理交易信号: {signal.trigger_coin_name} 触发")
                logging.info(f"   目标币种: {len(signal.target_coins)} 个")
                
                # 按跟涨百分比排序 (跟涨最少的优先)
                sorted_targets = sorted(signal.target_coins, key=lambda x: x[1])
                
                for symbol, follow_percentage in sorted_targets:
                    # 检查是否还能开仓
                    if len(self.trader.positions) >= self.trader.max_positions:
                        logging.info(f"⛔ 已达最大持仓数，停止开仓")
                        break
                    
                    # P0优化：检查是否允许交易（市场异常、风险限制等）
                    allowed, reason = self.trader.is_trading_allowed()
                    if not allowed:
                        logging.info(f"⏸️ 风险控制暂停交易: {reason}")
                        continue
                    
                    if self._market_anomaly_paused:
                        logging.info(f"⏸️ 市场异常检测暂停交易，跳过 {symbol}")
                        continue

                    # V8 Mode Full：更新预热状态（K线数）并检查是否允许交易
                    try:
                        df = self.trader.get_klines(symbol)
                        if df is not None:
                            self.mode_full_manager.update_indicator_data(symbol, df)
                        can_trade, reason = self.mode_full_manager.can_trade(symbol)
                        if not can_trade:
                            logging.info(f"⏭️ 跳过 {symbol}: {reason}")
                            continue
                    except Exception:
                        # Mode Full 检查失败则不阻塞主流程，但仍然继续后续风控（TraderV2 本身还有黑名单/限额等）
                        pass
                    
                    # P0优化：检查是否允许交易（市场异常、风险限制等）
                    allowed, reason = self.trader.is_trading_allowed()
                    if not allowed:
                        logging.info(f"⏸️ 风险控制暂停交易: {reason}")
                        continue
                    
                    if self._market_anomaly_paused:
                        logging.info(f"⏸️ 市场异常检测暂停交易，跳过 {symbol}")
                        continue
                    
                    # 尝试开仓
                    position = self.trader.open_position(
                        symbol=symbol,
                        category=signal.category,
                        trigger_change=signal.trigger_change,
                        coin_change=follow_percentage
                    )
                    
                    if position:
                        # 优化：记录开仓统计
                        self._cycle_stats['positions_opened'] += 1
                        
                        # 记录开仓
                        self.recorder.add_trade_record(
                            symbol=symbol,
                            entry_price=position.entry_price,
                            quantity=position.quantity,
                            amount=position.margin,
                            category=signal.category,
                            entry_time=position.entry_time
                        )
                        
                        # 发送通知
                        mode_str = "实盘" if self.is_real_trading else "虚拟"
                        # 尽量带上余额信息（虚拟用本地余额；实盘尽量实时查询）
                        balance = None
                        try:
                            if self.is_real_trading and getattr(self.trader, "binance_api", None):
                                balance = self.trader.binance_api.get_balance()
                            else:
                                balance = getattr(self.trader, "virtual_balance", None)
                        except Exception:
                            balance = None
                        self.notifier.send_order_execution(
                            symbol, 
                            position.margin, 
                            position.order_id, 
                            True, 
                            f"V3-{mode_str}",
                            balance=balance,
                            entry_price=position.entry_price,
                            quantity=position.quantity,
                            leverage=position.leverage,
                            category=signal.category,
                            signal_score=position.signal_score
                        )
                        
            except Exception as e:
                logging.error(f"❌ 处理交易信号失败: {e}")
                import traceback
                logging.error(traceback.format_exc())
    
    def _check_market_anomalies(self):
        """
        P0优化：市场异常检测（闪崩保护、流动性检测）
        """
        if not self.market_anomaly_enabled:
            return
        
        try:
            now = datetime.now()
            window_start = now - timedelta(minutes=self.flash_crash_window_minutes)
            
            # 检查所有活跃持仓和监控币种
            symbols_to_check = set(self.trader.positions.keys())
            
            # 添加监控分类中的币种
            for category in self.enabled_categories:
                try:
                    coins = self.fetcher.get_top_coins_by_category(category, 3)
                    for coin in coins:
                        symbol = coin.get('id') or coin.get('symbol', '')
                        if symbol:
                            symbols_to_check.add(symbol.upper())
                except Exception:
                    continue
            
            flash_crash_detected = False
            liquidity_issue_detected = False
            
            for symbol in symbols_to_check:
                try:
                    # 1. 闪崩检测：5分钟内价格下跌>20%
                    current_price = self.trader.get_current_price(symbol)
                    if current_price and current_price > 0:
                        # 更新价格历史
                        if symbol not in self._price_history:
                            self._price_history[symbol] = []
                        self._price_history[symbol].append((now, current_price))
                        
                        # 清理过期数据
                        self._price_history[symbol] = [
                            (t, p) for t, p in self._price_history[symbol]
                            if t >= window_start
                        ]
                        
                        # 检查闪崩
                        if len(self._price_history[symbol]) >= 2:
                            prices = [p for _, p in self._price_history[symbol]]
                            max_price = max(prices)
                            min_price = min(prices)
                            if max_price > 0:
                                drop_pct = ((max_price - min_price) / max_price) * 100
                                if drop_pct >= self.flash_crash_threshold:
                                    flash_crash_detected = True
                                    logging.error("=" * 60)
                                    logging.error(f"🚨 闪崩检测！{symbol} 在{self.flash_crash_window_minutes}分钟内下跌 {drop_pct:.2f}%")
                                    logging.error("🚨 触发闪崩保护，暂停新开仓，收紧止损到2%")
                                    logging.error("=" * 60)
                                    # 收紧该币种的止损（如果持有）
                                    if symbol in self.trader.positions:
                                        pos = self.trader.positions[symbol]
                                        if pos.current_stop_loss_pct > 2.0:
                                            pos.current_stop_loss_pct = 2.0
                                            pos.stop_loss_type = "flash_crash_protection"
                    
                    # 2. 流动性检测：成交量突然下降（优化：减少误报）
                    try:
                        df = self.trader.get_klines(symbol, interval='5m', limit=20)
                        if df is not None and not df.empty and 'volume' in df.columns:
                            volumes = pd.to_numeric(df['volume'], errors='coerce').dropna()
                            if len(volumes) >= 15:
                                # 优化1：使用更长的历史数据（最近15条的平均值）
                                avg_vol = float(volumes.iloc[-15:].mean())
                                
                                # 优化2：检查最近3条K线的平均成交量（避免单根K线异常）
                                recent_vol = float(volumes.iloc[-3:].mean())
                                
                                # 优化3：添加最小成交量阈值（避免小币种误报）
                                if avg_vol < self.liquidity_min_volume_threshold:
                                    # 小币种，跳过检测
                                    continue
                                
                                if avg_vol > 0:
                                    vol_drop_pct = ((avg_vol - recent_vol) / avg_vol) * 100
                                    
                                    # 优化4：需要连续下降（最近3根都低于平均值）
                                    recent_all_below = all(volumes.iloc[-3:].values < avg_vol * 0.5)
                                    
                                    # 优化5：下降幅度需要超过阈值，且是连续下降
                                    if vol_drop_pct >= self.liquidity_drop_threshold and recent_all_below:
                                        liquidity_issue_detected = True
                                        logging.warning(f"⚠️ 流动性异常：{symbol} 成交量下降 {vol_drop_pct:.2f}% (最近3根均低于平均值50%)")
                    except Exception:
                        pass
                        
                except Exception as e:
                    logging.debug(f"市场异常检测失败 {symbol}: {e}")
                    continue
            
            # 更新暂停状态
            if flash_crash_detected or liquidity_issue_detected:
                if not self._market_anomaly_paused:
                    self._market_anomaly_paused = True
                    self.trade_enabled = False
                    logging.warning("⚠️ 市场异常检测暂停交易")
            else:
                # 如果之前暂停了，现在恢复正常，可以解除暂停（但需要手动确认）
                # 这里保守处理：不自动解除，需要等待一段时间
                if self._market_anomaly_paused:
                    # 可以添加一个时间窗口，比如30分钟后自动解除
                    pass
                    
        except Exception as e:
            logging.error(f"❌ 市场异常检测异常: {e}")
    
    def _run_adaptive_learning(self):
        """运行自适应学习分析（优化：增加超时保护）"""
        if not self.learning_engine or not ADAPTIVE_LEARNING_AVAILABLE:
            return
        
        # 检查是否需要运行分析
        now = datetime.now()
        if self._last_learning_analysis_time:
            elapsed = (now - self._last_learning_analysis_time).total_seconds() / 60
            if elapsed < self._learning_analysis_interval_minutes:
                return
        
        # 优化：如果监控周期已经耗时过长，跳过本次学习分析
        if hasattr(self, '_current_cycle_time'):
            if self._current_cycle_time > self.monitor_interval * 60 * 0.4:  # 如果已耗时超过40%
                logging.debug("⏭️ 跳过自适应学习分析（监控周期耗时过长）")
                return
        
        try:
            # 1. 获取BTC数据用于市场分析
            btc_df = None
            try:
                btc_list = self.fetcher.get_top_coins_by_category("Layer1", 1)
                if btc_list:
                    btc_coin = btc_list[0]
                    btc_symbol = btc_coin.get('id') or btc_coin.get('symbol', 'BTCUSDT')
                    btc_df = self.trader.get_klines(btc_symbol, interval=BACKTEST_INTERVAL, limit=100)
            except Exception as e:
                logging.debug(f"获取BTC数据失败: {e}")
            
            # 2. 分析市场状态
            market_regime = self.learning_engine.market_analyzer.analyze_market_regime(btc_df)
            
            # 3. 分析交易表现
            performance = self.learning_engine.performance_analyzer.analyze_performance(
                self.trader.trade_history
            )
            
            # 4. 构建当前配置
            current_config = {
                'stop_loss': V2_STOP_LOSS,
                'take_profit': V2_TAKE_PROFIT,
                'signal_min_score': SIGNAL_MIN_SCORE,
                'category_weights': CATEGORY_WEIGHT_ADJUSTMENTS
            }
            
            # 5. 生成优化建议
            suggestions = self.learning_engine.generate_optimization_suggestions(
                market_regime, performance, current_config
            )
            
            # 6. 生成并输出报告
            if suggestions or performance.total_trades >= 10:
                report = self.learning_engine.get_summary_report(
                    market_regime, performance, suggestions
                )
                logging.info("\n" + report)
                
                # 保存分析结果
                self.learning_engine.save_analysis()
            
            self._last_learning_analysis_time = now
            
        except Exception as e:
            logging.error(f"❌ 自适应学习分析失败: {e}")
            import traceback
            logging.debug(traceback.format_exc())
    
    def _display_status(self):
        """显示交易状态"""
        # 限频：避免每个监控周期刷屏
        try:
            interval_min = max(1, int(STATUS_LOG_INTERVAL_MINUTES))
        except Exception:
            interval_min = 5
        if self._last_status_log_time is not None:
            if (datetime.now() - self._last_status_log_time).total_seconds() < interval_min * 60:
                return
        self._last_status_log_time = datetime.now()

        summary = self.trader.get_performance_summary()
        
        logging.info("\n" + "=" * 60)
        logging.info("📊 LiveTraderV3 交易状态")
        logging.info("=" * 60)
        logging.info(f"💰 初始资金: {summary['initial_balance']:,.2f} USDT")
        logging.info(f"💵 当前余额: {summary['current_balance']:,.2f} USDT")
        logging.info(f"📈 已实现盈亏: {summary['total_pnl']:+,.2f} USDT")
        logging.info(f"📊 未实现盈亏: {summary['unrealized_pnl']:+,.2f} USDT")
        logging.info(f"💎 总权益: {summary['total_equity']:,.2f} USDT")
        logging.info(f"📈 ROI: {summary['roi_percentage']:+.2f}%")
        logging.info("-" * 60)
        logging.info(f"📋 总交易: {summary['total_trades']} 次")
        logging.info(f"✅ 盈利: {summary['winning_trades']} 次")
        logging.info(f"❌ 亏损: {summary['losing_trades']} 次")
        logging.info(f"🎯 胜率: {summary['win_rate']:.1f}%")
        logging.info(f"📦 活跃持仓: {summary['active_positions']}/{self.trader.max_positions}")
        
        if summary['exit_reasons']:
            logging.info("-" * 60)
            logging.info("📊 平仓原因统计:")
            for reason, data in summary['exit_reasons'].items():
                logging.info(f"   {reason}: {data['count']}次, 盈亏: {data['pnl']:+.2f}")
        
        if summary['dynamic_blacklist']:
            logging.info("-" * 60)
            logging.info(f"⛔ 动态黑名单: {', '.join(summary['dynamic_blacklist'])}")
        
        logging.info("=" * 60)
        
        # 显示活跃持仓详情
        if self.trader.positions:
            logging.info("\n📦 活跃持仓详情:")
            for symbol, pos in self.trader.positions.items():
                holding_hours = (datetime.now() - pos.entry_time).total_seconds() / 3600
                emoji = "📈" if pos.unrealized_pnl >= 0 else "📉"
                logging.info(f"   {emoji} {symbol} [{pos.category}]")
                logging.info(f"      入场: {pos.entry_price:.6f}, 当前: {pos.current_price:.6f}")
                logging.info(f"      盈亏: {pos.unrealized_pnl:+.2f} ({pos.unrealized_pnl_pct:+.2f}%)")
                logging.info(f"      持仓: {holding_hours:.1f}h, 评分: {pos.signal_score:.0f}")
    
    def _is_duplicate_alert(self, alert: PriceAlert) -> bool:
        """检查是否为重复警报"""
        recent_time = datetime.now().timestamp() - 3600  # 1小时内
        
        recent_alerts = self.alert_history[-50:] if len(self.alert_history) > 50 else self.alert_history
        
        for old_alert in recent_alerts:
            if (old_alert.coin_id == alert.coin_id and 
                old_alert.time_window == alert.time_window and
                old_alert.alert_type == alert.alert_type and
                old_alert.timestamp.timestamp() > recent_time):
                return True
        return False
    
    def start(self):
        """启动实时交易系统"""
        logging.info("\n🚀 启动 LiveTraderV3 实时交易系统...")
        logging.info(f"📡 监控间隔: {self.monitor_interval} 分钟")
        logging.info(f"📂 监控分类: {', '.join(self.enabled_categories)}")
        
        # 实盘模式最终确认
        if self.is_real_trading:
            logging.warning("=" * 60)
            logging.warning("⚠️  实盘交易模式 - 最终确认")
            logging.warning("=" * 60)
            logging.warning("系统将在5秒后启动实盘交易...")
            logging.warning("如需取消，请立即按 Ctrl+C")
            logging.warning("=" * 60)
            try:
                time.sleep(5)
            except KeyboardInterrupt:
                logging.info("🛑 用户取消启动")
                return
        
        # 立即执行一次
        self.run_monitoring_cycle()
        
        # 设置定时任务
        schedule.every(self.monitor_interval).minutes.do(self.run_monitoring_cycle)
        
        # 每小时保存交易记录
        schedule.every(1).hours.do(lambda: self.recorder._save_to_excel())
        
        mode_str = "实盘" if self.is_real_trading else "虚拟"
        logging.info(f"✅ 实时交易系统已启动 ({mode_str}模式)，开始定时监控...")
        
        # 主循环
        while True:
            try:
                schedule.run_pending()
                time.sleep(1)
            except KeyboardInterrupt:
                logging.info("🛑 交易系统被用户中断")
                self.recorder._save_to_excel()
                self.trader.display_status()
                break
            except Exception as e:
                logging.error(f"❌ 主循环错误: {e}")
                import traceback
                logging.error(traceback.format_exc())
                time.sleep(60)


# 需要导入 timedelta
from datetime import timedelta


if __name__ == "__main__":
    try:
        setup_logging()
        
        # 创建并启动实时交易系统
        trader = LiveTraderV3(initial_balance=20000)
        trader.start()
        
    except Exception as e:
        logging.exception("程序启动失败: %s", e)
