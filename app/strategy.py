# ============================================================
# ARCHIVO: app/strategy.py
# ============================================================
# Estrategia de entrada por MOMENTUM ACUMULADO
# Hyperliquid – PRODUCCIÓN REAL
# ============================================================

from collections import deque
import time

from app.hyperliquid_client import get_price


# ======================
# CONFIGURACIÓN
# ======================

PRICE_WINDOW = 10
ENTRY_SIGNAL_THRESHOLD = 0.12  # % real
PRICE_BUFFER_TTL = 15  # segundos


# ======================
# BUFFER DE PRECIOS
# ======================

price_buffer = {}
price_timestamp = {}


# ======================
# LOG
# ======================

def log(msg: str):
    print(f"[STRATEGY] {msg}")


# ======================
# BUFFER UPDATE
# ======================

def update_price(symbol: str, price: float):
    now = time.time()

    if symbol not in price_buffer:
        price_buffer[symbol] = deque(maxlen=PRICE_WINDOW)
        price_timestamp[symbol] = now

    if now - price_timestamp[symbol] > PRICE_BUFFER_TTL:
        price_buffer[symbol].clear()
        log(f"Buffer reseteado {symbol}")

    price_buffer[symbol].append(price)
    price_timestamp[symbol] = now


# ======================
# ENTRY SIGNAL
# ======================

def get_entry_signal(symbol: str) -> dict:
    price = get_price(symbol)

    if price is None or price <= 0:
        log(f"Precio inválido {symbol}: {price}")
        return {"signal": False}

    update_price(symbol, price)

    prices = price_buffer.get(symbol)
    if not prices or len(prices) < PRICE_WINDOW:
        log(f"Buffer insuficiente {symbol} ({len(prices) if prices else 0})")
        return {"signal": False}

    old_price = prices[0]
    last_price = prices[-1]

    change = (last_price - old_price) / old_price
    strength = abs(change) * 100

    log(f"{symbol} change={round(change,5)} strength={round(strength,3)}%")

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
