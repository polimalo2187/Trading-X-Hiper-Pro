# ============================================================
# CONFIGURACIÓN GLOBAL – TRADING X HYPER PRO
# PRODUCCIÓN REAL – MODO GUERRA
# ============================================================

import os

# ============================================================
# TELEGRAM
# ============================================================

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
BOT_NAME = "TradingXHyperProBot"

if not TELEGRAM_BOT_TOKEN:
    raise RuntimeError("❌ TELEGRAM_BOT_TOKEN no definido")

# ============================================================
# DATABASE
# ============================================================

MONGO_URI = os.getenv("MONGO_URL")
DB_NAME = "TRADING_X_HIPER_PRO"

if not MONGO_URI:
    raise RuntimeError("❌ MONGO_URL no definido")

# ============================================================
# HYPERLIQUID
# ============================================================

HYPER_BASE_URL = "https://api.hyperliquid.xyz"
REQUEST_TIMEOUT = 10
DEFAULT_PAIR = "BTC"

# ============================================================
# SCANNER
# ============================================================

SCAN_INTERVAL = 15
SCANNER_DEPTH = 80

# ============================================================
# STRATEGY – SINGLE SOURCE OF TRUTH
# ============================================================

ENTRY_SIGNAL_THRESHOLD = 0.25   # % real acumulado
PRICE_WINDOW = 6
PRICE_BUFFER_TTL = 15

# ============================================================
# RISK
# ============================================================

MIN_CAPITAL = 5.0
POSITION_PERCENT = 0.35
MAX_CONCURRENT_TRADES = 3

# ============================================================
# FEES
# ============================================================

OWNER_FEE_PERCENT = 0.15
REFERRAL_FEE_PERCENT = 0.05

# ============================================================
# LOGGING
# ============================================================

VERBOSE_LOGS = True
PRODUCTION_MODE = True
