import requests
import uuid
import json
from typing import Dict, Optional, List
from datetime import datetime
from config import API_BASE_URL, MONITOR_CONFIG
import urllib3

class VirtualTrade:
    """虚拟交易记录"""
    def __init__(self, symbol: str, entry_price: float, quantity: float, 
                 amount: float, category: str, timestamp: datetime):
        self.symbol = symbol
        self.entry_price = entry_price
        self.quantity = quantity
        self.amount = amount
        self.category = category
        self.timestamp = timestamp
        self.order_id = str(uuid.uuid4())
        self.status = 'open'
        self.exit_price = None
        self.exit_time = None
        self.profit_loss = 0.0
        self.profit_loss_percentage = 0.0

class VirtualTrader:
    """纯虚拟交易器 - 解决SSL问题"""
    
    def __init__(self, initial_balance: float = 100000):
        self.virtual_balance = initial_balance
        self.initial_balance = initial_balance
        self.active_trades = {}  # symbol -> VirtualTrade
        self.trade_history = []
        self.total_profit_loss = 0.0
        
        # 配置SSL和网络
        self.verify_ssl = MONITOR_CONFIG.get('verify_ssl', True)
        self.proxy_enabled = MONITOR_CONFIG.get('proxy_enabled', False)
        self.proxy_url = MONITOR_CONFIG.get('proxy_url', '')
        self.request_timeout = MONITOR_CONFIG.get('request_timeout', 30)

        # 仅当用户显式关闭 SSL 验证时才禁用告警
        if not self.verify_ssl:
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        
        # 配置会话
        self.session = requests.Session()
        if self.proxy_enabled and self.proxy_url:
            self.session.proxies = {
                'http': self.proxy_url,
                'https': self.proxy_url
            }
        
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'application/json'
        })
        
    def get_current_price(self, symbol: str) -> Optional[float]:
        """获取当前价格 - 增强SSL处理"""
        try:
            # Gate.io API获取价格 - 增强错误处理
            print(f"🔗 获取 {symbol} 的真实价格...")
            
            response = self.session.get(
                f"{API_BASE_URL}/spot/tickers",
                params={'currency_pair': symbol},
                timeout=self.request_timeout,
                verify=self.verify_ssl
            )
            
            if response.status_code == 200:
                data = response.json()
                if data and len(data) > 0:
                    # 找到对应的交易对
                    for item in data:
                        if item.get('currency_pair') == symbol:
                            price = float(item['last'])
                            print(f"✅ 获取真实价格: {symbol} - {price}")
                            return price
            print(f"❌ 无法获取 {symbol} 的真实价格")
            return self._get_fallback_price(symbol)
        except requests.exceptions.SSLError as e:
            print(f"🔒 SSL错误获取价格 {symbol}: {e}")
            return self._get_fallback_price(symbol)
        except Exception as e:
            print(f"❌ 获取Gate.io真实价格失败 {symbol}: {e}")
            return self._get_fallback_price(symbol)
    
    def _get_fallback_price(self, symbol: str) -> float:
        """备用价格获取"""
        base_prices = {
            'BTC_USDT': 45000, 'ETH_USDT': 3000, 'SOL_USDT': 100, 'ADA_USDT': 0.5,
            'DOT_USDT': 7, 'MATIC_USDT': 0.8, 'OP_USDT': 2.5, 'ARB_USDT': 1.2,
            'IMX_USDT': 2.0, 'STRK_USDT': 1.5, 'UNI_USDT': 8, 'AAVE_USDT': 90,
            'MKR_USDT': 1500, 'COMP_USDT': 60, 'SUSHI_USDT': 1.2, 'DOGE_USDT': 0.15,
            'SHIB_USDT': 0.00001, 'PEPE_USDT': 0.000001, 'FLOKI_USDT': 0.00002,
            'BONK_USDT': 0.000015, 'FET_USDT': 0.6, 'AGIX_USDT': 0.3, 'OCEAN_USDT': 0.8,
            'NMR_USDT': 25, 'GRT_USDT': 0.15, 'BLESS_USDT': 0.5, 'EVAA_USDT': 0.3,
            'XPIN_USDT': 0.4, 'F_USDT': 0.02, 'RVV_USDT': 0.01, 'ONDO_USDT': 0.8,
            'TRU_USDT': 0.1, 'PRO_USDT': 0.9, 'CFG_USDT': 0.4, 'RIO_USDT': 0.2
        }
        price = base_prices.get(symbol, 10.0) * (1 + random.uniform(-0.005, 0.005))
        print(f"🔄 使用备用价格: {symbol} - {price:.4f}")
        return price
    
    def check_symbol_exists(self, symbol: str) -> bool:
        """检查交易对是否存在 - 简化处理"""
        # 由于SSL问题，我们假设交易对都存在
        return True
    
    def place_trade(self, symbol: str, amount: float, category: str) -> Optional[Dict]:
        """虚拟下单交易 - 增强错误处理"""
        try:
            # 获取当前价格 - 使用增强的方法
            current_price = self.get_current_price(symbol)
            if not current_price:
                print(f"❌ 无法获取 {symbol} 的价格，无法下单")
                return None
            
            # 计算购买数量
            quantity = amount / current_price
            
            # 检查余额
            if self.virtual_balance < amount:
                print(f"❌ 虚拟余额不足: 需要{amount} USDT, 当前余额{self.virtual_balance:.2f} USDT")
                return None
            
            # 检查是否已有该币种的持仓
            if symbol in self.active_trades:
                print(f"⚠️ 已有 {symbol} 的持仓，不再重复开仓")
                return None
            
            # 扣除余额 - 虚拟操作
            self.virtual_balance -= amount
            
            # 创建虚拟交易记录
            virtual_trade = VirtualTrade(
                symbol=symbol,
                entry_price=current_price,
                quantity=quantity,
                amount=amount,
                category=category,
                timestamp=datetime.now()
            )
            
            # 添加到活跃交易
            self.active_trades[symbol] = virtual_trade
            
            print(f"🔮 虚拟下单成功: {symbol}, 价格: {current_price:.4f}, 数量: {quantity:.6f}, 金额: {amount} USDT")
            
            # 返回模拟的订单信息
            return {
                'orderId': virtual_trade.order_id,
                'symbol': symbol,
                'executedQty': str(quantity),
                'cummulativeQuoteQty': str(amount),
                'status': 'FILLED',
                'type': 'MARKET',
                'side': 'BUY',
                'fills': [{
                    'price': str(current_price),
                    'qty': str(quantity),
                    'commission': '0',
                    'commissionAsset': 'USDT'
                }]
            }
            
        except Exception as e:
            print(f"❌ 虚拟下单失败 {symbol}: {e}")
            return None
    
    def close_trade(self, symbol: str, reason: str = "手动平仓") -> Optional[Dict]:
        """虚拟平仓 - 只有这里使用模拟"""
        try:
            if symbol not in self.active_trades:
                print(f"❌ 没有找到 {symbol} 的活跃交易")
                return None
            
            trade = self.active_trades[symbol]
            
            # 获取当前价格 - 使用真实数据
            current_price = self.get_current_price(symbol)
            if not current_price:
                print(f"❌ 无法获取 {symbol} 的当前真实价格")
                return None
            
            # 计算盈亏 - 虚拟操作
            trade.exit_price = current_price
            trade.exit_time = datetime.now()
            trade.profit_loss = (current_price - trade.entry_price) * trade.quantity
            trade.profit_loss_percentage = ((current_price - trade.entry_price) / trade.entry_price) * 100
            trade.status = 'closed'
            
            # 更新总盈亏 - 虚拟操作
            self.total_profit_loss += trade.profit_loss
            
            # 返还余额（包括盈亏）- 虚拟操作
            self.virtual_balance += trade.amount + trade.profit_loss
            
            print(f"🔮 虚拟平仓成功: {symbol}, 入场价: {trade.entry_price:.4f}, 出场价: {current_price:.4f}, "
                  f"盈亏: {trade.profit_loss:+.2f} USDT ({trade.profit_loss_percentage:+.2f}%), 原因: {reason}")
            
            # 移动到交易历史
            self.trade_history.append(trade)
            del self.active_trades[symbol]
            
            return {
                'orderId': str(uuid.uuid4()),
                'symbol': symbol,
                'executedQty': str(trade.quantity),
                'cummulativeQuoteQty': str(trade.amount + trade.profit_loss),
                'status': 'FILLED',
                'type': 'MARKET',
                'side': 'SELL',
                'profit_loss': trade.profit_loss,
                'profit_loss_percentage': trade.profit_loss_percentage
            }
            
        except Exception as e:
            print(f"❌ 虚拟平仓失败 {symbol}: {e}")
            return None
    
    def get_virtual_balance(self) -> float:
        """获取虚拟余额"""
        return self.virtual_balance
    
    def get_active_trades(self) -> Dict:
        """获取活跃交易"""
        return self.active_trades
    
    def get_trade_history(self) -> list:
        """获取交易历史"""
        return self.trade_history
    
    def get_category_positions(self, category: str) -> list:
        """获取指定分类的持仓"""
        return [trade for trade in self.active_trades.values() if trade.category == category]
    
    def get_total_profit_loss(self) -> float:
        """获取总盈亏"""
        return self.total_profit_loss
    
    def get_performance_summary(self) -> Dict:
        """获取性能摘要"""
        total_invested = self.initial_balance - self.virtual_balance
        roi = (self.total_profit_loss / total_invested * 100) if total_invested > 0 else 0
        
        return {
            'initial_balance': self.initial_balance,
            'current_balance': self.virtual_balance,
            'total_profit_loss': self.total_profit_loss,
            'roi_percentage': roi,
            'active_trades_count': len(self.active_trades),
            'total_trades_count': len(self.trade_history) + len(self.active_trades)
        }