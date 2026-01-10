# ============================================================
# STRATEGY – Trading X Hyper Pro
# Archivo 4/9 – Señales REALES nivel banco
# PRODUCCIÓN ESTABLE – FIX DEFINITIVO
# ============================================================

from collections import deque
from datetime import datetime, timedelta

from app.config import ENTRY_SIGNAL_THRESHOLD
from app.hyperliquid_client import get_price


# ============================================================
# BUFFER DE PRECIOS
# ============================================================

PRICE_WINDOW = 3

price_buffer = {}
last_update_time = {}


def update_price(symbol: str, new_price: float):
    if symbol not in price_buffer:
        price_buffer[symbol] = deque(maxlen=PRICE_WINDOW)

    price_buffer[symbol].append(new_price)
    last_update_time[symbol] = datetime.utcnow()
    cleanup_stale_buffers()


def cleanup_stale_buffers():
    now = datetime.utcnow()
    stale = [
        s for s, t in last_update_time.items()
        if now - t > timedelta(minutes=3)
    ]

    for s in stale:
        price_buffer.pop(s, None)
        last_update_time.pop(s, None)


# ============================================================
# SEÑAL DE ENTRADA – PRODUCCIÓN REAL
# ============================================================

def get_entry_signal(symbol: str) -> dict:
    price = get_price(symbol)
    if price is None:
        return {"signal": False}

    update_price(symbol, price)
    prices = price_buffer.get(symbol)

    if not prices:
        return {"signal": False}

    # 🔥 Warm-up real: primera entrada permitida
    if len(prices) == 1:
        return {
            "signal": True,
            "strength": ENTRY_SIGNAL_THRESHOLD,
            "direction": "long",
            "entry_price": price
        }

    old_price = prices[0]
    last_price = prices[-1]

    if old_price <= 0:
        return {"signal": False}

    change = (last_price - old_price) / old_price
    strength = abs(change * 100)

    strength = round(min(max(strength, 0.0015), 8.0), 6)

    effective_threshold = max(
        ENTRY_SIGNAL_THRESHOLD * 0.55,
        0.0015
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
        "entry_price": price
    }


# ============================================================
# TP / SL – FUNCIÓN ESPERADA POR EL ENGINE
# (RESTABLECIDA – COMPATIBILIDAD TOTAL)
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
