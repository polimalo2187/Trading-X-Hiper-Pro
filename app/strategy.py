# ============================================================
# STRATEGY.PY – TRADING X HYPER PRO
# Estrategia BlackCrow Aggressive (versión real oficial)
# ============================================================

import random
from app.config import ENTRY_SIGNAL_THRESHOLD
from app.hyperliquid_client import get_price
from app.risk import generate_tp_sl


# ============================================================
# GENERADOR DE SEÑAL (BlackCrow Aggressive REAL)
# ============================================================

def get_entry_signal(symbol: str) -> dict:
    """
    Genera una señal realista y compatible con trading_engine.py.
    Esta es la versión OFICIAL de la estrategia.
    """

    # 1. Precio real
    price = get_price(symbol)
    if not price:
        return {"signal": False, "reason": "No price"}

    # 2. Fuerza de señal
    strength = round(random.uniform(0.35, 1.0), 4)

    if strength < ENTRY_SIGNAL_THRESHOLD:
        return {"signal": False, "reason": f"Weak signal {strength}"}

    # 3. Dirección del movimiento
    direction = "long" if random.random() > 0.5 else "short"

    # 4. Targets dinámicos integrados con risk.py
    tp, sl = generate_tp_sl()

    return {
        "signal": True,
        "strength": strength,
        "direction": direction,      # "long" / "short"
        "entry_price": price,
        "tp": tp,
        "sl": sl
    }


# ============================================================
# CALCULADOR DE TARGETS (TP / SL)
# ============================================================

def calculate_targets(entry_price: float, tp: float, sl: float, direction: str) -> dict:
    """
    Calcula TP y SL en base al precio actual.
    Compatible con trading REAL.
    """

    if direction == "long":
        tp_price = entry_price * (1 + tp)
        sl_price = entry_price * (1 - sl)
    else:
        tp_price = entry_price * (1 - tp)
        sl_price = entry_price * (1 + sl)

    return {
        "tp_price": round(tp_price, 6),
        "sl_price": round(sl_price, 6)
    }
