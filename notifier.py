import requests
import json
import hmac
import hashlib
import base64
import time
from urllib.parse import quote_plus
from datetime import datetime
from typing import List
import logging
from analyzer import PriceAlert, TradeSignal
from config import (
    DINGTALK_WEBHOOK, DINGTALK_SECRET,
    VERIFY_SSL, PROXY_ENABLED, PROXY_URL, REQUEST_TIMEOUT,
    TRADE_MODE, DINGTALK_NOTIFY_IN_VIRTUAL,
    DINGTALK_NOTIFY_ALERTS, DINGTALK_NOTIFY_TRADES
)

logger = logging.getLogger(__name__)

class DingTalkNotifier:
    def __init__(self):
        self.webhook = DINGTALK_WEBHOOK
        self.secret = DINGTALK_SECRET
        self.trade_mode = (TRADE_MODE or "virtual").lower()
        self.notify_in_virtual = bool(DINGTALK_NOTIFY_IN_VIRTUAL)
        self.notify_alerts = bool(DINGTALK_NOTIFY_ALERTS)
        self.notify_trades = bool(DINGTALK_NOTIFY_TRADES)
        self.verify_ssl = bool(VERIFY_SSL)
        self.request_timeout = int(REQUEST_TIMEOUT) if REQUEST_TIMEOUT else 10

        self.session = requests.Session()
        if PROXY_ENABLED and PROXY_URL:
            self.session.proxies = {
                "http": PROXY_URL,
                "https": PROXY_URL,
            }
        
    def _sign(self, timestamp: str) -> str:
        """生成签名"""
        if not self.secret:
            return ""
            
        string_to_sign = f"{timestamp}\n{self.secret}"
        hmac_code = hmac.new(
            self.secret.encode('utf-8'),
            string_to_sign.encode('utf-8'),
            hashlib.sha256
        ).digest()
        return base64.b64encode(hmac_code).decode('utf-8')
    
    def send_alert(self, alert: PriceAlert) -> bool:
        """发送单条警报"""
        # 默认不推送价格警报（误报多，测试期刷屏）
        if not self.notify_alerts:
            return False
        # 虚拟模式默认不推送（如需推送请在 config.env 设置 DINGTALK_NOTIFY_IN_VIRTUAL=true）
        if self.trade_mode == "virtual" and not self.notify_in_virtual:
            return False
        if not self.webhook:
            logger.warning("钉钉 webhook 未配置，跳过通知")
            return False
            
        timestamp = str(round(time.time() * 1000))
        sign = self._sign(timestamp)
        
        webhook_url = f"{self.webhook}&timestamp={timestamp}&sign={quote_plus(sign)}"
        
        # 根据警报类型设置不同的标题和图标
        if alert.alert_type == 'surge':
            title = "🚨 数字货币暴涨警报"
            icon = "📈"
            trend = "上涨"
        else:
            title = "⚠️ 数字货币暴跌警报"
            icon = "📉"
            trend = "下跌"
        
        # 格式化变化百分比
        change_display = f"+{alert.change_percentage:.2f}%" if alert.alert_type == 'surge' else f"{alert.change_percentage:.2f}%"
        
        message = {
            "msgtype": "markdown",
            "markdown": {
                "title": title,
                "text": f"## {icon} {title}\n\n"
                       f"**币种**: {alert.coin_name}\n\n"
                       f"**分类**: {alert.category}\n\n"
                       f"**当前价格**: ${alert.current_price:,.4f}\n\n"
                       f"**{trend}幅度**: {change_display} ({alert.time_window})\n\n"
                       f"**交易量**: ${alert.volume:,.0f}\n\n"
                       f"**时间**: {alert.timestamp.strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                       f"---\n"
                       f"{'🚀 注意追高风险！' if alert.alert_type == 'surge' else '💥 注意止损风险！'}"
            }
        }
        
        try:
            response = self.session.post(
                webhook_url,
                headers={'Content-Type': 'application/json'},
                data=json.dumps(message),
                timeout=self.request_timeout,
                verify=self.verify_ssl
            )
            return response.status_code == 200
        except Exception as e:
            logger.warning("发送钉钉消息失败: %s", e)
            return False
    
    def send_trade_signal(self, signal: TradeSignal) -> bool:
        """发送交易信号"""
        # 默认不推送“信号触发”类消息，避免噪声；只推送成交事件
        return False
        if self.trade_mode == "virtual" and not self.notify_in_virtual:
            return False
        if not self.webhook:
            logger.warning("钉钉 webhook 未配置，跳过通知")
            return False
            
        timestamp = str(round(time.time() * 1000))
        sign = self._sign(timestamp)
        
        webhook_url = f"{self.webhook}&timestamp={timestamp}&sign={quote_plus(sign)}"
        
        target_coins_text = "\n".join([f"- {coin[0]} (跟涨: {coin[1]:.1f}%)" for coin in signal.target_coins])
        
        message = {
            "msgtype": "markdown",
            "markdown": {
                "title": "🎯 交易信号触发",
                "text": f"## 🎯 自动交易信号触发\n\n"
                       f"**触发币种**: {signal.trigger_coin_name}\n\n"
                       f"**分类**: {signal.category}\n\n"
                       f"**5分钟涨幅**: +{signal.change_percentage:.2f}%\n\n"
                       f"**跟涨不足的币种**: \n{target_coins_text}\n\n"
                       f"**下单金额**: 每个币种1000USDT\n\n"
                       f"**时间**: {signal.timestamp.strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                       f"---\n"
                       f"🚀 开始执行自动交易..."
            }
        }
        
        try:
            response = self.session.post(
                webhook_url,
                headers={'Content-Type': 'application/json'},
                data=json.dumps(message),
                timeout=self.request_timeout,
                verify=self.verify_ssl
            )
            return response.status_code == 200
        except Exception as e:
            logger.warning("发送交易信号失败: %s", e)
            return False
    
    def send_order_execution(
        self,
        symbol: str,
        amount: float,
        order_id: str,
        success: bool,
        trade_mode: str = "虚拟",
        balance: float = None,
        entry_price: float = None,
        quantity: float = None,
        leverage: int = None,
        category: str = None,
        signal_score: float = None
    ) -> bool:
        """发送订单执行结果"""
        # 只推送成交类通知（开仓/平仓），默认允许虚拟模式
        if not self.notify_trades:
            return False
        if not self.webhook:
            return False
            
        timestamp = str(round(time.time() * 1000))
        sign = self._sign(timestamp)
        
        webhook_url = f"{self.webhook}&timestamp={timestamp}&sign={quote_plus(sign)}"
        
        status_icon = "✅" if success else "❌"
        status_text = "成功" if success else "失败"
        mode_icon = "🔴" if "实盘" in trade_mode else "🔮"

        extra_lines = []
        if category:
            extra_lines.append(f"**分类**: {category}")
        if entry_price is not None:
            extra_lines.append(f"**入场价**: {float(entry_price):.6f}")
        if quantity is not None:
            extra_lines.append(f"**数量**: {float(quantity):.6f}")
        if leverage is not None:
            extra_lines.append(f"**杠杆**: {int(leverage)}x")
        if signal_score is not None:
            extra_lines.append(f"**评分**: {float(signal_score):.1f}")
        if balance is not None:
            extra_lines.append(f"**余额**: {float(balance):,.2f} USDT")
        extra_text = ("\n\n".join(extra_lines) + "\n\n") if extra_lines else ""
        
        message = {
            "msgtype": "markdown",
            "markdown": {
                "title": f"{mode_icon} 订单执行{status_text}",
                "text": f"## {mode_icon} 订单执行{status_text}\n\n"
                       f"**交易对**: {symbol}\n\n"
                       f"**金额**: {amount} USDT\n\n"
                       f"{extra_text}"
                       f"**订单ID**: {order_id}\n\n"
                       f"**状态**: {status_icon} {status_text}\n\n"
                       f"**时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            }
        }
        
        try:
            response = self.session.post(
                webhook_url,
                headers={'Content-Type': 'application/json'},
                data=json.dumps(message),
                timeout=self.request_timeout,
                verify=self.verify_ssl
            )
            return response.status_code == 200
        except Exception as e:
            logger.warning("发送订单执行结果失败: %s", e)
            return False
    
    def send_trade_result(self, symbol: str, entry_price: float, exit_price: float, 
                         quantity: float, profit_loss: float, reason: str, trade_mode: str = "虚拟") -> bool:
        """发送交易结果"""
        # 只推送成交类通知（开仓/平仓），默认允许虚拟模式
        if not self.notify_trades:
            return False
        if not self.webhook:
            return False
            
        timestamp = str(round(time.time() * 1000))
        sign = self._sign(timestamp)
        
        webhook_url = f"{self.webhook}&timestamp={timestamp}&sign={quote_plus(sign)}"
        
        pnl_icon = "💰" if profit_loss > 0 else "💸"
        pnl_text = f"+{profit_loss:.2f} USDT" if profit_loss > 0 else f"{profit_loss:.2f} USDT"
        mode_icon = "🔴" if "实盘" in trade_mode else "🔮"
        
        profit_loss_percentage = ((exit_price - entry_price) / entry_price) * 100
        
        message = {
            "msgtype": "markdown",
            "markdown": {
                "title": f"{mode_icon} 交易平仓结果",
                "text": f"## {mode_icon} 交易平仓\n\n"
                       f"**交易对**: {symbol}\n\n"
                       f"**入场价格**: ${entry_price:.4f}\n\n"
                       f"**出场价格**: ${exit_price:.4f}\n\n"
                       f"**涨跌幅**: {profit_loss_percentage:+.2f}%\n\n"
                       f"**数量**: {quantity:.6f}\n\n"
                       f"**盈亏**: {pnl_icon} {pnl_text}\n\n"
                       f"**原因**: {reason}\n\n"
                       f"**时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            }
        }
        
        try:
            response = self.session.post(
                webhook_url,
                headers={'Content-Type': 'application/json'},
                data=json.dumps(message),
                timeout=self.request_timeout,
                verify=self.verify_ssl
            )
            return response.status_code == 200
        except Exception as e:
            logger.warning("发送交易结果失败: %s", e)
            return False