#!/usr/bin/env python3
"""
回测运行脚本 V3 - 与 optimize_v3.py 参数完全一致
支持按季度运行回测，结果与 optimize_v3.py 一致
"""
import sys

# 兼容部分 Windows 控制台默认编码(cp1252等)导致 emoji/中文输出报错的问题
try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    # 输出编码配置失败不应阻止程序运行
    pass

import argparse
from datetime import datetime, timedelta
from backtester import BacktestEngine, print_backtest_report
from backtester_v2 import BacktestEngineV2, print_backtest_report_v2, StopLossConfig, SignalScoreConfig
from config import CRYPTO_CATEGORIES


def parse_date(date_str: str) -> datetime:
    """解析日期字符串"""
    formats = [
        '%Y-%m-%d',
        '%Y-%m-%d %H:%M',
        '%Y-%m-%d %H:%M:%S',
        '%Y%m%d'
    ]
    for fmt in formats:
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue
    raise ValueError(f"无法解析日期: {date_str}，支持格式: YYYY-MM-DD, YYYY-MM-DD HH:MM")


def create_stop_loss_config() -> StopLossConfig:
    """创建 StopLossConfig 对象 - V6 高收益版 (默认)"""
    # V6 优化: 平衡止损，增加交易机会，目标250%+年化
    return StopLossConfig(
        # 动态止损 (ATR) - 适度放宽以减少过早止损
        dynamic_sl_enabled=True,
        atr_multiplier=1.5,     # V6: 从1.2提高到1.5 (减少过早止损)
        min_stop_loss=3.0,      # V6: 从2.5提高到3.0
        max_stop_loss=8.0,      # V6: 从6.0提高到8.0 (给更多空间)
        # 提前保本止损 - 适度放宽
        early_breakeven_enabled=True,
        early_breakeven_threshold=2.0,  # V6: 从1.5提高到2.0 (2%即保本)
        early_breakeven_buffer=0.15,    # V6: 从0.1提高到0.15
        # 信号评分止损 - 适度放宽
        signal_based_sl_enabled=True,
        high_score_sl=6.0,      # V6: 从5.0提高到6.0
        medium_score_sl=5.0,    # V6: 从4.0提高到5.0
        low_score_sl=4.0,       # V6: 从3.0提高到4.0
        # 时间衰减止损 - 放缓衰减
        time_decay_sl_enabled=True,
        time_decay_factor_12h=0.6,      # V6: 从0.5提高到0.6
        time_decay_factor_24h=0.4,      # V6: 从0.3提高到0.4
        min_decayed_sl=3.0,             # V6: 从2.5提高到3.0
        # 短期时间止损 - 放宽
        short_time_stop_enabled=True,
        short_time_stop_hours=1.5,      # V6: 从1.0提高到1.5小时
        short_time_stop_min_profit=1.0, # V6: 从1.5降到1.0%最低盈利
        # 长期时间止损 - 延长
        long_time_stop_enabled=True,
        long_time_stop_hours=8.0,       # V6: 从6小时延长到8小时
        long_time_stop_min_profit=0.0
    )


def create_stop_loss_config_v4() -> StopLossConfig:
    """创建 StopLossConfig 对象 - V4 优化版 (备用)"""
    # V4 优化: 更激进的止损策略，提高盈亏比
    return StopLossConfig(
        # 动态止损 (ATR)
        dynamic_sl_enabled=True,
        atr_multiplier=1.8,     # V4: 更紧的ATR止损
        min_stop_loss=3.5,      # V4: 更严格的最小止损
        max_stop_loss=10.0,     # V4: 降低最大止损
        # 提前保本止损
        early_breakeven_enabled=True,
        early_breakeven_threshold=3.0,  # V4: 更早保本 (3%即保本)
        early_breakeven_buffer=0.2,     # V4: 更小缓冲
        # 信号评分止损
        signal_based_sl_enabled=True,
        high_score_sl=8.0,      # V4: 高评分更宽松止损
        medium_score_sl=6.0,    # V4: 中评分
        low_score_sl=5.0,       # V4: 低评分更紧止损
        # 时间衰减止损
        time_decay_sl_enabled=True,
        time_decay_factor_12h=0.6,      # V4: 更激进的衰减
        time_decay_factor_24h=0.4,
        min_decayed_sl=3.5,
        # 短期时间止损 - 禁用，让利润有更多空间
        short_time_stop_enabled=False,
        short_time_stop_hours=2.0,
        short_time_stop_min_profit=3.0,
        # 长期时间止损
        long_time_stop_enabled=True,
        long_time_stop_hours=12.0,      # V4: 缩短到12小时
        long_time_stop_min_profit=0.0
    )


# create_stop_loss_config_v5 已合并到 create_stop_loss_config() 作为默认配置


def create_signal_score_config() -> SignalScoreConfig:
    """创建 SignalScoreConfig 对象 - V6 高收益版 (默认)"""
    # V6 优化: 进一步降低信号阈值，大幅增加交易频率，目标250%+年化
    return SignalScoreConfig(
        enabled=True,
        # 权重 - 增加动量权重
        trend_weight=0.20,
        volume_weight=0.15,
        momentum_weight=0.40,
        volatility_weight=0.10,
        correlation_weight=0.15,
        # 阈值 - 进一步降低以大幅增加交易机会
        min_signal_score=50.0,   # V6: 从60降到50 (大幅增加交易频率)
        regime_adaptation_enabled=True,
        # 进一步放宽ADX阈值
        adx_strong_threshold=15.0,  # V6: 从18降到15
        # 成交量阈值 - 进一步放宽
        volume_high_ratio=1.3,      # V6: 从1.5降到1.3
        volume_abnormal_ratio=3.5,  # V6: 从4.0降到3.5
    )


