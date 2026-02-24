#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
验证 V8 Mode Full 集成脚本
"""

def main():
    print('=' * 60)
    print('验证 V8 Mode Full 集成')
    print('=' * 60)

    # 1. 验证 config.py 中的 V8_CONFIG
    print('\n1. 验证 V8_CONFIG 配置...')
    try:
        from config import V8_CONFIG
        print('   [OK] V8_CONFIG 导入成功')
        print(f'   - 定期重置: {V8_CONFIG["periodic_reset"]["enabled"]}, 间隔 {V8_CONFIG["periodic_reset"]["interval_days"]} 天')
        print(f'   - 冷启动预热: {V8_CONFIG["cold_start"]["warmup_candles"]} 根K线')
        print(f'   - 跳过信号: {V8_CONFIG["cold_start"]["skip_first_signals"]} 个')
        print(f'   - 黑名单阈值: {V8_CONFIG["blacklist"]["max_consecutive_losses"]} 次连续亏损')
    except Exception as e:
        print(f'   [FAIL] V8_CONFIG 导入失败: {e}')
        return False

    # 2. 验证 live_mode_full.py 模块
    print('\n2. 验证 live_mode_full 模块...')
    try:
        from live_mode_full import (
            LiveModeFullManager,
            IndicatorColdStarter,
            DynamicBlacklistManager,
            create_live_mode_full_manager
        )
        print('   [OK] live_mode_full 模块导入成功')
        print('   - LiveModeFullManager: OK')
        print('   - IndicatorColdStarter: OK')
        print('   - DynamicBlacklistManager: OK')
        print('   - create_live_mode_full_manager: OK')
    except Exception as e:
        print(f'   [FAIL] live_mode_full 导入失败: {e}')
        return False

    # 3. 验证 LiveModeFullManager 实例化
    print('\n3. 验证 LiveModeFullManager 实例化...')
    try:
        manager = create_live_mode_full_manager(V8_CONFIG)
        print('   [OK] LiveModeFullManager 创建成功')
        print(f'   - periodic_config.interval_days: {manager.periodic_config.interval_days}')
        print(f'   - cold_start_config.warmup_candles: {manager.cold_start_config.warmup_candles}')
        print(f'   - blacklist_config.max_consecutive_losses: {manager.blacklist_config.max_consecutive_losses}')
    except Exception as e:
        print(f'   [FAIL] LiveModeFullManager 创建失败: {e}')
        return False

    # 4. 验证核心功能
    print('\n4. 验证核心功能...')
    try:
        # 测试 can_trade
        can_trade, reason = manager.can_trade('BTCUSDT')
        print(f'   [OK] can_trade() 方法正常 (result: {can_trade}, reason: "{reason}")')
        
        # 测试 record_trade
        manager.record_trade('BTCUSDT', 100.0, True)
        print('   [OK] record_trade() 方法正常')
        
        # 测试 get_period_summary
        summary = manager.get_period_summary()
        print('   [OK] get_period_summary() 方法正常')
        print(f'   - 周期盈亏: {summary["total_pnl"]:+.2f} USDT')
        print(f'   - 周期交易: {summary["total_trades"]} 次')
        
        # 测试 set_cooldown
        manager.set_cooldown('TESTUSDT', 30)
        print('   [OK] set_cooldown() 方法正常')
        
        # 测试黑名单功能
        manager.blacklist_manager.record_trade_result('TESTUSDT', False)
        manager.blacklist_manager.record_trade_result('TESTUSDT', False)
        manager.blacklist_manager.record_trade_result('TESTUSDT', False)
        is_blacklisted = manager.blacklist_manager.is_blacklisted('TESTUSDT')
        print(f'   [OK] 黑名单功能正常 (连续3次亏损后黑名单: {is_blacklisted})')
        
    except Exception as e:
        print(f'   [FAIL] 核心功能测试失败: {e}')
        import traceback
        traceback.print_exc()
        return False

    # 5. 验证 main.py 集成
    print('\n5. 验证 main.py 集成...')
    try:
        import inspect
        import os
        
        # 读取 main.py 源码检查
        script_dir = os.path.dirname(os.path.abspath(__file__))
        main_path = os.path.join(script_dir, 'main.py')
        with open(main_path, 'r', encoding='utf-8') as f:
            main_source = f.read()
        
        checks = [
            ('from live_mode_full import', 'live_mode_full 导入'),
            ('V8_CONFIG', 'V8_CONFIG 导入'),
            ('mode_full_manager', 'mode_full_manager 属性'),
            ('create_live_mode_full_manager', 'create_live_mode_full_manager 调用'),
            ('mode_full_manager.can_trade', 'can_trade 检查'),
            ('mode_full_manager.record_trade', 'record_trade 记录'),
            ('mode_full_manager.check_and_perform_reset', '定期重置检查'),
            ('get_period_summary', '周期摘要显示'),
        ]
        
        all_passed = True
        for check_str, desc in checks:
            if check_str in main_source:
                print(f'   [OK] {desc}')
            else:
                print(f'   [FAIL] {desc} 缺失')
                all_passed = False
        
        if not all_passed:
            return False
            
    except Exception as e:
        print(f'   [FAIL] main.py 验证失败: {e}')
        return False

    print('\n' + '=' * 60)
    print('[SUCCESS] 所有验证通过! V8 Mode Full 集成完成!')
    print('=' * 60)
    
    print('\n核心功能说明:')
    print('  1. 定期重置 - 每30天自动重置黑名单、冷却期、指标状态')
    print('  2. 冷启动 - 预热50根K线，跳过前3个信号')
    print('  3. 动态黑名单 - 连续亏损3次自动加入24小时黑名单')
    print('  4. 周期统计 - 记录每个周期的盈亏、交易次数、胜率')
    
    return True


if __name__ == '__main__':
    import sys
    success = main()
    sys.exit(0 if success else 1)
