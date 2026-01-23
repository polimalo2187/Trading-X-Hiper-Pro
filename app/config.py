# ============================================================
# CONFIGURACIÓN GLOBAL – TRADING X HYPER PRO
# Archivo 1/9 – VERSIÓN MODO GUERRA (PRODUCCIÓN REAL)
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

# Símbolo base por defecto (fallback)
DEFAULT_PAIR = "BTC-USDC"

REQUEST_TIMEOUT = 10

# ============================================================
# SISTEMA DE SCANEO AUTOMÁTICO DE MERCADO
# ============================================================

# 🔥 Más escaneo = más oportunidades reales
SCAN_INTERVAL = 2           # segundos
SCANNER_DEPTH = 80          # top activos por volumen + OI

# ============================================================
# ESTRATEGIA – BLACKCROW AGGRESSIVE (MODO GUERRA)
# ============================================================

# 🔥 Threshold base (luego se ajusta dinámicamente en strategy.py)
ENTRY_SIGNAL_THRESHOLD = 0.58

# NOTA:
# TP / SL reales se calculan dinámicamente en risk.py + strategy.py.
# Estos valores se mantienen como referencia / compatibilidad.
TP_MIN = 0.010   # 1.0%
TP_MAX = 0.030   # 3.0%

SL_MIN = 0.006   # 0.6%
SL_MAX = 0.012   # 1.2%

# ============================================================
# GESTIÓN DE RIESGO (CAPITALES PEQUEÑOS FRIENDLY)
# ============================================================

MIN_CAPITAL = 5.0

# 🔥 Porcentaje base del capital por trade
# (luego se escala por fuerza de señal)
POSITION_PERCENT = 1.0

# 🔥 Trades simultáneos permitidos por usuario
MAX_CONCURRENT_TRADES = 3

# ============================================================
# SISTEMA DE FEES (ADMIN + REFERIDOS)
# ============================================================

OWNER_FEE_PERCENT = 0.15     # 15% sobre ganancias netas
REFERRAL_FEE_PERCENT = 0.05  # 5% del fee del admin

DAILY_FEE_COLLECTION_HOUR = 23
DAILY_FEE_COLLECTION_MINUTE = 59

REFERRAL_PAYOUT_DAY = "sunday"
REFERRAL_PAYOUT_HOUR = 23
REFERRAL_PAYOUT_MINUTE = 59

# ============================================================
# LOGS / SISTEMA
# ============================================================

# Logs detallados SOLO si PRODUCTION_MODE = False
VERBOSE_LOGS = True

# 🔒 Debe estar TRUE en producción real
PRODUCTION_MODE = True
