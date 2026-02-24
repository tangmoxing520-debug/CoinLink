"""
回测验证系统 - 用于验证监控策略的有效性
"""
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
import requests
import time
import json

from config import (
    CRYPTO_CATEGORIES, EXCHANGE, MONITOR_CONFIG, 
    BINANCE_FUTURES_API_URL, LEADER_COINS,
    CATEGORY_THRESHOLDS, THRESHOLD_DEFAULT
)


@dataclass
class BacktestTrade:
    """回测交易记录"""
    symbol: str
    category: str
    entry_time: datetime
    entry_price: float
    exit_time: Optional[datetime] = None
    exit_price: Optional[float] = None
    quantity: float = 0.0
    amount: float = 1000.0
    profit_loss: float = 0.0
    profit_loss_pct: float = 0.0
    status: str = 'open'
    trigger_coin: str = ''
    trigger_change: float = 0.0
    exit_reason: str = ''


@dataclass
class BacktestResult:
    """回测结果"""
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
    avg_profit_per_trade: float
    avg_holding_time: float  # 小时
    trades: List[BacktestTrade] = field(default_factory=list)
    equity_curve: List[Tuple[datetime, float]] = field(default_factory=list)


class HistoricalDataFetcher:
    """历史数据获取器"""
    
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0',
            'Accept': 'application/json'
        })
        self.cache = {}  # 缓存历史数据
        
    def get_historical_klines(
        self, 
        symbol: str, 
        interval: str = '5m',
        start_time: datetime = None,
        end_time: datetime = None,
        limit: int = 1000
    ) -> pd.DataFrame:
        """获取历史K线数据"""
        
        cache_key = f"{symbol}_{interval}_{start_time}_{end_time}"
        if cache_key in self.cache:
            return self.cache[cache_key]
        
        try:
            url = f"{BINANCE_FUTURES_API_URL}/klines"
            
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
            data = response.json()
            
            if not data:
                return pd.DataFrame()
            
            df = pd.DataFrame(data, columns=[
                'open_time', 'open', 'high', 'low', 'close', 'volume',
                'close_time', 'quote_volume', 'trades', 'taker_buy_base',
                'taker_buy_quote', 'ignore'
            ])
            
            df['timestamp'] = pd.to_datetime(df['open_time'], unit='ms')
            df.set_index('timestamp', inplace=True)
            
            for col in ['open', 'high', 'low', 'close', 'volume']:
                df[col] = pd.to_numeric(df[col], errors='coerce')
            
            # 计算价格变化百分比
            df['price_change_pct'] = df['close'].pct_change() * 100
            
            self.cache[cache_key] = df
            print(f"✅ 获取 {len(df)} 条历史数据")
            
            time.sleep(0.2)  # 避免请求过快
            return df
            
        except Exception as e:
            print(f"❌ 获取历史数据失败: {e}")
            return pd.DataFrame()
    
    def get_category_historical_data(
        self,
        category: str,
        interval: str = '5m',
        days: int = 7
    ) -> Dict[str, pd.DataFrame]:
        """获取分类下所有币种的历史数据 (按天数)"""
        
        end_time = datetime.now()
        start_time = end_time - timedelta(days=days)
        
        return self.get_category_historical_data_by_date(
            category, interval, start_time, end_time
        )
    
    def get_category_historical_data_by_date(
        self,
        category: str,
        interval: str = '5m',
        start_time: datetime = None,
        end_time: datetime = None
    ) -> Dict[str, pd.DataFrame]:
        """获取分类下所有币种的历史数据 (按日期范围)"""
        
        symbols = CRYPTO_CATEGORIES.get(category, {}).get(EXCHANGE, [])
        result = {}
        
        if end_time is None:
            end_time = datetime.now()
        if start_time is None:
            start_time = end_time - timedelta(days=7)
        
        for symbol in symbols:
            df = self.get_historical_klines(
                symbol, interval, start_time, end_time
            )
            if not df.empty:
                result[symbol] = df
        
        return result


