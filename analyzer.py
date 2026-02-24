import pandas as pd
from typing import Dict, List, Tuple
from datetime import datetime, timedelta
import logging
from config import EXCHANGE, MONITOR_CONFIG, MAX_ALERT_ABS_CHANGE_5M, DINGTALK_NOTIFY_ALERTS

logger = logging.getLogger(__name__)

class PriceAlert:
    """价格警报类"""
    def __init__(self, coin_id: str, coin_name: str, category: str, current_price: float,
                 price_change: float, change_percentage: float, time_window: str,
                 volume: float, timestamp: datetime, alert_type: str):
        self.coin_id = coin_id
        self.coin_name = coin_name
        self.category = category
        self.current_price = current_price
        self.price_change = price_change
        self.change_percentage = change_percentage
        self.time_window = time_window
        self.volume = volume
        self.timestamp = timestamp
        self.alert_type = alert_type  # 'surge'=暴涨, 'drop'=暴跌
    
    def __repr__(self):
        return f"PriceAlert({self.coin_name}, {self.change_percentage:+.2f}%, {self.time_window}, {self.alert_type})"

class TradeSignal:
    """交易信号类"""
    def __init__(self, trigger_coin: str, trigger_coin_name: str, category: str, 
                 change_percentage: float, target_coins: List[Tuple[str, float]], timestamp: datetime):
        self.trigger_coin = trigger_coin
        self.trigger_coin_name = trigger_coin_name
        self.category = category
        self.change_percentage = change_percentage
        self.target_coins = target_coins  # [(symbol, 跟涨百分比)]
        self.timestamp = timestamp
    
    def __repr__(self):
        target_info = ", ".join([f"{coin[0]}({coin[1]:.1f}%)" for coin in self.target_coins])
        return f"TradeSignal({self.trigger_coin_name}, {self.change_percentage:+.2f}%, 目标: {target_info})"

