import os
import logging
from dotenv import load_dotenv

# 加载配置文件
config_paths = [
    os.path.join(os.path.dirname(__file__), 'config.env'),
    os.path.join(os.path.dirname(__file__), 'conf', 'config.env'),
]

# 日志等级（默认 INFO；如需更详细输出设置 LOG_LEVEL=DEBUG）
LOG_LEVEL = (os.getenv("LOG_LEVEL", "INFO") or "INFO").upper()

# 查找并加载配置文件
loaded = False
LOADED_CONFIG_PATH = ""
for config_path in config_paths:
    if os.path.exists(config_path):
        load_dotenv(config_path)
        loaded = True
        LOADED_CONFIG_PATH = config_path
        break

if not loaded:
    # 不在 import 时刷屏；需要可在上层启动日志里查看 LOADED_CONFIG_PATH
    LOADED_CONFIG_PATH = ""

# 基本配置
EXCHANGE = os.getenv('EXCHANGE', 'binance')
DINGTALK_WEBHOOK = os.getenv('DINGTALK_WEBHOOK', '')
DINGTALK_SECRET = os.getenv('DINGTALK_SECRET', '')

# 钉钉通知控制：默认虚拟模式不推送，避免测试期误报/刷屏
DINGTALK_NOTIFY_IN_VIRTUAL = os.getenv('DINGTALK_NOTIFY_IN_VIRTUAL', 'false').lower() == 'true'

# 钉钉通知类型开关：
# - 默认仅推送交易事件（开仓/平仓/止盈止损/盈亏/余额）
# - 默认不推送价格警报/交易信号，避免误报刷屏
DINGTALK_NOTIFY_ALERTS = os.getenv('DINGTALK_NOTIFY_ALERTS', 'false').lower() == 'true'
DINGTALK_NOTIFY_TRADES = os.getenv('DINGTALK_NOTIFY_TRADES', 'true').lower() == 'true'

# 价格警报异常值过滤：5分钟涨跌幅超过此阈值视为数据异常（默认 100%，已优化）
MAX_ALERT_ABS_CHANGE_5M = float(os.getenv('MAX_ALERT_ABS_CHANGE_5M', '100'))

# ========== 币安合约 API 配置 ==========
BINANCE_FUTURES_API_URL = os.getenv('BINANCE_FUTURES_API_URL', 'https://fapi.binance.com/fapi/v1')
BINANCE_API_KEY = os.getenv('BINANCE_API_KEY', '')
BINANCE_SECRET_KEY = os.getenv('BINANCE_SECRET_KEY', '')

# 网络配置
VERIFY_SSL = os.getenv('VERIFY_SSL', 'true').lower() == 'true'
PROXY_ENABLED = os.getenv('PROXY_ENABLED', 'false').lower() == 'true'
PROXY_URL = os.getenv('PROXY_URL', '')
REQUEST_TIMEOUT = int(os.getenv('REQUEST_TIMEOUT', '30'))

# 行情缓存配置：用于批量 ticker 接口（降低请求量，默认 10 秒）
TICKER_CACHE_TTL_SECONDS = int(os.getenv('TICKER_CACHE_TTL_SECONDS', '10'))

# 交易配置
TRADE_MODE = os.getenv('TRADE_MODE', 'virtual')
TRADE_ENABLED = os.getenv('TRADE_ENABLED', 'false').lower() == 'true'
TRADE_AMOUNT = float(os.getenv('TRADE_AMOUNT', '1000'))
TAKE_PROFIT_RANGE = [float(x) for x in os.getenv('TAKE_PROFIT_RANGE', '10,15').split(',')]
STOP_LOSS = float(os.getenv('STOP_LOSS', '10'))
MAX_POSITIONS_PER_CATEGORY = int(os.getenv('MAX_POSITIONS_PER_CATEGORY', '5'))
FOLLOW_THRESHOLD = float(os.getenv('FOLLOW_THRESHOLD', '50'))

# ========== 实盘安全模式 / 持仓同步 ==========
# 启动/周期对账时发现“交易所已有仓位但本地无记录”的处理策略：
# - SAFE_MODE_ON_EXTERNAL_POSITIONS=true  -> 自动停开仓，只监控（更安全）
# - MANAGE_EXTERNAL_POSITIONS=true        -> 允许系统自动管理/平仓外部仓位（高风险，默认关闭）
SAFE_MODE_ON_EXTERNAL_POSITIONS = os.getenv("SAFE_MODE_ON_EXTERNAL_POSITIONS", "true").lower() == "true"
MANAGE_EXTERNAL_POSITIONS = os.getenv("MANAGE_EXTERNAL_POSITIONS", "false").lower() == "true"

# ========== 交易限额（建议参数化，避免硬编码） ==========
MAX_SINGLE_TRADE_AMOUNT = float(os.getenv("MAX_SINGLE_TRADE_AMOUNT", "5000"))
MAX_DAILY_TRADE_AMOUNT = float(os.getenv("MAX_DAILY_TRADE_AMOUNT", "50000"))

# ========== P0优化：风险控制参数 ==========
# 最大回撤硬止损
MAX_DRAWDOWN_THRESHOLD = float(os.getenv("MAX_DRAWDOWN_THRESHOLD", "20.0"))  # 最大回撤20%
MAX_DRAWDOWN_ACTION = os.getenv("MAX_DRAWDOWN_ACTION", "pause")  # pause=暂停交易, stop=完全停止
MAX_DRAWDOWN_SEVERE_THRESHOLD = float(os.getenv("MAX_DRAWDOWN_SEVERE_THRESHOLD", "30.0"))  # 严重回撤30%

# 单日亏损限制
MAX_DAILY_LOSS = float(os.getenv("MAX_DAILY_LOSS", "5.0"))  # 单日最大亏损5%
MAX_DAILY_LOSS_ACTION = os.getenv("MAX_DAILY_LOSS_ACTION", "pause")  # pause=暂停交易, stop=完全停止
MAX_DAILY_LOSS_SEVERE = float(os.getenv("MAX_DAILY_LOSS_SEVERE", "10.0"))  # 严重单日亏损10%

# 市场异常检测
MARKET_ANOMALY_ENABLED = os.getenv("MARKET_ANOMALY_ENABLED", "true").lower() == "true"
FLASH_CRASH_THRESHOLD = float(os.getenv("FLASH_CRASH_THRESHOLD", "20.0"))  # 5分钟内下跌>20%视为闪崩
FLASH_CRASH_WINDOW_MINUTES = int(os.getenv("FLASH_CRASH_WINDOW_MINUTES", "5"))  # 闪崩检测窗口
LIQUIDITY_DROP_THRESHOLD = float(os.getenv("LIQUIDITY_DROP_THRESHOLD", "80.0"))  # 成交量下降>80%视为流动性异常
LIQUIDITY_MIN_VOLUME_THRESHOLD = float(os.getenv("LIQUIDITY_MIN_VOLUME_THRESHOLD", "10000.0"))  # 最小成交量阈值（避免小币种误报）

# ========== 运维：状态汇总频率 ==========
# LiveTraderV3 每隔多少分钟输出一次状态摘要（避免每周期刷屏）
STATUS_LOG_INTERVAL_MINUTES = int(os.getenv("STATUS_LOG_INTERVAL_MINUTES", "5"))