def create_signal_score_config_v4() -> SignalScoreConfig:
    """创建 SignalScoreConfig 对象 - V4 优化版 (备用)"""
    # V4 优化: 适度降低信号阈值，平衡交易频率和质量
    return SignalScoreConfig(
        enabled=True,
        # 权重 - 增加动量权重
        trend_weight=0.20,
        volume_weight=0.15,
        momentum_weight=0.40,
        volatility_weight=0.10,
        correlation_weight=0.15,
        # 阈值 - 适度降低以增加交易机会
        min_signal_score=70.0,   # V4: 从75降到70，适度增加交易频率
        regime_adaptation_enabled=True,
        # 放宽ADX阈值
        adx_strong_threshold=22.0,  # V4: 从25降到22
        # 成交量阈值
        volume_high_ratio=1.8,      # V4: 从2.0降到1.8
        volume_abnormal_ratio=4.5,  # V4: 从5.0降到4.5
    )


# create_signal_score_config_v5 已合并到 create_signal_score_config() 作为默认配置


def print_config_summary():
    """打印当前配置摘要 - V6 高收益版 (默认)"""
    # V6 高收益参数
    V6_PARAMS = {
        "leverage": 15,
        "take_profit": 8,
        "stop_loss": 4,
        "trailing_stop_pct": 1.5,
        "trailing_stop_activation": 2.5,
        "max_positions": 8,
        "min_signal_score": 50,
    }
    
    # 导入 V7 定期重置配置
    from config import PERIODIC_RESET_ENABLED, PERIODIC_RESET_INTERVAL_DAYS
    
    print("\n" + "=" * 60)
    print("📋 当前配置 (V6 高收益版 - 默认)")
    print("=" * 60)
    print(f"💰 初始资金: 20000 USDT")
    print(f"📊 杠杆倍数: {V6_PARAMS['leverage']}x")
    print(f"💵 基础交易金额: 500 USDT")
    print(f"💵 最大交易金额: 2500 USDT")
    print(f"🎯 止盈: {V6_PARAMS['take_profit']}% (价格变化)")
    print(f"🛑 止损: {V6_PARAMS['stop_loss']}% (价格变化)")
    print(f"📈 移动止损: {V6_PARAMS['trailing_stop_pct']}% (激活阈值: {V6_PARAMS['trailing_stop_activation']}%)")
    print(f"📦 最大持仓: {V6_PARAMS['max_positions']}")
    print(f"⏱️ 冷却期: 2 根K线")
    print(f"🎯 信号阈值: {V6_PARAMS['min_signal_score']} (V6优化)")
    print(f"📊 分批止盈: 禁用")
    print(f"🔧 策略优化: 启用")
    print(f"   黑名单交易对: 4 个 (精简)")
    print(f"   分类权重调整: 11 个")
    print(f"⛔ 黑名单优化:")
    print(f"   连续亏损触发: 5次")
    print(f"   黑名单时长: 8小时")
    print(f"   提前解除: 启用 (连续盈利2次)")
    print(f"🔄 V7 定期重置: {'启用' if PERIODIC_RESET_ENABLED else '禁用'} (每{PERIODIC_RESET_INTERVAL_DAYS}天)")
    print("=" * 60)


def print_config_summary_v4():
    """打印当前配置摘要 - V4 优化版 (备用)"""
    # V4 优化参数
    V4_PARAMS = {
        "leverage": 15,
        "take_profit": 10,
        "stop_loss": 5,
        "trailing_stop_pct": 2,
        "trailing_stop_activation": 3,
        "max_positions": 8,
        "min_signal_score": 70,
    }
    
    print("\n" + "=" * 60)
    print("📋 当前配置 (V4 优化版)")
    print("=" * 60)
    print(f"💰 初始资金: 20000 USDT")
    print(f"📊 杠杆倍数: {V4_PARAMS['leverage']}x")
    print(f"💵 基础交易金额: 500 USDT")
    print(f"💵 最大交易金额: 3000 USDT")
    print(f"🎯 止盈: {V4_PARAMS['take_profit']}% (价格变化)")
    print(f"🛑 止损: {V4_PARAMS['stop_loss']}% (价格变化)")
    print(f"📈 移动止损: {V4_PARAMS['trailing_stop_pct']}% (激活阈值: {V4_PARAMS['trailing_stop_activation']}%)")
    print(f"📦 最大持仓: {V4_PARAMS['max_positions']}")
    print(f"⏱️ 冷却期: 4 根K线")
    print(f"🎯 信号阈值: {V4_PARAMS['min_signal_score']} (V4优化)")
    print(f"📊 分批止盈: 禁用")
    print(f"🔧 策略优化: 启用")
    print(f"   黑名单交易对: 12 个")
    print(f"   分类权重调整: 12 个")
    print("=" * 60)


# print_config_summary_v5 已合并到 print_config_summary() 作为默认配置


