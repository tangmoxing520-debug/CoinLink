"""
测试 Mode Full 功能
"""
import sys
from datetime import datetime, timedelta

# 添加路径
sys.path.insert(0, '.')

from live_mode_full import (
    create_live_mode_full_manager,
    LiveModeFullManager,
    PeriodicResetConfig,
    ColdStartConfig,
    BlacklistConfig
)


def test_cold_start():
    """测试冷启动功能"""
    print("\n" + "="*60)
    print("测试 1: 冷启动功能")
    print("="*60)
    
    manager = create_live_mode_full_manager({
        'cold_start': {
            'warmup_candles': 10,  # 测试用较小值
            'skip_first_signals': 2,
        }
    })
    
    symbol = "BTCUSDT"
    
    # 测试未预热状态
    can_trade, reason = manager.can_trade(symbol)
    print(f"未预热时: can_trade={can_trade}, reason={reason}")
    assert not can_trade, "未预热时应该不能交易"
    
    # 模拟K线数据更新
    manager.cold_starter.update_candle_count(symbol, 5)
    can_trade, reason = manager.can_trade(symbol)
    print(f"5根K线后: can_trade={can_trade}, reason={reason}")
    assert not can_trade, "5根K线时应该还在预热"
    
    # 完成预热
    manager.cold_starter.update_candle_count(symbol, 10)
    can_trade, reason = manager.can_trade(symbol)
    print(f"10根K线后: can_trade={can_trade}, reason={reason}")
    assert not can_trade, "预热完成但还需跳过前2个信号"
    
    # 跳过第一个信号
    can_trade, reason = manager.can_trade(symbol)
    print(f"第2个信号: can_trade={can_trade}, reason={reason}")
    assert not can_trade, "还需跳过1个信号"
    
    # 第三个信号应该可以交易
    can_trade, reason = manager.can_trade(symbol)
    print(f"第3个信号: can_trade={can_trade}, reason={reason}")
    assert can_trade, "第3个信号应该可以交易"
    
    print("✅ 冷启动测试通过!")


def test_blacklist():
    """测试黑名单功能"""
    print("\n" + "="*60)
    print("测试 2: 动态黑名单功能")
    print("="*60)
    
    manager = create_live_mode_full_manager({
        'cold_start': {
            'warmup_candles': 1,
            'skip_first_signals': 0,
        },
        'blacklist': {
            'max_consecutive_losses': 3,
            'blacklist_duration_hours': 1,
        }
    })
    
    symbol = "ETHUSDT"
    
    # 预热
    manager.cold_starter.update_candle_count(symbol, 10)
    
    # 连续亏损
    for i in range(3):
        manager.record_trade(symbol, -100, False)
        print(f"亏损 {i+1} 次后: 黑名单={manager.blacklist_manager.is_blacklisted(symbol)}")
    
    # 检查是否在黑名单
    can_trade, reason = manager.can_trade(symbol)
    print(f"连续亏损3次后: can_trade={can_trade}, reason={reason}")
    assert not can_trade, "连续亏损3次应该在黑名单"
    
    print("✅ 黑名单测试通过!")


def test_periodic_reset():
    """测试定期重置功能"""
    print("\n" + "="*60)
    print("测试 3: 定期重置功能")
    print("="*60)
    
    manager = create_live_mode_full_manager({
        'periodic_reset': {
            'enabled': True,
            'interval_days': 1,  # 测试用1天
        },
        'cold_start': {
            'warmup_candles': 1,
            'skip_first_signals': 0,
        },
        'blacklist': {
            'max_consecutive_losses': 2,
        }
    })
    
    symbol = "SOLUSDT"
    
    # 预热并加入黑名单
    manager.cold_starter.update_candle_count(symbol, 10)
    manager.record_trade(symbol, -100, False)
    manager.record_trade(symbol, -100, False)
    
    print(f"重置前黑名单数: {manager.blacklist_manager.blacklist_count}")
    assert manager.blacklist_manager.blacklist_count > 0, "应该有黑名单"
    
    # 模拟时间过去
    manager._last_reset_time = datetime.now() - timedelta(days=2)
    
    # 触发重置
    reset_performed = manager.check_and_perform_reset()
    print(f"重置执行: {reset_performed}")
    print(f"重置后黑名单数: {manager.blacklist_manager.blacklist_count}")
    
    assert reset_performed, "应该执行重置"
    assert manager.blacklist_manager.blacklist_count == 0, "重置后黑名单应该清空"
    
    print("✅ 定期重置测试通过!")


def test_period_stats():
    """测试周期统计功能"""
    print("\n" + "="*60)
    print("测试 4: 周期统计功能")
    print("="*60)
    
    manager = create_live_mode_full_manager({
        'cold_start': {
            'warmup_candles': 1,
            'skip_first_signals': 0,
        }
    })
    
    # 预热
    manager.cold_starter.update_candle_count("BTCUSDT", 10)
    
    # 记录交易
    manager.record_trade("BTCUSDT", 500, True)
    manager.record_trade("ETHUSDT", -200, False)
    manager.record_trade("SOLUSDT", 300, True)
    
    summary = manager.get_period_summary()
    print(f"周期统计:")
    print(f"  总盈亏: {summary['total_pnl']:+,.2f} USDT")
    print(f"  总交易: {summary['total_trades']} 次")
    print(f"  胜率: {summary['win_rate']:.1f}%")
    
    assert summary['total_pnl'] == 600, "总盈亏应该是600"
    assert summary['total_trades'] == 3, "总交易应该是3次"
    assert abs(summary['win_rate'] - 66.67) < 1, "胜率应该约66.67%"
    
    print("✅ 周期统计测试通过!")


def test_cooldown():
    """测试冷却期功能"""
    print("\n" + "="*60)
    print("测试 5: 冷却期功能")
    print("="*60)
    
    manager = create_live_mode_full_manager({
        'cold_start': {
            'warmup_candles': 1,
            'skip_first_signals': 0,
        }
    })
    
    symbol = "DOGEUSDT"
    
    # 预热
    manager.cold_starter.update_candle_count(symbol, 10)
    
    # 设置冷却期
    manager.set_cooldown(symbol, 30)
    
    can_trade, reason = manager.can_trade(symbol)
    print(f"冷却期内: can_trade={can_trade}, reason={reason}")
    assert not can_trade, "冷却期内不能交易"
    assert "冷却" in reason, "原因应该包含冷却"
    
    print("✅ 冷却期测试通过!")


if __name__ == "__main__":
    print("="*60)
    print("Mode Full 功能测试")
    print("="*60)
    
    try:
        test_cold_start()
        test_blacklist()
        test_peri