# 监控配置
MONITOR_INTERVAL = int(os.getenv('MONITOR_INTERVAL', '2'))
PRICE_CHANGE_THRESHOLD = float(os.getenv('PRICE_CHANGE_THRESHOLD', '5.0'))

# ========== 分类阈值配置 ==========
# 用于“龙头币 5m 暴涨触发”监控阈值（单位：%）
# 默认值对齐回测 V6 高收益版（run_backtest.py --mode full 的 V6_CATEGORY_THRESHOLDS）
THRESHOLD_DEFAULT = float(os.getenv('THRESHOLD_DEFAULT', '3.0'))
THRESHOLD_LAYER1 = float(os.getenv('THRESHOLD_LAYER1', '0.5'))
THRESHOLD_SOL = float(os.getenv('THRESHOLD_SOL', '1.5'))
THRESHOLD_MEME = float(os.getenv('THRESHOLD_MEME', '1.5'))
THRESHOLD_AI_AGENT = float(os.getenv('THRESHOLD_AI_AGENT', '1.8'))
THRESHOLD_AI_AGENCY = float(os.getenv('THRESHOLD_AI_AGENCY', '1.5'))
THRESHOLD_LAYER2 = float(os.getenv('THRESHOLD_LAYER2', '1.5'))
THRESHOLD_RWA = float(os.getenv('THRESHOLD_RWA', '1.8'))

# 分类阈值映射（其余未配置分类使用 THRESHOLD_DEFAULT）
CATEGORY_THRESHOLDS = {
    "Layer1": THRESHOLD_LAYER1,
    "SOL": THRESHOLD_SOL,
    "Meme": THRESHOLD_MEME,
    "AI Agent": THRESHOLD_AI_AGENT,
    "AI Agency": THRESHOLD_AI_AGENCY,
    "Layer2": THRESHOLD_LAYER2,
    "RWA": THRESHOLD_RWA,
}

# API端点配置
if EXCHANGE == 'binance':
    API_BASE_URL = BINANCE_FUTURES_API_URL
elif EXCHANGE == 'gate':
    API_BASE_URL = "https://api.gateio.ws/api/v4"
else:
    API_BASE_URL = "https://api.coingecko.com/api/v3"

# ========== 从配置文件读取交易对 ==========
def get_symbols_from_env(env_key, default_symbols):
    """
    从环境变量读取交易对列表（兼容键名）

    兼容说明：
    - Windows 环境变量名通常不支持 '/'，例如原来的 SYMBOLS_VR/AR 无法设置。
      这里会自动尝试把 '/' 替换成 '_'（SYMBOLS_VR_AR）。
    """
    keys_to_try = [env_key]
    if isinstance(env_key, str) and '/' in env_key:
        keys_to_try.append(env_key.replace('/', '_'))

    for key in keys_to_try:
        symbols_str = os.getenv(key, '')
        if symbols_str:
            return [s.strip() for s in symbols_str.split(',') if s.strip()]

    return default_symbols

# 数字货币分类 - 支持币安合约格式
CRYPTO_CATEGORIES = {
    "Layer1": {
        "binance": get_symbols_from_env('SYMBOLS_LAYER1', ["BTCUSDT", "ETHUSDT", "SOLUSDT", "ADAUSDT", "DOTUSDT"]),
        "gate": ["BTC_USDT", "ETH_USDT", "SOL_USDT", "ADA_USDT", "DOT_USDT"]
    },
    "Layer2": {
        "binance": get_symbols_from_env('SYMBOLS_LAYER2', ["OPUSDT", "ARBUSDT", "MATICUSDT", "STRKUSDT", "ZKSUSDT"]),
        "gate": ["OP_USDT", "ARB_USDT", "MATIC_USDT", "STRK_USDT", "ZKS_USDT"]
    },
    "DeFi": {
        "binance": get_symbols_from_env('SYMBOLS_DEFI', ["UNIUSDT", "AAVEUSDT", "COMPUSDT", "LINKUSDT", "MKRUSDT"]),
        "gate": ["UNI_USDT", "AAVE_USDT", "COMP_USDT", "LINK_USDT", "MKR_USDT"]
    },
    "Meme": {
        "binance": get_symbols_from_env('SYMBOLS_MEME', ["DOGEUSDT", "1000PEPEUSDT", "WIFUSDT", "1000SHIBUSDT", "1000BONKUSDT"]),
        "gate": ["DOGE_USDT", "PEPE_USDT", "WIF_USDT", "SHIB_USDT", "BONK_USDT"]
    },
    "AI Agent": {
        "binance": get_symbols_from_env('SYMBOLS_AI_Agent', ["FARTCOINUSDT", "VIRTUALUSDT", "AIXBTUSDT", "GRIFFAINUSDT", "SWARMSUSDT"]),
        "gate": ["FARTCOIN_USDT", "VIRTUAL_USDT", "AIXBT_USDT", "GRIFFAIN_USDT", "SWARMS_USDT"]
    },
    "AI Agency": {
        "binance": get_symbols_from_env('SYMBOLS_AI', ["TAOUSDT", "FETUSDT", "CYBERUSDT", "WLDUSDT", "AGIXUSDT"]),
        "gate": ["TAO_USDT", "FET_USDT", "CYBER_USDT", "WLD_USDT", "AGIX_USDT"]
    },
    "RWA": {
        "binance": get_symbols_from_env('SYMBOLS_RWA', ["ONDOUSDT", "RSRUSDT", "TRUUSDT", "CFGUSDT", "PROUSDT"]),
        "gate": ["ONDO_USDT", "RSR_USDT", "TRU_USDT", "CFG_USDT", "PRO_USDT"]
    },
    "Web3.0": {
        "binance": get_symbols_from_env('SYMBOLS_Web3', ["DOTUSDT", "KSMUSDT", "ATOMUSDT", "ICPUSDT", "SOLUSDT"]),
        "gate": ["DOT_USDT", "KSM_USDT", "ATOM_USDT", "ICP_USDT", "SOL_USDT"]
    },
    "DID": {
        "binance": get_symbols_from_env('SYMBOLS_DID', ["WLDUSDT", "IDUSDT", "SSIUSDT", "ONTUSDT", "CVCUSDT"]),
        "gate": ["WLD_USDT", "ID_USDT", "SSI_USDT", "ONT_USDT", "CVC_USDT"]
    },
    "NFT": {
        "binance": get_symbols_from_env('SYMBOLS_NFT', ["AZUKIUSDT", "BAYCUSDT", "MAGICUSDT", "LOOKSUSDT", "NFTUSDT"]),
        "gate": ["AZUKI_USDT", "BAYC_USDT", "MAGIC_USDT", "LOOKS_USDT", "NFT_USDT"]
    },
    "Payment": {
        "binance": get_symbols_from_env('SYMBOLS_Payment', ["XRPUSDT", "LTCUSDT", "XLMUSDT", "BCHUSDT", "DASHUSDT"]),
        "gate": ["XRP_USDT", "LTC_USDT", "XLM_USDT", "BCH_USDT", "DASH_USDT"]
    },
    "Privacy": {
        "binance": get_symbols_from_env('SYMBOLS_Privacy', ["XMRUSDT", "ZECUSDT", "DASHUSDT", "BELUSDT", "PHAUSDT"]),
        "gate": ["XMR_USDT", "ZEC_USDT", "DASH_USDT", "BEL_USDT", "PHA_USDT"]
    },
    "Storage": {
        "binance": get_symbols_from_env('SYMBOLS_Storage', ["FILUSDT", "ARUSDT", "SCPUSDT", "ARPAUSDT", "STORJUSDT"]),
        "gate": ["FIL_USDT", "AR_USDT", "SCP_USDT", "ARPA_USDT", "STORJ_USDT"]
    },
    "Metaverse": {
        "binance": get_symbols_from_env('SYMBOLS_Metaverse', ["SANDUSDT", "MANAUSDT", "ILVUSDT", "RNDRUSDT", "AXSUSDT"]),
        "gate": ["SAND_USDT", "MANA_USDT", "ILV_USDT", "RNDR_USDT", "AXS_USDT"]
    },
    "VR/AR": {
        "binance": get_symbols_from_env('SYMBOLS_VR/AR', ["MAGICUSDT", "ROSEUSDT", "UOSUSDT", "VRUSDT", "ARUSDT"]),
        "gate": ["MAGIC_USDT", "ROSE_USDT", "UOS_USDT", "VR_USDT", "AR_USDT"]
    },
    "SOL": {
        "binance": get_symbols_from_env('SYMBOLS_SOL', ["SOLUSDT", "WIFUSDT", "1000BONKUSDT", "JUPUSDT", "RAYUSDT"]),
        "gate": ["SOL_USDT", "WIF_USDT", "BONK_USDT", "JUP_USDT", "RAY_USDT"]
    },
    "Sports": {
        "binance": get_symbols_from_env('SYMBOLS_Sports', ["CHZUSDT", "PLAYUSDT", "OGUSDT", "ZILUSDT", "SANTOSUSDT"]),
        "gate": ["CHZ_USDT", "PLAY_USDT", "OG_USDT", "ZIL_USDT", "SANTOS_USDT"]
    },
    "STABLE": {
        "binance": get_symbols_from_env('SYMBOLS_STABLE', ["XPLUSDT", "STBLUSDT", "WLFIUSDT", "RESOLVUSDT", "USD1USDT"]),
        "gate": ["XPL_USDT", "STBL_USDT", "WLFI_USDT", "RESOLV_USDT", "USD1_USDT"]
    }
}

