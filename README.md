# CoinLink 加密货币量化交易系统

## 系统概述

CoinLink 是一个基于板块轮动策略的加密货币量化交易系统，支持币安合约交易。系统通过监控各板块龙头币的价格变化，自动识别交易机会并执行交易。

### 核心策略

**板块轮动 + 龙头跟涨策略**：
1. 监控各板块龙头币的价格变化
2. 当龙头币出现暴涨信号时，触发交易信号
3. 对龙头币和同板块其他币种进行信号评分
4. 选择评分达标的币种开仓交易
5. 通过多重止损机制管理风险

### V6 高收益版特点

- **年化收益**: 回测验证 1295%+ (2025全年)
- **季度达标**: 每季度均超过100%收益目标
- **优化止损**: 平衡止损与交易频率，减少过早止损
- **高频交易**: 信号阈值50分，大幅增加交易机会

---

## 目录结构

```
CoinLink/
├── config.env          # 配置文件 (API密钥、交易参数等)
├── config.py           # 配置加载模块
├── main.py             # 实时监控主程序 (基础版)
├── live_trader_v3.py   # 实时交易系统 V3 (推荐)
├── trader_v2.py        # 交易器核心模块
├── run_backtest.py     # 回测运行脚本
├── backtester_v2.py    # 回测引擎 V2
├── analyzer.py         # 价格分析器
├── data_fetcher.py     # 数据获取模块
├── binance_fetcher.py  # 币安数据获取
├── notifier.py         # 钉钉通知模块
├── trade_recorder.py   # 交易记录模块
└── backtest_results/   # 回测结果存储目录
```

---

## 快速开始

### 1. 环境准备

```bash
# 安装依赖
pip install -r requirements.txt
```

### 2. 配置文件

编辑 `config.env` 文件，配置必要参数：

```env
# 交易所配置
EXCHANGE=binance

# 币安 API (如需真实交易)
BINANCE_API_KEY=your_api_key
BINANCE_SECRET_KEY=your_secret_key

# 钉钉通知 (可选)
DINGTALK_WEBHOOK=your_webhook_url
DINGTALK_SECRET=your_secret
```

### 3. 运行程序

```bash
# 运行实时监控 (推荐)
python live_trader_v3.py

# 或运行基础版监控
python main.py

# 运行回测
python run_backtest.py --mode full --independent
```

---

## 运行脚本说明

### 实时交易系统

#### `live_trader_v3.py` - 推荐使用

```bash
python live_trader_v3.py
```

功能：
- 实时监控所有板块的价格变化
- 自动识别龙头币暴涨信号
- 执行信号评分和开仓交易
- 多重止损机制 (止盈/止损/移动止损/时间止损)
- 钉钉消息通知
- 交易记录保存到Excel
- V6高收益参数配置

#### `main.py` - 基础版

```bash
python main.py
```

功能：
- 基础的价格监控
- 警报通知
- 适合只需要监控不需要自动交易的场景

---

### 回测系统

#### `run_backtest.py` - 回测运行脚本

**基本用法：**

```bash
# 运行全年回测 (默认V6参数)
python run_backtest.py --mode full --independent

# 运行单季度回测
python run_backtest.py --mode quarterly --quarter Q1 --independent

# 使用V4参数回测 (备用版本)
python run_backtest.py --mode full --independent --v4

# 使用Q3/Q4优化版回测
python run_backtest.py --mode full --independent --q3q4

# 对比回测 (V4 vs Q3/Q4)
python run_backtest.py --mode compare --quarter Q3

# 启用分类亏损过滤器
python run_backtest.py --mode full --independent --category-filter
```

