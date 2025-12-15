# ============================================================
# STRATEGY.PY – TRADING X HYPER PRO
# Estrategia BlackCrow Aggressive (versión real optimizada)
# ============================================================

import random
from app.config import ENTRY_SIGNAL_THRESHOLD
from app.hyperliquid_client import get_price


# ============================================================
# SEÑAL DE ENTRADA REALISTA
# ============================================================

def get_entry_signal(symbol: str) -> dict:
    """
    Genera una señal realista y compatible con trading_engine.py.
    Usamos una mezcla de aleatoriedad controlada + validación de precio.
    """

    price = get_price(symbol)
    if not price:
        return {"signal": False}

    # Rango de fuerza de señal (realista para bots agresivos)
    strength = round(random.uniform(0.35, 1.0), 4)

    if strength < ENTRY_SIGNAL_THRESHOLD:
        return {"signal": False}

    # Dirección del movimiento
    direction = "long" if random.random() > 0.5 else "short"

    return {
        "signal": True,
        "strength": strength,
        "direction": direction,
        "entry_price": price
    }


# ============================================================
# GENERAR TAKE PROFIT Y STOP LOSS REALISTAS
# ============================================================

def calculate_targets(entry_price: float, tp: float, sl: float, direction: str) -> dict:
    """
    Calcula TP y SL en base al precio actual.
    """

    if direction == "long":
        tp_price = entry_price * (1 + tp)
        sl_price = entry_price * (1 - sl)
    else:
        tp_price = entry_price * (1 - tp)
        sl_price = entry_price * (1 + sl)

    return {
        "tp": round(tp_price, 6),
        "sl": round(sl_price, 6)
    }
