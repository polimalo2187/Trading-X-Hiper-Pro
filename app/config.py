# ============================================================
# CONFIGURACIÓN GLOBAL – TRADING X HYPER PRO
# Archivo 1/9 – Versión FINAL para producción real
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
# EXCHANGE – HYPERLIQUID
# ============================================================

HYPER_BASE_URL = "https://api.hyperliquid.xyz"
DEFAULT_PAIR = "BTC-USDC"
REQUEST_TIMEOUT = 10

# ============================================================
# SISTEMA DE SCANEO AUTOMÁTICO DE MERCADO
# ============================================================

SCAN_INTERVAL = 30
SCANNER_DEPTH = 50

# ============================================================
# ESTRATEGIA – BLACKCROW AGGRESSIVE
# ============================================================

ENTRY_SIGNAL_THRESHOLD = 0.72
TP_MIN = 0.015
TP_MAX = 0.045
SL_MIN = 0.007
SL_MAX = 0.015

# ============================================================
# GESTIÓN DE RIESGO
# ============================================================

MIN_CAPITAL = 5
POSITION_PERCENT = 0.20
MAX_CONCURRENT_TRADES = 1

# ============================================================
# SISTEMA DE FEES (ADMIN + REFERIDOS)
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

VERBOSE_LOGS = True
PRODUCTION_MODE = True
