import pandas as pd
import os
import logging
from datetime import datetime
from typing import Dict, List  # 确保导入 List

logger = logging.getLogger(__name__)

class TradeRecorder:
    """交易记录管理器"""
    
    def __init__(self, excel_path: str = "trade_records.xlsx"):
        self.excel_path = excel_path
        base, _ = os.path.splitext(self.excel_path)
        self.csv_path = f"{base}.csv"
        self.records = []
        self._warned_openpyxl_missing = False
        self._using_csv_fallback = False
        
        # 如果Excel文件存在，加载历史记录
        if os.path.exists(self.excel_path):
            try:
                self.df = pd.read_excel(self.excel_path)
                self.records = self.df.to_dict('records')
                self._using_csv_fallback = False
            except Exception as e:
                # 常见：未安装 openpyxl，导致 read_excel 失败；此时降级从 CSV 读取（如果存在）
                if isinstance(e, ModuleNotFoundError) and "openpyxl" in str(e):
                    self._warn_openpyxl_missing(action="读取")
                else:
                    logger.warning("加载交易记录失败（Excel）: %s", e)

                if os.path.exists(self.csv_path):
                    try:
                        self.df = pd.read_csv(self.csv_path)
                        self.records = self.df.to_dict('records')
                        self._using_csv_fallback = True
                        logger.info("已从 CSV 加载交易记录: %s", self.csv_path)
                    except Exception as csv_e:
                        logger.warning("加载交易记录失败（CSV）: %s", csv_e)
                        self.df = pd.DataFrame()
                else:
                    self.df = pd.DataFrame()
        else:
            # 如果没有 Excel，但存在 CSV，也尝试加载
            if os.path.exists(self.csv_path):
                try:
                    self.df = pd.read_csv(self.csv_path)
                    self.records = self.df.to_dict('records')
                    self._using_csv_fallback = True
                    logger.info("已从 CSV 加载交易记录: %s", self.csv_path)
                except Exception as csv_e:
                    logger.warning("加载交易记录失败（CSV）: %s", csv_e)
                    self.df = pd.DataFrame()
            else:
                self.df = pd.DataFrame()
    
    def add_trade_record(self, symbol: str, entry_price: float, quantity: float, 
                        amount: float, category: str, entry_time: datetime,
                        exit_price: float = None, exit_time: datetime = None,
                        profit_loss: float = 0, profit_loss_percentage: float = 0,
                        status: str = 'open', close_reason: str = None):
        """添加交易记录"""
        
        record = {
            'symbol': symbol,
            'category': category,
            'entry_price': entry_price,
            'quantity': quantity,
            'amount': amount,
            'entry_time': entry_time,
            'exit_price': exit_price,
            'exit_time': exit_time,
            'profit_loss': profit_loss,
            'profit_loss_percentage': profit_loss_percentage,
            'status': status,
            'close_reason': close_reason
        }
        
        self.records.append(record)
        self._save_to_excel()
    
    def update_trade_record(self, symbol: str, exit_price: float, exit_time: datetime,
                          profit_loss: float, profit_loss_percentage: float,
                          status: str = 'closed', close_reason: str = None):
        """更新交易记录（平仓时调用）"""
        
        for record in self.records:
            if record['symbol'] == symbol and record['status'] == 'open':
                record.update({
                    'exit_price': exit_price,
                    'exit_time': exit_time,
                    'profit_loss': profit_loss,
                    'profit_loss_percentage': profit_loss_percentage,
                    'status': status,
                    'close_reason': close_reason
                })
                break
        
        self._save_to_excel()
    
    def _warn_openpyxl_missing(self, action: str):
        """openpyxl 未安装时的提示（只提示一次，避免刷屏）"""
        if self._warned_openpyxl_missing:
            return
        self._warned_openpyxl_missing = True
        logger.warning(
            "保存/读取交易记录需要 openpyxl 才能写入/读取 xlsx（当前未安装）。已自动降级为 CSV。"
            " 如需继续使用 xlsx，请安装: pip install openpyxl"
            "（当前动作: %s）",
            action
        )

    def _save_to_csv(self, df: pd.DataFrame):
        """保存到 CSV（Excel 兼容 utf-8-sig）"""
        try:
            df.to_csv(self.csv_path, index=False, encoding="utf-8-sig")
            if not self._using_csv_fallback:
                self._using_csv_fallback = True
                logger.info("交易记录将保存为 CSV: %s", self.csv_path)
            else:
                logger.debug("交易记录已保存到 CSV: %s", self.csv_path)
        except Exception as e:
            logger.error("保存交易记录失败（CSV）: %s", e, exc_info=True)

    def _save_to_excel(self):
        """保存到文件（优先 xlsx；缺少 openpyxl 时自动降级 CSV）"""
        try:
            df = pd.DataFrame(self.records)
            
            # 格式化时间列
            if 'entry_time' in df.columns:
                df['entry_time'] = pd.to_datetime(df['entry_time']).dt.strftime('%Y-%m-%d %H:%M:%S')
            if 'exit_time' in df.columns:
                df['exit_time'] = pd.to_datetime(df['exit_time']).dt.strftime('%Y-%m-%d %H:%M:%S')
            
            # 重新排列列顺序
            columns_order = [
                'symbol', 'category', 'entry_price', 'exit_price', 'quantity', 
                'amount', 'profit_loss', 'profit_loss_percentage', 'status',
                'close_reason', 'entry_time', 'exit_time'
            ]
            
            # 只保留存在的列
            existing_columns = [col for col in columns_order if col in df.columns]
            df = df[existing_columns]
            
            df.to_excel(self.excel_path, index=False)
            self._using_csv_fallback = False
            logger.debug("交易记录已保存到: %s", self.excel_path)
            
        except Exception as e:
            # openpyxl 缺失是最常见原因：自动降级为 CSV，不影响交易主流程
            if isinstance(e, ModuleNotFoundError) and "openpyxl" in str(e):
                self._warn_openpyxl_missing(action="写入")
                self._save_to_csv(df)
                return
            logger.error("保存交易记录失败（Excel）: %s", e, exc_info=True)
    
    def get_trade_statistics(self) -> Dict:
        """获取交易统计信息"""
        if not self.records:
            return {}
        
        df = pd.DataFrame(self.records)
        
        # 只统计已平仓的交易
        closed_trades = df[df['status'] == 'closed']
        
        if closed_trades.empty:
            return {
                'total_trades': 0,
                'winning_trades': 0,
                'losing_trades': 0,
                'total_profit_loss': 0,
                'win_rate': 0,
                'avg_profit_per_trade': 0
            }
        
        winning_trades = closed_trades[closed_trades['profit_loss'] > 0]
        losing_trades = closed_trades[closed_trades['profit_loss'] <= 0]
        
        return {
            'total_trades': len(closed_trades),
            'winning_trades': len(winning_trades),
            'losing_trades': len(losing_trades),
            'total_profit_loss': closed_trades['profit_loss'].sum(),
            'win_rate': len(winning_trades) / len(closed_trades) * 100,
            'avg_profit_per_trade': closed_trades['profit_loss'].mean(),
            'max_profit': closed_trades['profit_loss'].max(),
            'max_loss': closed_trades['profit_loss'].min()
        }
    
    def get_category_statistics(self) -> Dict:
        """按分类获取统计信息"""
        if not self.records:
            return {}
        
        df = pd.DataFrame(self.records)
        closed_trades = df[df['status'] == 'closed']
        
        if closed_trades.empty:
            return {}
        
        category_stats = {}
        for category in closed_trades['category'].unique():
            category_trades = closed_trades[closed_trades['category'] == category]
            winning_trades = category_trades[category_trades['profit_loss'] > 0]
            
            category_stats[category] = {
                'total_trades': len(category_trades),
                'winning_trades': len(winning_trades),
                'total_profit_loss': category_trades['profit_loss'].sum(),
                'win_rate': len(winning_trades) / len(category_trades) * 100 if len(category_trades) > 0 else 0
            }
        
        return category_stats