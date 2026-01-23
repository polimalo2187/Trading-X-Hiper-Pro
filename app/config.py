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

REQUEST_TIMEOUT = 10

# ============================================================
# SISTEMA DE SCANEO AUTOMÁTICO DE MERCADO
# ============================================================

# ✅ IMPORTANTE: baja el rate de llamadas al API /info (evita 429)
SCAN_INTERVAL = 15          # ✅ antes 2 — ahora 15s (BANK GRADE)
SCANNER_DEPTH = 80          # top activos por volumen + OI

# ============================================================
# ESTRATEGIA – (Compatibilidad)
# ============================================================

ENTRY_SIGNAL_THRESHOLD = 0.58

TP_MIN = 0.010
TP_MAX = 0.030

SL_MIN = 0.006
SL_MAX = 0.012

# ============================================================
# GESTIÓN DE RIESGO
# ============================================================

MIN_CAPITAL = 5.0
POSITION_PERCENT = 1.0
MAX_CONCURRENT_TRADES = 3

# ============================================================
# SISTEMA DE FEES
# ============================================================

OWNER_FEE_PERCENT = 0.15
REFERRAL_FEE_PERCENT = 0.05

DAILY_FEE_COLLECTION_HOUR = 23
DAILY_FEE_COLLECTION_MINUTE = 59

REFERRAL_PAYOUT_DAY = "sunday"
REFERRAL_PAYOUT_HOUR = 23
REFERRAL_PAYOUT_MINUTE = 59

# ============================================================
# LOGS / SISTEMA
# ============================================================

# ✅ En producción real, esto debería ser False para no spamear y no saturar logs
VERBOSE_LOGS = False

# 🔒 Debe estar TRUE en producción real
PRODUCTION_MODE = True
