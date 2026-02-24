#!/usr/bin/env python3
"""
启动脚本 - 自动检测网络并选择模式
"""
import sys
import requests
from main import CryptoMonitor

def check_network_connection():
    """检查网络连接"""
    try:
        print("检查网络连接...")
        response = requests.get("https://api.coingecko.com/api/v3/ping", timeout=5)
        if response.status_code == 200:
            print("✅ 网络连接正常")
            return True
        else:
            print("❌ 网络连接异常")
            return False
    except Exception as e:
        print(f"❌ 网络连接失败: {e}")
        return False

def main():
    """主启动函数"""
    print("=== 数字货币监控系统启动 ===")
    
    # 检查网络
    if check_network_connection():
        print("启动在线监控模式...")
        monitor = CryptoMonitor(offline_mode=False)
    else:
        print("启动离线测试模式...")
        monitor = CryptoMonitor(offline_mode=True)
    
    try:
        monitor.start_monitoring()
    except KeyboardInterrupt:
        print("\n程序被用户中断")
    except Exception as e:
        print(f"程序运行出错: {e}")

if __name__ == "__main__":
    main()