# ========== 实盘/监控对齐回测默认行为 ==========
# 回测 optimize_v3/run_backtest.py 默认使用的强势分类（7个）
DEFAULT_OPTIMIZED_CATEGORIES = ["SOL", "Meme", "AI Agent", "AI Agency", "Layer1", "Layer2", "RWA"]

# 实盘监控的分类：若未配置则默认对齐回测的7个分类
MONITOR_ENABLED_CATEGORIES_STR = os.getenv("MONITOR_ENABLED_CATEGORIES", "").strip()
if MONITOR_ENABLED_CATEGORIES_STR:
    MONITOR_ENABLED_CATEGORIES = [c.strip() for c in MONITOR_ENABLED_CATEGORIES_STR.split(",") if c.strip()]
else:
    MONITOR_ENABLED_CATEGORIES = DEFAULT_OPTIMIZED_CATEGORIES.copy()

# 过滤掉不存在的分类，避免拼写导致异常
MONITOR_ENABLED_CATEGORIES = [c for c in MONITOR_ENABLED_CATEGORIES if c in CRYPTO_CATEGORIES]

# 信号触发时间窗口：默认对齐回测 K 线间隔（run_backtest 默认 15m）
# 注意：这是“龙头触发/跟涨筛选”的窗口，不影响 TraderV2 的评分 K 线（其默认也是 15m）
# 这里不能直接依赖 BACKTEST_INTERVAL 变量（其定义在后方），因此直接读取 env 作为默认回退。
_BACKTEST_INTERVAL_ENV = (os.getenv("BACKTEST_INTERVAL", "15m") or "15m").strip()
SIGNAL_TRIGGER_INTERVAL = (os.getenv("SIGNAL_TRIGGER_INTERVAL", _BACKTEST_INTERVAL_ENV) or _BACKTEST_INTERVAL_ENV).strip()

# 是否交易龙头币：回测 V6 默认不交易龙头币（仅做触发器）
TRADE_LEADER_COIN = os.getenv("TRADE_LEADER_COIN", "false").lower() == "true"

# 龙头币种映射
LEADER_COINS = {
    "Layer1": "BTCUSDT" if EXCHANGE == 'binance' else "BTC_USDT",
    "Layer2": "OPUSDT" if EXCHANGE == 'binance' else "OP_USDT",
    "DeFi": "UNIUSDT" if EXCHANGE == 'binance' else "UNI_USDT",
    "Meme": "DOGEUSDT" if EXCHANGE == 'binance' else "DOGE_USDT",
    "AI Agent": "FARTCOINUSDT" if EXCHANGE == 'binance' else "FARTCOIN_USDT",
    "AI Agency": "TAOUSDT" if EXCHANGE == 'binance' else "TAO_USDT",
    "RWA": "ONDOUSDT" if EXCHANGE == 'binance' else "ONDO_USDT",
    "Web3.0": "DOTUSDT" if EXCHANGE == 'binance' else "DOT_USDT",
    "DID": "WLDUSDT" if EXCHANGE == 'binance' else "WLD_USDT",
    "NFT": "AZUKIUSDT" if EXCHANGE == 'binance' else "AZUKI_USDT",
    "Payment": "XRPUSDT" if EXCHANGE == 'binance' else "XRP_USDT",
    "Privacy": "XMRUSDT" if EXCHANGE == 'binance' else "XMR_USDT",
    "Storage": "FILUSDT" if EXCHANGE == 'binance' else "FIL_USDT",
    "Metaverse": "SANDUSDT" if EXCHANGE == 'binance' else "SAND_USDT",
    "VR/AR": "MAGICUSDT" if EXCHANGE == 'binance' else "MAGIC_USDT",
    "SOL": "SOLUSDT" if EXCHANGE == 'binance' else "SOL_USDT",
    "Sports": "CHZUSDT" if EXCHANGE == 'binance' else "CHZ_USDT",
    "STABLE": "XPLUSDT" if EXCHANGE == 'binance' else "XPL_USDT"
}

# 监控参数
MONITOR_CONFIG = {
    "exchange": EXCHANGE,
    "enabled_categories": MONITOR_ENABLED_CATEGORIES,
    "top_n": 10,  # 优化：从5增加到10，但实际扫描时只检查前3个币种
    # 对齐回测：默认用回测 interval 做信号触发窗口（例如 15m）
    # 优化：减少时间窗口数量，只监控信号触发窗口（减少API请求）
    "time_windows": [SIGNAL_TRIGGER_INTERVAL],  # 只监控信号触发窗口，减少API请求
    "threshold_map": {"5m": PRICE_CHANGE_THRESHOLD},
    "price_change_threshold": PRICE_CHANGE_THRESHOLD,
    "price_drop_threshold": -PRICE_CHANGE_THRESHOLD,
    "monitor_interval": MONITOR_INTERVAL,
    "trade_enabled": TRADE_ENABLED,
    "trade_mode": TRADE_MODE,
    "trade_amount": TRADE_AMOUNT,
    "take_profit_range": TAKE_PROFIT_RANGE,
    "stop_loss": STOP_LOSS,
    "max_positions_per_category": MAX_POSITIONS_PER_CATEGORY,
    "follow_threshold": FOLLOW_THRESHOLD,
    "leader_coins": LEADER_COINS,
    "verify_ssl": VERIFY_SSL,
    "proxy_enabled": PROXY_ENABLED,
    "proxy_url": PROXY_URL,
    "request_timeout": REQUEST_TIMEOUT,
    "ticker_cache_ttl_seconds": TICKER_CACHE_TTL_SECONDS,
    "binance_futures_url": BINANCE_FUTURES_API_URL,
    "category_thresholds": CATEGORY_THRESHOLDS,
    "threshold_default": THRESHOLD_DEFAULT,
    # 信号触发/交易行为开关（用于对齐回测）
    "signal_trigger_interval": SIGNAL_TRIGGER_INTERVAL,
    "trade_leader_coin": TRADE_LEADER_COIN,
}

