# ============================================================
# CONFIGURACIÓN GLOBAL – TRADING X HYPER PRO
# PRODUCCIÓN REAL
# ============================================================

import os

# ============================================================
# BOT DE TELEGRAM
# ============================================================

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
BOT_NAME = "TradingXHyperProBot"

if not TELEGRAM_BOT_TOKEN:
    raise RuntimeError("❌ TELEGRAM_BOT_TOKEN no está definido en variables de entorno")

# ============================================================
# BASE DE DATOS – MongoDB Atlas
# ============================================================

MONGO_URI = os.getenv("MONGO_URL")
DB_NAME = "TRADING_X_HIPER_PRO"

if not MONGO_URI:
    raise RuntimeError("❌ MONGO_URL no está definido en variables de entorno")

# ============================================================
# EXCHANGE – HYPERLIQUID (PRODUCCIÓN)
# ============================================================

HYPER_BASE_URL = "https://api.hyperliquid.xyz"
DEFAULT_PAIR = "BTC-USDC"

REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "10"))

# ============================================================
# SISTEMA DE SCANEO AUTOMÁTICO DE MERCADO (PROD)
# ============================================================

SCAN_INTERVAL = int(os.getenv("SCAN_INTERVAL", "15"))
SCANNER_DEPTH = int(os.getenv("SCANNER_DEPTH", "80"))

SCANNER_MIN_24H_NOTIONAL = float(os.getenv("SCANNER_MIN_24H_NOTIONAL", "2000000"))  # 2,000,000
SCANNER_MIN_OPEN_INTEREST = float(os.getenv("SCANNER_MIN_OPEN_INTEREST", "250000"))  # 250,000
SCANNER_MAX_SPREAD_BPS = float(os.getenv("SCANNER_MAX_SPREAD_BPS", "25"))
SCANNER_MIN_TOP_BOOK_NOTIONAL = float(os.getenv("SCANNER_MIN_TOP_BOOK_NOTIONAL", "2000"))  # 2,000 USDC
SCANNER_SHORTLIST_DEPTH_FOR_L2 = int(os.getenv("SCANNER_SHORTLIST_DEPTH_FOR_L2", "25"))

SCANNER_STATS_CACHE_TTL = float(os.getenv("SCANNER_STATS_CACHE_TTL", "5.0"))
SCANNER_L2_CACHE_TTL = float(os.getenv("SCANNER_L2_CACHE_TTL", "1.5"))

# ============================================================
# ESTRATEGIA – (Compatibilidad)
# ============================================================

ENTRY_SIGNAL_THRESHOLD = float(os.getenv("ENTRY_SIGNAL_THRESHOLD", "0.58"))

# ============================================================
# TP / SL (ALINEADO CON trading_engine.py)
# ------------------------------------------------------------
# IMPORTANTE:
# - Todo es % de PRECIO (no ROE, no margen).
# - TP de activación == SL (misma cifra), como acordaste.
# - Trailing (cierre dinámico) = retroceso desde el máximo.
# ============================================================

# ✅ TP activación (igual que SL): 1.17% precio
TP_ACTIVATE_TRAIL_PRICE = float(os.getenv("TP_ACTIVATE_TRAIL_PRICE", "0.0117"))   # +1.17% precio

# ✅ Ajuste pedido por ti:
#    Antes: 0.00585 (0.585% precio). Ahora: 0.00100 (0.10% precio)
TRAIL_RETRACE_PRICE     = float(os.getenv("TRAIL_RETRACE_PRICE", "0.00100"))     # 0.10% precio

# ✅ SL fijo (igual al TP de activación)
SL_MIN_PRICE = float(os.getenv("SL_MIN_PRICE", "0.0117"))  # -1.17% precio
SL_MAX_PRICE = float(os.getenv("SL_MAX_PRICE", "0.0117"))  # fijo = min = max

# ------------------------------------------------------------
# Backwards-compat / legado (por si otra parte del bot usa estos)
# Los igualamos para que NO haya incoherencias.
# ============================================================

TP_MIN = float(os.getenv("TP_MIN", str(TP_ACTIVATE_TRAIL_PRICE)))
TP_MAX = float(os.getenv("TP_MAX", str(TP_ACTIVATE_TRAIL_PRICE)))

SL_MIN = float(os.getenv("SL_MIN", str(SL_MIN_PRICE)))
SL_MAX = float(os.getenv("SL_MAX", str(SL_MAX_PRICE)))

# ============================================================
# GESTIÓN DE RIESGO
# ============================================================

MIN_CAPITAL = float(os.getenv("MIN_CAPITAL", "5.0"))
POSITION_PERCENT = float(os.getenv("POSITION_PERCENT", "1.0"))

# ✅ Un solo trade a la vez
MAX_CONCURRENT_TRADES = int(os.getenv("MAX_CONCURRENT_TRADES", "1"))

# ============================================================
# SISTEMA DE FEES
# ============================================================

OWNER_FEE_PERCENT = float(os.getenv("OWNER_FEE_PERCENT", "0.15"))
REFERRAL_FEE_PERCENT = float(os.getenv("REFERRAL_FEE_PERCENT", "0.05"))

DAILY_FEE_COLLECTION_HOUR = int(os.getenv("DAILY_FEE_COLLECTION_HOUR", "23"))
DAILY_FEE_COLLECTION_MINUTE = int(os.getenv("DAILY_FEE_COLLECTION_MINUTE", "59"))

REFERRAL_PAYOUT_DAY = os.getenv("REFERRAL_PAYOUT_DAY", "sunday")
REFERRAL_PAYOUT_HOUR = int(os.getenv("REFERRAL_PAYOUT_HOUR", "23"))
REFERRAL_PAYOUT_MINUTE = int(os.getenv("REFERRAL_PAYOUT_MINUTE", "59"))

# ============================================================
# LOGS / SISTEMA
# ============================================================

VERBOSE_LOGS = (os.getenv("VERBOSE_LOGS", "False").lower() == "true")
PRODUCTION_MODE = (os.getenv("PRODUCTION_MODE", "True").lower() == "true")
