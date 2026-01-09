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

# Hyperliquid usa símbolos simples (PERPS)
DEFAULT_PAIR = "BTC"

REQUEST_TIMEOUT = 10

# ============================================================
# SISTEMA DE SCANEO AUTOMÁTICO DE MERCADO
# ============================================================

# 🔥 Más escaneo = más trades
SCAN_INTERVAL = 15          # antes 30
SCANNER_DEPTH = 80          # antes 50

# ============================================================
# ESTRATEGIA – BLACKCROW AGGRESSIVE (MODO GUERRA)
# ============================================================

# 🔥 Baja el rigor → entra mucho más
ENTRY_SIGNAL_THRESHOLD = 0.58   # antes 0.72

# 🎯 TP más frecuentes
TP_MIN = 0.010                  # 1.0%
TP_MAX = 0.030                  # 3.0%

# 🛡️ SL ajustado pero agresivo
SL_MIN = 0.006                  # 0.6%
SL_MAX = 0.012                  # 1.2%

# ============================================================
# GESTIÓN DE RIESGO (CAPITALES PEQUEÑOS FRIENDLY)
# ============================================================

MIN_CAPITAL = 5

# 🔥 Usa más capital por trade
POSITION_PERCENT = 0.35         # antes 0.20

# 🔥 Permite varias operaciones simultáneas
MAX_CONCURRENT_TRADES = 3       # antes 1

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
