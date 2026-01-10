# ============================================================
# ARCHIVO: app/strategy.py
# ============================================================
# Estrategia de entrada por MOMENTUM ACUMULADO
# FIX PRODUCCIÓN REAL – NO BLOQUEA MERCADOS
# ============================================================

from collections import deque
import time

# ======================
# CONFIGURACIÓN REAL
# ======================

PRICE_WINDOW = 5              # 🔥 Menos ticks requeridos
ENTRY_SIGNAL_THRESHOLD = 0.03 # 🔥 Realista para Hyperliquid
PRICE_BUFFER_TTL = 20         # segundos

# ======================
# BUFFER DE PRECIOS
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
        price_timestamp[symbol] = now

    if now - price_timestamp[symbol] > PRICE_BUFFER_TTL:
        price_buffer[symbol].clear()

    price_buffer[symbol].append(price)
    price_timestamp[symbol] = now


def get_price(symbol: str):
    try:
        from app.market import get_mark_price
        return get_mark_price(symbol)
    except Exception:
        return None


# ======================
# FUNCIÓN PRINCIPAL
# ======================

def get_entry_signal(symbol: str) -> dict:
    price = get_price(symbol)
    if price is None or price <= 0:
        return {"signal": False}

    update_price(symbol, price)

    prices = price_buffer.get(symbol)
    if not prices or len(prices) < 3:
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