# ========== 策略优化配置 (V5) ==========
# 分类黑名单 - 这些分类将被完全禁止交易
CATEGORY_BLACKLIST = [
    "Payment",   # 胜率 31.2%, 总亏损 -2663
    "Sports",    # 胜率 37.5%, 总亏损 -1170
]

# 交易对黑名单 - V5精简版 (只保留最差的)
SYMBOL_BLACKLIST = [
    "XLMUSDT",      # Payment, 胜率 25.0%
    "SANTOSUSDT",   # Sports, 胜率 33.3%
    "RLCUSDT",      # VR/AR, 胜率 42.9%
    "UAIUSDT",      # AI Agent, 胜率 36.4%
]

# 分类权重调整 - V6高收益版本 (基于全年分析)
# 权重 < 1.0 表示降低该分类的仓位
# 权重 > 1.0 表示增加该分类的仓位
CATEGORY_WEIGHT_ADJUSTMENTS = {
    # 表现差的分类 - 降低权重
    "VR/AR": 0.3,       # V6: 保持0.3
    "Metaverse": 0.5,   # V6: 保持0.5
    "DID": 0.6,         # V6: 保持0.6
    "STABLE": 0.6,      # V6: 保持0.6
    
    # 表现好的分类 - 大幅提高权重
    "SOL": 2.0,         # V6: 从1.8提高到2.0 (最佳表现)
    "Meme": 1.8,        # V6: 从1.5提高到1.8
    "AI Agent": 1.0,    # V6: 从1.2降到1.0 (频繁亏损，中性权重)
    "AI Agency": 1.6,   # V6: 从1.5提高到1.6
    "Layer1": 1.8,      # V6: 从1.6提高到1.8
    "Layer2": 1.5,      # V6: 从1.4提高到1.5
    "RWA": 1.3,         # V6: 从1.4降到1.3
}

# 策略优化开关
STRATEGY_OPTIMIZATION_ENABLED = os.getenv('STRATEGY_OPTIMIZATION_ENABLED', 'true').lower() == 'true'

# ========== 回测配置 ==========
BACKTEST_START_DATE = os.getenv('BACKTEST_START_DATE', '')
BACKTEST_END_DATE = os.getenv('BACKTEST_END_DATE', '')
BACKTEST_DAYS = int(os.getenv('BACKTEST_DAYS', '7'))
BACKTEST_INTERVAL = os.getenv('BACKTEST_INTERVAL', '15m')
BACKTEST_INITIAL_BALANCE = float(os.getenv('BACKTEST_INITIAL_BALANCE', '20000'))
BACKTEST_CATEGORIES_STR = os.getenv('BACKTEST_CATEGORIES', '')
BACKTEST_CATEGORIES = [c.strip() for c in BACKTEST_CATEGORIES_STR.split(',') if c.strip()] if BACKTEST_CATEGORIES_STR else []

# ========== V6 高收益版策略参数 (默认) ==========
# V6参数: 平衡止损与交易频率，目标250%+年化
V2_BASE_TRADE_AMOUNT = float(os.getenv('V2_BASE_TRADE_AMOUNT', '500'))
V2_MAX_TRADE_AMOUNT = float(os.getenv('V2_MAX_TRADE_AMOUNT', '2500'))  # V6: 从2000提高到2500
V2_TAKE_PROFIT = float(os.getenv('V2_TAKE_PROFIT', '8'))   # V6: 8%止盈
V2_STOP_LOSS = float(os.getenv('V2_STOP_LOSS', '4'))       # V6: 4%止损
V2_TRAILING_STOP_PCT = float(os.getenv('V2_TRAILING_STOP_PCT', '1.5'))  # V6: 1.5%移动止损
V2_TRAILING_STOP_ACTIVATION = float(os.getenv('V2_TRAILING_STOP_ACTIVATION', '2.5'))  # V6: 2.5%激活
V2_MAX_POSITIONS = int(os.getenv('V2_MAX_POSITIONS', '8'))  # V6: 8个最大持仓
V2_COOLDOWN_PERIODS = int(os.getenv('V2_COOLDOWN_PERIODS', '2'))  # V6: 2根K线冷却

# ========== 分批止盈配置 ==========
PARTIAL_TP_ENABLED = os.getenv('PARTIAL_TP_ENABLED', 'false').lower() == 'true'
PARTIAL_TP_LEVELS_STR = os.getenv('PARTIAL_TP_LEVELS', '10,20,30')
PARTIAL_TP_LEVELS = [float(x.strip()) for x in PARTIAL_TP_LEVELS_STR.split(',') if x.strip()]
PARTIAL_TP_RATIOS_STR = os.getenv('PARTIAL_TP_RATIOS', '0.33,0.33,0.34')
PARTIAL_TP_RATIOS = [float(x.strip()) for x in PARTIAL_TP_RATIOS_STR.split(',') if x.strip()]

# ========== 永续合约配置 ==========
# 最优杠杆: 15x (Q1测试最佳表现)
LEVERAGE = int(os.getenv('LEVERAGE', '15'))
FUTURES_MODE = os.getenv('FUTURES_MODE', 'true').lower() == 'true'
LIQUIDATION_BUFFER = float(os.getenv('LIQUIDATION_BUFFER', '2.0'))

BACKTEST_CONFIG = {
    "start_date": BACKTEST_START_DATE,
    "end_date": BACKTEST_END_DATE,
    "days": BACKTEST_DAYS,
    "interval": BACKTEST_INTERVAL,
    "initial_balance": BACKTEST_INITIAL_BALANCE,
    "categories": BACKTEST_CATEGORIES,
    "trade_amount": TRADE_AMOUNT,
    "take_profit_range": TAKE_PROFIT_RANGE,
    "stop_loss": STOP_LOSS,
    "follow_threshold": FOLLOW_THRESHOLD,
    "price_change_threshold": PRICE_CHANGE_THRESHOLD,
    # V2 参数
    "base_trade_amount": V2_BASE_TRADE_AMOUNT,
    "max_trade_amount": V2_MAX_TRADE_AMOUNT,
    "take_profit": V2_TAKE_PROFIT,
    "trailing_stop_pct": V2_TRAILING_STOP_PCT,
    "trailing_stop_activation": V2_TRAILING_STOP_ACTIVATION,
    "max_positions": V2_MAX_POSITIONS,
    "cooldown_periods": V2_COOLDOWN_PERIODS,
    # 永续合约参数
    "leverage": LEVERAGE,
    "futures_mode": FUTURES_MODE,
    "liquidation_buffer": LIQUIDATION_BUFFER,
    # 分批止盈参数
    "partial_tp_enabled": PARTIAL_TP_ENABLED,
    "partial_tp_levels": PARTIAL_TP_LEVELS,
    "partial_tp_ratios": PARTIAL_TP_RATIOS
}

