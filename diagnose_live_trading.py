"""
实盘交易诊断工具
用于分析为什么实盘没有触发开仓，而回测有开仓
"""
import sys
import logging
from datetime import datetime
from config import *
from live_trader_v3 import LiveTraderV3
from analyzer import CryptoAnalyzer
from gate_data_fetcher import GateDataFetcher

# 修复Windows控制台编码问题
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except:
        pass

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

def diagnose_live_trading():
    """诊断实盘交易未开仓的原因"""
    print("\n" + "=" * 80)
    print("[诊断] 实盘交易诊断工具")
    print("=" * 80)
    
    # 1. 检查基础配置
    print("\n[1] 基础配置检查")
    print(f"   TRADE_MODE: {TRADE_MODE}")
    print(f"   TRADE_ENABLED: {TRADE_ENABLED}")
    print(f"   SAFE_MODE_ON_EXTERNAL_POSITIONS: {SAFE_MODE_ON_EXTERNAL_POSITIONS}")
    print(f"   SIGNAL_MIN_SCORE: {SIGNAL_MIN_SCORE}")
    print(f"   CALIBRATOR_NORMAL_MIN_SCORE: {CALIBRATOR_NORMAL_MIN_SCORE}")
    print(f"   CALIBRATOR_BEARISH_MIN_SCORE: {CALIBRATOR_BEARISH_MIN_SCORE}")
    print(f"   V8_WARMUP_CANDLES: {V8_WARMUP_CANDLES}")
    print(f"   V8_SKIP_FIRST_SIGNALS: {V8_SKIP_FIRST_SIGNALS}")
    
    # 2. 初始化交易器（但不运行主循环）
    try:
        trader = LiveTraderV3(initial_balance=20000)
        print(f"\n[OK] 交易器初始化成功")
        print(f"   trade_enabled: {trader.trade_enabled}")
        
        # 检查安全模式
        if not trader.trade_enabled:
            print(f"\n[WARN] 交易功能已禁用！")
            if trader.is_real_trading:
                print(f"   可能原因：检测到外部持仓，进入安全模式")
                print(f"   检查：SAFE_MODE_ON_EXTERNAL_POSITIONS={SAFE_MODE_ON_EXTERNAL_POSITIONS}")
        
    except Exception as e:
        print(f"\n[ERROR] 交易器初始化失败: {e}")
        import traceback
        traceback.print_exc()
        return
    
    # 3. 测试数据获取
    print(f"\n[2] 数据获取测试")
    fetcher = trader.fetcher
    analyzer = trader.analyzer
    
    test_categories = ["Layer1", "SOL", "Meme", "AI Agent"]
    for category in test_categories:
        if category not in CRYPTO_CATEGORIES:
            continue
        print(f"\n   测试分类: {category}")
        try:
            coins = fetcher.get_top_coins_by_category(category, 5)
            if not coins:
                print(f"      [ERROR] 无法获取币种数据")
                continue
            
            print(f"      [OK] 获取到 {len(coins)} 个币种")
            
            # 检查龙头币
            leader = MONITOR_CONFIG.get("leader_coins", {}).get(category)
            if leader:
                print(f"      龙头币: {leader}")
                
                # 查找龙头币
                leader_coin = None
                for coin in coins:
                    if coin.get('id') == leader or coin.get('symbol') == leader:
                        leader_coin = coin
                        break
                
                if leader_coin:
                    print(f"      [OK] 找到龙头币: {leader_coin.get('name', leader_coin.get('id'))}")
                    
                    # 检测价格警报
                    alerts = analyzer.detect_price_alerts(leader_coin, category, fetcher)
                    print(f"      价格警报数: {len(alerts)}")
                    
                    for alert in alerts:
                        if alert.alert_type == 'surge':
                            print(f"        [ALERT] 暴涨警报: {alert.coin_name} {alert.change_percentage:+.2f}% ({alert.time_window})")
                            
                            # 检查是否为触发窗口
                            trigger_interval = MONITOR_CONFIG.get('signal_trigger_interval', BACKTEST_INTERVAL)
                            if alert.time_window == trigger_interval:
                                print(f"        [OK] 触发窗口匹配: {alert.time_window}")
                                
                                # 检查是否为龙头币
                                if analyzer.is_leader_coin(alert.coin_id, category):
                                    print(f"        [OK] 确认为龙头币")
                                    
                                    # 检查趋势/成交量确认
                                    try:
                                        leader_df = trader.trader.get_klines(alert.coin_id, interval=BACKTEST_INTERVAL)
                                        if leader_df is None or leader_df.empty or len(leader_df) < 20:
                                            print(f"        [ERROR] K线数据不足: len={0 if leader_df is None else len(leader_df)}")
                                        else:
                                            print(f"        [OK] K线数据充足: {len(leader_df)} 根")
                                            
                                            # 检查趋势
                                            import pandas as pd
                                            close = pd.to_numeric(leader_df.get("close"), errors="coerce")
                                            volume = pd.to_numeric(leader_df.get("volume"), errors="coerce")
                                            
                                            if close.isna().all():
                                                print(f"        [ERROR] close 数据全为 NaN")
                                            else:
                                                ma5 = close.rolling(5).mean().iloc[-1]
                                                ma10 = close.rolling(10).mean().iloc[-1]
                                                ma20 = close.rolling(20).mean().iloc[-1]
                                                last_close = float(close.iloc[-1])
                                                
                                                trend_ok = True
                                                if pd.notna(ma5) and pd.notna(ma10) and ma5 < ma10:
                                                    trend_ok = False
                                                    print(f"        [ERROR] 趋势确认失败: ma5={ma5:.4f} < ma10={ma10:.4f}")
                                                if pd.notna(ma20) and last_close < float(ma20) * 0.98:
                                                    trend_ok = False
                                                    print(f"        [ERROR] 趋势确认失败: last_close={last_close:.4f} < ma20*0.98={float(ma20)*0.98:.4f}")
                                                
                                                vol_ok = True
                                                vol_ratio = None
                                                if volume is not None and not volume.isna().all():
                                                    current_vol = float(volume.iloc[-1])
                                                    avg_vol = float(volume.iloc[-20:].mean()) if len(volume) >= 20 else float(volume.mean())
                                                    if avg_vol > 0:
                                                        vol_ratio = current_vol / avg_vol
                                                        if vol_ratio < 0.8:
                                                            vol_ok = False
                                                            print(f"        [ERROR] 成交量确认失败: vol_ratio={vol_ratio:.2f} < 0.8")
                                                
                                                if trend_ok and vol_ok:
                                                    print(f"        [OK] 趋势/成交量确认通过")
                                                else:
                                                    print(f"        [ERROR] 趋势/成交量确认失败: trend_ok={trend_ok}, vol_ok={vol_ok}")
                                    except Exception as e:
                                        print(f"        [ERROR] 趋势/成交量确认异常: {e}")
                else:
                    print(f"      [WARN] 未找到龙头币 {leader} 在返回列表中")
        except Exception as e:
            print(f"      [ERROR] 测试失败: {e}")
            import traceback
            traceback.print_exc()
    
    # 4. 检查 Mode Full 冷启动状态
    print(f"\n[3] Mode Full 冷启动状态检查")
    try:
        manager = trader.mode_full_manager
        print(f"   预热K线数: {manager.cold_start_config.warmup_candles}")
        print(f"   跳过信号数: {manager.cold_start_config.skip_first_signals}")
        
        # 测试几个币种
        test_symbols = ["BTCUSDT", "SOLUSDT", "DOGEUSDT", "FARTCOINUSDT"]
        for symbol in test_symbols:
            try:
                df = trader.trader.get_klines(symbol)
                if df is not None:
                    manager.update_indicator_data(symbol, df)
                    can_trade, reason = manager.can_trade(symbol)
                    status = "[OK]" if can_trade else "[BLOCK]"
                    print(f"   {status} {symbol}: can_trade={can_trade}, reason={reason}")
            except Exception as e:
                print(f"   [WARN] {symbol}: 检查失败 - {e}")
    except Exception as e:
        print(f"   [ERROR] Mode Full 检查失败: {e}")
    
    # 5. 检查分类冷却状态
    print(f"\n[4] 分类冷却状态检查")
    for category in test_categories:
        if category not in CRYPTO_CATEGORIES:
            continue
        in_cooldown = trader._is_category_in_cooldown(category)
        cooldown_min = trader._cooldown_minutes()
        last_signal = trader._category_last_signal_time.get(category)
        status = "冷却中" if in_cooldown else "可交易"
        print(f"   {category}: {status} (冷却期: {cooldown_min} 分钟)")
        if last_signal:
            elapsed = (datetime.now() - last_signal).total_seconds() / 60
            print(f"      上次信号: {elapsed:.1f} 分钟前")
    
    print("\n" + "=" * 80)
    print("[完成] 诊断完成")
    print("=" * 80)

if __name__ == "__main__":
    diagnose_live_trading()
