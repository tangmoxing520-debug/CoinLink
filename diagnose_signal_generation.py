"""
诊断脚本：分析为什么实盘没有生成交易信号
对比回测和实盘的差异
"""
import os
import sys
import io
from datetime import datetime, timedelta
import pandas as pd
import logging

# 设置UTF-8编码
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# 设置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

from config import (
    MONITOR_CONFIG, BACKTEST_INTERVAL, V2_COOLDOWN_PERIODS,
    CRYPTO_CATEGORIES, LEADER_COINS, CATEGORY_THRESHOLDS
)
from data_fetcher import create_data_fetcher
from analyzer import CryptoAnalyzer

def diagnose_signal_generation():
    """诊断交易信号生成问题"""
    print("=" * 80)
    print("交易信号生成诊断")
    print("=" * 80)
    
    fetcher = create_data_fetcher()
    analyzer = CryptoAnalyzer(MONITOR_CONFIG)
    
    # 检查配置
    print("\n配置检查:")
    print(f"  BACKTEST_INTERVAL: {BACKTEST_INTERVAL}")
    print(f"  SIGNAL_TRIGGER_INTERVAL: {MONITOR_CONFIG.get('signal_trigger_interval', BACKTEST_INTERVAL)}")
    print(f"  FOLLOW_THRESHOLD: {MONITOR_CONFIG.get('follow_threshold', 100)}")
    print(f"  V2_COOLDOWN_PERIODS: {V2_COOLDOWN_PERIODS}")
    print(f"  冷却期: {V2_COOLDOWN_PERIODS * 15} 分钟")
    
    # 检查每个分类的龙头币和阈值
    print("\n分类配置:")
    for category in MONITOR_CONFIG.get('enabled_categories', []):
        leader = LEADER_COINS.get(category, 'N/A')
        threshold = CATEGORY_THRESHOLDS.get(category, 2.0)
        print(f"  {category}: 龙头币={leader}, 阈值={threshold}%")
    
    # 检查最近的价格变化
    print("\n检查最近价格变化（最近24小时）:")
    now = datetime.now()
    start_time = now - timedelta(hours=24)
    
    issues_found = []
    
    for category in MONITOR_CONFIG.get('enabled_categories', []):
        leader_symbol = LEADER_COINS.get(category)
        if not leader_symbol:
            continue
        
        threshold = CATEGORY_THRESHOLDS.get(category, 2.0)
        
        try:
            # 获取15分钟K线数据
            df = fetcher.get_price_history(leader_symbol, BACKTEST_INTERVAL)
            if df is None or df.empty:
                issues_found.append(f"[ERROR] {category} [{leader_symbol}]: 无法获取K线数据")
                continue
            
            # 计算最近的价格变化
            if len(df) < 2:
                issues_found.append(f"[WARN] {category} [{leader_symbol}]: K线数据不足（{len(df)}条）")
                continue
            
            # 获取最近的价格变化
            latest_close = float(df['close'].iloc[-1])
            prev_close = float(df['close'].iloc[-2])
            change_pct = ((latest_close - prev_close) / prev_close) * 100
            
            # 检查是否达到阈值
            if change_pct >= threshold:
                print(f"  [OK] {category} [{leader_symbol}]: {change_pct:+.2f}% >= {threshold}% (达到阈值)")
            else:
                print(f"  [SKIP] {category} [{leader_symbol}]: {change_pct:+.2f}% < {threshold}% (未达到阈值)")
            
            # 检查K线数据是否足够（需要至少20根用于趋势确认）
            if len(df) < 20:
                issues_found.append(f"[WARN] {category} [{leader_symbol}]: K线数据不足20根（只有{len(df)}根），无法进行趋势确认")
            
            # 检查趋势确认条件
            if len(df) >= 20:
                close = pd.to_numeric(df['close'], errors='coerce')
                volume = pd.to_numeric(df['volume'], errors='coerce')
                
                ma5 = close.rolling(5).mean().iloc[-1]
                ma10 = close.rolling(10).mean().iloc[-1]
                ma20 = close.rolling(20).mean().iloc[-1]
                last_close = float(close.iloc[-1])
                
                trend_ok = True
                if pd.notna(ma5) and pd.notna(ma10) and ma5 < ma10:
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
                        if vol_ratio < 0.6:
                            vol_ok = False
                
                if not trend_ok:
                    issues_found.append(f"[WARN] {category} [{leader_symbol}]: 趋势确认失败 (ma5={ma5:.4f}, ma10={ma10:.4f}, ma20={ma20:.4f}, last={last_close:.4f})")
                
                if not vol_ok:
                    issues_found.append(f"[WARN] {category} [{leader_symbol}]: 成交量确认失败 (vol_ratio={vol_ratio:.2f} < 0.6)")
                
                if trend_ok and vol_ok:
                    print(f"    [OK] 趋势和成交量确认通过")
                else:
                    vol_str = f"{vol_ratio:.2f}" if vol_ratio is not None else "N/A"
                    print(f"    [FAIL] 趋势确认: {trend_ok}, 成交量确认: {vol_ok} (vol_ratio={vol_str})")
        
        except Exception as e:
            issues_found.append(f"[ERROR] {category} [{leader_symbol}]: 检查失败 - {e}")
            logging.error(f"检查 {category} [{leader_symbol}] 失败: {e}", exc_info=True)
    
    # 输出发现的问题
    print("\n" + "=" * 80)
    print("问题诊断:")
    print("=" * 80)
    
    if issues_found:
        for issue in issues_found:
            print(f"  {issue}")
    else:
        print("  [OK] 未发现明显问题")
    
    # 建议
    print("\n建议:")
    print("  1. 检查实盘日志，查看是否有以下信息：")
    print("     - '跳过龙头触发确认' - 可能是趋势/成交量确认失败")
    print("     - '跳过生成交易信号: 分类冷却中' - 分类在冷却期内")
    print("     - '市场异常检测暂停交易' - 市场异常检测暂停了交易")
    print("     - '风险控制暂停交易' - 最大回撤或单日亏损限制触发")
    print("     - '跳过 XXX: Mode Full 冷启动' - K线数据不足")
    print("  2. 对比回测和实盘的差异：")
    print("     - 回测没有趋势/成交量确认（这是实盘独有的）")
    print("     - 回测使用历史数据，实盘使用实时数据")
    print("     - 实盘有市场异常检测和风险控制，回测没有")
    print("  3. 如果趋势/成交量确认过于严格，可以考虑：")
    print("     - 放宽趋势确认条件（例如将 ma20 * 0.95 改为 0.90）")
    print("     - 降低成交量要求（例如将 0.6 改为 0.5）")
    print("     - 或者在反弹行情中临时禁用确认")
    
    print("\n" + "=" * 80)

if __name__ == "__main__":
    diagnose_signal_generation()