# ========== 止损优化配置 (V6) ==========
# 动态止损 (ATR) - V6适度放宽
DYNAMIC_SL_ENABLED = os.getenv('DYNAMIC_SL_ENABLED', 'true').lower() == 'true'
ATR_MULTIPLIER = float(os.getenv('ATR_MULTIPLIER', '1.5'))  # V6: 从1.2提高到1.5
MIN_STOP_LOSS = float(os.getenv('MIN_STOP_LOSS', '3.0'))    # V6: 从2.5提高到3.0
MAX_STOP_LOSS = float(os.getenv('MAX_STOP_LOSS', '8.0'))    # V6: 从6.0提高到8.0

# 提前保本止损 - V6适度放宽
EARLY_BREAKEVEN_ENABLED = os.getenv('EARLY_BREAKEVEN_ENABLED', 'true').lower() == 'true'
EARLY_BREAKEVEN_THRESHOLD = float(os.getenv('EARLY_BREAKEVEN_THRESHOLD', '2.0'))  # V6: 从1.5提高到2.0
EARLY_BREAKEVEN_BUFFER = float(os.getenv('EARLY_BREAKEVEN_BUFFER', '0.15'))  # V6: 从0.1提高到0.15

# 信号评分止损 - V6适度放宽
SIGNAL_BASED_SL_ENABLED = os.getenv('SIGNAL_BASED_SL_ENABLED', 'true').lower() == 'true'
HIGH_SCORE_SL = float(os.getenv('HIGH_SCORE_SL', '6.0'))    # V6: 从5.0提高到6.0
MEDIUM_SCORE_SL = float(os.getenv('MEDIUM_SCORE_SL', '5.0'))  # V6: 从4.0提高到5.0
LOW_SCORE_SL = float(os.getenv('LOW_SCORE_SL', '4.0'))      # V6: 从3.0提高到4.0

# 时间衰减止损 - V6放缓衰减
TIME_DECAY_SL_ENABLED = os.getenv('TIME_DECAY_SL_ENABLED', 'true').lower() == 'true'
TIME_DECAY_FACTOR_12H = float(os.getenv('TIME_DECAY_FACTOR_12H', '0.6'))  # V6: 从0.5提高到0.6
TIME_DECAY_FACTOR_24H = float(os.getenv('TIME_DECAY_FACTOR_24H', '0.4'))  # V6: 从0.3提高到0.4
MIN_DECAYED_SL = float(os.getenv('MIN_DECAYED_SL', '3.0'))  # V6: 从2.5提高到3.0

# 短期时间止损 - V6放宽
SHORT_TIME_STOP_ENABLED = os.getenv('SHORT_TIME_STOP_ENABLED', 'true').lower() == 'true'
SHORT_TIME_STOP_HOURS = float(os.getenv('SHORT_TIME_STOP_HOURS', '1.5'))  # V6: 从1.0提高到1.5
SHORT_TIME_STOP_MIN_PROFIT = float(os.getenv('SHORT_TIME_STOP_MIN_PROFIT', '1.0'))  # V6: 从1.5降到1.0

# 长期时间止损 - V6延长
LONG_TIME_STOP_ENABLED = os.getenv('LONG_TIME_STOP_ENABLED', 'true').lower() == 'true'
LONG_TIME_STOP_HOURS = float(os.getenv('LONG_TIME_STOP_HOURS', '8.0'))  # V6: 从6.0延长到8.0
LONG_TIME_STOP_MIN_PROFIT = float(os.getenv('LONG_TIME_STOP_MIN_PROFIT', '0.0'))

# 止损配置字典
STOP_LOSS_CONFIG = {
    # 动态止损 (ATR)
    "dynamic_sl_enabled": DYNAMIC_SL_ENABLED,
    "atr_multiplier": ATR_MULTIPLIER,
    "min_stop_loss": MIN_STOP_LOSS,
    "max_stop_loss": MAX_STOP_LOSS,
    # 提前保本止损
    "early_breakeven_enabled": EARLY_BREAKEVEN_ENABLED,
    "early_breakeven_threshold": EARLY_BREAKEVEN_THRESHOLD,
    "early_breakeven_buffer": EARLY_BREAKEVEN_BUFFER,
    # 信号评分止损
    "signal_based_sl_enabled": SIGNAL_BASED_SL_ENABLED,
    "high_score_sl": HIGH_SCORE_SL,
    "medium_score_sl": MEDIUM_SCORE_SL,
    "low_score_sl": LOW_SCORE_SL,
    # 时间衰减止损
    "time_decay_sl_enabled": TIME_DECAY_SL_ENABLED,
    "time_decay_factor_12h": TIME_DECAY_FACTOR_12H,
    "time_decay_factor_24h": TIME_DECAY_FACTOR_24H,
    "min_decayed_sl": MIN_DECAYED_SL,
    # 短期时间止损 (2小时)
    "short_time_stop_enabled": SHORT_TIME_STOP_ENABLED,
    "short_time_stop_hours": SHORT_TIME_STOP_HOURS,
    "short_time_stop_min_profit": SHORT_TIME_STOP_MIN_PROFIT,
    # 长期时间止损 (24小时)
    "long_time_stop_enabled": LONG_TIME_STOP_ENABLED,
    "long_time_stop_hours": LONG_TIME_STOP_HOURS,
    "long_time_stop_min_profit": LONG_TIME_STOP_MIN_PROFIT
}

# ========== 分类止损配置 (V6) ==========
# 不同板块使用不同的止损阈值
# AI Agent 从 13% 收紧到 10% (Q2分析: 胜率35%, 亏损-9597)
CATEGORY_STOP_LOSS = {
    "AI Agent": 10.0,   # V6: 从13%收紧到10%
    "Meme": 13.0,       # 保持13%
    "SOL": 12.0,        # 保持12%
    "AI Agency": 10.0,  # 保持10%
    "Layer1": 10.0,     # 保持10%
    "Layer2": 10.0,     # 保持10%
    "RWA": 10.0,        # 保持10%
    "DeFi": 10.0,       # 保持10%
}

# ========== 单日最大亏损限制 (V6) ==========
DAILY_LOSS_LIMIT_ENABLED = os.getenv('DAILY_LOSS_LIMIT_ENABLED', 'true').lower() == 'true'
DAILY_LOSS_LIMIT_PCT = float(os.getenv('DAILY_LOSS_LIMIT_PCT', '10.0'))  # 单日最大亏损10%
DAILY_LOSS_LIMIT_COOLDOWN_HOURS = float(os.getenv('DAILY_LOSS_LIMIT_COOLDOWN_HOURS', '24.0'))  # 触发后冷却24小时

DAILY_LOSS_LIMIT_CONFIG = {
    "enabled": DAILY_LOSS_LIMIT_ENABLED,
    "max_daily_loss_pct": DAILY_LOSS_LIMIT_PCT,
    "cooldown_hours": DAILY_LOSS_LIMIT_COOLDOWN_HOURS
}

# ========== V6 黑名单优化配置 ==========
BLACKLIST_CONSECUTIVE_LOSSES = int(os.getenv('BLACKLIST_CONSECUTIVE_LOSSES', '5'))  # V6: 从4提高到5
BLACKLIST_DURATION_HOURS = float(os.getenv('BLACKLIST_DURATION_HOURS', '8'))  # V6: 从12降到8
BLACKLIST_EARLY_RELEASE_ENABLED = os.getenv('BLACKLIST_EARLY_RELEASE_ENABLED', 'true').lower() == 'true'
BLACKLIST_EARLY_RELEASE_WINS = int(os.getenv('BLACKLIST_EARLY_RELEASE_WINS', '2'))

