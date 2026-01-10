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
# BUFFER REAL DE PRECIOS (ULTRA AGRESIVO CONTROLADO)
# ============================================================

PRICE_WINDOW = 3   # 🔥 Muy rápido, ideal para scalp compuesto
price_buffer = {}          # { symbol: deque([...]) }
last_update_time = {}      # { symbol: datetime }


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
        if now - t > timedelta(minutes=10)
    ]
    for s in stale:
        del price_buffer[s]
        del last_update_time[s]


# ============================================================
# SEÑAL DE ENTRADA – GUERRA RENTABLE
# ============================================================

def get_entry_signal(symbol: str) -> dict:
    price = get_price(symbol)
    if not price:
        return {"signal": False}

    update_price(symbol, price)

    prices = price_buffer[symbol]
    if len(prices) < PRICE_WINDOW:
        return {"signal": False}

    old_price = prices[0]
    last_price = prices[-1]

    if old_price <= 0:
        return {"signal": False}

    # Variación acumulada real
    change = (last_price - old_price) / old_price
    raw_strength = abs(change * 100)

    # 🔥 Strength optimizado para scalp rentable
    strength = round(min(max(raw_strength, 0.004), 7.5), 6)

    # 🔥 UMBRAL DINÁMICO GUERRA (sin tocar config)
    effective_threshold = ENTRY_SIGNAL_THRESHOLD * 0.65

    if strength < effective_threshold:
        return {"signal": False, "strength": strength}

    direction = "long" if last_price > old_price else "short"

    return {
        "signal": True,
        "strength": strength,
        "direction": direction,
        "entry_price": price
    }


# ============================================================
# TP / SL – RENTABILIDAD COMPUESTA
# ============================================================

def calculate_targets(entry_price: float, tp_percent: float, sl_percent: float, direction: str) -> dict:

    # 🎯 TP frecuentes + SL controlado
    tp_percent = min(max(tp_percent, 0.0015), 0.045)   # hasta 4.5%
    sl_percent = min(max(sl_percent, 0.0009), 0.020)   # hasta 2.0%

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
