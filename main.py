import schedule
import time
import logging
import sys
from datetime import datetime
from typing import Dict, List
import traceback

from config import (
    CRYPTO_CATEGORIES, MONITOR_CONFIG, EXCHANGE, DINGTALK_WEBHOOK,
    SYMBOL_BLACKLIST, CATEGORY_WEIGHT_ADJUSTMENTS, CATEGORY_BLACKLIST,
    STRATEGY_OPTIMIZATION_ENABLED,
    PERIODIC_RESET_ENABLED, PERIODIC_RESET_INTERVAL_DAYS,
    V8_CONFIG
)
from data_fetcher import create_data_fetcher
from analyzer import CryptoAnalyzer, PriceAlert, TradeSignal
from notifier import DingTalkNotifier
from trader import VirtualTrader
from trade_recorder import TradeRecorder
from live_mode_full import create_live_mode_full_manager, LiveModeFullManager

class SafeStreamHandler(logging.StreamHandler):
    """安全的流处理器，处理编码问题"""
    
    def emit(self, record):
        try:
            msg = self.format(record)
            # 替换或移除表情符号
            msg = self._safe_encode(msg)
            stream = self.stream
            enc = getattr(stream, "encoding", None) or "utf-8"
            msg = msg.encode(enc, errors="replace").decode(enc, errors="replace")
            stream.write(msg + self.terminator)
            self.flush()
        except Exception:
            self.handleError(record)
    
    def _safe_encode(self, text):
        """安全编码处理"""
        # 替换常见表情符号为文本
        emoji_map = {
            # 用 ASCII 标签替换 emoji，避免 Windows 控制台默认编码写入失败
            '🔍': '[SCAN]', '🚀': '[START]', '📊': '[DATA]', '✅': '[OK]',
            '❌': '[ERR]', '⚠️': '[WARN]', '🚨': '[ALERT]', '💼': '[TRADE]',
            '🎯': '[TARGET]', '📈': '[UP]', '📉': '[DOWN]', '💰': '[P&L]',
            '💸': '[LOSS]', '📦': '[ACTIVE]', '📋': '[TOTAL]', '📂': '[CAT]',
            '🐲': '[LEADER]', '🔮': '[VIRTUAL]', '⏹️': '[STOP]', '⏭️': '[SKIP]',
            '🔒': '[SSL]', '🔗': '[LINK]', '⏰': '[TIMEOUT]', '🏦': '[EXCHANGE]',
            '📢': '[NOTIFY]', '🚫': '[LIMIT]', '💳': '[BAL]', '🔄': '[RETRY]',
            '🌐': '[NET]', '🔑': '[KEY]', '📜': '[LOG]', '🔧': '[CFG]',
            '📡': '[MON]', '⚙️': '[SET]', '🖥️': '[SYS]', '🎉': '[DONE]',
            '🛑': '[STOP]', '🔄': '[REFRESH]', '⏸️': '[PAUSE]'
        }
        
        for emoji, text_replacement in emoji_map.items():
            text = text.replace(emoji, text_replacement)
        return text

def setup_logging():
    """安全地设置日志配置"""
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    
    # 清除现有的处理器
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
    
    # 文件处理器 - 使用UTF-8编码
    file_handler = logging.FileHandler('crypto_monitor.log', encoding='utf-8')
    file_handler.setLevel(logging.INFO)
    
    # 控制台处理器 - 使用安全的处理器
    console_handler = SafeStreamHandler()
    console_handler.setLevel(logging.INFO)
    
    # 格式化器
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)
    
    # 添加处理器
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    return logger

# === 删除原有的 logging.basicConfig 配置 ===
# 注释掉或删除以下代码：
# logging.basicConfig(
#     level=logging.INFO,
#     format='%(asctime)s - %(levelname)s - %(message)s',
#     handlers=[
#         logging.FileHandler('crypto_monitor.log'),
#         logging.StreamHandler()
#     ]
# )

class ActiveTrade:
    """活跃交易类"""
    def __init__(self, symbol: str, entry_price: float, quantity: float, 
                 category: str, timestamp: datetime):
        self.symbol = symbol
        self.entry_price = entry_price
        self.quantity = quantity
        self.category = category
        self.timestamp = timestamp
        self.current_price = entry_price
        self.profit_loss = 0.0
        self.profit_loss_percentage = 0.0