BLACKLIST_CONFIG = {
    "consecutive_losses": BLACKLIST_CONSECUTIVE_LOSSES,
    "duration_hours": BLACKLIST_DURATION_HOURS,
    "early_release_enabled": BLACKLIST_EARLY_RELEASE_ENABLED,
    "early_release_wins": BLACKLIST_EARLY_RELEASE_WINS
}

# ========== V7 定期重置配置 (模拟独立季度模式) ==========
PERIODIC_RESET_ENABLED = os.getenv('PERIODIC_RESET_ENABLED', 'true').lower() == 'true'
PERIODIC_RESET_INTERVAL_DAYS = int(os.getenv('PERIODIC_RESET_INTERVAL_DAYS', '7'))

PERIODIC_RESET_CONFIG = {
    "enabled": PERIODIC_RESET_ENABLED,
    "interval_days": PERIODIC_RESET_INTERVAL_DAYS
}

# ========== V8 分段回测配置 (复刻 --mode full 高收益机制) ==========
# 分段回测的核心优势:
# 1. 每段开始时技术指标重新计算 (冷启动效应)
# 2. 资金和持仓状态保持连续
# 3. 避免长期趋势的"惯性"影响
# 4. 结合定期重置机制，形成双重"新鲜开始"效果
SEGMENT_BACKTEST_ENABLED = os.getenv('SEGMENT_BACKTEST_ENABLED', 'false').lower() == 'true'
SEGMENT_BACKTEST_DAYS = int(os.getenv('SEGMENT_BACKTEST_DAYS', '90'))  # 默认90天=季度

SEGMENT_BACKTEST_CONFIG = {
    "enabled": SEGMENT_BACKTEST_ENABLED,
    "segment_days": SEGMENT_BACKTEST_DAYS
}

# ========== V8 实盘 Mode Full 配置 (复刻 --mode full 高收益机制) ==========
# 核心优势:
# 1. 技术指标冷启动 - 定期重新计算，避免历史数据污染
# 2. 状态完全重置 - 黑名单、冷却期定期清空
# 3. 新鲜开始效应 - 每周期都能捕捉新趋势
# 4. 指标预热期 - 跳过前N个信号等待指标稳定

# 定期重置配置（默认对齐回测 full/independent 的“季度重置”思路：使用 PERIODIC_RESET_INTERVAL_DAYS）
V8_RESET_ENABLED = os.getenv('V8_RESET_ENABLED', 'true').lower() == 'true'
V8_RESET_INTERVAL_DAYS = int(os.getenv('V8_RESET_INTERVAL_DAYS', str(PERIODIC_RESET_INTERVAL_DAYS)))
V8_RESET_BLACKLIST = os.getenv('V8_RESET_BLACKLIST', 'true').lower() == 'true'
V8_RESET_COOLDOWN = os.getenv('V8_RESET_COOLDOWN', 'true').lower() == 'true'
V8_RESET_PRICE_CACHE = os.getenv('V8_RESET_PRICE_CACHE', 'true').lower() == 'true'
V8_RESET_INDICATORS = os.getenv('V8_RESET_INDICATORS', 'true').lower() == 'true'

# 冷启动配置（对齐回测：不额外跳过信号；预热K线仅满足信号评分最低需求）
# 优化：降低默认预热要求（从20降到10），使实盘更接近回测行为
V8_WARMUP_CANDLES = int(os.getenv('V8_WARMUP_CANDLES', '10'))
V8_SKIP_FIRST_SIGNALS = int(os.getenv('V8_SKIP_FIRST_SIGNALS', '0'))

# 黑名单配置（默认对齐 V6 回测：5次触发 / 8小时）
V8_BLACKLIST_CONSECUTIVE_LOSSES = int(os.getenv('V8_BLACKLIST_CONSECUTIVE_LOSSES', str(BLACKLIST_CONSECUTIVE_LOSSES)))
V8_BLACKLIST_DURATION_HOURS = int(os.getenv('V8_BLACKLIST_DURATION_HOURS', str(int(BLACKLIST_DURATION_HOURS))))

V8_CONFIG = {
    # 定期重置配置
    'periodic_reset': {
        'enabled': V8_RESET_ENABLED,
        'interval_days': V8_RESET_INTERVAL_DAYS,
        'reset_blacklist': V8_RESET_BLACKLIST,
        'reset_cooldown': V8_RESET_COOLDOWN,
        'reset_price_cache': V8_RESET_PRICE_CACHE,
        'reset_indicators': V8_RESET_INDICATORS,
    },
    
    # 冷启动配置
    'cold_start': {
        'warmup_candles': V8_WARMUP_CANDLES,
        'skip_first_signals': V8_SKIP_FIRST_SIGNALS,
        'indicator_reset_on_period': True,
    },
    
    # 黑名单配置
    'blacklist': {
        'max_consecutive_losses': V8_BLACKLIST_CONSECUTIVE_LOSSES,
        'blacklist_duration_hours': V8_BLACKLIST_DURATION_HOURS,
        'auto_remove_on_reset': True,
    },
}

# ========== 信号评分配置 (V6) ==========
SIGNAL_SCORE_ENABLED = os.getenv('SIGNAL_SCORE_ENABLED', 'true').lower() == 'true'

# 各维度权重 (自动归一化)
SIGNAL_TREND_WEIGHT = float(os.getenv('SIGNAL_TREND_WEIGHT', '0.20'))
SIGNAL_VOLUME_WEIGHT = float(os.getenv('SIGNAL_VOLUME_WEIGHT', '0.15'))
SIGNAL_MOMENTUM_WEIGHT = float(os.getenv('SIGNAL_MOMENTUM_WEIGHT', '0.40'))
SIGNAL_VOLATILITY_WEIGHT = float(os.getenv('SIGNAL_VOLATILITY_WEIGHT', '0.10'))
SIGNAL_CORRELATION_WEIGHT = float(os.getenv('SIGNAL_CORRELATION_WEIGHT', '0.15'))  # V5: 从0.20降到0.15

# 最低入场评分 - V6大幅降低以增加交易频率
SIGNAL_MIN_SCORE = float(os.getenv('SIGNAL_MIN_SCORE', '50.0'))  # V6: 从60降到50

# 趋势评分参数 - V6进一步放宽
SIGNAL_ADX_STRONG_THRESHOLD = float(os.getenv('SIGNAL_ADX_STRONG_THRESHOLD', '15.0'))  # V6: 从18降到15

# 成交量评分参数 - V6进一步放宽
SIGNAL_VOLUME_HIGH_RATIO = float(os.getenv('SIGNAL_VOLUME_HIGH_RATIO', '1.3'))  # V6: 从1.5降到1.3
SIGNAL_VOLUME_ABNORMAL_RATIO = float(os.getenv('SIGNAL_VOLUME_ABNORMAL_RATIO', '3.5'))  # V6: 从4.0降到3.5

# 波动率评分参数
SIGNAL_VOLATILITY_HIGH = float(os.getenv('SIGNAL_VOLATILITY_HIGH', '5.0'))
SIGNAL_VOLATILITY_LOW = float(os.getenv('SIGNAL_VOLATILITY_LOW', '1.0'))

