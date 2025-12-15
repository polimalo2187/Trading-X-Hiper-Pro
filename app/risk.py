# ============================================================
# RISK MANAGEMENT – Trading X Hyper Pro
# Archivo 5/9 – Gestión de riesgo REAL (versión producción)
# ============================================================

from app.config import (
    MIN_CAPITAL,
    POSITION_PERCENT,
)


# ============================================================
# CALCULAR TP / SL BASADOS EN LA FUERZA DE LA SEÑAL
# ============================================================

def calculate_dynamic_tp_sl(strength: float):
    """
    TP y SL se calculan en función de la fuerza real de la señal.
    Sin aleatoriedad. 100% determinístico.

    Regla profesional:
    - Señal fuerte  → TP amplio y SL estrecho
    - Señal débil   → TP moderado y SL más amplio
    """

    # Normalizamos la fuerza a un rango útil
    weight = min(max(strength, 0.01), 3.0)

    # TP y SL se ajustan de manera proporcional a la fuerza real
    tp = round(0.008 * weight, 4)    # TP dinámico
    sl = round(0.004 * weight, 4)    # SL dinámico

    return tp, sl


# ============================================================
# VALIDAR SI EL USUARIO PUEDE OPERAR + TAMAÑO DE POSICIÓN
# ============================================================

def validate_trade_conditions(balance: float, strength: float) -> dict:
    """
    Valida si el usuario está apto para operar y calcula:
      ✓ Tamaño de posición real
      ✓ TP/SL determinísticos basados en la señal
      ✓ Riesgo coherente con el Trading Engine
    """

    # 1) CAPITAL MÍNIMO
    if balance < MIN_CAPITAL:
        return {"ok": False, "reason": "Capital insuficiente para operar."}

    # 2) TAMAÑO DE POSICIÓN CENTRALIZADO (20% del capital)
    position_size = round(balance * POSITION_PERCENT, 4)

    if position_size <= 0:
        return {"ok": False, "reason": "Capital insuficiente para calcular posición."}

    # 3) TP / SL REAL basado en la fuerza de la señal
    tp, sl = calculate_dynamic_tp_sl(strength)

    return {
        "ok": True,
        "tp": tp,
        "sl": sl,
        "position_size": position_size
    }
