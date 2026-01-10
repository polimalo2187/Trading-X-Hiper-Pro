# ============================================================
# ARCHIVO: app/strategy.py
# ============================================================
# Estrategia de entrada por MOMENTUM ACUMULADO
# Compatible con markPx (Hyperliquid)
# ============================================================

from collections import deque
import time
from app.hyperliquid_client import get_price as get_mark_price

# ======================
# CONFIGURACIÓN
# ======================

PRICE_WINDOW = 6
ENTRY_SIGNAL_THRESHOLD = 0.25   # %
PRICE_BUFFER_TTL = 60           # ⬅ FIX: antes 15 (imposible llenar buffer)

# ======================
# BUFFER
# ======================

price_buffer = {}
price_timestamp = {}

# ======================
# UTILIDADES
# ======================

def update_price(symbol: str, price: float):
    now = time.time()

    if symbol not in price_buffer:
        price_buffer[symbol] = deque(maxlen=PRICE_WINDOW)

    last_ts = price_timestamp.get(symbol, now)

    # Reset SOLO si está realmente muerto
    if now - last_ts > PRICE_BUFFER_TTL:
        price_buffer[symbol].clear()

    price_buffer[symbol].append(price)
    price_timestamp[symbol] = now


def get_entry_signal(symbol: str) -> dict:
    """
    Retorna:
    {
        signal: bool,
        direction: 'long' | 'short',
        strength: float,
        entry_price: float
    }
    """

    price = get_mark_price(symbol)
    if not price or price <= 0:
        return {"signal": False}

    update_price(symbol, price)

    prices = price_buffer.get(symbol)
    if not prices or len(prices) < PRICE_WINDOW:
        return {"signal": False}

    old_price = prices[0]
    last_price = prices[-1]

    if old_price <= 0:
        return {"signal": False}

    change = (last_price - old_price) / old_price
    strength = abs(change) * 100

    if strength < ENTRY_SIGNAL_THRESHOLD:
        return {
            "signal": False,
            "strength": round(strength, 4)
        }

    direction = "long" if change > 0 else "short"

    return {
        "signal": True,
        "direction": direction,
        "strength": round(strength, 4),
        "entry_price": last_price
  }