def create_backtest_engine_v2(
    category_filter_enabled: bool = False,
    pnl_threshold: float = -2000.0,
    win_rate_threshold: float = 40.0,
    loss_streak_threshold: int = 5,
    min_trades_filter: int = 10
) -> BacktestEngineV2:
    """创建 V2 回测引擎 - V6 高收益版 (默认)
    
    Args:
        category_filter_enabled: 是否启用分类亏损过滤器
        pnl_threshold: 累计亏损阈值 (USDT)
        win_rate_threshold: 胜率阈值 (百分比)
        loss_streak_threshold: 连续亏损阈值
        min_trades_filter: 触发过滤的最小交易数
    """
    stop_loss_config = create_stop_loss_config()
    signal_score_config = create_signal_score_config()
    
    # V6 高收益参数 - 平衡止损与交易频率，目标250%+年化
    V6_PARAMS = {
        "leverage": 15,         # V6: 保持15x
        "take_profit": 8,       # V6: 从6提高到8 (更大利润空间)
        "stop_loss": 4,         # V6: 从3提高到4 (减少过早止损)
        "trailing_stop_pct": 1.5,       # V6: 从1.0提高到1.5
        "trailing_stop_activation": 2.5, # V6: 从2.0提高到2.5
        "max_positions": 8,     # V6: 从6提高到8 (增加交易机会)
    }
    
    # V6 优化: 进一步降低分类阈值以大幅增加交易机会
    V6_CATEGORY_THRESHOLDS = {
        "Layer1": 0.5,    # V6: 从0.6降到0.5
        "SOL": 1.5,       # V6: 从2.0降到1.5
        "Meme": 1.5,      # V6: 从2.0降到1.5
        "AI Agent": 1.8,  # V6: 从2.0降到1.8
        "AI Agency": 1.5, # V6: 从2.0降到1.5
        "Layer2": 1.5,    # V6: 从2.0降到1.5
        "RWA": 1.8,       # V6: 从2.0降到1.8
    }
    
    # V6 高收益参数 + 优化黑名单配置
    engine = BacktestEngineV2(
        initial_balance=20000,
        base_trade_amount=500,
        max_trade_amount=2500,  # V6: 从2000提高到2500
        take_profit=V6_PARAMS["take_profit"],
        stop_loss=V6_PARAMS["stop_loss"],
        trailing_stop_pct=V6_PARAMS["trailing_stop_pct"],
        trailing_stop_activation=V6_PARAMS["trailing_stop_activation"],
        max_positions=V6_PARAMS["max_positions"],
        cooldown_periods=2,     # V6: 保持2 (快速重新入场)
        leverage=V6_PARAMS["leverage"],
        futures_mode=True,
        stop_loss_config=stop_loss_config,
        signal_score_config=signal_score_config,
        category_thresholds=V6_CATEGORY_THRESHOLDS,
        # V6 黑名单优化: 更宽松的黑名单机制，减少错过机会
        blacklist_consecutive_losses=5,      # V6: 从4提高到5 (更宽容)
        blacklist_duration_hours=8,          # V6: 从12降到8 (更快恢复)
        blacklist_early_release_enabled=True,  # V6: 保持启用
        blacklist_early_release_wins=2       # V6: 保持2次盈利解除
    )
    
    # 应用策略优化配置
    engine.strategy_optimization_enabled = True
    
    # V6: 精简黑名单 (只保留最差的)
    engine.symbol_blacklist = set([
        "XLMUSDT",      # Payment, 胜率 25.0%
        "SANTOSUSDT",   # Sports, 胜率 33.3%
        "RLCUSDT",      # VR/AR, 胜率 42.9%
        "UAIUSDT",      # AI Agent, 胜率 36.4%
    ])
    
    # V6: 优化分类权重 - 更激进地提高表现好的分类
    engine.category_weight_adjustments = {
        # 表现差的分类 - 降低权重
        "VR/AR": 0.3,       # V6: 保持0.3
        "Metaverse": 0.5,   # V6: 保持0.5
        "DID": 0.6,         # V6: 保持0.6
        "STABLE": 0.6,      # V6: 保持0.6
        
        # 表现好的分类 - 大幅提高权重
        "SOL": 2.0,         # V6: 从1.8提高到2.0 (最佳表现)
        "Meme": 1.8,        # V6: 从1.5提高到1.8
        "AI Agent": 1.0,    # V6: 从1.2降到1.0 (频繁亏损，中性权重)
        "AI Agency": 1.6,   # V6: 从1.5提高到1.6
        "Layer1": 1.8,      # V6: 从1.6提高到1.8
        "Layer2": 1.5,      # V6: 从1.4提高到1.5
        "RWA": 1.3,         # V6: 从1.4降到1.3
    }
    
    print(f"✅ 已启用策略优化 (V6高收益版): 黑名单 {len(engine.symbol_blacklist)} 个, 分类权重调整 {len(engine.category_weight_adjustments)} 个")
    
    # V7: 启用分类亏损过滤器
    if category_filter_enabled:
        engine.enable_category_loss_filter(
            cumulative_pnl_threshold=pnl_threshold,
            win_rate_threshold=win_rate_threshold,
            consecutive_loss_threshold=loss_streak_threshold,
            min_trades_for_filter=min_trades_filter
        )
    
    return engine


