# ============================================================
# ARCHIVO: app/strategy.py
# ============================================================
# Estrategia de entrada por MOMENTUM ACUMULADO
# Compatible con feed markPx (Hyperliquid)
# PRODUCCIÓN REAL – AJUSTADA
# ============================================================

from collections import deque
import time

# ======================
# CONFIGURACIÓN ESTRATEGIA (PRODUCCIÓN)
# ======================

PRICE_WINDOW = 10              # contexto de mercado
ENTRY_SIGNAL_THRESHOLD = 0.12  # sensibilidad momentum
PRICE_BUFFER_TTL = 15          # segundos

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

    # Reset buffer si quedó viejo
    if now - price_timestamp[symbol] > PRICE_BUFFER_TTL:
        price_buffer[symbol].clear()

    price_buffer[symbol].append(price)
    price_timestamp[symbol] = now


def get_price(symbol: str):
    """
    Fallback seguro si el engine no pasa el precio.
    """
    try:
        from market import get_mark_price
        return get_mark_price(symbol)
    except Exception:
        return None


# ======================
# FUNCIÓN PRINCIPAL (RETROCOMPATIBLE)
# ======================

def get_entry_signal(symbol: str, price: float = None) -> dict:
    """
    Compatible con:
    - get_entry_signal(symbol)
    - get_entry_signal(symbol, price)

    Retorna:
    {
        signal: bool,
        direction: 'long' | 'short',
        strength: float,
        entry_price: float
    }
    """

    # 🔒 Si el engine no pasa el precio, lo buscamos
    if price is None:
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

    change = (last_price - old_price) / old_price
    strength = abs(change) * 100

    # Umbral de entrada
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