# 相关性评分参数
SIGNAL_CORRELATION_HIGH = float(os.getenv('SIGNAL_CORRELATION_HIGH', '0.7'))
SIGNAL_CORRELATION_LOOKBACK = int(os.getenv('SIGNAL_CORRELATION_LOOKBACK', '20'))

# 市场状态自适应
SIGNAL_REGIME_ADAPTATION = os.getenv('SIGNAL_REGIME_ADAPTATION', 'true').lower() == 'true'

# 信号评分配置字典
SIGNAL_SCORE_CONFIG = {
    "enabled": SIGNAL_SCORE_ENABLED,
    # 权重
    "trend_weight": SIGNAL_TREND_WEIGHT,
    "volume_weight": SIGNAL_VOLUME_WEIGHT,
    "momentum_weight": SIGNAL_MOMENTUM_WEIGHT,
    "volatility_weight": SIGNAL_VOLATILITY_WEIGHT,
    "correlation_weight": SIGNAL_CORRELATION_WEIGHT,
    # 阈值
    "min_signal_score": SIGNAL_MIN_SCORE,
    "adx_strong_threshold": SIGNAL_ADX_STRONG_THRESHOLD,
    "volume_high_ratio": SIGNAL_VOLUME_HIGH_RATIO,
    "volume_abnormal_ratio": SIGNAL_VOLUME_ABNORMAL_RATIO,
    "volatility_high_threshold": SIGNAL_VOLATILITY_HIGH,
    "volatility_low_threshold": SIGNAL_VOLATILITY_LOW,
    "correlation_high_threshold": SIGNAL_CORRELATION_HIGH,
    "correlation_lookback": SIGNAL_CORRELATION_LOOKBACK,
    "regime_adaptation_enabled": SIGNAL_REGIME_ADAPTATION
}

# ========== 信号校准器配置（开仓前的二次门控） ==========
# 说明：
# - TraderV2.open_position 会先计算 signal_score，然后调用 SignalCalibrator 校准并决定是否 should_skip
# - SignalCalibrator 默认门槛较高（normal>=70，bearish>=80），会显著降低“暴跌后反弹”的开仓频率
# - 这里参数化，便于在不改策略主逻辑的前提下，按实盘/回测效果调优
CALIBRATOR_VOLUME_BONUS_THRESHOLD = float(os.getenv("CALIBRATOR_VOLUME_BONUS_THRESHOLD", "1.5"))
CALIBRATOR_VOLUME_BONUS_POINTS = float(os.getenv("CALIBRATOR_VOLUME_BONUS_POINTS", "10"))
CALIBRATOR_VOLATILITY_PENALTY_THRESHOLD = float(os.getenv("CALIBRATOR_VOLATILITY_PENALTY_THRESHOLD", "2.0"))
CALIBRATOR_VOLATILITY_PENALTY_POINTS = float(os.getenv("CALIBRATOR_VOLATILITY_PENALTY_POINTS", "15"))
CALIBRATOR_BULLISH_BONUS_POINTS = float(os.getenv("CALIBRATOR_BULLISH_BONUS_POINTS", "10"))
CALIBRATOR_BEARISH_PENALTY_POINTS = float(os.getenv("CALIBRATOR_BEARISH_PENALTY_POINTS", "10"))
CALIBRATOR_NORMAL_MIN_SCORE = float(os.getenv("CALIBRATOR_NORMAL_MIN_SCORE", "70"))
CALIBRATOR_BEARISH_MIN_SCORE = float(os.getenv("CALIBRATOR_BEARISH_MIN_SCORE", "80"))

SIGNAL_CALIBRATOR_CONFIG = {
    "volume_bonus_threshold": CALIBRATOR_VOLUME_BONUS_THRESHOLD,
    "volume_bonus_points": CALIBRATOR_VOLUME_BONUS_POINTS,
    "volatility_penalty_threshold": CALIBRATOR_VOLATILITY_PENALTY_THRESHOLD,
    "volatility_penalty_points": CALIBRATOR_VOLATILITY_PENALTY_POINTS,
    "bullish_bonus_points": CALIBRATOR_BULLISH_BONUS_POINTS,
    "bearish_penalty_points": CALIBRATOR_BEARISH_PENALTY_POINTS,
    "normal_min_score": CALIBRATOR_NORMAL_MIN_SCORE,
    "bearish_min_score": CALIBRATOR_BEARISH_MIN_SCORE,
}


# ========== 板块轮动配置 ==========
ROTATION_ENABLED = os.getenv('ROTATION_ENABLED', 'true').lower() == 'true'
ROTATION_LOOKBACK_PERIODS = int(os.getenv('ROTATION_LOOKBACK_PERIODS', '24'))
ROTATION_REBALANCE_INTERVAL = int(os.getenv('ROTATION_REBALANCE_INTERVAL', '16'))

# 维度权重 (自动归一化)
ROTATION_MOMENTUM_WEIGHT = float(os.getenv('ROTATION_MOMENTUM_WEIGHT', '0.35'))
ROTATION_VOLUME_WEIGHT = float(os.getenv('ROTATION_VOLUME_WEIGHT', '0.25'))
ROTATION_RELATIVE_STRENGTH_WEIGHT = float(os.getenv('ROTATION_RELATIVE_STRENGTH_WEIGHT', '0.25'))
ROTATION_LEADER_WEIGHT = float(os.getenv('ROTATION_LEADER_WEIGHT', '0.15'))

# 权重分配参数
ROTATION_MIN_SECTOR_WEIGHT = float(os.getenv('ROTATION_MIN_SECTOR_WEIGHT', '0.05'))
ROTATION_REBALANCE_THRESHOLD = float(os.getenv('ROTATION_REBALANCE_THRESHOLD', '0.10'))
ROTATION_HOT_MULTIPLIER = float(os.getenv('ROTATION_HOT_MULTIPLIER', '1.75'))
ROTATION_COLD_MULTIPLIER = float(os.getenv('ROTATION_COLD_MULTIPLIER', '0.35'))

# 高波动保护
ROTATION_HIGH_VOLATILITY_ATR_THRESHOLD = float(os.getenv('ROTATION_HIGH_VOLATILITY_ATR_THRESHOLD', '5.0'))

# Hot 板块评分加成
ROTATION_HOT_SCORE_BOOST = float(os.getenv('ROTATION_HOT_SCORE_BOOST', '1.2'))

# 板块轮动配置字典
ROTATION_CONFIG = {
    "enabled": ROTATION_ENABLED,
    "lookback_periods": ROTATION_LOOKBACK_PERIODS,
    "rebalance_interval": ROTATION_REBALANCE_INTERVAL,
    # 维度权重
    "momentum_weight": ROTATION_MOMENTUM_WEIGHT,
    "volume_weight": ROTATION_VOLUME_WEIGHT,
    "relative_strength_weight": ROTATION_RELATIVE_STRENGTH_WEIGHT,
    "leader_weight": ROTATION_LEADER_WEIGHT,
    # 权重分配参数
    "min_sector_weight": ROTATION_MIN_SECTOR_WEIGHT,
    "rebalance_threshold": ROTATION_REBALANCE_THRESHOLD,
    "hot_multiplier": ROTATION_HOT_MULTIPLIER,
    "cold_multiplier": ROTATION_COLD_MULTIPLIER,
    # 高波动保护
    "high_volatility_atr_threshold": ROTATION_HIGH_VOLATILITY_ATR_THRESHOLD,
    # Hot 板块评分加成
    "hot_score_boost": ROTATION_HOT_SCORE_BOOST
}


