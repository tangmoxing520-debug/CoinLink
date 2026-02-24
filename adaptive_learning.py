"""
自适应学习模块 (Adaptive Learning Module)
通过实时监控行情走势和交易表现，自动给出优化建议以提高收益率

核心功能：
1. 行情走势分析：监控市场波动率、趋势强度、成交量变化
2. 交易表现分析：分析胜率、盈亏比、持仓时间、分类表现
3. 参数优化建议：动态调整止损、止盈、信号阈值等参数
4. 策略调整建议：优化分类权重、黑名单规则、仓位管理
"""

import logging
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from collections import defaultdict
import json
import os

logger = logging.getLogger(__name__)


@dataclass
class MarketRegime:
    """市场状态"""
    volatility: float  # 波动率
    trend_strength: float  # 趋势强度 (-1到1)
    volume_trend: float  # 成交量趋势 (-1到1)
    market_phase: str  # 市场阶段: "trending_up", "trending_down", "sideways", "volatile"
    confidence: float  # 置信度 (0-1)


@dataclass
class PerformanceMetrics:
    """交易表现指标"""
    win_rate: float
    profit_factor: float
    avg_win: float
    avg_loss: float
    avg_holding_hours: float
    sharpe_ratio: float
    max_drawdown: float
    total_trades: int
    recent_win_rate: float  # 最近N笔交易的胜率
    category_performance: Dict[str, Dict]  # 分类表现


@dataclass
class OptimizationSuggestion:
    """优化建议"""
    parameter: str  # 参数名称
    current_value: float
    suggested_value: float
    reason: str
    confidence: float  # 置信度 (0-1)
    priority: int  # 优先级 (1-5, 1最高)


@dataclass
class StrategyAdjustment:
    """策略调整建议"""
    adjustment_type: str  # "stop_loss", "take_profit", "signal_threshold", "category_weight", etc.
    current_value: float
    suggested_value: float
    reason: str
    expected_impact: str  # 预期影响
    confidence: float