class CryptoMonitor:
    def __init__(self, offline_mode: bool = False):
        self.fetcher = create_data_fetcher()
        # 兼容 start.py 的 offline_mode：若 fetcher 支持该属性则启用
        if hasattr(self.fetcher, "offline_mode"):
            try:
                self.fetcher.offline_mode = bool(offline_mode)
            except Exception:
                pass
        self.analyzer = CryptoAnalyzer(MONITOR_CONFIG)
        self.notifier = DingTalkNotifier()
        self.trader = VirtualTrader()
        self.recorder = TradeRecorder()
        self.alert_history = []
        self.active_trades = {}  # symbol -> ActiveTrade
        self.trade_signals_history = []
        self.category_positions = {}  # 每个分类的持仓数量
        
        # 策略优化配置
        self.strategy_optimization_enabled = STRATEGY_OPTIMIZATION_ENABLED
        self.symbol_blacklist = set(SYMBOL_BLACKLIST) if STRATEGY_OPTIMIZATION_ENABLED else set()
        self.category_blacklist = set(CATEGORY_BLACKLIST) if STRATEGY_OPTIMIZATION_ENABLED else set()
        self.category_weights = CATEGORY_WEIGHT_ADJUSTMENTS if STRATEGY_OPTIMIZATION_ENABLED else {}
        
        # V8: Mode Full 管理器 (复刻 --mode full 高收益机制)
        self.mode_full_manager: LiveModeFullManager = create_live_mode_full_manager(V8_CONFIG)
        
        # V7: 定期重置配置 (保留兼容性，实际由 mode_full_manager 管理)
        self.periodic_reset_enabled = PERIODIC_RESET_ENABLED
        self.reset_interval_days = PERIODIC_RESET_INTERVAL_DAYS
        self.last_reset_time = datetime.now()
        self.period_pnl = 0.0
        self.period_trades = 0
        self.period_history = []
        
        # 动态黑名单 (由 mode_full_manager 管理)
        self.dynamic_blacklist = set()
        self.symbol_loss_count = {}  # symbol -> 连续亏损次数
        
        # 初始化分类持仓计数
        for category in MONITOR_CONFIG['enabled_categories']:
            self.category_positions[category] = 0
        
        if self.strategy_optimization_enabled:
            logging.info(f"[配置] 策略优化已启用: 黑名单交易对 {len(self.symbol_blacklist)} 个, 黑名单分类 {len(self.category_blacklist)} 个, 分类权重调整 {len(self.category_weights)} 个")
        
        if self.periodic_reset_enabled:
            logging.info(f"[配置] V8 Mode Full已启用: 每{self.mode_full_manager.periodic_config.interval_days}天重置")
            logging.info(f"[配置] 冷启动: 预热{self.mode_full_manager.cold_start_config.warmup_candles}根K线, 跳过前{self.mode_full_manager.cold_start_config.skip_first_signals}个信号")
        
    def run_monitoring_cycle(self):
        """执行监控周期 - 使用真实数据监控，模拟交易"""
        try:
            # V8: 检查定期重置 (Mode Full 机制)
            if self.mode_full_manager.check_and_perform_reset():
                # 同步重置旧的 V7 状态
                self.dynamic_blacklist.clear()
                self.symbol_loss_count.clear()
                self.last_reset_time = datetime.now()
                self.period_pnl = 0.0
                self.period_trades = 0
            
            # 使用 SafeStreamHandler 处理后的日志输出
            logging.info(f"[启动] 开始监控周期 - {datetime.now()}")
            all_alerts = []
            trade_signals = []
            
            for category in MONITOR_CONFIG['enabled_categories']:
                # 检查分类是否在黑名单中
                if category in self.category_blacklist:
                    logging.info(f"[跳过] 分类 {category} 在黑名单中，跳过监控")
                    continue
                    
                if category not in CRYPTO_CATEGORIES:
                    continue
                    
                logging.info(f"[数据] 监控分类: {category}")
                
                # 获取真实数据
                coins = self.fetcher.get_top_coins_by_category(
                    category, 
                    MONITOR_CONFIG['top_n']
                )
                
                if not coins:
                    logging.warning(f"[失败] 分类 {category} 没有获取到真实数据")
                    continue
                
                logging.info(f"[成功] 获取到 {len(coins)} 个币种的真实数据")
                
                # 过滤黑名单交易对
                filtered_coins = []
                for coin in coins:
                    coin_id = coin.get('id', '')
                    if coin_id in self.symbol_blacklist:
                        logging.info(f"[跳过] 交易对 {coin_id} 在黑名单中")
                        continue
                    filtered_coins.append(coin)
                
                if len(filtered_coins) < len(coins):
                    logging.info(f"[过滤] 过滤后剩余 {len(filtered_coins)} 个币种")
                
                # 存储当前分类的所有币种用于交易信号生成
                category_coins = filtered_coins.copy()
                    
                for coin in filtered_coins:
                    coin_id = coin.get('id')
                    if not coin_id:
                        continue
                        
                    logging.info(f"[搜索] 分析币种: {coin.get('name')} - 价格: {coin.get('current_price', 0):.4f}")
                    
                    # 检测价格警报 - 使用真实数据
                    alerts = self.analyzer.detect_price_alerts(coin, category, self.fetcher)
                    
                    for alert in alerts:
                        if not self._is_duplicate_alert(alert):
                            if self.notifier.send_alert(alert):
                                self.alert_history.append(alert)
                                alert_type = "暴涨" if alert.alert_type == 'surge' else "暴跌"
                                logging.info(f"[警报] 发送{alert_type}警报: {alert.coin_name} {alert.change_percentage:+.2f}% ({alert.time_window})")
                                
                                # 如果是5分钟暴涨警报且交易功能开启，生成交易信号
                                if (alert.alert_type == 'surge' and alert.time_window == '5m' and 
                                    MONITOR_CONFIG.get('trade_enabled', False) and
                                    self.analyzer.is_leader_coin(alert.coin_id, category)):
                                    logging.info(f"[龙头] 龙头币种触发，生成交易信号...")
                                    trade_signal = self.analyzer.generate_trade_signal(alert, category_coins, self.fetcher)
                                    if trade_signal.target_coins:  # 只有有目标币种时才处理
                                        trade_signals.append(trade_signal)
                                        self.trade_signals_history.append(trade_signal)
                                        logging.info(f"[目标] 生成交易信号: {trade_signal}")
                                    else:
                                        logging.info("[失败] 没有找到合适的交易目标")
                            
                            all_alerts.append(alert)
            
            # 处理交易信号 - 使用模拟交易
            if trade_signals and MONITOR_CONFIG.get('trade_enabled', False):
                logging.info(f"[交易] 处理 {len(trade_signals)} 个交易信号 (模拟交易)")
                self._process_trade_signals(trade_signals)
            else:
                logging.info("[跳过] 没有交易信号需要处理")
            
            # 监控活跃交易的止盈止损 - 使用真实价格
            self._monitor_active_trades()
            
            # 显示虚拟交易状态
            self._display_trading_status()
            
            # 统计本周期警报
            surge_count = len([a for a in all_alerts if a.alert_type == 'surge'])
            drop_count = len([a for a in all_alerts if a.alert_type == 'drop'])
            
            if surge_count > 0 or drop_count > 0:
                logging.info(f"[上涨] 监控周期完成，发现 {surge_count} 个暴涨警报，{drop_count} 个暴跌警报")
            else:
                logging.info(f"[成功] 监控周期完成，未发现价格异常")
            
        except Exception as e:
            logging.error(f"[失败] 监控周期执行失败: {e}")
            logging.error(traceback.format_exc())
    
    def _process_trade_signals(self, trade_signals: List[TradeSignal]):
        """处理交易信号 - 使用模拟交易"""
        for signal in trade_signals:
            try:
                # 检查分类持仓限制
                max_positions = MONITOR_CONFIG.get('max_positions_per_category', 5)
                current_positions = self.category_positions.get(signal.category, 0)
                
                if current_positions >= max_positions:
                    logging.info(f"[限制] 分类 {signal.category} 已达到最大持仓限制 ({current_positions}/{max_positions})，跳过交易")
                    continue
                
                # 发送交易信号通知
                self.notifier.send_trade_signal(signal)
                logging.info(f"[虚拟] 处理交易信号: {signal.trigger_coin_name} 触发，发现 {len(signal.target_coins)} 个跟涨不足的币种")
                
                # 执行交易（按跟涨百分比排序，选择跟涨最少的）- 使用模拟交易
                sorted_targets = sorted(signal.target_coins, key=lambda x: x[1])
                available_slots = max_positions - current_positions
                targets_to_trade = sorted_targets[:available_slots]
                
                for symbol, follow_percentage in targets_to_trade:
                    if self._execute_trade(symbol, signal.category):
                        self.category_positions[signal.category] += 1
                        logging.info(f"[成功] 虚拟开仓成功: {symbol}, 分类持仓: {self.category_positions[signal.category]}/{max_positions}")
                    
            except Exception as e:
                logging.error(f"[失败] 处理交易信号失败: {e}")
    
    def _execute_trade(self, symbol: str, category: str) -> bool:
        """执行交易 - 使用模拟交易"""
        try:
            # 检查交易对是否在静态黑名单中
            if symbol in self.symbol_blacklist:
                logging.info(f"[跳过] 交易对 {symbol} 在静态黑名单中，不执行交易")
                return False
            
            # V8: 使用 Mode Full 管理器检查是否可以交易
            can_trade, reason = self.mode_full_manager.can_trade(symbol)
            if not can_trade:
                logging.info(f"[Mode Full] 跳过交易 {symbol}: {reason}")
                return False
            
            # V7 兼容: 检查交易对是否在动态黑名单中
            if self._is_in_dynamic_blacklist(symbol):
                logging.info(f"[跳过] 交易对 {symbol} 在动态黑名单中，不执行交易")
                return False
            
            # 获取基础交易金额
            base_trade_amount = MONITOR_CONFIG.get('trade_amount', 1000)
            
            # 应用分类权重调整交易金额
            category_weight = self.category_weights.get(category, 1.0)
            trade_amount = base_trade_amount * category_weight
            
            if category_weight != 1.0:
                logging.info(f"[权重] 分类 {category} 权重 {category_weight}, 交易金额调整为 {trade_amount:.2f} USDT")
            
            # 下单 - 使用模拟交易
            order_result = self.trader.place_trade(symbol, trade_amount, category)
            
            if order_result and 'orderId' in order_result:
                order_id = order_result['orderId']
                
                # 计算实际成交数量
                if 'executedQty' in order_result:
                    executed_qty = float(order_result['executedQty'])
                else:
                    # 估算数量
                    current_price = self.trader.get_current_price(symbol)
                    executed_qty = trade_amount / current_price if current_price else 0
                
                # 记录活跃交易
                active_trade = ActiveTrade(
                    symbol=symbol,
                    entry_price=float(order_result['fills'][0]['price']),
                    quantity=executed_qty,
                    category=category,
                    timestamp=datetime.now()
                )
                self.active_trades[symbol] = active_trade
                
                # 记录到Excel
                self.recorder.add_trade_record(
                    symbol=symbol,
                    entry_price=active_trade.entry_price,
                    quantity=executed_qty,
                    amount=trade_amount,
                    category=category,
                    entry_time=datetime.now()
                )
                
                # 发送订单执行通知
                self.notifier.send_order_execution(symbol, trade_amount, order_id, True, "虚拟")
                logging.info(f"[虚拟] 虚拟下单成功: {symbol}: {trade_amount} USDT, 订单ID: {order_id}")
                return True
            else:
                self.notifier.send_order_execution(symbol, trade_amount, "失败", False, "虚拟")
                logging.error(f"[失败] 虚拟下单失败 {symbol}")
                return False
                
        except Exception as e:
            logging.error(f"[失败] 执行虚拟交易失败 {symbol}: {e}")
            self.notifier.send_order_execution(symbol, trade_amount, f"错误: {str(e)}", False, "虚拟")
            return False
    
    def _monitor_active_trades(self):
        """监控活跃交易的止盈止损 - 使用真实价格"""
        symbols_to_remove = []
        
        for symbol, trade in list(self.active_trades.items()):
            try:
                # 获取当前价格 - 使用真实数据
                current_price = self.trader.get_current_price(symbol)
                if not current_price:
                    continue
                
                trade.current_price = current_price
                trade.profit_loss_percentage = ((current_price - trade.entry_price) / trade.entry_price) * 100
                trade.profit_loss = (current_price - trade.entry_price) * trade.quantity
                
                take_profit_range = MONITOR_CONFIG.get('take_profit_range', [10, 15])
                stop_loss = MONITOR_CONFIG.get('stop_loss', 10)
                
                close_reason = None
                
                # 检查止盈条件
                if take_profit_range[0] <= trade.profit_loss_percentage <= take_profit_range[1]:
                    close_reason = f"止盈 ({trade.profit_loss_percentage:.2f}%)"
                
                # 检查止损条件
                elif trade.profit_loss_percentage <= -stop_loss:
                    close_reason = f"止损 ({trade.profit_loss_percentage:.2f}%)"
                
                if close_reason:
                    if self._close_trade(trade, close_reason):
                        symbols_to_remove.append(symbol)
                        self.category_positions[trade.category] -= 1
                    
            except Exception as e:
                logging.error(f"[失败] 监控交易 {symbol} 失败: {e}")
        
        # 移除已平仓的交易
        for symbol in symbols_to_remove:
            if symbol in self.active_trades:
                del self.active_trades[symbol]
    
    def _close_trade(self, trade: ActiveTrade, reason: str) -> bool:
        """平仓交易 - 使用模拟交易"""
        try:
            # 执行平仓 - 使用模拟交易
            close_result = self.trader.close_trade(trade.symbol, reason)
            
            if close_result and 'orderId' in close_result:
                # 获取盈亏
                profit_loss = close_result.get('profit_loss', trade.profit_loss)
                is_win = profit_loss > 0
                
                # V8: 记录交易结果到 Mode Full 管理器
                self.mode_full_manager.record_trade(trade.symbol, profit_loss, is_win)
                
                # 如果亏损，设置冷却期
                if not is_win:
                    self.mode_full_manager.set_cooldown(trade.symbol, 30)
                
                # V7 兼容: 更新动态黑名单
                self._update_dynamic_blacklist(trade.symbol, is_win)
                
                # V7 兼容: 更新周期统计
                self.period_pnl += profit_loss
                self.period_trades += 1
                
                # 更新交易记录
                self.recorder.update_trade_record(
                    symbol=trade.symbol,
                    exit_price=trade.current_price,
                    exit_time=datetime.now(),
                    profit_loss=profit_loss,
                    profit_loss_percentage=close_result.get('profit_loss_percentage', trade.profit_loss_percentage),
                    status='closed',
                    close_reason=reason
                )
                
                # 发送交易结果通知
                self.notifier.send_trade_result(
                    trade.symbol,
                    trade.entry_price,
                    trade.current_price,
                    trade.quantity,
                    profit_loss,
                    reason,
                    "虚拟"
                )
                logging.info(f"[虚拟] 虚拟平仓: {trade.symbol}: {reason}, 盈亏: {profit_loss:+.2f} USDT")
                return True
            else:
                logging.error(f"[失败] 虚拟平仓失败 {trade.symbol}")
                return False
                
        except Exception as e:
            logging.error(f"[失败] 虚拟平仓操作失败 {trade.symbol}: {e}")
            return False
    
    def _display_trading_status(self):
        """显示交易状态"""
        performance = self.trader.get_performance_summary()
        stats = self.recorder.get_trade_statistics()
        
        logging.info("=" * 60)
        logging.info("[数据] 交易状态概览 (模拟交易)")
        logging.info(f"[盈利] 初始资金: {performance['initial_balance']:,.2f} USDT")
        logging.info(f"[余额] 当前资金: {performance['current_balance']:,.2f} USDT")
        logging.info(f"[上涨] 总盈亏: {performance['total_profit_loss']:+.2f} USDT")
        logging.info(f"[目标] ROI: {performance['roi_percentage']:+.2f}%")
        logging.info(f"[活跃] 活跃交易: {performance['active_trades_count']} 个")
        logging.info(f"[总计] 总交易次数: {performance['total_trades_count']} 次")
        
        if stats['total_trades'] > 0:
            logging.info(f"[成功] 胜率: {stats['win_rate']:.1f}%")
            logging.info(f"[数据] 盈利交易: {stats['winning_trades']} 次")
            logging.info(f"[下跌] 亏损交易: {stats['losing_trades']} 次")
        
        # 显示分类持仓
        logging.info("[分类] 分类持仓:")
        for category, count in self.category_positions.items():
            max_positions = MONITOR_CONFIG.get('max_positions_per_category', 5)
            logging.info(f"  {category}: {count}/{max_positions}")
        
        # V8: 显示 Mode Full 状态
        mode_full_summary = self.mode_full_manager.get_period_summary()
        logging.info("-" * 60)
        logging.info("[Mode Full] 周期状态:")
        logging.info(f"  周期开始: {mode_full_summary['start_time'].strftime('%Y-%m-%d')}")
        logging.info(f"  距离重置: {mode_full_summary['days_until_reset']} 天")
        logging.info(f"  周期盈亏: {mode_full_summary['total_pnl']:+,.2f} USDT")
        logging.info(f"  周期交易: {mode_full_summary['total_trades']} 次")
        logging.info(f"  周期胜率: {mode_full_summary['win_rate']:.1f}%")
        logging.info(f"  跳过信号: {mode_full_summary['signals_skipped']} 个 (冷启动)")
        logging.info(f"  动态黑名单: {mode_full_summary['blacklist_count']} 个")
        
        logging.info("=" * 60)
    
    def _is_duplicate_alert(self, alert: PriceAlert) -> bool:
        """检查是否为重复警报"""
        recent_time = datetime.now().timestamp() - 3600  # 1小时内
        
        # 只检查最近50个警报
        recent_alerts = self.alert_history[-50:] if len(self.alert_history) > 50 else self.alert_history
        
        for old_alert in recent_alerts:
            if (old_alert.coin_id == alert.coin_id and 
                old_alert.time_window == alert.time_window and
                old_alert.alert_type == alert.alert_type and
                old_alert.timestamp.timestamp() > recent_time):
                return True
        return False
    
    def _check_periodic_reset(self):
        """
        V7: 检查并执行定期重置 - 复刻 --mode full 高收益机制
        
        核心优势:
        1. 定期清空动态黑名单，给交易对"新鲜开始"的机会
        2. 重置连续亏损计数，避免过度惩罚
        3. 模拟 --mode full 每季度重新开始的效果
        """
        if not self.periodic_reset_enabled:
            return
        
        current_time = datetime.now()
        days_since_reset = (current_time - self.last_reset_time).days
        
        if days_since_reset >= self.reset_interval_days:
            self._perform_periodic_reset(current_time)
    
    def _perform_periodic_reset(self, current_time: datetime):
        """
        执行定期重置 - V7新增
        
        重置内容:
        1. 清空动态黑名单
        2. 重置连续亏损计数
        3. 记录周期统计
        """
        # 记录当前周期统计
        period_record = {
            'start_time': self.last_reset_time,
            'end_time': current_time,
            'pnl': self.period_pnl,
            'trades': self.period_trades,
            'dynamic_blacklist_count': len(self.dynamic_blacklist)
        }
        self.period_history.append(period_record)
        
        logging.info("=" * 60)
        logging.info(f"[重置] V7定期重置 - 周期结束")
        logging.info("=" * 60)
        logging.info(f"   周期: {self.last_reset_time.strftime('%Y-%m-%d')} ~ {current_time.strftime('%Y-%m-%d')}")
        logging.info(f"   周期盈亏: {self.period_pnl:+,.2f} USDT")
        logging.info(f"   周期交易: {self.period_trades} 次")
        logging.info(f"   清空动态黑名单: {len(self.dynamic_blacklist)} 个交易对")
        
        # 重置动态黑名单 (核心优化点!)
        self.dynamic_blacklist.clear()
        self.symbol_loss_count.clear()
        
        # 重置周期统计
        self.last_reset_time = current_time
        self.period_pnl = 0.0
        self.period_trades = 0
        
        logging.info(f"[成功] 重置完成，开始新周期")
        logging.info("=" * 60)
    
    def _update_dynamic_blacklist(self, symbol: str, is_win: bool):
        """
        更新动态黑名单 - V7新增
        
        规则:
        - 连续亏损5次加入动态黑名单
        - 盈利则重置亏损计数
        - 定期重置时清空动态黑名单
        """
        if is_win:
            # 盈利，重置亏损计数
            self.symbol_loss_count[symbol] = 0
        else:
            # 亏损，增加计数
            self.symbol_loss_count[symbol] = self.symbol_loss_count.get(symbol, 0) + 1
            
            # 连续亏损5次加入动态黑名单
            if self.symbol_loss_count[symbol] >= 5:
                self.dynamic_blacklist.add(symbol)
                logging.info(f"[黑名单] {symbol} 连续亏损{self.symbol_loss_count[symbol]}次，加入动态黑名单")
    
    def _is_in_dynamic_blacklist(self, symbol: str) -> bool:
        """检查交易对是否在动态黑名单中"""
        return symbol in self.dynamic_blacklist
    
    def start_monitoring(self):
        """启动监控"""
        logging.info("=== 数字货币监控系统启动 ===")
        logging.info(f"[交易所] 交易所: {EXCHANGE.upper()} (Gate.io)")
        logging.info(f"[通知] 钉钉通知: {'[成功] 已配置' if DINGTALK_WEBHOOK else '[失败] 未配置'}")
        logging.info(f"[超时] 监控间隔: {MONITOR_CONFIG.get('monitor_interval', 5)}分钟")
        logging.info(f"[数据] 监控时间窗口: {', '.join(MONITOR_CONFIG.get('time_windows', []))}")
        logging.info(f"[目标] 价格监控: [成功] 使用真实数据")
        
        # 显示策略优化配置
        if self.strategy_optimization_enabled:
            logging.info(f"[优化] 策略优化: [成功] 已启用")
            logging.info(f"   黑名单交易对: {len(self.symbol_blacklist)} 个")
            logging.info(f"   黑名单分类: {len(self.category_blacklist)} 个")
            logging.info(f"   分类权重调整: {len(self.category_weights)} 个")
            # 显示权重调整详情
            for cat, weight in self.category_weights.items():
                if weight > 1.0:
                    logging.info(f"     {cat}: {weight}x (增加)")
                elif weight < 1.0:
                    logging.info(f"     {cat}: {weight}x (降低)")
        else:
            logging.info(f"[优化] 策略优化: [失败] 未启用")
        
        trade_enabled = MONITOR_CONFIG.get('trade_enabled', False)
        
        if trade_enabled:
            logging.info(f"[交易] 自动交易: [成功] 已启用 ([虚拟] 虚拟模式)")
            logging.info(f"[余额] 单币种交易金额: {MONITOR_CONFIG.get('trade_amount', 1000)} USDT")
            logging.info(f"[上涨] 止盈范围: {MONITOR_CONFIG.get('take_profit_range', [10, 15])}%")
            logging.info(f"[下跌] 止损: {MONITOR_CONFIG.get('stop_loss', 10)}%")
            logging.info(f"[限制] 每分类最大持仓: {MONITOR_CONFIG.get('max_positions_per_category', 5)}")
            logging.info(f"[目标] 跟涨阈值: {MONITOR_CONFIG.get('follow_threshold', 50)}%")
            logging.info(f"[余额] 初始虚拟余额: 100,000 USDT")
            
            # 显示龙头币种
            logging.info("[龙头] 龙头币种配置:")
            for category, leader in MONITOR_CONFIG.get('leader_coins', {}).items():
                logging.info(f"  {category}: {leader}")
        else:
            logging.info(f"[交易] 自动交易: [失败] 未启用")
        
        # 立即执行一次
        self.run_monitoring_cycle()
        
        # 设置定时任务
        monitor_interval = MONITOR_CONFIG.get('monitor_interval', 5)
        schedule.every(monitor_interval).minutes.do(self.run_monitoring_cycle)
        
        # 每小时保存一次交易记录
        schedule.every(1).hours.do(lambda: self.recorder._save_to_excel())
        
        logging.info(f"[启动] {EXCHANGE.upper()} 数字货币监控已启动，开始定时监控...")
        
        # 主循环
        while True:
            try:
                schedule.run_pending()
                time.sleep(1)
            except KeyboardInterrupt:
                logging.info("[停止] 监控程序被用户中断")
                # 保存最终交易记录
                self.recorder._save_to_excel()
                break
            except Exception as e:
                logging.error(f"[失败] 监控主循环错误: {e}")
                time.sleep(60)

if __name__ == "__main__":
    try:
        # 首先设置安全的日志配置
        setup_logging()
        
        monitor = CryptoMonitor()
        monitor.start_monitoring()
    except Exception as e:
        # 如果setup_logging失败，使用基本的错误输出
        print(f"程序启动失败: {e}")
        logging.error(f"[失败] 程序启动失败: {e}")