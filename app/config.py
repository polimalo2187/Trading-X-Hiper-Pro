import os

# ============================================================
# CONFIGURACIÓN GLOBAL – TRADING X HYPER PRO
# ============================================================

# -------------------------
# BOT DE TELEGRAM
# -------------------------
# Se carga desde Render → variable: BotToken
TELEGRAM_BOT_TOKEN = os.getenv("BotToken")

BOT_NAME = "Trading X Hyper Pro"
BOT_USERNAME = "TradingXHyperProBot"

# -------------------------
# EXCHANGE – HYPERLIQUID
# -------------------------
HYPER_BASE_URL = "https://api.hyperliquid.xyz"
DEFAULT_PAIR = "BTC-USDC"

# -------------------------
# TRADING ENGINE
# -------------------------
MIN_CAPITAL = 5
MAX_CONCURRENT_TRADES = 3
BASE_LEVERAGE = 3
USE_LEVERAGE = True

# -------------------------
# ESTRATEGIA – BLACKCROW AGGRESSIVE
# -------------------------
ENTRY_SIGNAL_THRESHOLD = 0.78
TP_MIN = 0.03
TP_MAX = 0.06
SL_MIN = 0.01
SL_MAX = 0.015

# -------------------------
# GESTIÓN DE RIESGO
# -------------------------
USE_TRAILING_SL = True
TRAILING_SL_OFFSET = 0.004

# -------------------------
# FEE – ADMINISTRADOR (TÚ)
# -------------------------
OWNER_FEE = 0.15
REFERRAL_FEE = 0.05
OWNER_EARNINGS = OWNER_FEE - REFERRAL_FEE

# -------------------------
# BASE DE DATOS
# -------------------------
# Se carga desde Render → variable: MONGO_URL
MONGO_URI = os.getenv("MONGO_URL")
DB_NAME = "trading_x_hyperpro"

# -------------------------
# SCHEDULER
# -------------------------
SCAN_INTERVAL = 30