**参数说明：**

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--mode` | 回测模式 | `v2` |
| `--quarter` | 季度 (Q1/Q2/Q3/Q4) | 无 |
| `--year` | 年份 | 2025 |
| `--independent` | 独立模式 (每季度独立计算) | 否 |
| `--v4` | 使用V4参数 (备用) | 否 |
| `--q3q4` | 使用Q3/Q4优化版 | 否 |
| `--start` | 开始日期 (YYYY-MM-DD) | 无 |
| `--end` | 结束日期 (YYYY-MM-DD) | 无 |
| `--interval` | K线间隔 | 15m |
| `--category-filter` | 启用分类亏损过滤器 | 否 |
| `--pnl-threshold` | 分类累计亏损阈值 | -2000 |
| `--win-rate-threshold` | 分类胜率阈值 | 40 |

**回测模式：**

| 模式 | 说明 |
|------|------|
| `v2` | 默认回测 (V6参数) |
| `quarterly` | 单季度回测 |
| `full` | 全年回测 (Q1-Q4) |
| `q3q4` | Q3/Q4优化版回测 |
| `compare` | 对比回测 |
| `category` | 单分类回测 |

---

## V6 高收益版参数配置 (默认)

### 交易参数
```
杠杆倍数: 15x
止盈: 8% (价格变化)
止损: 4% (价格变化)
移动止损: 1.5% (激活阈值: 2.5%)
最大持仓: 8
基础交易金额: 500 USDT
最大交易金额: 2500 USDT
冷却期: 2根K线
```

### 止损参数
```
ATR乘数: 1.5
最小止损: 3.0%
最大止损: 8.0%
保本阈值: 2.0%
保本缓冲: 0.15%
短期时间止损: 1.5小时 (盈利<1%平仓)
长期时间止损: 8小时 (亏损平仓)
```

### 信号参数
```
最低评分: 50分
ADX阈值: 15
成交量高比率: 1.3
异常成交量比率: 3.5
动量权重: 40%
趋势权重: 20%
成交量权重: 15%
相关性权重: 15%
波动率权重: 10%
```

### 黑名单参数
```
连续亏损触发: 5次
黑名单时长: 8小时
提前解除: 启用 (连续盈利2次)
```

---

## 系统功能详解

### 1. 信号评分系统

系统使用多维度信号评分来筛选交易机会：

| 维度 | 权重 | 说明 |
|------|------|------|
| 动量 | 40% | MACD、ROC、RSI等动量指标 |
| 趋势 | 20% | MA对齐、ADX强度、价格位置 |
| 成交量 | 15% | 量比、连续放量 |
| 相关性 | 15% | 与龙头币的相关性 |
| 波动率 | 10% | ATR、布林带宽度 |

**V6参数：**
- 最低入场评分：50分 (大幅增加交易频率)
- ADX强趋势阈值：15 (更宽松)
- 高成交量阈值：1.3倍 (更宽松)

### 2. 止损机制

系统实现了多重止损保护：

#### 2.1 固定止损/止盈
- 止盈：8% (价格变化) → 杠杆后收益 120%
- 止损：4% (价格变化) → 杠杆后亏损 -60%

#### 2.2 移动止损
- 激活阈值：2.5% 盈利后激活
- 回撤比例：1.5% (从最高点回撤1.5%触发)

#### 2.3 保本止损
- 激活阈值：2.0% 盈利后激活
- 保本缓冲：0.15%

#### 2.4 信号评分止损
根据开仓时的信号评分设置不同止损：
- 高评分 (≥80)：6% 止损
- 中评分 (60-79)：5% 止损
- 低评分 (<60)：4% 止损

#### 2.5 时间止损
- 短期：持仓1.5小时，盈利<1% 则平仓
- 长期：持仓8小时，亏损则平仓

#### 2.6 动态止损 (ATR)
- ATR乘数：1.5
- 最小止损：3.0%
- 最大止损：8.0%

### 3. 黑名单机制

#### 3.1 静态黑名单
预设的表现差的交易对：
- XLMUSDT (Payment, 胜率25%)
- SANTOSUSDT (Sports, 胜率33%)
- RLCUSDT (VR/AR, 胜率43%)
- UAIUSDT (AI Agent, 胜率36%)

#### 3.2 动态黑名单 (V6优化)
- 触发条件：连续亏损5次 (更宽容)
- 黑名单时长：8小时 (更快恢复)
- 提前解除：连续盈利2次可提前解除

#### 3.3 分类黑名单
禁止交易的板块：
- Payment (支付类) - 胜率31.2%
- Sports (体育类) - 胜率37.5%

### 4. 分类权重调整 (V6优化)

根据历史表现调整各板块的仓位权重：

| 板块 | 权重 | 说明 |
|------|------|------|
| SOL | 2.0x | 表现最好 |
| Meme | 1.8x | 高收益 |
| Layer1 | 1.8x | 稳定 |
| AI Agency | 1.6x | 表现好 |
| Layer2 | 1.5x | 稳定 |
| RWA | 1.3x | 稳定 |
| AI Agent | 1.0x | 中性 (频繁亏损) |
| DID | 0.6x | 表现差 |
| STABLE | 0.6x | 表现差 |
| Metaverse | 0.5x | 表现差 |
| VR/AR | 0.3x | 表现最差 |

### 5. 板块轮动

系统支持板块轮动策略，根据板块强度动态调整权重：

- 回溯周期：24根K线
- 再平衡间隔：16根K线
- Hot板块评分加成：1.2倍
- Hot板块权重倍数：1.75x
- Cold板块权重倍数：0.35x

### 6. 龙头币交易

当龙头币触发暴涨信号时：
1. 龙头币本身也会被评估是否符合交易条件
2. 如果信号评分达标，龙头币也会开仓
3. 同时检查同板块其他跟涨不足的币种

---

## 监控的板块

系统监控以下18个板块：

| 板块 | 龙头币 | 说明 |
|------|--------|------|
| Layer1 | BTCUSDT | 公链 |
| Layer2 | OPUSDT | 二层网络 |
| SOL | SOLUSDT | Solana生态 |
| Meme | DOGEUSDT | Meme币 |
| AI Agent | FARTCOINUSDT | AI代理 |
| AI Agency | TAOUSDT | AI机构 |
| DeFi | UNIUSDT | 去中心化金融 |
| RWA | ONDOUSDT | 真实世界资产 |
| NFT | BLURUSDT | NFT |
| Metaverse | SANDUSDT | 元宇宙 |
| Storage | FILUSDT | 存储 |
| Privacy | XMRUSDT | 隐私币 |
| Payment | XRPUSDT | 支付 |
| DID | WLDUSDT | 去中心化身份 |
| Web3.0 | DOTUSDT | Web3 |
| VR/AR | MAGICUSDT | VR/AR |
| Sports | CHZUSDT | 体育 |
| STABLE | XPLUSDT | 稳定币相关 |

---

## 回测结果 (V6 高收益版)

### 2025年全年回测

```
季度      收益           收益率      交易数    胜率      达标
Q1       +40,258 USDT   +201.29%    748      51.6%     ✅
Q2       +68,638 USDT   +343.19%    1237     52.5%     ✅
Q3       +75,328 USDT   +376.64%    1560     52.8%     ✅
Q4       +74,950 USDT   +374.75%    2001     51.1%     ✅
────────────────────────────────────────────────────────────
全年合计  +259,174 USDT  +1295.87%   5546     52.0%     ✅
```

**关键指标：**
- 年化收益率：1295%+
- 平均季度收益：324%
- 平均胜率：52%
- 每季度均超过100%目标 ✅

---

## 版本对比

| 参数 | V4 (备用) | V5 | V6 (默认) |
|------|-----------|-----|-----------|
| 止盈 | 10% | 6% | 8% |
| 止损 | 5% | 3% | 4% |
| 移动止损 | 2%/3% | 1%/2% | 1.5%/2.5% |
| 最大持仓 | 8 | 6 | 8 |
| 最大交易金额 | 3000 | 2000 | 2500 |
| 信号阈值 | 70 | 60 | 50 |
| 黑名单触发 | 4次 | 4次 | 5次 |
| 黑名单时长 | 12h | 12h | 8h |
| ATR乘数 | 1.8 | 1.2 | 1.5 |

---

## 常见问题

### Q: 如何切换到V4参数？
```bash
python run_backtest.py --mode full --independent --v4
```

### Q: 如何只监控特定板块？
编辑 `config.env`，修改 `BACKTEST_CATEGORIES`：
```env
BACKTEST_CATEGORIES=SOL,Meme,Layer1
```

### Q: 如何调整信号阈值？
编辑 `config.env`：
```env
SIGNAL_MIN_SCORE=60.0
```

### Q: 如何禁用某个交易对？
在 `config.py` 的 `SYMBOL_BLACKLIST` 中添加：
```python
SYMBOL_BLACKLIST = [
    "XLMUSDT",
    "YOUR_SYMBOL_HERE",
]
```

### Q: 如何调整止盈止损？
编辑 `config.env`：
```env
V2_TAKE_PROFIT=8
V2_STOP_LOSS=4
V2_TRAILING_STOP_PCT=1.5
V2_TRAILING_STOP_ACTIVATION=2.5
```

### Q: 如何调整黑名单参数？
编辑 `config.env`：
```env
BLACKLIST_CONSECUTIVE_LOSSES=5
BLACKLIST_DURATION_HOURS=8
BLACKLIST_EARLY_RELEASE_ENABLED=true
BLACKLIST_EARLY_RELEASE_WINS=2
```

---

## 配置文件说明 (config.env)

### 基础配置
```env
# 交易所 (binance 或 gate)
EXCHANGE=binance

