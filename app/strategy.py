# ============================================================
# STRATEGY – Trading X Hyper Pro
# Archivo 4/9 – Señales reales basadas en comportamiento del precio
# ============================================================

from app.config import ENTRY_SIGNAL_THRESHOLD
from app.hyperliquid_client import get_price


# ============================================================
# GENERAR SEÑAL REAL (SIN MOMENTUM SIMULADO)
# ============================================================
"""
IMPORTANTE:
Ya NO usamos:
❌ momentum inventado
❌ volatilidad simulada
❌ aleatoriedad basada en random
❌ cálculos falsos para generar señales

Ahora el bot genera señal REAL basándose SOLO en:
✔ precio actual
✔ comparación contra precios previos inmediatos (micro-tendencia real)
✔ reglas fijas, sin simulación

Esto es lo que un bot real simple hace: tomar decisiones basadas en
micro-cambios reales del precio.
"""


# Guardamos últimos precios para medir micro tendencia real
LAST_PRICES = {}


def get_entry_signal(symbol: str) -> dict:
    """
    Decisión basada únicamente en datos REALES:
    - Precio actual
    - Movimiento real mínimo (micro tendencia)
    """

    price = get_price(symbol)
    if not price:
        return {"signal": False}

    # Obtener último precio registrado
    last_price = LAST_PRICES.get(symbol)

    # Actualizar para la próxima lectura
    LAST_PRICES[symbol] = price

    # Si no existe precio previo, no se puede analizar tendencia
    if last_price is None:
        return {"signal": False}

    # ------------------------------------------------------------
    # CÁLCULO REAL DE MICRO-TENDENCIA
    # ------------------------------------------------------------
    change = (price - last_price) / last_price  # cambio porcentual real

    # Convertimos el cambio a un "strength" real
    strength = abs(round(change, 6))

    # Si el movimiento es demasiado débil, descartamos
    if strength < ENTRY_SIGNAL_THRESHOLD:
        return {"signal": False, "strength": strength}

    # Dirección real basada en el movimiento actual
    direction = "long" if price > last_price else "short"

    return {
        "signal": True,
        "strength": strength,
        "direction": direction,
        "entry_price": price
    }


# ============================================================
# CALCULAR TP/SL REAL
# ============================================================

def calculate_targets(entry_price: float, tp_percent: float, sl_percent: float, direction: str) -> dict:
    """
    Cálculo 100% real de TP/SL.
    Nada inventado. Nada simulado.
    """

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
