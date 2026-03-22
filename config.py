"""
Bot Configuration - All trading parameters in one place
"""
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv('.env.local')

# ============================================================
# BINANCE API CONFIG
# ============================================================
BINANCE_API_KEY = os.getenv('BINANCE_API_DEMO', '')
BINANCE_SECRET_KEY = os.getenv('BINANCE_SECRET_DEMO', '')

# Binance Futures Testnet
BINANCE_TESTNET = True
BINANCE_FUTURES_TESTNET_URL = 'https://testnet.binancefuture.com'

# ============================================================
# AI MODEL CONFIG
# ============================================================
AI_API_URL = os.getenv('URL_ENPOINT', '')
AI_API_KEY = os.getenv('API_ENPOINT', '')
AI_MODEL = os.getenv('MODEL', 'cx/gpt-5.4')

# ============================================================
# TRADING CONFIG
# ============================================================
TRADING_PAIR = 'ETH/USDT'
LEVERAGE = 5
INITIAL_CAPITAL = 500  # USD

# Strategy Selection ('TREND_FOLLOWING' or 'MEAN_REVERSION')
ACTIVE_STRATEGY = os.getenv('STRATEGY', 'MEAN_REVERSION')

# Timeframes for multi-timeframe analysis
TIMEFRAMES = {
    'entry': '15m',       # Entry signal timeframe
    'scalp': '5m',        # Scalp entry refinement
    'confirm': '1h',      # Confirmation timeframe
    'trend': '4h',        # Overall trend direction
}

# ============================================================
# TECHNICAL ANALYSIS CONFIG
# ============================================================
TA_CONFIG = {
    # EMA periods
    'ema_fast': 9,
    'ema_medium': 21,
    'ema_slow': 50,
    'ema_trend': 200,

    # RSI
    'rsi_period': 14,
    'rsi_overbought': 70,
    'rsi_oversold': 30,

    # MACD
    'macd_fast': 12,
    'macd_slow': 26,
    'macd_signal': 9,

    # Bollinger Bands
    'bb_period': 20,
    'bb_std': 2,

    # ATR
    'atr_period': 14,

    # Stochastic RSI
    'stoch_rsi_period': 14,
    'stoch_rsi_k': 3,
    'stoch_rsi_d': 3,
}

# ============================================================
# SIGNAL CONFIG
# ============================================================
SIGNAL_CONFIG = {
    'min_confidence': 0.70,  # Minimum 70% confidence to trade
    'weights': {
        'ema_crossover': 0.25,
        'rsi_zone': 0.15,
        'macd_signal': 0.20,
        'bollinger_position': 0.15,
        'volume_confirmation': 0.10,
        'multi_tf_alignment': 0.15,
    }
}

# ============================================================
# RISK MANAGEMENT CONFIG
# ============================================================
RISK_CONFIG = {
    'max_risk_per_trade': 0.015,       # 1.5% of capital per trade
    'max_daily_loss': 10.0,            # $10 max daily loss
    'max_daily_loss_pct': 0.02,        # 2% of capital
    'max_concurrent_positions': 2,
    'max_drawdown_pct': 0.10,          # 10% max drawdown -> stop trading
    'min_balance': 450,                # Absolute minimum balance

    # Consecutive loss protection
    'max_consecutive_losses': 3,       # After 3 losses, reduce size by 50%
    'loss_reduction_factor': 0.5,
}

# Apply Strategy-Specific Risk Rules
if ACTIVE_STRATEGY == 'TREND_FOLLOWING':
    RISK_CONFIG.update({
        'sl_atr_multiplier': 2.5,          # SL = 2.5 × ATR (Wide to survive noise)
        'tp_atr_multiplier': 3.5,          # TP = 3.5 × ATR
        'trailing_activation_atr': 2.5,
        'trailing_distance_atr': 1.5,
        'min_risk_reward': 1.3,
    })
else:
    # MEAN REVERSION requires high win rate and shorter holding times
    RISK_CONFIG.update({
        'sl_atr_multiplier': 2.0,          # SL = 2.0 × ATR
        'tp_atr_multiplier': 1.5,          # TP = 1.5 × ATR (High win rate target)
        'trailing_activation_atr': 1.0,
        'trailing_distance_atr': 0.5,
        'min_risk_reward': 0.7,            # Mean reversion often has R:R < 1.0
    })

# ============================================================
# TELEGRAM CONFIG
# ============================================================
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID', '')
TELEGRAM_ENABLED = bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)

# ============================================================
# BACKTEST CONFIG
# ============================================================
BACKTEST_CONFIG = {
    'data_months': 12,                 # Months of historical data
    'data_timeframes': ['5m', '15m', '1h'],  # Timeframes to download
    'initial_capital': 500,
    'commission_rate': 0.0004,         # 0.04% Binance futures fee
    'slippage_pct': 0.0005,            # 0.05% estimated slippage
    'min_confidence': 0.60,
    'cooldown_bars': 3,
    'max_hold_bars': 96,
    'risk_per_trade': 0.03,            # More aggressive than live risk for research
    'trend_risk_multiplier': 5.0,
    'range_risk_multiplier': 0.5,
    'trend_confidence_bonus': 0.12,
}

# ============================================================
# DASHBOARD CONFIG
# ============================================================
DASHBOARD_HOST = '0.0.0.0'
DASHBOARD_PORT = 5555

# ============================================================
# LOGGING CONFIG
# ============================================================
LOG_LEVEL = 'INFO'
LOG_FILE = 'data/bot.log'
TRADE_LOG_FILE = 'data/trades.json'

# ============================================================
# SCHEDULING
# ============================================================
MAIN_LOOP_INTERVAL = 60  # seconds between analysis cycles
NEWS_CHECK_INTERVAL = 300  # 5 minutes between news checks
AI_ANALYSIS_INTERVAL = 900  # 15 minutes between AI analysis