class CryptoAnalyzer:
    def __init__(self, config: Dict):
        self.config = config
        self.threshold_map = config.get('threshold_map', {})
        self.leader_coins = config.get('leader_coins', {})
        self.follow_threshold = config.get('follow_threshold', 50)  # 跟涨阈值
        self.category_thresholds = config.get('category_thresholds', {}) or {}
        self.threshold_default = config.get('threshold_default', config.get('price_change_threshold', 5.0))
        self.signal_trigger_interval = config.get('signal_trigger_interval', '5m')
        self.trade_leader_coin = bool(config.get('trade_leader_coin', False))
        
    def calculate_price_changes(self, current_data: Dict, historical_data: pd.DataFrame, interval: str) -> Dict[str, float]:
        """计算指定时间间隔的价格变化"""
        changes = {}
        try:
            current_price = float(current_data.get('current_price', 0) or 0)
        except Exception:
            current_price = 0.0
        current_time = datetime.now()
        
        if historical_data.empty:
            logger.debug("历史数据为空，无法计算价格变化")
            return changes
            
        # 根据时间间隔计算变化（支持 5m/15m/1h/4h/24h）
        time_ago = current_time - self._get_time_delta(interval)
            
        # 找到指定时间点的价格
        historical_data_filtered = historical_data[historical_data.index <= time_ago]
        if not historical_data_filtered.empty:
            # 使用最接近指定时间的价格
            try:
                historical_price = float(historical_data_filtered.iloc[-1]['close'])
                if current_price > 0 and historical_price > 0:  # 确保价格有效
                    change_percentage = ((current_price - historical_price) / historical_price) * 100
                    changes[interval] = change_percentage
                    logger.debug("价格变化计算: %s - %s = %.2f%%", current_price, historical_price, change_percentage)
                else:
                    logger.debug("价格无效: current=%s historical=%s", current_price, historical_price)
            except Exception as e:
                logger.debug("计算价格变化时出错: %s", e)
        else:
            logger.debug("在指定时间点 %s 之前没有历史数据", time_ago)
            
        return changes
    
    def detect_price_alerts(self, coin_data: Dict, category: str, fetcher) -> List[PriceAlert]:
        """检测价格异常变动（包括暴涨和暴跌）"""
        alerts = []
        
        # 获取配置的时间窗口
        time_windows = self.config.get('time_windows', ['5m'])
        
        for time_window in time_windows:
            try:
                logger.debug("获取 %s 的 %s 历史数据...", coin_data.get('name'), time_window)
                # 获取对应时间间隔的历史数据
                historical_data = fetcher.get_price_history(coin_data['id'], time_window)
                
                if historical_data.empty:
                    logger.debug("%s 的历史数据为空", coin_data.get('name'))
                    continue
                
                logger.debug("获取到 %d 条历史数据", len(historical_data))
                
                # 计算价格变化
                price_changes = self.calculate_price_changes(coin_data, historical_data, time_window)
                
                for interval, change_percentage in price_changes.items():
                    # 异常数据过滤：短周期涨跌幅过大通常是数据错配/缺失导致的“误报”
                    # 规则：以 5m 的上限为基准，按时间窗口线性放大（15m = 3x）
                    try:
                        td = self._get_time_delta(interval)
                        minutes = max(1.0, float(td.total_seconds() / 60.0))
                    except Exception:
                        minutes = 5.0
                    max_abs = float(MAX_ALERT_ABS_CHANGE_5M) * (minutes / 5.0)
                    if abs(change_percentage) > max_abs:
                        logger.debug(
                            "跳过异常警报: %s %s %.2f%% (>%.2f%%)",
                            coin_data.get('name'), interval, change_percentage, MAX_ALERT_ABS_CHANGE_5M
                        )
                        continue

                    # 获取该时间窗口的阈值
                    # 监控阈值优先级：
                    # 1) 触发窗口使用“分类阈值”（对齐回测 V6）
                    # 2) 全局 interval 阈值（threshold_map）
                    # 3) 全局默认阈值（threshold_default / price_change_threshold）
                    if interval == self.signal_trigger_interval:
                        threshold = float(self.category_thresholds.get(category, self.threshold_default))
                    else:
                        threshold = float(self.threshold_map.get(interval, self.threshold_default))
                    drop_threshold = self.config.get('price_drop_threshold', -5.0)
                    
                    logger.debug(
                        "%s %s 变化: %.2f%%, 阈值: %.2f%%",
                        coin_data.get('name'), interval, change_percentage, threshold
                    )
                    
                    # 计算历史价格
                    time_ago = datetime.now() - self._get_time_delta(interval)
                    historical_data_filtered = historical_data[historical_data.index <= time_ago]
                    if historical_data_filtered.empty:
                        continue
                        
                    historical_price = historical_data_filtered.iloc[-1]['close']
                    price_change = coin_data.get('current_price', 0) - historical_price
                    
                    # 检测暴涨
                    if change_percentage >= threshold:
                        alert = PriceAlert(
                            coin_id=coin_data.get('id', ''),
                            coin_name=coin_data.get('name', ''),
                            category=category,
                            current_price=coin_data.get('current_price', 0),
                            price_change=price_change,
                            change_percentage=change_percentage,
                            time_window=interval,
                            volume=coin_data.get('total_volume', 0),
                            timestamp=datetime.now(),
                            alert_type='surge'
                        )
                        alerts.append(alert)
                        # 默认不推送价格警报时，不要用 INFO 刷屏
                        if bool(DINGTALK_NOTIFY_ALERTS):
                            logger.info(
                                "检测到暴涨警报: %s [%s] %.2f%% (%s)",
                                coin_data.get('name'), category, change_percentage, interval
                            )
                        else:
                            logger.debug(
                                "检测到暴涨警报(未推送): %s [%s] %.2f%% (%s)",
                                coin_data.get('name'), category, change_percentage, interval
                            )
                    
                    # 检测暴跌
                    elif change_percentage <= drop_threshold:
                        alert = PriceAlert(
                            coin_id=coin_data.get('id', ''),
                            coin_name=coin_data.get('name', ''),
                            category=category,
                            current_price=coin_data.get('current_price', 0),
                            price_change=price_change,
                            change_percentage=change_percentage,
                            time_window=interval,
                            volume=coin_data.get('total_volume', 0),
                            timestamp=datetime.now(),
                            alert_type='drop'
                        )
                        alerts.append(alert)
                        if bool(DINGTALK_NOTIFY_ALERTS):
                            logger.info(
                                "检测到暴跌警报: %s [%s] %.2f%% (%s)",
                                coin_data.get('name'), category, change_percentage, interval
                            )
                        else:
                            logger.debug(
                                "检测到暴跌警报(未推送): %s [%s] %.2f%% (%s)",
                                coin_data.get('name'), category, change_percentage, interval
                            )
            except Exception as e:
                logger.debug("检测%s时间窗口警报失败: %s", time_window, e)
                continue
                    
        return alerts
    
    def generate_trade_signal(self, alert: PriceAlert, all_coins_in_category: List[Dict], fetcher) -> TradeSignal:
        """生成交易信号 - 检查跟涨情况（默认对齐回测：龙头币只触发不交易）"""
        target_coins = []
        
        logger.debug("检查 %s 分类下币种的交易机会...", alert.category)
        
        # 检查所有币种（包括龙头币）
        for coin in all_coins_in_category:
            coin_symbol = coin.get('id')
            
            # 获取该币种的价格变化
            try:
                # 龙头币处理：默认不交易（对齐回测 backtester_v2: 龙头币不参与交易，只作为信号触发器）
                if coin_symbol == alert.coin_id:
                    if self.trade_leader_coin:
                        logger.info("龙头币加入交易目标(已启用): %s [%s]", coin_symbol, alert.category)
                        target_coins.append((coin_symbol, 100.0))
                    else:
                        logger.debug("龙头币仅触发不交易: %s [%s]", coin_symbol, alert.category)
                    continue
                
                logger.debug("检查 %s 的跟涨情况...", coin_symbol)
                historical_data = fetcher.get_price_history(coin_symbol, alert.time_window)
                if not historical_data.empty:
                    price_changes = self.calculate_price_changes(coin, historical_data, alert.time_window)
                    coin_change = price_changes.get(alert.time_window, 0)
                    
                    # 计算跟涨百分比（相对于触发币种）
                    follow_percentage = (coin_change / alert.change_percentage) * 100 if alert.change_percentage != 0 else 0
                    
                    logger.debug("%s 跟涨幅度: %.1f%% (阈值: %.1f%%)", coin_symbol, follow_percentage, self.follow_threshold)
                    
                    # 如果跟涨幅度小于阈值，则加入交易目标
                    if follow_percentage < self.follow_threshold:
                        target_coins.append((coin_symbol, follow_percentage))
                        logger.debug("%s 加入交易目标（跟涨不足）", coin_symbol)
                    else:
                        logger.debug("%s 跟涨充足，不加入交易目标", coin_symbol)
                    
            except Exception as e:
                logger.debug("检查 %s 跟涨情况失败: %s", coin_symbol, e)
                continue
        
        logger.info("交易目标生成: %s [%s] 目标 %d 个", alert.trigger_coin_name, alert.category, len(target_coins))
        return TradeSignal(
            trigger_coin=alert.coin_id,
            trigger_coin_name=alert.coin_name,
            category=alert.category,
            change_percentage=alert.change_percentage,
            target_coins=target_coins,
            timestamp=datetime.now()
        )
    
    def is_leader_coin(self, coin_symbol: str, category: str) -> bool:
        """检查是否为龙头币种"""
        leader_coin = self.leader_coins.get(category)
        is_leader = coin_symbol == leader_coin
        if is_leader:
            logger.debug("%s 是 %s 分类的龙头币种", coin_symbol, category)
        return is_leader
    
    def _get_time_delta(self, interval: str) -> timedelta:
        """获取时间间隔对应的timedelta"""
        if interval == '5m':
            return timedelta(minutes=5)
        elif interval == '15m':
            return timedelta(minutes=15)
        elif interval == '1h':
            return timedelta(hours=1)
        elif interval == '4h':
            return timedelta(hours=4)
        elif interval == '24h':
            return timedelta(hours=24)
        else:
            return timedelta(minutes=5)