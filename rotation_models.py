"""
板块轮动数据模型

定义板块轮动策略所需的所有数据类和枚举类型。
"""
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Any
import pandas as pd


# ============================================================================
# 枚举类型
# ============================================================================

class SectorTier(Enum):
    """板块层级"""
    HOT = "hot"        # 热门 (Top 25%)
    WARM = "warm"      # 温和 (25-50%)
    NEUTRAL = "neutral"  # 中性 (50-75%)
    COLD = "cold"      # 冷门 (Bottom 25%)


class RotationSignalType(Enum):
    """轮动信号类型"""
    SECTOR_BREAKOUT = "sector_breakout"    # 板块突破 (Cold -> Hot)
    SECTOR_BREAKDOWN = "sector_breakdown"  # 板块崩溃 (Hot -> Cold)
    BROAD_RALLY = "broad_rally"            # 广泛上涨 (>=3板块同步上涨)
    BROAD_SELLOFF = "broad_selloff"        # 广泛下跌 (>=3板块同步下跌)
    MOMENTUM_SHIFT = "momentum_shift"      # 动量转换


# ============================================================================
# 配置数据模型
# ============================================================================

@dataclass
class RotationConfig:
    """板块轮动配置"""
    # 开关
    enabled: bool = True
    
    # 计算参数
    lookback_periods: int = 24  # 回溯周期数
    rebalance_interval: int = 16  # 再平衡间隔 (K线数)
    
    # 维度权重 (自动归一化)
    momentum_weight: float = 0.35
    volume_weight: float = 0.25
    relative_strength_weight: float = 0.25
    leader_weight: float = 0.15
    
    # 权重分配参数
    min_sector_weight: float = 0.05  # 最小权重下限
    rebalance_threshold: float = 0.10  # 再平衡阈值
    hot_multiplier: float = 1.75  # Hot层级默认倍数
    cold_multiplier: float = 0.35  # Cold层级默认倍数
    
    # 高波动保护
    high_volatility_atr_threshold: float = 5.0  # BTC ATR > 5% 延迟再平衡
    
    # Hot 板块评分加成
    hot_score_boost: float = 1.2
    
    def __post_init__(self):
        """初始化后自动归一化权重"""
        self._normalize_weights()
    
    def _normalize_weights(self):
        """归一化维度权重使总和为1.0"""
        total = (self.momentum_weight + self.volume_weight + 
                 self.relative_strength_weight + self.leader_weight)
        if total > 0 and abs(total - 1.0) > 0.001:
            self.momentum_weight /= total
            self.volume_weight /= total
            self.relative_strength_weight /= total
            self.leader_weight /= total
    
    @classmethod
    def from_dict(cls, config_dict: dict) -> 'RotationConfig':
        """从字典创建配置对象"""
        return cls(
            enabled=config_dict.get('enabled', True),
            lookback_periods=config_dict.get('lookback_periods', 24),
            rebalance_interval=config_dict.get('rebalance_interval', 16),
            momentum_weight=config_dict.get('momentum_weight', 0.35),
            volume_weight=config_dict.get('volume_weight', 0.25),
            relative_strength_weight=config_dict.get('relative_strength_weight', 0.25),
            leader_weight=config_dict.get('leader_weight', 0.15),
            min_sector_weight=config_dict.get('min_sector_weight', 0.05),
            rebalance_threshold=config_dict.get('rebalance_threshold', 0.10),
            hot_multiplier=config_dict.get('hot_multiplier', 1.75),
            cold_multiplier=config_dict.get('cold_multiplier', 0.35),
            high_volatility_atr_threshold=config_dict.get('high_volatility_atr_threshold', 5.0),
            hot_score_boost=config_dict.get('hot_score_boost', 1.2)
        )


# ============================================================================
# 运行时数据模型
# ============================================================================

@dataclass
class CoinData:
    """币种数据"""
    symbol: str
    prices: Optional[pd.DataFrame] = None  # OHLCV数据
    current_price: float = 0.0
    price_change_pct: float = 0.0  # 回溯周期内涨幅
    volume_ratio: float = 1.0  # 成交量/均值


@dataclass
class SectorData:
    """板块数据"""
    sector: str
    coins: List[CoinData] = field(default_factory=list)
    leader_coin: str = ""
    avg_price_change: float = 0.0
    avg_volume_ratio: float = 1.0


@dataclass
class SectorStrength:
    """板块强度数据"""
    sector: str
    score: float  # 0-100
    momentum_score: float = 0.0
    volume_score: float = 0.0
    relative_strength_score: float = 0.0
    leader_score: float = 0.0
    confidence: str = "high"  # "high", "medium", "low", "none", "error"
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class SectorClassification:
    """板块分类结果"""
    sector: str
    tier: SectorTier
    rank: int
    score: float
    prev_tier: Optional[SectorTier] = None
    momentum_shift: bool = False


@dataclass
class SectorWeight:
    """板块权重"""
    sector: str
    weight: float  # 0-1
    multiplier: float  # 相对基础权重的倍数
    tier: SectorTier


@dataclass
class RotationSignal:
    """轮动信号"""
    signal_type: RotationSignalType
    sectors: List[str]
    timestamp: datetime
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RotationSnapshot:
    """轮动快照 (用于历史追踪)"""
    timestamp: datetime
    strengths: Dict[str, SectorStrength] = field(default_factory=dict)
    classifications: Dict[str, SectorClassification] = field(default_factory=dict)
    weights: Dict[str, float] = field(default_factory=dict)
    signals: List[RotationSignal] = field(default_factory=list)


# ============================================================================
# 统计报告数据模型
# ============================================================================

@dataclass
class RotationStats:
    """轮动统计"""
    # 板块表现
    sector_avg_strength: Dict[str, float] = field(default_factory=dict)
    sector_time_in_tier: Dict[str, Dict[str, float]] = field(default_factory=dict)  # 各层级停留时间比例
    
    # 交易表现
    trades_by_tier: Dict[str, int] = field(default_factory=dict)
    win_rate_by_tier: Dict[str, float] = field(default_factory=dict)
    avg_profit_by_tier: Dict[str, float] = field(default_factory=dict)
    
    # 轮动效率
    rotation_efficiency: float = 0.0  # Hot板块利润 / Cold板块利润
    rebalance_count: int = 0
    signals_generated: Dict[str, int] = field(default_factory=dict)
    
    # 贡献分析
    profit_contribution: Dict[str, float] = field(default_factory=dict)  # 各板块利润贡献
    top_contributors: List[str] = field(default_factory=list)  # 贡献最大的板块
