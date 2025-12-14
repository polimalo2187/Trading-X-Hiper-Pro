# ============================================================
# ESTRATEGIA BLACKCROW AGGRESSIVE – TRADING X HYPER PRO
# ============================================================

from app.config import (
    ENTRY_SIGNAL_THRESHOLD,
    TP_MIN, TP_MAX,
    SL_MIN, SL_MAX
)
from app.hyper_api import get_price


# ============================================================
# FUNCIÓN PRINCIPAL DE SEÑAL
# ============================================================

def get_entry_signal(symbol):
    """
    Genera una señal de entrada usando la estrategia BLACKCROW.
    Esta versión es ultra-optimizada para trading agresivo.
    """

    price = get_price(symbol)

    if not price:
        return {"signal": False}

    # --------------------------------------------------------
    # Modelo simplificado temporal de volatilidad + momentum
    # --------------------------------------------------------

    from random import uniform

    # Fuerza del movimiento actual (simulación temporal)
    momentum = uniform(0.60, 0.95)

    # Volatilidad estimada (simulación temporal)
    volatility = uniform(0.50, 1.00)

    # Strength combinada
    strength = round((momentum * 0.6) + (volatility * 0.4), 4)

    # --------------------------------------------------------
    # Validación de señal
    # --------------------------------------------------------

    if strength < ENTRY_SIGNAL_THRESHOLD:
        return {"signal": False}

    # Dirección basada en momentum
    side = "buy" if momentum > 0.7 else "sell"

    return {
        "signal": True,
        "side": side,
        "strength": strength,
        "entry_price": price,
        "tp_min": TP_MIN,
        "tp_max": TP_MAX,
        "sl_min": SL_MIN,
        "sl_max": SL_MAX
    }


# ============================================================
# CALCULAR TARGETS (TP y SL)
# ============================================================

def calculate_targets(entry_price, tp_min, tp_max, sl_min, sl_max, side):
    """
    Devuelve precios objetivos adaptados al side (buy o sell).
    """

    if side == "buy":
        tp = entry_price * (1 + tp_min)
        tp2 = entry_price * (1 + tp_max)
        sl = entry_price * (1 - sl_min)
        sl2 = entry_price * (1 - sl_max)

    else:  # SELL
        tp = entry_price * (1 - tp_min)
        tp2 = entry_price * (1 - tp_max)
        sl = entry_price * (1 + sl_min)
        sl2 = entry_price * (1 + sl_max)

    return {
        "tp1": round(tp, 6),
        "tp2": round(tp2, 6),
        "sl1": round(sl, 6),
        "sl2": round(sl2, 6)
      }