class BacktestEngine:
    """回测引擎"""
    
    def __init__(
        self,
        initial_balance: float = 100000,
        trade_amount: float = 1000,
        take_profit_range: List[float] = [10, 15],
        stop_loss: float = 10,
        follow_threshold: float = 50,
        price_change_threshold: float = 5.0,
        category_thresholds: Dict[str, float] = None
    ):
        self.initial_balance = initial_balance
        self.balance = initial_balance
        self.trade_amount = trade_amount
        self.take_profit_range = take_profit_range
        self.stop_loss = stop_loss
        self.follow_threshold = follow_threshold
        self.price_change_threshold = price_change_threshold
        
        # 分类阈值配置 - Layer1使用1%，其他使用默认阈值
        self.category_thresholds = category_thresholds or CATEGORY_THRESHOLDS
        self.threshold_default = THRESHOLD_DEFAULT
        
        self.trades: List[BacktestTrade] = []
        self.active_trades: Dict[str, BacktestTrade] = {}
        self.equity_curve: List[Tuple[datetime, float]] = []
        self.max_balance = initial_balance
        self.max_drawdown = 0
        
        self.data_fetcher = HistoricalDataFetcher()
    
    def get_category_threshold(self, category: str) -> float:
        """获取分类的阈值"""
        return self.category_thresholds.get(category, self.threshold_default)
    
    def calculate_5m_change(
        self, 
        df: pd.DataFrame, 
        current_idx: int
    ) -> float:
        """计算5分钟价格变化"""
        if current_idx < 1:
            return 0.0
        
        current_price = df.iloc[current_idx]['close']
        prev_price = df.iloc[current_idx - 1]['close']
        
        if prev_price == 0:
            return 0.0
        
        return ((current_price - prev_price) / prev_price) * 100
    
    def detect_surge(
        self,
        symbol: str,
        df: pd.DataFrame,
        idx: int,
        category: str
    ) -> bool:
        """检测是否为龙头币暴涨"""
        leader = LEADER_COINS.get(category)
        
        # 获取该分类的阈值
        threshold = self.get_category_threshold(category)
        
        change = self.calculate_5m_change(df, idx)
        
        # 打印较大波动
        if abs(change) >= threshold * 0.5:
            print(f"  📊 {symbol} [{category}] 15m变化: {change:+.2f}% (阈值: {threshold}%)")
        
        if symbol != leader:
            return False
        
        # 检测是否触发
        if change >= threshold:
            print(f"  🚀 触发信号! {symbol} 涨幅 {change:+.2f}% >= {threshold}%")
            return True
        
        return False
    
    def find_follow_targets(
        self,
        category_data: Dict[str, pd.DataFrame],
        trigger_symbol: str,
        trigger_change: float,
        current_time: datetime
    ) -> List[Tuple[str, float]]:
        """找出跟涨不足的币种 - 买入涨幅低于龙头的币种"""
        targets = []
        
        # 收集所有币种的涨幅
        coin_changes = []
        for symbol, df in category_data.items():
            if symbol == trigger_symbol:
                continue
            
            mask = df.index <= current_time
            if not mask.any():
                continue
            
            idx = mask.sum() - 1
            if idx < 1:
                continue
            
            coin_change = self.calculate_5m_change(df, idx)
            price = df.iloc[idx]['close']
            coin_changes.append((symbol, coin_change, price))
        
        if not coin_changes:
            return targets
        
        # 按涨幅排序，选择涨幅最小的币种
        coin_changes.sort(key=lambda x: x[1])
        
        # 选择涨幅低于龙头的币种（跟涨不足）
        for symbol, change, price in coin_changes:
            # 如果涨幅低于龙头，则认为跟涨不足，可以买入
            if change < trigger_change:
                follow_pct = (change / trigger_change * 100) if trigger_change != 0 else 0
                targets.append((symbol, follow_pct, price))
        
        return targets
    
    def open_trade(
        self,
        symbol: str,
        category: str,
        entry_time: datetime,
        entry_price: float,
        trigger_coin: str,
        trigger_change: float
    ):
        """开仓"""
        if symbol in self.active_trades:
            return
        
        if self.balance < self.trade_amount:
            return
        
        quantity = self.trade_amount / entry_price
        self.balance -= self.trade_amount
        
        trade = BacktestTrade(
            symbol=symbol,
            category=category,
            entry_time=entry_time,
            entry_price=entry_price,
            quantity=quantity,
            amount=self.trade_amount,
            trigger_coin=trigger_coin,
            trigger_change=trigger_change
        )
        
        self.active_trades[symbol] = trade
    
    def check_exit_conditions(
        self,
        trade: BacktestTrade,
        current_price: float,
        current_time: datetime
    ) -> Tuple[bool, str]:
        """检查平仓条件"""
        pnl_pct = ((current_price - trade.entry_price) / trade.entry_price) * 100
        
        # 止盈
        if self.take_profit_range[0] <= pnl_pct <= self.take_profit_range[1]:
            return True, f"止盈 ({pnl_pct:.2f}%)"
        
        # 强制止盈（超过上限）
        if pnl_pct > self.take_profit_range[1]:
            return True, f"强制止盈 ({pnl_pct:.2f}%)"
        
        # 止损
        if pnl_pct <= -self.stop_loss:
            return True, f"止损 ({pnl_pct:.2f}%)"
        
        return False, ""
    
    def close_trade(
        self,
        symbol: str,
        exit_time: datetime,
        exit_price: float,
        reason: str
    ):
        """平仓"""
        if symbol not in self.active_trades:
            return
        
        trade = self.active_trades[symbol]
        trade.exit_time = exit_time
        trade.exit_price = exit_price
        trade.exit_reason = reason
        trade.profit_loss = (exit_price - trade.entry_price) * trade.quantity
        trade.profit_loss_pct = ((exit_price - trade.entry_price) / trade.entry_price) * 100
        trade.status = 'closed'
        
        # 更新余额
        self.balance += trade.amount + trade.profit_loss
        
        # 记录交易
        self.trades.append(trade)
        del self.active_trades[symbol]
    
    def update_equity(self, current_time: datetime, category_data: Dict[str, pd.DataFrame]):
        """更新权益曲线"""
        # 计算持仓市值
        holdings_value = 0
        for symbol, trade in self.active_trades.items():
            if symbol in category_data:
                df = category_data[symbol]
                mask = df.index <= current_time
                if mask.any():
                    current_price = df.loc[mask].iloc[-1]['close']
                    holdings_value += trade.quantity * current_price
        
        total_equity = self.balance + holdings_value
        self.equity_curve.append((current_time, total_equity))
        
        # 更新最大回撤
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
        interval: str = '5m'
    ) -> BacktestResult:
        """
        运行回测
        
        Args:
            categories: 要测试的分类列表
            start_date: 回测开始日期 (优先使用)
            end_date: 回测结束日期 (优先使用)
            days: 回测天数 (当未指定start_date/end_date时使用)
            interval: K线时间间隔
        """
        
        if categories is None:
            categories = list(CRYPTO_CATEGORIES.keys())[:3]
        
        # 确定回测时间范围
        if end_date is None:
            end_date = datetime.now()
        
        if start_date is None:
            start_date = end_date - timedelta(days=days)
        
        actual_days = (end_date - start_date).days
        
        print(f"\n{'='*60}")
        print(f"🚀 开始回测")
        print(f"📅 开始日期: {start_date.strftime('%Y-%m-%d %H:%M')}")
        print(f"📅 结束日期: {end_date.strftime('%Y-%m-%d %H:%M')}")
        print(f"📅 回测周期: {actual_days} 天")
        print(f"📊 时间间隔: {interval}")
        print(f"📂 测试分类: {', '.join(categories)}")
        print(f"💰 初始资金: {self.initial_balance:,.2f} USDT")
        print(f"\n📈 分类阈值配置:")
        for cat in categories:
            threshold = self.get_category_threshold(cat)
            print(f"   {cat}: {threshold}%")
        print(f"{'='*60}\n")
        
        # 获取所有分类的历史数据
        all_category_data = {}
        for category in categories:
            print(f"\n📥 加载 {category} 分类数据...")
            data = self.data_fetcher.get_category_historical_data_by_date(
                category, interval, start_date, end_date
            )
            if data:
                all_category_data[category] = data
        
        if not all_category_data:
            print("❌ 没有获取到历史数据")
            return None
        
        # 获取时间范围
        all_timestamps = set()
        for category, data in all_category_data.items():
            for symbol, df in data.items():
                all_timestamps.update(df.index.tolist())
        
        sorted_timestamps = sorted(all_timestamps)
        
        print(f"\n📈 开始模拟交易 ({len(sorted_timestamps)} 个时间点)...")
        
        # 遍历每个时间点
        for i, current_time in enumerate(sorted_timestamps):
            if i % 100 == 0:
                progress = (i / len(sorted_timestamps)) * 100
                print(f"  进度: {progress:.1f}% - {current_time}")
            
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
                
                # 检测龙头币暴涨
                if self.detect_surge(leader, leader_df, idx, category):
                    trigger_change = self.calculate_5m_change(leader_df, idx)
                    
                    # 找出跟涨不足的币种
                    targets = self.find_follow_targets(
                        category_data, leader, trigger_change, current_time
                    )
                    
                    # 开仓
                    for symbol, follow_pct, price in targets[:3]:  # 最多开3个
                        self.open_trade(
                            symbol, category, current_time, price,
                            leader, trigger_change
                        )
                
                # 检查持仓的止盈止损
                for symbol in list(self.active_trades.keys()):
                    trade = self.active_trades[symbol]
                    
                    if symbol not in category_data:
                        continue
                    
                    df = category_data[symbol]
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
                # 合并所有分类数据
                merged_data = {}
                for cat_data in all_category_data.values():
                    merged_data.update(cat_data)
                self.update_equity(current_time, merged_data)
        
        # 强制平仓所有持仓
        for symbol in list(self.active_trades.keys()):
            for cat_data in all_category_data.values():
                if symbol in cat_data:
                    df = cat_data[symbol]
                    if not df.empty:
                        self.close_trade(
                            symbol, 
                            df.index[-1], 
                            df.iloc[-1]['close'],
                            "回测结束强制平仓"
                        )
                    break
        
        # 计算回测结果
        end_time = datetime.now()
        
        return self._calculate_results(
            sorted_timestamps[0] if sorted_timestamps else start_time,
            sorted_timestamps[-1] if sorted_timestamps else end_time
        )
    
    def _calculate_results(
        self, 
        start_date: datetime, 
        end_date: datetime
    ) -> BacktestResult:
        """计算回测结果"""
        
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
        
        # 计算夏普比率（简化版）
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
            else:
                sharpe = 0
        else:
            sharpe = 0
        
        result = BacktestResult(
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
            avg_profit_per_trade=total_pnl / len(self.trades) if self.trades else 0,
            avg_holding_time=avg_holding_time,
            trades=self.trades,
            equity_curve=self.equity_curve
        )
        
        return result