def validate_rotation_config(config: dict) -> dict:
    """
    验证板块轮动配置，无效值使用默认值，自动归一化权重
    
    验证规则:
    - 权重自动归一化到总和为1.0
    - 百分比值必须在 [0, 1] 范围内
    - 正整数值必须 > 0
    - 倍数值必须 > 0
    
    Returns:
        验证并修正后的配置字典
    """
    defaults = {
        "enabled": True,
        "lookback_periods": 24,
        "rebalance_interval": 16,
        "momentum_weight": 0.35,
        "volume_weight": 0.25,
        "relative_strength_weight": 0.25,
        "leader_weight": 0.15,
        "min_sector_weight": 0.05,
        "rebalance_threshold": 0.10,
        "hot_multiplier": 1.75,
        "cold_multiplier": 0.35,
        "high_volatility_atr_threshold": 5.0,
        "hot_score_boost": 1.2
    }
    
    validated = {}
    errors = []
    
    for key, default_value in defaults.items():
        value = config.get(key, default_value)
        
        # 验证布尔值
        if key == 'enabled':
            if not isinstance(value, bool):
                errors.append(f"{key} must be boolean")
                value = default_value
        # 验证正整数
        elif key in ['lookback_periods', 'rebalance_interval']:
            if not isinstance(value, int) or value <= 0:
                errors.append(f"{key} must be positive integer")
                value = default_value
        # 验证百分比值 [0, 1]
        elif key in ['min_sector_weight', 'rebalance_threshold'] or key.endswith('_weight'):
            if not isinstance(value, (int, float)) or value < 0 or value > 1:
                errors.append(f"{key} must be between 0 and 1")
                value = default_value
        # 验证正数倍数
        elif key in ['hot_multiplier', 'cold_multiplier', 'high_volatility_atr_threshold', 'hot_score_boost']:
            if not isinstance(value, (int, float)) or value <= 0:
                errors.append(f"{key} must be positive number")
                value = default_value
        
        validated[key] = value
    
    # 自动归一化维度权重
    weight_keys = ['momentum_weight', 'volume_weight', 'relative_strength_weight', 'leader_weight']
    total_weight = sum(validated[k] for k in weight_keys)
    
    if total_weight > 0 and abs(total_weight - 1.0) > 0.001:
        logging.getLogger(__name__).info("轮动权重总和为 %.3f，自动归一化...", total_weight)
        for k in weight_keys:
            validated[k] = validated[k] / total_weight
    
    if errors:
        logging.getLogger(__name__).warning("板块轮动配置验证警告: %s", errors)
    
    return validated


def validate_stop_loss_config(config: dict) -> dict:
    """验证止损配置，无效值使用默认值"""
    defaults = {
        "dynamic_sl_enabled": True,
        "atr_multiplier": 2.0,
        "min_stop_loss": 5.0,
        "max_stop_loss": 15.0,
        "early_breakeven_enabled": True,
        "early_breakeven_threshold": 5.0,
        "early_breakeven_buffer": 0.2,
        "signal_based_sl_enabled": True,
        "high_score_sl": 12.0,
        "medium_score_sl": 10.0,
        "low_score_sl": 8.0,
        "time_decay_sl_enabled": True,
        "time_decay_factor_12h": 0.8,
        "time_decay_factor_24h": 0.6,
        "min_decayed_sl": 5.0,
        # 短期时间止损 (2小时)
        "short_time_stop_enabled": True,
        "short_time_stop_hours": 2.0,
        "short_time_stop_min_profit": 3.0,
        # 长期时间止损 (24小时)
        "long_time_stop_enabled": True,
        "long_time_stop_hours": 24.0,
        "long_time_stop_min_profit": 0.0
    }
    
    validated = {}
    for key, default_value in defaults.items():
        value = config.get(key, default_value)
        
        # 验证百分比值为正数
        if key in ['atr_multiplier', 'min_stop_loss', 'max_stop_loss', 
                   'early_breakeven_threshold', 'early_breakeven_buffer',
                   'high_score_sl', 'medium_score_sl', 'low_score_sl',
                   'time_decay_factor_12h', 'time_decay_factor_24h', 'min_decayed_sl',
                   'short_time_stop_hours', 'long_time_stop_hours']:
            if not isinstance(value, (int, float)) or value <= 0:
                logging.getLogger(__name__).warning("配置 %s 值无效 (%s)，使用默认值 %s", key, value, default_value)
                value = default_value
        
        # 验证可以为0或正数的值
        if key in ['short_time_stop_min_profit', 'long_time_stop_min_profit']:
            if not isinstance(value, (int, float)):
                logging.getLogger(__name__).warning("配置 %s 值无效 (%s)，使用默认值 %s", key, value, default_value)
                value = default_value
        
        validated[key] = value
    
    return validated


def validate_signal_score_config(config: dict) -> dict:
    """验证信号评分配置，无效值使用默认值，自动归一化权重"""
    defaults = {
        "enabled": True,
        "trend_weight": 0.25,
        "volume_weight": 0.20,
        "momentum_weight": 0.20,
        "volatility_weight": 0.15,
        "correlation_weight": 0.20,
        "min_signal_score": 30.0,
        "adx_strong_threshold": 25.0,
        "volume_high_ratio": 2.0,
        "volume_abnormal_ratio": 5.0,
        "volatility_high_threshold": 5.0,
        "volatility_low_threshold": 1.0,
        "correlation_high_threshold": 0.7,
        "correlation_lookback": 20,
        "regime_adaptation_enabled": True
    }
    
    validated = {}
    for key, default_value in defaults.items():
        value = config.get(key, default_value)
        
        # 验证权重值在 0-1 之间
        if key.endswith('_weight'):
            if not isinstance(value, (int, float)) or value < 0 or value > 1:
                logging.getLogger(__name__).warning("配置 %s 值无效 (%s)，使用默认值 %s", key, value, default_value)
                value = default_value
        # 验证阈值为正数
        elif key in ['min_signal_score', 'adx_strong_threshold', 'volume_high_ratio',
                     'volume_abnormal_ratio', 'volatility_high_threshold', 
                     'volatility_low_threshold', 'correlation_high_threshold']:
            if not isinstance(value, (int, float)) or value < 0:
                logging.getLogger(__name__).warning("配置 %s 值无效 (%s)，使用默认值 %s", key, value, default_value)
                value = default_value
        # 验证整数值
        elif key == 'correlation_lookback':
            if not isinstance(value, int) or value < 1:
                logging.getLogger(__name__).warning("配置 %s 值无效 (%s)，使用默认值 %s", key, value, default_value)
                value = default_value
        
        validated[key] = value
    
    # 自动归一化权重
    weight_keys = ['trend_weight', 'volume_weight', 'momentum_weight', 
                   'volatility_weight', 'correlation_weight']
    total_weight = sum(validated[k] for k in weight_keys)
    
    if total_weight > 0 and abs(total_weight - 1.0) > 0.001:
        logging.getLogger(__name__).info("权重总和为 %.3f，自动归一化...", total_weight)
        for k in weight_keys:
            validated[k] = validated[k] / total_weight
    
    return validated
