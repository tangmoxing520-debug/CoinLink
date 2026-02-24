"""
策略优化 V3 - 针对全年收益率提升的改进方案

改进方案:
1. 收紧止损: 从6%降到5%，减少单次亏损
2. 提高止盈: 从8%提到10%，增加盈亏比
3. 提高信号阈值: 从70提到75，过滤低质量信号
4. 加强时间止损: 持仓超过2小时且未盈利则平仓
5. 更新黑名单: 加入表现差的交易对
6. 调整分类权重: 降低DeFi权重
"""
from datetime import datetime
from backtester_v2 import BacktestEngineV2, StopLossConfig, SignalScoreConfig

# ========== V3 优化参数 ==========
V3_PARAMS = {
    "leverage": 15,
    "take_profit": 10,      # 改进2: 从8%提到10%
    "stop_loss": 5,         # 改进1: 从6%降到5%
    "trailing_stop_pct": 2,
    "trailing_stop_activation": 3,
    "max_positions": 8,
    "min_signal_score": 75,  # 改进3: 从70提到75
    "early_breakeven_threshold": 4,  # 更早保本
}

# 改进5: 更新黑名单 (加入新发现的表现差交易对)
UPDATED_SYMBOL_BLACKLIST = [
    # 原有黑名单
    "XLMUSDT",      # Payment, 胜率 25.0%, 总亏损 -755
    "SANTOSUSDT",   # Sports, 胜率 33.3%, 总亏损 -852
    "RLCUSDT",      # VR/AR, 胜率 42.9%, 总亏损 -2157
    "STORJUSDT",    # Storage, 胜率 46.7%, 总亏损 -1814
    "AXSUSDT",      # Metaverse, 胜率 40.0%, 总亏损 -1251
    "STBLUSDT",     # STABLE, 胜率 40.7%, 总亏损 -788
    "THETAUSDT",    # VR/AR, 胜率 51.4%, 总亏损 -1416
    "SOONUSDT",     # VR/AR, 胜率 50.0%, 总亏损 -752
    "UAIUSDT",      # AI Agent, 胜率 36.4%, 总亏损 -641
    # 新增黑名单 (2025全年分析)
    "SWARMSUSDT",   # AI Agent, 胜率 50.0%, 总亏损 -1366
    "LINKUSDT",     # DeFi, 胜率 40.0%, 总亏损 -939
    "1000SHIBUSDT", # Meme, 胜率 54.5%, 总亏损 -764
]

# 改进6: 调整分类权重
UPDATED_CATEGORY_WEIGHTS = {
    # 表现差的分类 - 降低权重
    "VR/AR": 0.4,       # 进一步降低
    "Metaverse": 0.6,   # 进一步降低
    "DID": 0.7,         # 降低
    "STABLE": 0.7,      # 降低
    "DeFi": 0.8,        # 新增: 降低DeFi权重 (LINKUSDT亏损)
    
    # 表现好的分类 - 提高权重
    "SOL": 1.5,         # 进一步提高
    "Meme": 1.3,        # 提高
    "AI Agent": 1.3,    # 提高
    "AI Agency": 1.3,   # 提高
    "Layer1": 1.2,      # 提高
    "Layer2": 1.2,      # 提高
    "RWA": 1.2,         # 提高
}

# 优化的分类列表 (排除表现差的)
OPTIMIZED_CATEGORIES = ["SOL", "Meme", "AI Agent", "AI Agency", "Layer1", "Layer2", "RWA"]


def create_v3_engine():
    """创建V3优化版回测引擎"""
    stop_loss_config = StopLossConfig(
        dynamic_sl_enabled=True,
        atr_multiplier=2.0,
        min_stop_loss=4.0,      # 更严格的最小止损
        max_stop_loss=12.0,     # 降低最大止损
        early_breakeven_enabled=True,
        early_breakeven_threshold=V3_PARAMS["early_breakeven_threshold"],
        early_breakeven_buffer=0.3,
        signal_based_sl_enabled=True,
        high_score_sl=10.0,     # 降低
        medium_score_sl=8.0,    # 降低
        low_score_sl=6.0,       # 降低
        time_decay_sl_enabled=True,  # 启用时间衰减
        time_decay_factor_12h=0.7,   # 更激进的衰减
        time_decay_factor_24h=0.5,
        min_decayed_sl=4.0
    )
    
    signal_config = SignalScoreConfig(
        enabled=True,
        trend_weight=0.20,
        volume_weight=0.15,
        momentum_weight=0.40,
        volatility_weight=0.10,
        correlation_weight=0.15,
        min_signal_score=V3_PARAMS["min_signal_score"],
        regime_adaptation_enabled=True
    )
    
    engine = BacktestEngineV2(
        initial_balance=20000,
        base_trade_amount=500,
        max_trade_amount=3000,
        take_profit=V3_PARAMS["take_profit"],
        stop_loss=V3_PARAMS["stop_loss"],
        trailing_stop_pct=V3_PARAMS["trailing_stop_pct"],
        trailing_stop_activation=V3_PARAMS["trailing_stop_activation"],
        max_positions=V3_PARAMS["max_positions"],
        cooldown_periods=4,
        leverage=V3_PARAMS["leverage"],
        futures_mode=True,
        stop_loss_config=stop_loss_config,
        signal_score_config=signal_config
    )
    
    engine.strategy_optimization_enabled = True
    
    # 应用更新的黑名单
    engine.symbol_blacklist = set(UPDATED_SYMBOL_BLACKLIST)
    
    # 应用更新的分类权重
    engine.category_weight_adjustments = UPDATED_CATEGORY_WEIGHTS
    
    return engine