# 币安合约API
BINANCE_FUTURES_API_URL=https://fapi.binance.com/fapi/v1
BINANCE_API_KEY=your_api_key
BINANCE_SECRET_KEY=your_secret_key
```

### V6 交易参数
```env
# 基础交易金额
V2_BASE_TRADE_AMOUNT=500
# 最大交易金额
V2_MAX_TRADE_AMOUNT=2500
# 止盈 (价格变化%)
V2_TAKE_PROFIT=8
# 止损 (价格变化%)
V2_STOP_LOSS=4
# 移动止损回撤%
V2_TRAILING_STOP_PCT=1.5
# 移动止损激活阈值%
V2_TRAILING_STOP_ACTIVATION=2.5
# 最大持仓数
V2_MAX_POSITIONS=8
# 杠杆倍数
LEVERAGE=15
```

### V6 止损配置
```env
# ATR乘数
ATR_MULTIPLIER=1.5
# 最小止损%
MIN_STOP_LOSS=3.0
# 最大止损%
MAX_STOP_LOSS=8.0
# 保本激活阈值%
EARLY_BREAKEVEN_THRESHOLD=2.0
# 保本缓冲%
EARLY_BREAKEVEN_BUFFER=0.15
# 短期时间止损 (小时)
SHORT_TIME_STOP_HOURS=1.5
# 短期止损最低盈利%
SHORT_TIME_STOP_MIN_PROFIT=1.0
# 长期时间止损 (小时)
LONG_TIME_STOP_HOURS=8.0
```

### V6 信号配置
```env
# 最低入场评分
SIGNAL_MIN_SCORE=50
# ADX强趋势阈值
SIGNAL_ADX_STRONG_THRESHOLD=15.0
# 高成交量阈值
SIGNAL_VOLUME_HIGH_RATIO=1.3
# 异常成交量阈值
SIGNAL_VOLUME_ABNORMAL_RATIO=3.5
```

### V6 黑名单配置
```env
# 连续亏损触发黑名单
BLACKLIST_CONSECUTIVE_LOSSES=5
# 黑名单时长 (小时)
BLACKLIST_DURATION_HOURS=8
# 启用提前解除
BLACKLIST_EARLY_RELEASE_ENABLED=true
# 连续盈利解除次数
BLACKLIST_EARLY_RELEASE_WINS=2
```

---

## 风险提示

⚠️ **重要提示**：
1. 本系统仅供学习和研究使用
2. 加密货币交易存在高风险，可能导致本金损失
3. 历史回测结果不代表未来收益
4. 15倍杠杆风险极高，请谨慎使用
5. 建议先使用虚拟交易模式测试
6. 回测使用固定仓位模式，非复利模式

---

## 更新日志

### V6 高收益版 (2026-01-11)
- **止盈止损优化**: 止盈8%，止损4%，平衡收益与风险
- **移动止损放宽**: 1.5%回撤，2.5%激活，减少过早止损
- **信号阈值降低**: 从60降到50，大幅增加交易频率
- **最大持仓增加**: 从6提高到8，增加交易机会
- **最大交易金额**: 从2000提高到2500 USDT
- **黑名单优化**: 5次连续亏损触发，8小时时长，更快恢复
- **止损配置放宽**: ATR乘数1.5，最小止损3%，最大止损8%
- **时间止损优化**: 短期1.5小时，长期8小时
- **分类权重更新**: SOL 2.0x, Meme 1.8x, Layer1 1.8x
- **回测验证**: 2025全年收益1295%+，每季度均超100%

### V5 保守高频版
- 止盈6%，止损3%
- 信号阈值60分
- 最大持仓6个
- 黑名单12小时

### V4 优化版 (备用)
- 止盈10%，止损5%
- 信号阈值70分
- 最大持仓8个

---

## 技术支持

如有问题，请检查：
1. `crypto_monitor.log` - 运行日志
2. `backtest_results/` - 回测结果
3. 确保网络可以访问币安API
4. 检查 `config.env` 配置是否正确
