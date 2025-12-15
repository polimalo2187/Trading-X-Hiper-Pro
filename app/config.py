# ============================================================
# CONFIGURACIÓN GLOBAL – TRADING X HYPER PRO
# Archivo 1/9
# ============================================================

import os

# ============================================================
# BOT DE TELEGRAM
# ============================================================

TELEGRAM_BOT_TOKEN = os.getenv("BOT_TOKEN")   # Guardado en Render / Railway
BOT_NAME = "TradingXHyperProBot"

# ============================================================
# EXCHANGE – HYPERLIQUID
# ============================================================

HYPER_BASE_URL = "https://api.hyperliquid.xyz"
DEFAULT_PAIR = "BTC-USDC"   # Solo como fallback

# ============================================================
# SISTEMA DE SCANEO AUTOMÁTICO DE MERCADO
# ============================================================

SCAN_INTERVAL = 30   # segundos entre cada operación
SCANNER_DEPTH = 50   # cantidad máxima de pares que evaluará el scanner

# ============================================================
# ESTRATEGIA BLACKCROW AGGRESSIVE (SEÑALES)
# ============================================================

ENTRY_SIGNAL_THRESHOLD = 0.72   # fuerza mínima
TP_MIN = 0.015
TP_MAX = 0.045
SL_MIN = 0.007
SL_MAX = 0.015

# ============================================================
# GESTIÓN DE RIESGO
# ============================================================

MIN_CAPITAL = 5
POSITION_PERCENT = 0.20          # 20% del capital por operación
MAX_CONCURRENT_TRADES = 1        # el bot no hace múltiples trades simultáneos

# ============================================================
# SISTEMA DE FEES (100% REAL)
# ============================================================

# Fee base del dueño (tú) sobre cada ganancia del usuario
OWNER_FEE_PERCENT = 0.15

# Porcentaje para referido (sale de la fee del dueño)
REFERRAL_FEE_PERCENT = 0.05

# Pago del dueño → diario (a las 24h)
DAILY_FEE_COLLECTION_HOUR = 23   # 23:00 (final del día)
DAILY_FEE_COLLECTION_MINUTE = 59

# Pago del referido → semanal (domingo)
REFERRAL_PAYOUT_DAY = "sunday"
REFERRAL_PAYOUT_HOUR = 23
REFERRAL_PAYOUT_MINUTE = 59

# ============================================================
# BASE DE DATOS
# ============================================================

MONGO_URI = os.getenv("MONGO_URL")
DB_NAME = "TradingX_HyperPro"

# ============================================================
# OTROS AJUSTES
# ============================================================

VERBOSE_LOGS = True