def run_quarterly_backtest(engine, year=2025):
    """运行季度回测"""
    quarters = [
        (f"Q1 {year}", datetime(year, 1, 1), datetime(year, 3, 31)),
        (f"Q2 {year}", datetime(year, 4, 1), datetime(year, 6, 30)),
        (f"Q3 {year}", datetime(year, 7, 1), datetime(year, 9, 30)),
        (f"Q4 {year}", datetime(year, 10, 1), datetime(year, 12, 31)),
    ]
    
    results = {}
    total_pnl = 0
    
    for name, start, end in quarters:
        print(f"\n{'='*60}")
        print(f"📊 回测 {name}: {start.date()} ~ {end.date()}")
        print('='*60)
        
        result = engine.run_backtest(
            categories=OPTIMIZED_CATEGORIES,
            start_date=start,
            end_date=end,
            interval='15m'
        )
        
        if result:
            pnl = result.total_profit_loss
            pnl_pct = (result.final_balance - result.initial_balance) / result.initial_balance * 100
            total_pnl += pnl
            
            results[name] = {
                'pnl': pnl,
                'pnl_pct': pnl_pct,
                'trades': result.total_trades,
                'win_rate': result.win_rate,
                'max_dd': result.max_drawdown_pct
            }
            
            print(f"   收益: {pnl:+,.2f} USDT ({pnl_pct:+.2f}%)")
            print(f"   交易数: {result.total_trades}, 胜率: {result.win_rate:.1f}%")
            print(f"   最大回撤: {result.max_drawdown_pct:.2f}%")
    
    return results, total_pnl


def compare_v2_vs_v3():
    """对比V2和V3策略"""
    print("\n" + "="*80)
    print("🔬 策略对比: V2 (原版) vs V3 (优化版)")
    print("="*80)
    
    # V2 原版参数
    v2_params = {
        "leverage": 15,
        "take_profit": 8,
        "stop_loss": 6,
        "min_signal_score": 70,
    }
    
    # V3 优化参数
    v3_params = V3_PARAMS
    
    print("\n📋 参数对比:")
    print(f"{'参数':<25} {'V2 (原版)':<15} {'V3 (优化版)':<15}")
    print("-"*55)
    print(f"{'止盈':<25} {v2_params['take_profit']}%{'':<12} {v3_params['take_profit']}%")
    print(f"{'止损':<25} {v2_params['stop_loss']}%{'':<12} {v3_params['stop_loss']}%")
    print(f"{'信号阈值':<25} {v2_params['min_signal_score']}{'':<13} {v3_params['min_signal_score']}")
    print(f"{'盈亏比':<25} {v2_params['take_profit']/v2_params['stop_loss']:.2f}{'':<13} {v3_params['take_profit']/v3_params['stop_loss']:.2f}")
    
    # 运行V3回测
    print("\n" + "="*80)
    print("🚀 运行 V3 优化版回测...")
    print("="*80)
    
    engine = create_v3_engine()
    results, total_pnl = run_quarterly_backtest(engine)
    
    # 汇总
    print("\n" + "="*80)
    print("📊 V3 优化版全年汇总")
    print("="*80)
    
    total_pnl_pct = total_pnl / 20000 * 100
    
    print(f"\n{'季度':<15} {'收益':<20} {'收益率':<15} {'交易数':<10} {'胜率':<10}")
    print("-"*70)
    for name, data in results.items():
        print(f"{name:<15} {data['pnl']:>+15,.2f} {data['pnl_pct']:>+10.2f}% {data['trades']:>10} {data['win_rate']:>8.1f}%")
    
    print("-"*70)
    print(f"{'全年合计':<15} {total_pnl:>+15,.2f} {total_pnl_pct:>+10.2f}%")
    
    print("\n" + "="*80)
    print("📈 改进效果分析")
    print("="*80)
    
    # V2 原版结果 (从之前的分析)
    v2_total_pnl = 31353  # 164.22%
    v2_total_pnl_pct = 164.22
    
    improvement = total_pnl - v2_total_pnl
    improvement_pct = total_pnl_pct - v2_total_pnl_pct
    
    print(f"\nV2 原版全年收益: {v2_total_pnl:+,.2f} USDT ({v2_total_pnl_pct:+.2f}%)")
    print(f"V3 优化版全年收益: {total_pnl:+,.2f} USDT ({total_pnl_pct:+.2f}%)")
    print(f"改进幅度: {improvement:+,.2f} USDT ({improvement_pct:+.2f}%)")
    
    return results, total_pnl


if __name__ == "__main__":
    compare_v2_vs_v3()
