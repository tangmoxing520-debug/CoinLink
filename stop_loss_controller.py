"""
动态止损控制器 (Stop Loss Controller)
根据市场环境和板块特性动态调整止损阈值

Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6
"""
from enum import Enum
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from datetime import datetime

from market_regime_detector import MarketRegimeType


class SectorVolatility(Enum):
    """板块波动性分类"""
    HIGH = "high"      # 高波动: AI Agent, Meme, STABLE
    MEDIUM = "medium"  # 中波动: Layer2, NFT, etc.
    LOW = "low"        # 低波动: Layer1, DeFi, Payment


@dataclass
class StopLossResult:
    """止损计算结果"""
    base_threshold: float       # 基础止损阈值
    regime_multiplier: float    # 市场环境倍数
    sector_multiplier: float    # 板块波动性倍数
    final_threshold: float      # 最终止损阈值
    sector: str                 # 板块名称
    market_regime: str          # 市场状态


@dataclass
class StopLossLogEntry:
    """止损触发日志条目"""
    symbol: str
    sector: str
    threshold: float
    market_regime: str
    timestamp: datetime
    exit_price: float = 0.0
    entry_price: float = 0.0
    loss_pct: float = 0.0


class StopLossController:
    """
    动态止损控制器
    
    根据市场环境和板块特性动态调整止损阈值:
    - 熊市: 止损阈值 × 1.2 (更宽松，避免频繁止损)
    - 高波动板块 (AI Agent, Meme, STABLE): 止损阈值 × 1.3
    - 低波动板块 (Layer1, DeFi, Payment): 止损阈值 × 1.0
    """
    
    # 板块波动性分类
    HIGH_VOLATILITY_SECTORS = {"AI Agent", "Meme", "STABLE"}
    LOW_VOLATILITY_SECTORS = {"Layer1", "DeFi", "Payment"}
    
    def __init__(
        self,
        base_stop_loss: float = 10.0,
        bearish_multiplier: float = 1.2,
        high_volatility_multiplier: float = 1.3,
        low_volatility_multiplier: float = 1.0,
        medium_volatility_multiplier: float = 1.0
    ):
        """
        初始化止损控制器
        
        Args:
            base_stop_loss: 基础止损百分比 (默认10%)
            bearish_multiplier: 熊市止损倍数 (默认1.2)
            high_volatility_multiplier: 高波动板块止损倍数 (默认1.3)
            low_volatility_multiplier: 低波动板块止损倍数 (默认1.0)
            medium_volatility_multiplier: 中波动板块止损倍数 (默认1.0)
        """
        self.base_stop_loss = base_stop_loss
        self.bearish_multiplier = bearish_multiplier
        self.high_volatility_multiplier = high_volatility_multiplier
        self.low_volatility_multiplier = low_volatility_multiplier
        self.medium_volatility_multiplier = medium_volatility_multiplier
        self._stop_loss_logs: List[StopLossLogEntry] = []
    
    def get_stop_loss_threshold(
        self,
        sector: str,
        market_regime: MarketRegimeType
    ) -> StopLossResult:
        """
        获取止损阈值
        
        Args:
            sector: 板块名称
            market_regime: 市场状态
            
        Returns:
            StopLossResult: 止损计算结果
        """
        # 计算市场环境倍数
        if market_regime == MarketRegimeType.BEARISH:
            regime_multiplier = self.bearish_multiplier
        else:
            regime_multiplier = 1.0
        
        # 计算板块波动性倍数
        volatility = self.get_sector_volatility(sector)
        if volatility == SectorVolatility.HIGH:
            sector_multiplier = self.high_volatility_multiplier
        elif volatility == SectorVolatility.LOW:
            sector_multiplier = self.low_volatility_multiplier
        else:
            sector_multiplier = self.medium_volatility_multiplier
        
        # 计算最终止损阈值
        final_threshold = self.base_stop_loss * regime_multiplier * sector_multiplier
        
        return StopLossResult(
            base_threshold=self.base_stop_loss,
            regime_multiplier=regime_multiplier,
            sector_multiplier=sector_multiplier,
            final_threshold=final_threshold,
            sector=sector,
            market_regime=market_regime.value
        )
    
    def get_sector_volatility(self, sector: str) -> SectorVolatility:
        """
        获取板块波动性分类
        
        Args:
            sector: 板块名称
            
        Returns:
            SectorVolatility: 波动性分类
        """
        if sector in self.HIGH_VOLATILITY_SECTORS:
            return SectorVolatility.HIGH
        elif sector in self.LOW_VOLATILITY_SECTORS:
            return SectorVolatility.LOW
        else:
            return SectorVolatility.MEDIUM
    
    def log_stop_loss_trigger(
        self,
        symbol: str,
        sector: str,
        threshold: float,
        market_regime: str,
        timestamp: datetime,
        exit_price: float = 0.0,
        entry_price: float = 0.0
    ) -> None:
        """
        记录止损触发日志
        
        Args:
            symbol: 交易对
            sector: 板块名称
            threshold: 使用的止损阈值
            market_regime: 市场状态
            timestamp: 触发时间
            exit_price: 退出价格
            entry_price: 入场价格
        """
        loss_pct = 0.0
        if entry_price > 0:
            loss_pct = (entry_price - exit_price) / entry_price * 100
        
        log_entry = StopLossLogEntry(
            symbol=symbol,
            sector=sector,
            threshold=threshold,
            market_regime=market_regime,
            timestamp=timestamp,
            exit_price=exit_price,
            entry_price=entry_price,
            loss_pct=loss_pct
        )
        
        self._stop_loss_logs.append(log_entry)
        
        print(f"📉 止损触发: {symbol} [{sector}] @ {exit_price:.4f}, "
              f"阈值: {threshold:.1f}%, 市场: {market_regime}, "
              f"亏损: {loss_pct:.2f}%")
    
    def get_stop_loss_logs(self) -> List[StopLossLogEntry]:
        """获取所有止损日志"""
        return self._stop_loss_logs.copy()
    
    def get_sector_stop_loss_stats(self) -> Dict[str, Dict]:
        """
        获取各板块止损统计
        
        Returns:
            Dict: 板块 -> {count, avg_loss, total_loss}
        """
        stats = {}
        
        for log in self._stop_loss_logs:
            if log.sector not in stats:
                stats[log.sector] = {
                    'count': 0,
                    'total_loss': 0.0,
                    'losses': []
                }
            
            stats[log.sector]['count'] += 1
            stats[log.sector]['total_loss'] += log.loss_pct
            stats[log.sector]['losses'].append(log.loss_pct)
        
        # 计算平均亏损
        for sector in stats:
            count = stats[sector]['count']
            if count > 0:
                stats[sector]['avg_loss'] = stats[sector]['total_loss'] / count
            else:
                stats[sector]['avg_loss'] = 0.0
            del stats[sector]['losses']
        
        return stats
    
    def clear_logs(self) -> None:
        """清空止损日志"""
        self._stop_loss_logs.clear()
