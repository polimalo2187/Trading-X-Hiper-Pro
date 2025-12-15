# ============================================================
# CONFIGURACIÓN GLOBAL – TRADING X HYPER PRO
# Archivo 1/9 – Versión FINAL para producción real
# ============================================================

import os

# ============================================================
# BOT DE TELEGRAM
# ============================================================

TELEGRAM_BOT_TOKEN = os.getenv("BOT_TOKEN")
BOT_NAME = "TradingXHyperProBot"

# ============================================================
# EXCHANGE – HYPERLIQUID
# ============================================================

HYPER_BASE_URL = "https://api.hyperliquid.xyz"

# Par fallback (no se usa normalmente porque el scanner elige el mejor)
DEFAULT_PAIR = "BTC-USDC"

# Tiempo máximo para requests al exchange
REQUEST_TIMEOUT = 10

# ============================================================
# SISTEMA DE SCANEO AUTOMÁTICO DE MERCADO
# ============================================================

SCAN_INTERVAL = 30     # tiempo entre ciclos del trading loop
SCANNER_DEPTH = 50     # reservado para futuras versiones (no usado actualmente)

# ============================================================
# ESTRATEGIA – BLACKCROW AGGRESSIVE
# ============================================================

ENTRY_SIGNAL_THRESHOLD = 0.72  # fuerza mínima requerida
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

OWNER_FEE_PERCENT = 0.15       # 15% del profit
REFERRAL_FEE_PERCENT = 0.05    # 5% del fee del admin

# Admin cobra diario
DAILY_FEE_COLLECTION_HOUR = 23
DAILY_FEE_COLLECTION_MINUTE = 59

# Referido cobra semanal (domingo)
REFERRAL_PAYOUT_DAY = "sunday"
REFERRAL_PAYOUT_HOUR = 23
REFERRAL_PAYOUT_MINUTE = 59

# ============================================================
# LOGS / SISTEMA
# ============================================================

VERBOSE_LOGS = True            # logs detallados
PRODUCTION_MODE = True         # modo producción real
