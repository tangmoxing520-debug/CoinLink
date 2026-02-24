"""
优化回测引擎包装器
集成策略优化组件到BacktestEngineV2
Requirements: 7.1, 8.1-8.6
"""
import pandas as pd
from datetime import datetime
from typing import Dict, Optional, Tuple

from backtester_v2 import BacktestEngineV2, BacktestTradeV2, BacktestResultV2
from market_regime_detector import MarketRegimeDetector, MarketRegimeType
from stop_loss_controller import StopLossController
from sector_weight_manager import SectorWeightManager
from signal_calibrator import SignalCalibrator
from strategy_optimizer import StrategyOptimizer


class OptimizedBacktestEngine(BacktestEngineV2):
    """
    优化回测引擎 - 集成策略优化组件
    
    新增功能:
    1. 市场环境检测 (BTC MA20)
    2. 动态止损 (熊市1.2x, 高波动板块1.3x)
    3. 板块权重调整 (胜率<40%权重减半)
    4. 信号校准 (成交量/波动率/市场环境)
    5. 熊市保护 (持仓减半, 阈值提高)
    6. 板块黑名单 (连续亏损5次)
    """
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # 初始化策略优化组件
        self.regime_detector = MarketRegimeDetector()
        self.dynamic_stop_loss = StopLossController()
        self.sector_weight_mgr = SectorWeightManager()
        self.signal_calibrator = SignalCalibrator()
        self.strategy_optimizer = StrategyOptimizer(
            self.regime_detector,
            self.dynamic_stop_loss,
            self.sector_weight_mgr,
            self.signal_calibrator
        )
        
        # 当前市场状态缓存
        self._current_regime: MarketRegimeType = MarketRegimeType.SIDEWAYS
        self._current_drawdown_pct: float = 0.0
        
        # 优化统计
        self.optimization_stats = {
            'regime_changes': [],
            'skipped_trades': 0,
            'blacklisted_skips': 0,
            'dynamic_sl_triggers': 0,
            'pause_periods': 0
        }
    
    def detect_market_regime(self, btc_df: pd.DataFrame) -> MarketRegimeType:
        """检测市场环境"""
        if btc_df is None or len(btc_df) < 20:
            return MarketRegimeType.SIDEWAYS
        
        result = self.regime_detector.detect_regime(btc_df)
        
        # 记录状态变化
        if result.regime != self._current_regime:
            self.optimization_stats['regime_changes'].append({
                'time': btc_df.index[-1] if hasattr(btc_df.index, '__getitem__') else datetime.now(),
                'from': self._current_regime.value,
                'to': result.regime.value
            })
        
        self._current_regime = result.regime
        return result.regime
    
    def get_dynamic_stop_loss(self, sector: str) -> float:
        """获取动态止损阈值"""
        result = self.dynamic_stop_loss.get_stop_loss_threshold(sector, self._current_regime)
        return result.final_threshold
    
    def get_sector_weight(self, sector: str) -> float:
        """获取板块权重"""
        result = self.sector_weight_mgr.get_sector_weight(sector)
        return result.final_weight
    
    def is_sector_blacklisted(self, sector: str) -> bool:
        """检查板块是否在黑名单"""
        return self.sector_weight_mgr.is_sector_blacklisted(sector)
    
    def calibrate_signal(
        self,
        raw_score: float,
        volume_ratio: float,
        atr_ratio: float
    ) -> Tuple[float, bool, Optional[str]]:
        """校准信号评分"""
        result = self.signal_calibrator.calibrate_signal(
            raw_score, volume_ratio, atr_ratio, self._current_regime
        )
        return result.final_score, result.should_skip, result.skip_reason
    
    def get_trading_parameters(self, sector: str, current_time: datetime):
        """获取当前交易参数"""
        return self.strategy_optimizer.get_trading_parameters(
            self._current_regime, sector, self._current_drawdown_pct, current_time
        )
    
    def record_trade_result(self, trade: BacktestTradeV2, current_time: datetime):
        """记录交易结果"""
        is_win = trade.profit_loss > 0
        
        # 更新板块权重管理器
        self.sector_weight_mgr.record_trade(
            trade.category, trade.profit_loss, current_time
        )
        
        # 更新策略优化器
        self.strategy_optimizer.record_trade_result(
            is_win, self._current_drawdown_pct, current_time
        )
    
    def update_drawdown(self):
        """更新当前回撤"""
        if self.max_balance > 0:
            current_equity = self.balance + sum(t.margin for t in self.active_trades.values())
            self._current_drawdown_pct = ((self.max_balance - current_equity) / self.max_balance) * 100
    
    def should_open_trade(
        self,
        sector: str,
        raw_score: float,
        volume_ratio: float,
        atr_ratio: float,
        current_time: datetime
    ) -> Tuple[bool, str]:
        """
        判断是否应该开仓
        综合考虑: 黑名单、信号校准、交易暂停、熊市保护
        """
        # 1. 检查黑名单
        if self.is_sector_blacklisted(sector):
            self.optimization_stats['blacklisted_skips'] += 1
            return False, f"板块 {sector} 在黑名单中"
        
        # 2. 检查交易暂停
        allowed, reason = self.strategy_optimizer.is_trading_allowed(current_time)
        if not allowed:
            self.optimization_stats['pause_periods'] += 1
            return False, reason
        
        # 3. 校准信号
        calibrated_score, should_skip, skip_reason = self.calibrate_signal(
            raw_score, volume_ratio, atr_ratio
        )
        
        if should_skip:
            self.optimization_stats['skipped_trades'] += 1
            return False, skip_reason
        
        # 4. 获取交易参数
        params = self.get_trading_parameters(sector, current_time)
        
        # 5. 检查持仓限制
        if len(self.active_trades) >= params.max_positions:
            return False, f"持仓已达上限 {params.max_positions}"
        
        return True, ""
    
    def calculate_position_size(self, sector: str, base_amount: float) -> float:
        """计算仓位大小 (应用板块权重和回撤调整)"""
        # 板块权重
        sector_weight = self.get_sector_weight(sector)
        
        # 回撤调整
        params = self.get_trading_parameters(sector, datetime.now())
        
        adjusted_amount = base_amount * sector_weight * params.position_size_multiplier
        
        # 限制最大仓位
        return min(adjusted_amount, self.max_trade_amount)
    
    def update_blacklist(self, current_time: datetime):
        """更新黑名单状态"""
        removed = self.sector_weight_mgr.update_blacklist(current_time)
        return removed
    
    def get_optimization_summary(self) -> dict:
        """获取优化统计摘要"""
        return {
            'current_regime': self._current_regime.value,
            'current_drawdown_pct': self._current_drawdown_pct,
            'regime_changes': len(self.optimizati