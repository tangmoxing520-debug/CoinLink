"""
测试自适应学习模块
"""
import sys
import logging
from datetime import datetime, timedelta
from adaptive_learning import (
    AdaptiveLearningEngine, MarketAnalyzer, PerformanceAnalyzer,
    MarketRegime, PerformanceMetrics, OptimizationSuggestion
)
import pandas as pd
import numpy as np

# 修复Windows控制台编码
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except:
        pass

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def create_mock_btc_data():
    """创建模拟BTC数据"""
    dates = pd.date_range(end=datetime.now(), periods=100, freq='15min')
    base_price = 45000
    prices = base_price + np.cumsum(np.random.randn(100) * 100)
    
    df = pd.DataFrame({
        'open': prices,
        'high': prices * 1.01,
        'low': prices * 0.99,
        'close': prices,
        'volume': np.random.rand(100) * 1000000
    }, index=dates)
    
    return df

def create_mock_trade_history():
    """创建模拟交易历史"""
    from trader_v2 import TradeResult
    
    trades = []
    base_time = datetime.now() - timedelta(days=7)
    
    # 创建一些盈利和亏损的交易
    for i in range(20):
        is_win = i % 2 == 0
        pnl = np.random.uniform(100, 500) if is_win else np.random.uniform(-300, -50)
        pnl_pct = pnl / 1000 * 100  # 假设保证金1000
        
        trade = TradeResult(
            symbol=f"TEST{i}USDT",
            entry_price=100.0,
            exit_price=100.0 + pnl_pct / 100,
            quantity=10.0,
            margin=1000.0,
            leverage=15,
            pnl=pnl,
            pnl_pct=pnl_pct,
            exit_reason="止盈" if is_win else "止损",
            holding_hours=np.random.uniform(0.5, 2.0),
            signal_score=np.random.uniform(60, 100)
        )
        trade.category = "AI Agent" if i % 3 == 0 else "Meme"
        trades.append(trade)
    
    return trades

def test_adaptive_learning():
    """测试自适应学习模块"""
    print("\n" + "=" * 60)
    print("[测试] 自适应学习模块")
    print("=" * 60)
    
    # 1. 创建引擎
    engine = AdaptiveLearningEngine(
        market_analyzer=MarketAnalyzer(),
        performance_analyzer=PerformanceAnalyzer(),
        min_trades_for_analysis=10
    )
    print("\n[OK] 学习引擎创建成功")
    
    # 2. 分析市场状态
    btc_df = create_mock_btc_data()
    market_regime = engine.market_analyzer.analyze_market_regime(btc_df)
    print(f"\n[市场分析]")
    print(f"  波动率: {market_regime.volatility:.2f}%")
    print(f"  趋势强度: {market_regime.trend_strength:.2f}")
    print(f"  成交量趋势: {market_regime.volume_trend:.2f}")
    print(f"  市场阶段: {market_regime.market_phase}")
    
    # 3. 分析交易表现
    trade_history = create_mock_trade_history()
    performance = engine.performance_analyzer.analyze_performance(trade_history)
    print(f"\n[交易表现]")
    print(f"  总交易数: {performance.total_trades}")
    print(f"  胜率: {performance.win_rate:.1%}")
    print(f"  盈亏比: {performance.profit_factor:.2f}")
    print(f"  平均盈利: {performance.avg_win:.2f} USDT")
    print(f"  平均亏损: {performance.avg_loss:.2f} USDT")
    print(f"  平均持仓时间: {performance.avg_holding_hours:.1f} 小时")
    
    # 4. 生成优化建议
    current_config = {
        'stop_loss': 4.0,
        'take_profit': 8.0,
        'signal_min_score': 50.0,
        'category_weights': {'AI Agent': 1.0, 'Meme': 1.0}
    }
    
    suggestions = engine.generate_optimization_suggestions(
        market_regime, performance, current_config
    )
    
    print(f"\n[优化建议] 共 {len(suggestions)} 条")
    for i, sug in enumerate(suggestions[:5], 1):
        print(f"  {i}. [{sug.parameter}]")
        print(f"     当前值: {sug.current_value}")
        print(f"     建议值: {sug.suggested_value}")
        print(f"     原因: {sug.reason}")
        print(f"     置信度: {sug.confidence:.1%}, 优先级: {sug.priority}")
    
    # 5. 生成完整报告
    report = engine.get_summary_report(market_regime, performance, suggestions)
    print("\n" + report)
    
    # 6. 保存分析结果
    engine.save_analysis("test_learning_analysis.json")
    print("\n[OK] 分析结果已保存")
    
    print("\n" + "=" * 60)
    print("[完成] 测试完成")
    print("=" * 60)

if __name__ == "__main__":
    test_adaptive_learning()
