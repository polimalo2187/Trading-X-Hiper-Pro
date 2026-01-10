# ============================================================
# STRATEGY – Trading X Hyper Pro
# Archivo 4/9 – Señales REALES nivel banco
# MODO GUERRA RENTABLE (4% → 18%)
# ============================================================

from collections import deque
from datetime import datetime, timedelta

from app.config import ENTRY_SIGNAL_THRESHOLD
from app.hyperliquid_client import get_price


# ============================================================
# BUFFER DE PRECIOS (SCALPING REAL FUNCIONAL)
# ============================================================

PRICE_WINDOW = 6  # ⬅ suficiente para micro-tendencia real

price_buffer = {}       # { symbol: deque }
last_update_time = {}   # { symbol: datetime }


def update_price(symbol: str, price: float):
    if symbol not in price_buffer:
        price_buffer[symbol] = deque(maxlen=PRICE_WINDOW)

    price_buffer[symbol].append(price)
    last_update_time[symbol] = datetime.utcnow()

    cleanup_stale_buffers()


def cleanup_stale_buffers():
    now = datetime.utcnow()
    stale = [
        s for s, t in last_update_time.items()
        if now - t > timedelta(minutes=15)
    ]

    for s in stale:
        price_buffer.pop(s, None)
        last_update_time.pop(s, None)


# ============================================================
# SEÑAL DE ENTRADA – PRODUCCIÓN REAL (FIX DEFINITIVO)
# ============================================================

def get_entry_signal(symbol: str) -> dict:

    price = get_price(symbol)
    if price is None or price <= 0:
        return {"signal": False}

    update_price(symbol, price)

    prices = price_buffer.get(symbol)
    if not prices or len(prices) < PRICE_WINDOW:
        return {"signal": False}

    old_price = prices[0]
    last_price = prices[-1]

    if old_price <= 0:
        return {"signal": False}

    # ========================================================
    # FUERZA REAL (MICRO-TENDENCIA REAL)
    # ========================================================

    change = (last_price - old_price) / old_price
    raw_strength = abs(change) * 100  # % real

    # Clamp REAL para Hyperliquid
    strength = round(min(max(raw_strength, 0.0008), 6.5), 6)

    effective_threshold = max(
        ENTRY_SIGNAL_THRESHOLD * 0.40,  # ⬅ más realista
        0.0008
    )

    if strength < effective_threshold:
        return {
            "signal": False,
            "strength": strength
        }

    direction = "long" if last_price > old_price else "short"

    return {
        "signal": True,
        "strength": strength,
        "direction": direction,
        "entry_price": last_price
    }


# ============================================================
# TP / SL – RENTABILIDAD COMPUESTA REAL
# ============================================================

def calculate_targets(
    entry_price: float,
    tp_percent: float,
    sl_percent: float,
    direction: str
) -> dict:

    tp_percent = min(max(tp_percent, 0.0015), 0.045)
    sl_percent = min(max(sl_percent, 0.0009), 0.020)

    if direction == "long":
        tp_price = entry_price * (1 + tp_percent)
        sl_price = entry_price * (1 - sl_percent)
    else:
        tp_price = entry_price * (1 - tp_percent)
        sl_price = entry_price * (1 + sl_percent)

    return {
        "tp": round(tp_price, 6),
        "sl": round(sl_price, 6)
  }
