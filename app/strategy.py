# ============================================================
# STRATEGY – Trading X Hyper Pro
# Archivo 4/9 – Señales REALES basadas en micro–tendencia real
# ============================================================

from collections import deque
from app.config import ENTRY_SIGNAL_THRESHOLD
from app.hyperliquid_client import get_price


# ============================================================
# BUFFER DE PRECIOS (REAL, SIN SIMULACIÓN)
# ============================================================

"""
Usamos una ventana fija de 5 precios reales.
Esto elimina ruido y produce una señal realmente profesional.
"""

PRICE_WINDOW = 5
price_buffer = {}   # { "BTC-USDC": deque([...]) }


def update_price(symbol: str, new_price: float):
    """Mantiene buffer de precios por símbolo."""
    if symbol not in price_buffer:
        price_buffer[symbol] = deque(maxlen=PRICE_WINDOW)

    price_buffer[symbol].append(new_price)


# ============================================================
# SEÑAL REAL PROFESIONAL (NO SIMULADA)
# ============================================================

def get_entry_signal(symbol: str) -> dict:
    """
    Genera una señal real basada en:
    - Variación acumulada en la ventana
    - Pendiente real del movimiento (micro tendencia)
    """

    price = get_price(symbol)
    if not price:
        return {"signal": False}

    update_price(symbol, price)

    # Si no hay suficientes datos → no analizamos
    prices = price_buffer[symbol]
    if len(prices) < PRICE_WINDOW:
        return {"signal": False}

    # -----------------------------------------
    # CÁLCULO DE MICRO-TENDENCIA REAL
    # -----------------------------------------

    old_price = prices[0]
    last_price = prices[-1]

    if old_price <= 0:
        return {"signal": False}

    # Variación acumulada real
    change = (last_price - old_price) / old_price

    # Strength REAL que sí funciona para mercados
    # Normalizamos la variación multiplicando por 100 (para %)
    strength = abs(change * 100)

    # Debe superar el umbral real definido por el admin
    if strength < ENTRY_SIGNAL_THRESHOLD:
        return {"signal": False, "strength": round(strength, 6)}

    # Dirección real
    direction = "long" if last_price > old_price else "short"

    return {
        "signal": True,
        "strength": round(strength, 6),
        "direction": direction,
        "entry_price": price
    }


# ============================================================
# TP / SL 100% REALES
# ============================================================

def calculate_targets(entry_price: float, tp_percent: float, sl_percent: float, direction: str) -> dict:

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
