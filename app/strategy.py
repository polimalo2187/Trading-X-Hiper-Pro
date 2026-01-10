# strategy.py
# ============================================================
# Estrategia de entrada por MOMENTUM ACUMULADO
# Compatible con feed markPx (Hyperliquid)
# NO modifica TP / SL / Risk
# ============================================================

from collections import deque
import time

# ======================
# CONFIGURACIÓN ESTRATEGIA
# ======================

PRICE_WINDOW = 6              # Ventana corta (momentum real)
ENTRY_SIGNAL_THRESHOLD = 0.25 # % mínimo de movimiento acumulado
PRICE_BUFFER_TTL = 15         # segundos

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
    Esta función DEBE ser provista por el engine o data provider.
    Aquí solo se llama.
    """
    try:
        from market import get_mark_price
        return get_mark_price(symbol)
    except Exception:
        return None


# ======================
# FUNCIÓN PRINCIPAL
# ======================

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

    # 🔒 NO tocamos rentabilidad
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
