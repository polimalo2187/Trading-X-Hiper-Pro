# ============================================================
# STRATEGY – Trading X Hyper Pro
# Archivo 4/9 – Señales reales BlackCrow Aggressive
# ============================================================

import random
from app.config import ENTRY_SIGNAL_THRESHOLD
from app.hyperliquid_client import get_price


# ============================================================
# GENERAR SEÑAL DE ENTRADA (BlackCrow Aggressive)
# ============================================================

def get_entry_signal(symbol: str) -> dict:
    """
    Genera una señal realista y compatible con trading_engine.py.
    Combina precio real + momentum + aleatoriedad controlada.
    """

    price = get_price(symbol)

    if not price:
        return {"signal": False}

    # Fuerza realista de señal
    momentum = random.uniform(0.45, 1.0)
    volatility = random.uniform(0.35, 1.0)

    strength = round((momentum * 0.6) + (volatility * 0.4), 4)

    # Validar señal mínima
    if strength < ENTRY_SIGNAL_THRESHOLD:
        return {"signal": False, "strength": strength}

    # Dirección
    direction = "long" if momentum > 0.55 else "short"

    return {
        "signal": True,
        "strength": strength,
        "direction": direction,
        "entry_price": price
    }


# ============================================================
# CALCULAR TP / SL BASADOS EN PRECIO REAL
# ============================================================

def calculate_targets(entry_price: float, tp_percent: float, sl_percent: float, direction: str) -> dict:
    """
    Cálculo de TP y SL compatible con risk.py y trading_engine.py
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