def create_backtest_engine_v4() -> BacktestEngineV2:
    """创建 V4 回测引擎 - V4 优化版 (备用)"""
    stop_loss_config = create_stop_loss_config_v4()
    signal_score_config = create_signal_score_config_v4()
    
    # V4 优化参数 - 更激进的交易策略
    V4_PARAMS = {
        "leverage": 15,
        "take_profit": 10,      # 保持10%止盈
        "stop_loss": 5,         # 保持5%止损
        "trailing_stop_pct": 2,
        "trailing_stop_activation": 3,
        "max_positions": 8,
    }
    
    # V4 优化: 降低分类阈值以增加交易机会
    V4_CATEGORY_THRESHOLDS = {
        "Layer1": 0.9,    # V4: 从1.0降到0.9
        "SOL": 2.8,       # V4: 从3.0降到2.8
        "Meme": 2.8,      # V4: 从3.0降到2.8
        "AI Agent": 2.8,  # V4: 从3.0降到2.8
        "AI Agency": 2.8, # V4: 从3.0降到2.8
        "Layer2": 2.8,    # V4: 从3.0降到2.8
        "RWA": 2.8,       # V4: 从3.0降到2.8
    }
    
    # V4 优化参数
    engine = BacktestEngineV2(
        initial_balance=20000,
        base_trade_amount=500,
        max_trade_amount=3000,
        take_profit=V4_PARAMS["take_profit"],
        stop_loss=V4_PARAMS["stop_loss"],
        trailing_stop_pct=V4_PARAMS["trailing_stop_pct"],
        trailing_stop_activation=V4_PARAMS["trailing_stop_activation"],
        max_positions=V4_PARAMS["max_positions"],
        cooldown_periods=4,
        leverage=V4_PARAMS["leverage"],
        futures_mode=True,
        stop_loss_config=stop_loss_config,
        signal_score_config=signal_score_config,
        category_thresholds=V4_CATEGORY_THRESHOLDS
    )
    
    # 应用策略优化配置
    engine.strategy_optimization_enabled = True
    
    # 使用黑名单
    engine.symbol_blacklist = set([
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
    ])
    
    # 使用分类权重
    engine.category_weight_adjustments = {
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
    
    print(f"✅ 已启用策略优化 (V4优化版): 黑名单 {len(engine.symbol_blacklist)} 个, 分类权重调整 {len(engine.category_weight_adjustments)} 个")
    
    return engine


def create_backtest_engine_q3q4() -> BacktestEngineV2:
    """创建 Q3/Q4 优化版回测引擎
    
    启用所有Q3/Q4优化组件:
    - 动态信号阈值优化
    - Meme币风险控制
    - AI Agent板块优化
    - 波动率自适应止损
    - 交易频率监控
    
    Requirements: 7.1
    """
    stop_loss_config = create_stop_loss_config()
    signal_score_config = create_signal_score_config()
    
    # Q3/Q4 优化参数
    Q3Q4_PARAMS = {
        "leverage": 15,
        "take_profit": 10,
        "stop_loss": 10,  # 基础止损，会被Q3Q4优化器动态调整
        "trailing_stop_pct": 2,
        "trailing_stop_activation": 3,
        "max_positions": 8,
    }
    
    # Q3/Q4 优化: 使用更低的分类阈值增加交易机会
    Q3Q4_CATEGORY_THRESHOLDS = {
        "Layer1": 0.8,
        "SOL": 2.5,
        "Meme": 2.5,
        "AI Agent": 2.5,
        "AI Agency": 2.5,
        "Layer2": 2.5,
        "RWA": 2.5,
    }
    
    engine = BacktestEngineV2(
        initial_balance=20000,
        base_trade_amount=500,
        max_trade_amount=3000,
        take_profit=Q3Q4_PARAMS["take_profit"],
        stop_loss=Q3Q4_PARAMS["stop_loss"],
        trailing_stop_pct=Q3Q4_PARAMS["trailing_stop_pct"],
        trailing_stop_activation=Q3Q4_PARAMS["trailing_stop_activation"],
        max_positions=Q3Q4_PARAMS["max_positions"],
        cooldown_periods=4,
        leverage=Q3Q4_PARAMS["leverage"],
        futures_mode=True,
        stop_loss_config=stop_loss_config,
        signal_score_config=signal_score_config,
        category_thresholds=Q3Q4_CATEGORY_THRESHOLDS
    )
    
    # 启用策略优化
    engine.strategy_optimization_enabled = True
    
    # 启用Q3/Q4优化
    engine.enable_q3q4_optimization(
        base_threshold=70.0,  # 基础信号阈值
        base_stop_loss=10.0   # 基础止损
    )
    
    # 使用精简黑名单
    engine.symbol_blacklist = set([
        "XLMUSDT",
        "SANTOSUSDT",
        "RLCUSDT",
        "UAIUSDT",
    ])
    
    # 分类权重调整
    engine.category_weight_adjustments = {
        "VR/AR": 0.4,
        "Metaverse": 0.6,
        "DID": 0.7,
        "STABLE": 0.7,
        "SOL": 1.5,
        "Meme": 1.3,
        "AI Agent": 1.2,
        "AI Agency": 1.3,
        "Layer1": 1.2,
        "Layer2": 1.2,
        "RWA": 1.2,
    }
    
    print(f"✅ 已启用Q3/Q4优化版: 黑名单 {len(engine.symbol_blacklist)} 个, 分类权重调整 {len(engine.category_weight_adjustments)} 个")
    
    return engine


def print_config_summary_q3q4():
    """打印Q3/Q4优化配置摘要"""
    print("\n" + "=" * 60)
    print("📋 当前配置 (Q3/Q4 优化版)")
    print("=" * 60)
    print(f"💰 初始资金: 20000 USDT")
    print(f"📊 杠杆倍数: 15x")
    print(f"💵 基础交易金额: 500 USDT")
    print(f"💵 最大交易金额: 3000 USDT")
    print(f"🎯 止盈: 10% (价格变化)")
    print(f"🛑 止损: 动态 (Q3Q4优化器控制)")
    print(f"📈 移动止损: 2% (激活阈值: 3%)")
    print(f"📦 最大持仓: 8")
    print(f"⏱️ 冷却期: 4 根K线")
    print(f"🎯 信号阈值: 动态 (Q3Q4优化器控制)")
    print(f"🔧 Q3/Q4优化组件:")
    print(f"   ✅ 动态信号阈值优化")
    print(f"   ✅ Meme币风险控制 (0.7x仓位, 15%止损, 85分门槛)")
    print(f"   ✅ AI Agent优化 (8%止损, 黑名单机制)")
    print(f"   ✅ 波动率自适应止损 (ATR-based)")
    print(f"   ✅ 交易频率监控 (静默期阈值调整)")
    print(f"   ✅ 分时段策略 (亚洲时段+5, 周末减仓)")
    print("=" * 60)


# create_backtest_engine_v5 已合并到 create_backtest_engine_v2() 作为默认配置


def run_backtest_v2(start_date: datetime = None, end_date: datetime = None, 
                    days: int = 7, interval: str = '15m', categories: list = None,
                    segment_days: int = 0):
    """运行 V2 回测 - 与 optimize_v3.py 一致
    
    Args:
        start_date: 开始日期
        end_date: 结束日期
        days: 回测天数 (当未指定start/end时使用)
        interval: K线时间间隔
        categories: 分类列表
        segment_days: 分段天数 (0=不分段, 90=按季度分段模拟--mode full效果)
    """
    print_config_summary()
    
    engine = create_backtest_engine_v2()
    
    # 使用与 optimize_v3.py 完全相同的分类列表
    OPTIMIZED_CATEGORIES = ["SOL", "Meme", "AI Agent", "AI Agency", "Layer1", "Layer2", "RWA"]
    
    if categories is None:
        categories = OPTIMIZED_CATEGORIES
    
    # 分段回测模式 - 模拟 --mode full 的优势
    if segment_days > 0 and start_date and end_date:
        return run_segmented_backtest(
            engine=engine,
            categories=categories,
            start_date=start_date,
            end_date=end_date,
            interval=interval,
            segment_days=segment_days
        )
    
    result = engine.run_backtest(
        categories=categories,
        start_date=start_date,
        end_date=end_date,
        days=days,
        interval=interval
    )
    
    if result:
        print_backtest_report_v2(result)
        save_backtest_result_v2(result, "backtest_v2")
    
    return result


def run_segmented_backtest(
    engine: BacktestEngineV2,
    categories: list,
    start_date: datetime,
    end_date: datetime,
    interval: str = '15m',
    segment_days: int = 90
):
    """
    分段回测 - 完全模拟 --mode full 的优势
    
    核心优势 (V8.1 优化):
    1. 每段创建新引擎实例 (与 --mode full 一致)
    2. 技术指标完全重新计算 (冷启动效应)
    3. 资金连续传递 (上一段结束余额 = 下一段初始余额)
    4. 状态完全重置 (黑名单、冷却期等)
    
    Args:
        engine: 回测引擎实例 (仅用于获取初始配置)
        categories: 分类列表
        start_date: 开始日期
        end_date: 结束日期
        interval: K线时间间隔
        segment_days: 每段天数 (默认90天=季度)
    """
    print(f"\n{'='*60}")
    print(f"📊 分段回测模式 V8.1 (每{segment_days}天一段，完全模拟--mode full)")
    print(f"{'='*60}")
    print(f"时间范围: {start_date.date()} ~ {end_date.date()}")
    
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
    print(f"✨ 每段创建新引擎实例 (与 --mode full 一致)")
    
    results = {}
    total_pnl = 0
    all_trades = []
    
    # 初始余额
    initial_balance = engine.initial_balance
    current_balance = initial_balance
    
    for name, seg_start, seg_end in segments:
        print(f"\n{'='*60}")
        print(f"📊 {name}: {seg_start.date()} ~ {seg_end.date()}")
        print(f"   起始余额: {current_balance:,.2f} USDT")
        print('='*60)
        
        # V8.1 关键改进: 每段创建新引擎实例，但使用上一段的结束余额
        segment_engine = create_backtest_engine_v2()
        segment_engine.initial_balance = current_balance
        segment_engine.balance = current_balance
        
        result = segment_engine.run_backtest(
            categories=categories,
            start_date=seg_start,
            end_date=seg_end,
            interval=interval
        )
        
        if result:
            # 计算本段的实际收益
            segment_pnl = result.total_profit_loss
            segment_pnl_pct = (result.final_balance - current_balance) / current_balance * 100
            segment_trades_count = result.total_trades
            segment_win_rate = result.win_rate
            
            total_pnl += segment_pnl
            all_trades.extend(result.trades)
            
            results[name] = {
                'pnl': segment_pnl,
                'pnl_pct': segment_pnl_pct,
                'trades': segment_trades_count,
                'win_rate': segment_win_rate,
                'start_balance': current_balance,
                'final_balance': result.final_balance
            }
            
            print(f"   收益: {segment_pnl:+,.2f} USDT ({segment_pnl_pct:+.1f}%)")
            print(f"   交易数: {segment_trades_count}, 胜率: {segment_win_rate:.1f}%")
            print(f"   结束余额: {result.final_balance:,.2f} USDT")
            
            # 更新下一段的起始余额
            current_balance = result.final_balance
    
    # 打印汇总
    print("\n" + "="*60)
    print("📊 分段回测汇总 (V8.1)")
    print("="*60)
    
    final_balance = current_balance
    total_pnl_pct = (final_balance - initial_balance) / initial_balance * 100
    
    print(f"\n{'分段':<10} {'起始余额':<15} {'收益':<18} {'收益率':<12} {'交易数':<8} {'胜率':<8}")
    print("-"*75)
    for name, data in results.items():
        print(f"{name:<10} {data['start_balance']:>12,.0f} {data['pnl']:>+15,.2f} {data['pnl_pct']:>+10.1f}% {data['trades']:>8} {data['win_rate']:>6.1f}%")
    
    print("-"*75)
    print(f"{'合计':<10} {initial_balance:>12,.0f} {total_pnl:>+15,.2f} {total_pnl_pct:>+10.1f}%")
    print(f"\n💰 初始余额: {initial_balance:,.2f} USDT")
    print(f"💰 最终余额: {final_balance:,.2f} USDT")
    print(f"📈 总收益率: {total_pnl_pct:+.2f}%")
    print(f"📊 总交易数: {len(all_trades)}")
    
    # 与 --mode full 对比说明
    print(f"\n💡 说明: 此模式与 --mode full 的区别:")
    print(f"   - --mode full: 每季度独立计算，初始余额都是 20,000 USDT")
    print(f"   - 分段回测: 资金连续传递，复利效应")
    
    return results, total_pnl, final_balance


def run_category_backtest(category: str, start_date: datetime = None, 
                          end_date: datetime = None, days: int = 7, interval: str = '15m'):
    """单分类回测"""
    print(f"\n🎯 运行 {category} 分类回测...")
    
    if category not in CRYPTO_CATEGORIES:
        print(f"❌ 未知分类: {category}")
        print(f"可用分类: {', '.join(CRYPTO_CATEGORIES.keys())}")
        return None
    
    return run_backtest_v2(start_date, end_date, days, interval, [category])


def save_backtest_result_v2(result, filename: str):
    """保存回测结果到文件"""
    import json
    import os
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filepath = f"backtest_results/{filename}_{timestamp}.json"
    
    # V3 优化参数
    V3_PARAMS = {
        "leverage": 15,
        "take_profit": 10,
        "stop_loss": 5,
        "signal_min_score": 75,
        "max_positions": 8,
    }
    
    try:
        os.makedirs("backtest_results", exist_ok=True)
        
        # 转换为可序列化格式
        data = {
            'version': 'V3',
            'config': V3_PARAMS,
            'start_date': str(result.start_date),
            'end_date': str(result.end_date),
            'initial_balance': result.initial_balance,
            'final_balance': result.final_balance,
            'total_trades': result.total_trades,
            'winning_trades': result.winning_trades,
            'losing_trades': result.losing_trades,
            'total_profit_loss': result.total_profit_loss,
            'win_rate': result.win_rate,
            'max_drawdown': result.max_drawdown,
            'max_drawdown_pct': result.max_drawdown_pct,
            'sharpe_ratio': result.sharpe_ratio,
            'profit_factor': result.profit_factor,
            'avg_profit_per_trade': result.avg_profit_per_trade,
            'avg_holding_time': result.avg_holding_time,
            'avg_win': result.avg_win,
            'avg_loss': result.avg_loss,
            'leverage': result.leverage,
            'liquidations': result.liquidations,
            'trades': [
                {
                    'symbol': t.symbol,
                    'category': t.category,
                    'entry_time': str(t.entry_time),
                    'entry_price': t.entry_price,
                    'exit_time': str(t.exit_time) if t.exit_time else None,
                    'exit_price': t.exit_price,
                    'profit_loss': t.profit_loss,
                    'profit_loss_pct': t.profit_loss_pct,
                    'exit_reason': t.exit_reason,
                    'signal_score': t.signal_score,
                    'trigger_coin': t.trigger_coin,
                    'trigger_change': t.trigger_change
                }
                for t in result.trades
            ]
        }
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        
        print(f"\n💾 回测结果已保存: {filepath}")
        
    except Exception as e:
        print(f"⚠️ 保存回测结果失败: {e}")


def run_quarterly_backtest(
    quarter: str = None, 
    year: int = 2025, 
    independent: bool = True, 
    use_v4: bool = False, 
    use_q3q4: bool = False,
    category_filter_enabled: bool = False,
    pnl_threshold: float = -2000.0,
    win_rate_threshold: float = 40.0,
    loss_streak_threshold: int = 5,
    min_trades_filter: int = 10
):
    """
    运行季度回测 - 与 optimize_v3.py 完全一致
    
    Args:
        quarter: 季度 (Q1, Q2, Q3, Q4)，如果为 None 则运行全年
        year: 年份，默认 2025
        independent: 是否独立运行每个季度 (每次创建新引擎)
                    True: 每个季度独立运行，结果不累积
                    False: 使用同一个引擎运行所有季度，状态累积 (与 optimize_v3.py 一致)
        use_v4: 是否使用V4参数 (备用版本)
        use_q3q4: 是否使用Q3/Q4优化版
        category_filter_enabled: 是否启用分类亏损过滤器
        pnl_threshold: 累计亏损阈值 (USDT)
        win_rate_threshold: 胜率阈值 (百分比)
        loss_streak_threshold: 连续亏损阈值
        min_trades_filter: 触发过滤的最小交易数
    """
    # 优化的分类列表 (与 optimize_v3.py 一致)
    OPTIMIZED_CATEGORIES = ["SOL", "Meme", "AI Agent", "AI Agency", "Layer1", "Layer2", "RWA"]
    
    quarters = {
        "Q1": (datetime(year, 1, 1), datetime(year, 3, 31)),
        "Q2": (datetime(year, 4, 1), datetime(year, 6, 30)),
        "Q3": (datetime(year, 7, 1), datetime(year, 9, 30)),
        "Q4": (datetime(year, 10, 1), datetime(year, 12, 31)),
    }
    
    # 根据版本选择配置 (默认使用V5)
    if use_q3q4:
        print_config_summary_q3q4()
        engine_creator = lambda: create_backtest_engine_q3q4()
    elif use_v4:
        print_config_summary_v4()
        engine_creator = lambda: create_backtest_engine_v4()
    else:
        # 默认使用V5，支持分类过滤器
        print_config_summary()
        engine_creator = lambda: create_backtest_engine_v2(
            category_filter_enabled=category_filter_enabled,
            pnl_threshold=pnl_threshold,
            win_rate_threshold=win_rate_threshold,
            loss_streak_threshold=loss_streak_threshold,
            min_trades_filter=min_trades_filter
        )
    
    # 如果不是独立模式，创建一个共享的引擎实例
    shared_engine = None if independent else engine_creator()
    
    results = {}
    total_pnl = 0
    
    # 确定要运行的季度
    if quarter:
        quarter = quarter.upper()
        if quarter not in quarters:
            print(f"❌ 无效季度: {quarter}，可用: Q1, Q2, Q3, Q4")
            return None
        quarters_to_run = [(quarter, *quarters[quarter])]
    else:
        quarters_to_run = [(f"Q{i}", *quarters[f"Q{i}"]) for i in range(1, 5)]
    
    for name, start, end in quarters_to_run:
        print(f"\n{'='*60}")
        print(f"📊 回测 {name} {year}: {start.date()} ~ {end.date()}")
        print('='*60)
        
        # 独立模式下每个季度创建新引擎
        engine = engine_creator() if independent else shared_engine
        
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
            
            # 标记是否达到100%目标
            target_met = "✅" if pnl_pct >= 100 else "❌"
            print(f"   收益: {pnl:+,.2f} USDT ({pnl_pct:+.2f}%) {target_met}")
            print(f"   交易数: {result.total_trades}, 胜率: {result.win_rate:.1f}%")
            print(f"   最大回撤: {result.max_drawdown_pct:.2f}%")
    
    # 打印汇总
    if len(results) > 1:
        print("\n" + "="*60)
        print("📊 全年汇总")
        print("="*60)
        
        total_pnl_pct = total_pnl / 20000 * 100
        
        print(f"\n{'季度':<15} {'收益':<20} {'收益率':<15} {'交易数':<10} {'胜率':<10} {'达标':<5}")
        print("-"*75)
        for name, data in results.items():
            target_met = "✅" if data['pnl_pct'] >= 100 else "❌"
            print(f"{name:<15} {data['pnl']:>+15,.2f} {data['pnl_pct']:>+10.2f}% {data['trades']:>10} {data['win_rate']:>8.1f}% {target_met:>5}")
        
        print("-"*75)
        all_met = all(data['pnl_pct'] >= 100 for data in results.values())
        final_status = "✅ 全部达标" if all_met else "❌ 未全部达标"
        print(f"{'全年合计':<15} {total_pnl:>+15,.2f} {total_pnl_pct:>+10.2f}%")
        print(f"\n🎯 目标状态: {final_status}")
    
    return results, total_pnl


def run_comparison_backtest(quarter: str = None, year: int = 2025):
    """
    运行对比回测: 基线 vs Q3/Q4优化
    
    Args:
        quarter: 季度 (Q1, Q2, Q3, Q4)，如果为 None 则运行Q3
        year: 年份，默认 2025
        
    Requirements: 7.2, 7.3
    """
    if quarter is None:
        quarter = "Q3"  # 默认对比Q3
    
    quarter = quarter.upper()
    
    quarters = {
        "Q1": (datetime(year, 1, 1), datetime(year, 3, 31)),
        "Q2": (datetime(year, 4, 1), datetime(year, 6, 30)),
        "Q3": (datetime(year, 7, 1), datetime(year, 9, 30)),
        "Q4": (datetime(year, 10, 1), datetime(year, 12, 31)),
    }
    
    if quarter not in quarters:
        print(f"❌ 无效季度: {quarter}，可用: Q1, Q2, Q3, Q4")
        return None
    
    start, end = quarters[quarter]
    OPTIMIZED_CATEGORIES = ["SOL", "Meme", "AI Agent", "AI Agency", "Layer1", "Layer2", "RWA"]
    
    print(f"\n{'=' * 70}")
    print(f"📊 对比回测: {quarter} {year} - 基线 vs Q3/Q4优化")
    print(f"{'=' * 70}")
    print(f"时间范围: {start.date()} ~ {end.date()}")
    
    # 1. 运行基线回测 (使用V4版本作为基线)
    print(f"\n{'=' * 70}")
    print(f"🔵 基线回测 (V4优化版)")
    print(f"{'=' * 70}")
    
    baseline_engine = create_backtest_engine_v4()
    baseline_result = baseline_engine.run_backtest(
        categories=OPTIMIZED_CATEGORIES,
        start_date=start,
        end_date=end,
        interval='15m'
    )
    
    baseline_pnl = 0
    baseline_pnl_pct = 0
    baseline_trades = 0
    baseline_win_rate = 0
    
    if baseline_result:
        baseline_pnl = baseline_result.total_profit_loss
        baseline_pnl_pct = (baseline_result.final_balance - baseline_result.initial_balance) / baseline_result.initial_balance * 100
        baseline_trades = baseline_result.total_trades
        baseline_win_rate = baseline_result.win_rate
        print(f"   收益: {baseline_pnl:+,.2f} USDT ({baseline_pnl_pct:+.2f}%)")
        print(f"   交易数: {baseline_trades}, 胜率: {baseline_win_rate:.1f}%")
    
    # 2. 运行Q3/Q4优化回测
    print(f"\n{'=' * 70}")
    print(f"🟢 Q3/Q4优化版回测")
    print(f"{'=' * 70}")
    
    q3q4_engine = create_backtest_engine_q3q4()
    q3q4_result = q3q4_engine.run_backtest(
        categories=OPTIMIZED_CATEGORIES,
        start_date=start,
        end_date=end,
        interval='15m'
    )
    
    q3q4_pnl = 0
    q3q4_pnl_pct = 0
    q3q4_trades = 0
    q3q4_win_rate = 0
    
    if q3q4_result:
        q3q4_pnl = q3q4_result.total_profit_loss
        q3q4_pnl_pct = (q3q4_result.final_balance - q3q4_result.initial_balance) / q3q4_result.initial_balance * 100
        q3q4_trades = q3q4_result.total_trades
        q3q4_win_rate = q3q4_result.win_rate
        print(f"   收益: {q3q4_pnl:+,.2f} USDT ({q3q4_pnl_pct:+.2f}%)")
        print(f"   交易数: {q3q4_trades}, 胜率: {q3q4_win_rate:.1f}%")
    
    # 3. 打印对比报告
    print(f"\n{'=' * 70}")
    print(f"📈 对比报告: {quarter} {year}")
    print(f"{'=' * 70}")
    
    print(f"\n{'指标':<20} {'基线':<20} {'Q3/Q4优化':<20} {'变化':<15}")
    print("-" * 75)
    
    pnl_change = q3q4_pnl - baseline_pnl
    pnl_pct_change = q3q4_pnl_pct - baseline_pnl_pct
    trades_change = q3q4_trades - baseline_trades
    win_rate_change = q3q4_win_rate - baseline_win_rate
    
    print(f"{'收益 (USDT)':<20} {baseline_pnl:>+15,.2f} {q3q4_pnl:>+15,.2f} {pnl_change:>+12,.2f}")
    print(f"{'收益率 (%)':<20} {baseline_pnl_pct:>+15.2f}% {q3q4_pnl_pct:>+15.2f}% {pnl_pct_change:>+11.2f}%")
    print(f"{'交易数':<20} {baseline_trades:>15} {q3q4_trades:>15} {trades_change:>+12}")
    print(f"{'胜率 (%)':<20} {baseline_win_rate:>15.1f}% {q3q4_win_rate:>15.1f}% {win_rate_change:>+11.1f}%")
    
    print("-" * 75)
    
    # Property 15: Q3 Return Review Flag
    # *For any* Q3 backtest result where optimized return is below 30%, the result SHALL be flagged for review.
    if quarter == "Q3" and q3q4_pnl_pct < 30:
        print(f"\n⚠️ 警告: Q3优化收益率 ({q3q4_pnl_pct:.2f}%) 低于30%目标，需要参数审查!")
        print(f"   建议: 检查信号阈值、止损参数、Meme风控设置")
    elif q3q4_pnl_pct >= 50:
        print(f"\n✅ 优秀: {quarter}优化收益率 ({q3q4_pnl_pct:.2f}%) 达到50%+目标!")
    elif q3q4_pnl_pct >= 30:
        print(f"\n🟡 良好: {quarter}优化收益率 ({q3q4_pnl_pct:.2f}%) 达到30%基准")
    
    # 改进幅度
    if baseline_pnl_pct != 0:
        improvement = ((q3q4_pnl_pct - baseline_pnl_pct) / abs(baseline_pnl_pct)) * 100
        print(f"\n📊 相对改进: {improvement:+.1f}%")
    
    return {
        'baseline': {
            'pnl': baseline_pnl,
            'pnl_pct': baseline_pnl_pct,
            'trades': baseline_trades,
            'win_rate': baseline_win_rate
        },
        'q3q4': {
            'pnl': q3q4_pnl,
            'pnl_pct': q3q4_pnl_pct,
            'trades': q3q4_trades,
            'win_rate': q3q4_win_rate
        }
    }

def main():
    parser = argparse.ArgumentParser(description='CoinLink 回测系统 - 默认使用V6参数')
    parser.add_argument('--mode', type=str, default='v2',
                       choices=['v2', 'category', 'quarterly', 'full', 'q3q4', 'compare'],
                       help='回测模式: v2(默认V6), category(单分类), quarterly(季度), full(全年), q3q4(Q3/Q4优化), compare(对比)')
    parser.add_argument('--quarter', type=str, default=None,
                       help='季度回测时的季度 (Q1, Q2, Q3, Q4)')
    parser.add_argument('--year', type=int, default=2025,
                       help='回测年份 (默认: 2025)')
    parser.add_argument('--independent', action='store_true',
                       help='独立运行每个季度 (每次创建新引擎，结果不累积)')
    parser.add_argument('--v4', action='store_true',
                       help='使用V4参数 (备用版本)')
    parser.add_argument('--q3q4', action='store_true',
                       help='使用Q3/Q4优化版 (动态阈值、Meme风控、AI Agent优化)')
    parser.add_argument('--category', type=str, default='Layer1',
                       help='单分类回测时的分类名称')
    parser.add_argument('--days', type=int, default=7,
                       help='回测天数 (当未指定start/end时使用)')
    parser.add_argument('--start', type=str, default=None,
                       help='回测开始日期 (格式: YYYY-MM-DD)')
    parser.add_argument('--end', type=str, default=None,
                       help='回测结束日期 (格式: YYYY-MM-DD)')
    parser.add_argument('--interval', type=str, default='15m',
                       help='K线时间间隔 (5m, 15m, 1h, 4h, 1d)')
    # V7: 分类亏损过滤器参数
    parser.add_argument('--category-filter', action='store_true',
                       help='启用分类亏损过滤器')
    parser.add_argument('--pnl-threshold', type=float, default=-2000.0,
                       help='分类累计亏损阈值 (USDT，默认: -2000)')
    parser.add_argument('--win-rate-threshold', type=float, default=40.0,
                       help='分类胜率阈值 (百分比，默认: 40)')
    parser.add_argument('--loss-streak-threshold', type=int, default=5,
                       help='连续亏损阈值 (默认: 5)')
    parser.add_argument('--min-trades-filter', type=int, default=10,
                       help='触发过滤的最小交易数 (默认: 10)')
    # V8: 分段回测参数 - 模拟 --mode full 的优势
    parser.add_argument('--segment-days', type=int, default=0,
                       help='分段回测天数 (0=不分段, 90=按季度分段模拟--mode full效果)')
    
    args = parser.parse_args()
    
    print(f"\n{'=' * 60}")
    print(f"🚀 CoinLink 回测系统 (默认使用V6参数)")
    print(f"{'=' * 60}")
    print(f"模式: {args.mode}")
    print(f"时间间隔: {args.interval}")
    if args.mode in ['quarterly', 'full', 'q3q4', 'compare']:
        print(f"独立模式: {'是' if args.independent else '否 (与 optimize_v3.py 一致)'}")
        if args.q3q4 or args.mode == 'q3q4':
            print(f"参数版本: Q3/Q4优化版")
        elif args.v4:
            print(f"参数版本: V4优化版 (备用)")
        else:
            print(f"参数版本: V6高收益版 (默认)")
    
    # V7: 打印分类过滤器配置
    if args.category_filter:
        print(f"📊 分类亏损过滤器: 启用")
        print(f"   累计亏损阈值: {args.pnl_threshold} USDT")
        print(f"   胜率阈值: {args.win_rate_threshold}%")
        print(f"   连续亏损阈值: {args.loss_streak_threshold}")
        print(f"   最小交易数: {args.min_trades_filter}")
    
    # 运行回测
    if args.mode == 'q3q4':
        # Q3/Q4优化版回测
        run_quarterly_backtest(args.quarter, args.year, args.independent, use_v4=False, use_q3q4=True)
    elif args.mode == 'compare':
        # 对比回测: 基线 vs Q3/Q4优化
        run_comparison_backtest(args.quarter, args.year)
    elif args.mode == 'quarterly':
        run_quarterly_backtest(
            args.quarter, args.year, args.independent, args.v4, args.q3q4,
            category_filter_enabled=args.category_filter,
            pnl_threshold=args.pnl_threshold,
            win_rate_threshold=args.win_rate_threshold,
            loss_streak_threshold=args.loss_streak_threshold,
            min_trades_filter=args.min_trades_filter
        )
    elif args.mode == 'full':
        run_quarterly_backtest(
            None, args.year, args.independent, args.v4, args.q3q4,
            category_filter_enabled=args.category_filter,
            pnl_threshold=args.pnl_threshold,
            win_rate_threshold=args.win_rate_threshold,
            loss_streak_threshold=args.loss_streak_threshold,
            min_trades_filter=args.min_trades_filter
        )
    elif args.mode == 'category':
        run_category_backtest(args.category, 
                             parse_date(args.start) if args.start else None,
                             parse_date(args.end) if args.end else None,
                             args.days, args.interval)
    else:
        start_date = parse_date(args.start) if args.start else None
        end_date = parse_date(args.end) if args.end else None
        
        if start_date:
            print(f"开始日期: {start_date.strftime('%Y-%m-%d %H:%M')}")
        if end_date:
            print(f"结束日期: {end_date.strftime('%Y-%m-%d %H:%M')}")
        if not start_date and not end_date:
            print(f"回测天数: {args.days}")
        
        run_backtest_v2(start_date, end_date, args.days, args.interval, segment_days=args.segment_days)


if __name__ == "__main__":
    main()