def print_backtest_report(result: BacktestResult):
    """打印回测报告"""
    
    print(f"\n{'='*60}")
    print(f"📊 回测报告")
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
    
    print(f"\n📈 交易统计:")
    print(f"   总交易次数: {result.total_trades}")
    print(f"   盈利交易: {result.winning_trades}")
    print(f"   亏损交易: {result.losing_trades}")
    print(f"   胜率: {result.win_rate:.1f}%")
    print(f"   平均每笔盈亏: {result.avg_profit_per_trade:+.2f} USDT")
    print(f"   平均持仓时间: {result.avg_holding_time:.1f} 小时")
    
    print(f"\n⚠️ 风险指标:")
    print(f"   最大回撤: {result.max_drawdown:,.2f} USDT ({result.max_drawdown_pct:.2f}%)")
    print(f"   夏普比率: {result.sharpe_ratio:.2f}")
    
    # 打印最近10笔交易
    if result.trades:
        print(f"\n📋 最近交易记录 (最多10笔):")
        print(f"   {'币种':<12} {'入场价':<12} {'出场价':<12} {'盈亏%':<10} {'原因'}")
        print(f"   {'-'*60}")
        for trade in result.trades[-10:]:
            exit_price = trade.exit_price or 0
            print(f"   {trade.symbol:<12} {trade.entry_price:<12.4f} {exit_price:<12.4f} {trade.profit_loss_pct:+8.2f}%  {trade.exit_reason}")
    
    print(f"\n{'='*60}")


def run_quick_backtest():
    """快速回测入口"""
    engine = BacktestEngine(
        initial_balance=100000,
        trade_amount=1000,
        take_profit_range=[10, 15],
        stop_loss=10,
        follow_threshold=50,
        price_change_threshold=5.0
    )
    
    # 测试 Layer1, Meme, DeFi 分类，回测7天
    result = engine.run_backtest(
        categories=["Layer1", "Meme", "DeFi"],
        days=7,
        interval='5m'
    )
    
    if result:
        print_backtest_report(result)
        return result
    else:
        print("❌ 回测失败")
        return None


if __name__ == "__main__":
    run_quick_backtest()