class MarketAnalyzer:
    """市场行情分析器"""
    
    def __init__(self, lookback_periods: int = 50):
        """
        Args:
            lookback_periods: 回溯周期数（用于计算指标）
        """
        self.lookback_periods = lookback_periods
        self._btc_data_cache: List[Dict] = []
    
    def analyze_market_regime(self, btc_df: pd.DataFrame) -> MarketRegime:
        """
        分析当前市场状态
        
        Args:
            btc_df: BTC K线数据
            
        Returns:
            MarketRegime: 市场状态
        """
        if btc_df is None or len(btc_df) < 20:
            return MarketRegime(
                volatility=0.0,
                trend_strength=0.0,
                volume_trend=0.0,
                market_phase="sideways",
                confidence=0.0
            )
        
        try:
            close = pd.to_numeric(btc_df['close'], errors='coerce')
            volume = pd.to_numeric(btc_df.get('volume', pd.Series()), errors='coerce')
            
            if len(close) < 20:
                return MarketRegime(
                    volatility=0.0,
                    trend_strength=0.0,
                    volume_trend=0.0,
                    market_phase="sideways",
                    confidence=0.0
                )
            
            # 1. 计算波动率（ATR百分比）
            high = pd.to_numeric(btc_df['high'], errors='coerce')
            low = pd.to_numeric(btc_df['low'], errors='coerce')
            atr = self._calculate_atr(high, low, close, period=14)
            volatility = (atr / close.iloc[-1] * 100) if close.iloc[-1] > 0 else 0.0
            
            # 2. 计算趋势强度（MA斜率）
            ma20 = close.rolling(20).mean()
            ma50 = close.rolling(50).mean() if len(close) >= 50 else ma20
            
            if len(ma20) >= 2:
                ma_slope = (ma20.iloc[-1] - ma20.iloc[-min(10, len(ma20)-1)]) / ma20.iloc[-min(10, len(ma20)-1)]
                trend_strength = np.clip(ma_slope * 100, -1, 1)
            else:
                trend_strength = 0.0
            
            # 3. 计算成交量趋势
            if not volume.empty and len(volume) >= 20:
                vol_ma20 = volume.rolling(20).mean()
                current_vol = volume.iloc[-1]
                avg_vol = vol_ma20.iloc[-1] if not vol_ma20.empty else current_vol
                volume_trend = np.clip((current_vol - avg_vol) / avg_vol if avg_vol > 0 else 0, -1, 1)
            else:
                volume_trend = 0.0
            
            # 4. 判断市场阶段
            market_phase = self._classify_market_phase(volatility, trend_strength, volume_trend)
            
            # 5. 计算置信度
            confidence = min(1.0, len(close) / 50.0)
            
            return MarketRegime(
                volatility=volatility,
                trend_strength=trend_strength,
                volume_trend=volume_trend,
                market_phase=market_phase,
                confidence=confidence
            )
            
        except Exception as e:
            logger.error(f"市场分析失败: {e}")
            return MarketRegime(
                volatility=0.0,
                trend_strength=0.0,
                volume_trend=0.0,
                market_phase="sideways",
                confidence=0.0
            )
    
    def _calculate_atr(self, high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> float:
        """计算ATR"""
        try:
            tr1 = high - low
            tr2 = abs(high - close.shift())
            tr3 = abs(low - close.shift())
            tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
            atr = tr.rolling(period).mean().iloc[-1]
            return float(atr) if not pd.isna(atr) else 0.0
        except:
            return 0.0
    
    def _classify_market_phase(self, volatility: float, trend_strength: float, volume_trend: float) -> str:
        """分类市场阶段"""
        if volatility > 3.0:
            return "volatile"
        elif trend_strength > 0.3:
            return "trending_up"
        elif trend_strength < -0.3:
            return "trending_down"
        else:
            return "sideways"


class PerformanceAnalyzer:
    """交易表现分析器"""
    
    def __init__(self, recent_trades_window: int = 20):
        """
        Args:
            recent_trades_window: 最近N笔交易用于计算近期表现
        """
        self.recent_trades_window = recent_trades_window
    
    def analyze_performance(self, trade_history: List) -> PerformanceMetrics:
        """
        分析交易表现
        
        Args:
            trade_history: 交易历史列表（TradeResult对象或字典）
            
        Returns:
            PerformanceMetrics: 表现指标
        """
        if not trade_history:
            return PerformanceMetrics(
                win_rate=0.0,
                profit_factor=0.0,
                avg_win=0.0,
                avg_loss=0.0,
                avg_holding_hours=0.0,
                sharpe_ratio=0.0,
                max_drawdown=0.0,
                total_trades=0,
                recent_win_rate=0.0,
                category_performance={}
            )
        
        # 转换为统一格式
        trades = []
        for t in trade_history:
            if hasattr(t, 'pnl'):
                trades.append({
                    'pnl': t.pnl,
                    'pnl_pct': getattr(t, 'pnl_pct', 0),
                    'holding_hours': getattr(t, 'holding_hours', 0),
                    'symbol': getattr(t, 'symbol', ''),
                    'category': getattr(t, 'category', ''),
                    'signal_score': getattr(t, 'signal_score', 0),
                    'exit_reason': getattr(t, 'exit_reason', '')
                })
            elif isinstance(t, dict):
                trades.append(t)
        
        if not trades:
            return PerformanceMetrics(
                win_rate=0.0,
                profit_factor=0.0,
                avg_win=0.0,
                avg_loss=0.0,
                avg_holding_hours=0.0,
                sharpe_ratio=0.0,
                max_drawdown=0.0,
                total_trades=0,
                recent_win_rate=0.0,
                category_performance={}
            )
        
        # 计算基础指标
        wins = [t for t in trades if t['pnl'] > 0]
        losses = [t for t in trades if t['pnl'] < 0]
        
        win_rate = len(wins) / len(trades) if trades else 0.0
        avg_win = np.mean([t['pnl'] for t in wins]) if wins else 0.0
        avg_loss = abs(np.mean([t['pnl'] for t in losses])) if losses else 0.0
        profit_factor = (sum([t['pnl'] for t in wins]) / abs(sum([t['pnl'] for t in losses]))) if losses and sum([t['pnl'] for t in losses]) < 0 else 0.0
        
        avg_holding_hours = np.mean([t['holding_hours'] for t in trades]) if trades else 0.0
        
        # 计算夏普比率（简化版）
        if len(trades) > 1:
            returns = [t['pnl_pct'] for t in trades]
            sharpe_ratio = np.mean(returns) / np.std(returns) if np.std(returns) > 0 else 0.0
        else:
            sharpe_ratio = 0.0
        
        # 计算最大回撤
        cumulative_pnl = np.cumsum([t['pnl'] for t in trades])
        running_max = np.maximum.accumulate(cumulative_pnl)
        drawdown = running_max - cumulative_pnl
        max_drawdown = float(np.max(drawdown)) if len(drawdown) > 0 else 0.0
        
        # 计算近期胜率
        recent_trades = trades[-self.recent_trades_window:]
        recent_wins = [t for t in recent_trades if t['pnl'] > 0]
        recent_win_rate = len(recent_wins) / len(recent_trades) if recent_trades else 0.0
        
        # 分类表现
        category_performance = self._analyze_category_performance(trades)
        
        return PerformanceMetrics(
            win_rate=win_rate,
            profit_factor=profit_factor,
            avg_win=avg_win,
            avg_loss=avg_loss,
            avg_holding_hours=avg_holding_hours,
            sharpe_ratio=sharpe_ratio,
            max_drawdown=max_drawdown,
            total_trades=len(trades),
            recent_win_rate=recent_win_rate,
            category_performance=category_performance
        )
    
    def _analyze_category_performance(self, trades: List[Dict]) -> Dict[str, Dict]:
        """分析分类表现"""
        category_stats = defaultdict(lambda: {'wins': 0, 'losses': 0, 'total_pnl': 0.0, 'trades': []})
        
        for t in trades:
            category = t.get('category', 'Unknown')
            category_stats[category]['trades'].append(t)
            if t['pnl'] > 0:
                category_stats[category]['wins'] += 1
            else:
                category_stats[category]['losses'] += 1
            category_stats[category]['total_pnl'] += t['pnl']
        
        result = {}
        for category, stats in category_stats.items():
            total = stats['wins'] + stats['losses']
            result[category] = {
                'win_rate': stats['wins'] / total if total > 0 else 0.0,
                'total_trades': total,
                'total_pnl': stats['total_pnl'],
                'avg_pnl': stats['total_pnl'] / total if total > 0 else 0.0
            }
        
        return result


class AdaptiveLearningEngine:
    """自适应学习引擎"""
    
    def __init__(
        self,
        market_analyzer: MarketAnalyzer = None,
        performance_analyzer: PerformanceAnalyzer = None,
        min_trades_for_analysis: int = 10
    ):
        """
        Args:
            market_analyzer: 市场分析器
            performance_analyzer: 表现分析器
            min_trades_for_analysis: 最少交易次数才进行分析
        """
        self.market_analyzer = market_analyzer or MarketAnalyzer()
        self.performance_analyzer = performance_analyzer or PerformanceAnalyzer()
        self.min_trades_for_analysis = min_trades_for_analysis
        
        self._optimization_history: List[Dict] = []
        self._suggestions_cache: List[OptimizationSuggestion] = []
    
    def generate_optimization_suggestions(
        self,
        market_regime: MarketRegime,
        performance: PerformanceMetrics,
        current_config: Dict
    ) -> List[OptimizationSuggestion]:
        """
        生成优化建议
        
        Args:
            market_regime: 市场状态
            performance: 交易表现
            current_config: 当前配置
            
        Returns:
            List[OptimizationSuggestion]: 优化建议列表
        """
        suggestions = []
        
        # 如果交易次数不足，不生成建议
        if performance.total_trades < self.min_trades_for_analysis:
            return suggestions
        
        # 1. 止损优化建议
        stop_loss_suggestion = self._suggest_stop_loss_adjustment(
            market_regime, performance, current_config
        )
        if stop_loss_suggestion:
            suggestions.append(stop_loss_suggestion)
        
        # 2. 止盈优化建议
        take_profit_suggestion = self._suggest_take_profit_adjustment(
            market_regime, performance, current_config
        )
        if take_profit_suggestion:
            suggestions.append(take_profit_suggestion)
        
        # 3. 信号阈值优化建议
        signal_threshold_suggestion = self._suggest_signal_threshold_adjustment(
            market_regime, performance, current_config
        )
        if signal_threshold_suggestion:
            suggestions.append(signal_threshold_suggestion)
        
        # 4. 分类权重优化建议
        category_weight_suggestions = self._suggest_category_weight_adjustments(
            performance, current_config
        )
        suggestions.extend(category_weight_suggestions)
        
        # 5. 持仓时间优化建议
        holding_time_suggestion = self._suggest_holding_time_adjustment(
            performance, current_config
        )
        if holding_time_suggestion:
            suggestions.append(holding_time_suggestion)
        
        # 按优先级排序
        suggestions.sort(key=lambda x: x.priority)
        
        self._suggestions_cache = suggestions
        return suggestions
    
    def _suggest_stop_loss_adjustment(
        self,
        market_regime: MarketRegime,
        performance: PerformanceMetrics,
        current_config: Dict
    ) -> Optional[OptimizationSuggestion]:
        """建议止损调整"""
        current_sl = current_config.get('stop_loss', 4.0)
        
        # 如果胜率低且平均亏损大，建议收紧止损
        if performance.win_rate < 0.45 and performance.avg_loss > performance.avg_win * 1.5:
            new_sl = max(2.0, current_sl * 0.8)  # 收紧20%
            return OptimizationSuggestion(
                parameter="stop_loss",
                current_value=current_sl,
                suggested_value=new_sl,
                reason=f"胜率{performance.win_rate:.1%}较低，平均亏损{performance.avg_loss:.2f}USDT大于平均盈利{performance.avg_win:.2f}USDT，建议收紧止损",
                confidence=0.7,
                priority=1
            )
        
        # 如果高波动市场，建议放宽止损
        if market_regime.volatility > 3.0 and performance.win_rate > 0.5:
            new_sl = min(6.0, current_sl * 1.2)  # 放宽20%
            return OptimizationSuggestion(
                parameter="stop_loss",
                current_value=current_sl,
                suggested_value=new_sl,
                reason=f"高波动市场(波动率{market_regime.volatility:.2f}%)，当前胜率{performance.win_rate:.1%}，建议放宽止损以避免过早止损",
                confidence=0.6,
                priority=3
            )
        
        return None
    
    def _suggest_take_profit_adjustment(
        self,
        market_regime: MarketRegime,
        performance: PerformanceMetrics,
        current_config: Dict
    ) -> Optional[OptimizationSuggestion]:
        """建议止盈调整"""
        current_tp = current_config.get('take_profit', 8.0)
        
        # 如果平均盈利远小于止盈目标，建议降低止盈
        if performance.avg_win > 0 and (performance.avg_win / current_tp) < 0.5:
            new_tp = max(5.0, current_tp * 0.75)  # 降低25%
            return OptimizationSuggestion(
                parameter="take_profit",
                current_value=current_tp,
                suggested_value=new_tp,
                reason=f"平均盈利{performance.avg_win:.2f}USDT远小于止盈目标，建议降低止盈以提高止盈率",
                confidence=0.7,
                priority=2
            )
        
        # 如果趋势强劲且胜率高，建议提高止盈
        if market_regime.trend_strength > 0.5 and performance.win_rate > 0.55:
            new_tp = min(12.0, current_tp * 1.2)  # 提高20%
            return OptimizationSuggestion(
                parameter="take_profit",
                current_value=current_tp,
                suggested_value=new_tp,
                reason=f"趋势强劲(趋势强度{market_regime.trend_strength:.2f})，胜率{performance.win_rate:.1%}，建议提高止盈以获取更大利润",
                confidence=0.6,
                priority=3
            )
        
        return None
    
    def _suggest_signal_threshold_adjustment(
        self,
        market_regime: MarketRegime,
        performance: PerformanceMetrics,
        current_config: Dict
    ) -> Optional[OptimizationSuggestion]:
        """建议信号阈值调整"""
        current_threshold = current_config.get('signal_min_score', 50.0)
        
        # 如果胜率低，建议提高阈值
        if performance.win_rate < 0.45 and performance.recent_win_rate < 0.4:
            new_threshold = min(70.0, current_threshold + 10)
            return OptimizationSuggestion(
                parameter="signal_min_score",
                current_value=current_threshold,
                suggested_value=new_threshold,
                reason=f"胜率{performance.win_rate:.1%}较低，近期胜率{performance.recent_win_rate:.1%}，建议提高信号阈值以过滤低质量信号",
                confidence=0.7,
                priority=1
            )
        
        # 如果胜率高但交易频率低，建议降低阈值
        if performance.win_rate > 0.55 and performance.total_trades < 30:
            new_threshold = max(40.0, current_threshold - 5)
            return OptimizationSuggestion(
                parameter="signal_min_score",
                current_value=current_threshold,
                suggested_value=new_threshold,
                reason=f"胜率{performance.win_rate:.1%}较高但交易频率低({performance.total_trades}笔)，建议降低阈值以增加交易机会",
                confidence=0.6,
                priority=4
            )
        
        return None
    
    def _suggest_category_weight_adjustments(
        self,
        performance: PerformanceMetrics,
        current_config: Dict
    ) -> List[OptimizationSuggestion]:
        """建议分类权重调整"""
        suggestions = []
        
        for category, stats in performance.category_performance.items():
            if stats['total_trades'] < 5:  # 交易次数太少，不调整
                continue
            
            current_weight = current_config.get('category_weights', {}).get(category, 1.0)
            
            # 如果分类表现好，建议增加权重
            if stats['win_rate'] > 0.6 and stats['avg_pnl'] > 0:
                new_weight = min(1.5, current_weight * 1.2)
                suggestions.append(OptimizationSuggestion(
                    parameter=f"category_weight_{category}",
                    current_value=current_weight,
                    suggested_value=new_weight,
                    reason=f"{category}分类表现优秀：胜率{stats['win_rate']:.1%}，平均盈亏{stats['avg_pnl']:.2f}USDT，建议增加权重",
                    confidence=0.7,
                    priority=2
                ))
            
            # 如果分类表现差，建议降低权重
            elif stats['win_rate'] < 0.4 and stats['avg_pnl'] < 0:
                new_weight = max(0.5, current_weight * 0.8)
                suggestions.append(OptimizationSuggestion(
                    parameter=f"category_weight_{category}",
                    current_value=current_weight,
                    suggested_value=new_weight,
                    reason=f"{category}分类表现较差：胜率{stats['win_rate']:.1%}，平均盈亏{stats['avg_pnl']:.2f}USDT，建议降低权重",
                    confidence=0.7,
                    priority=2
                ))
        
        return suggestions
    
    def _suggest_holding_time_adjustment(
        self,
        performance: PerformanceMetrics,
        current_config: Dict
    ) -> Optional[OptimizationSuggestion]:
        """建议持仓时间调整"""
        # 分析持仓时间与盈亏的关系
        # 这里简化处理，实际可以更详细分析
        
        # 如果平均持仓时间短但胜率低，可能是过早平仓
        if performance.avg_holding_hours < 1.0 and performance.win_rate < 0.45:
            return OptimizationSuggestion(
                parameter="min_holding_time",
                current_value=0.0,
                suggested_value=1.0,
                reason=f"平均持仓时间{performance.avg_holding_hours:.1f}小时过短，胜率{performance.win_rate:.1%}较低，建议延长持仓时间",
                confidence=0.6,
                priority=4
            )
        
        return None
    
    def get_summary_report(
        self,
        market_regime: MarketRegime,
        performance: PerformanceMetrics,
        suggestions: List[OptimizationSuggestion]
    ) -> str:
        """生成摘要报告"""
        report = []
        report.append("=" * 60)
        report.append("📊 自适应学习模块 - 分析报告")
        report.append("=" * 60)
        
        report.append("\n📈 市场状态:")
        report.append(f"  波动率: {market_regime.volatility:.2f}%")
        report.append(f"  趋势强度: {market_regime.trend_strength:.2f}")
        report.append(f"  成交量趋势: {market_regime.volume_trend:.2f}")
        report.append(f"  市场阶段: {market_regime.market_phase}")
        
        report.append("\n💰 交易表现:")
        report.append(f"  总交易数: {performance.total_trades}")
        report.append(f"  胜率: {performance.win_rate:.1%}")
        report.append(f"  盈亏比: {performance.profit_factor:.2f}")
        report.append(f"  平均盈利: {performance.avg_win:.2f} USDT")
        report.append(f"  平均亏损: {performance.avg_loss:.2f} USDT")
        report.append(f"  平均持仓时间: {performance.avg_holding_hours:.1f} 小时")
        report.append(f"  近期胜率: {performance.recent_win_rate:.1%}")
        
        if suggestions:
            report.append("\n💡 优化建议:")
            for i, sug in enumerate(suggestions[:5], 1):  # 只显示前5个
                report.append(f"  {i}. [{sug.parameter}]")
                report.append(f"     当前值: {sug.current_value}")
                report.append(f"     建议值: {sug.suggested_value}")
                report.append(f"     原因: {sug.reason}")
                report.append(f"     置信度: {sug.confidence:.1%}, 优先级: {sug.priority}")
        else:
            report.append("\n💡 暂无优化建议（交易数据不足或表现良好）")
        
        report.append("\n" + "=" * 60)
        
        return "\n".join(report)
    
    def save_analysis(self, filepath: str = "learning_analysis.json"):
        """保存分析结果"""
        try:
            data = {
                'timestamp': datetime.now().isoformat(),
                'suggestions': [
                    {
                        'parameter': s.parameter,
                        'current_value': s.current_value,
                        'suggested_value': s.suggested_value,
                        'reason': s.reason,
                        'confidence': s.confidence,
                        'priority': s.priority
                    }
                    for s in self._suggestions_cache
                ]
            }
            
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            
            logger.info(f"分析结果已保存: {filepath}")
        except Exception as e:
            logger.error(f"保存分析结果失败: {e}")
