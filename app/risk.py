# ============================================================
# RISK MANAGEMENT – Trading X Hyper Pro
# Archivo 5/9 – Gestión de riesgo REAL, versión producción
# ============================================================

from app.config import (
    MIN_CAPITAL,
    POSITION_PERCENT,
)


# ============================================================
# CALCULAR TP / SL BASADOS EN FUERZA (REALISTA para PERP)
# ============================================================

def calculate_dynamic_tp_sl(strength: float):
    """
    Cálculo profesional de TP/SL basado en fuerza real de microtendencia.
    Rango final:
        TP → 0.30%  a  1.40%
        SL → 0.15%  a  0.70%
    """

    # Normalizamos fuerza al rango 0.0 – 1.0
    s = max(min(strength, 1.0), 0.0)

    # TP: más fuerza → más amplio
    tp = 0.003 + (0.011 * s)   # 0.30% – 1.40%

    # SL: más fuerza → más estrecho
    sl = 0.007 - (0.005 * s)   # 0.70% – 0.20%

    return round(tp, 4), round(sl, 4)


# ============================================================
# VALIDAR CONDICIONES DE TRADE + TAMAÑO DE POSICIÓN
# ============================================================

def validate_trade_conditions(balance: float, strength: float) -> dict:
    """
    Valida si el usuario puede operar y calcula:
        ✓ Tamaño de posición
        ✓ TP / SL dinámicos
        ✓ Apto para motores reales de derivados
    """

    # 1) Capital mínimo
    if balance < MIN_CAPITAL:
        return {"ok": False, "reason": "Capital insuficiente para operar."}

    # 2) Tamaño de la posición (porcentaje del capital)
    position_size = round(balance * POSITION_PERCENT, 4)

    if position_size <= 0:
        return {"ok": False, "reason": "Capital insuficiente para posición."}

    # 3) TP/SL reales basados en fuerza de señal
    tp, sl = calculate_dynamic_tp_sl(strength)

    return {
        "ok": True,
        "tp": tp,
        "sl": sl,
        "position_size": position_size
    }
