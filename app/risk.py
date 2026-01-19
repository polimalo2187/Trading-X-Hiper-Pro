# ============================================================
# RISK MANAGEMENT – Trading X Hyper Pro
# Archivo 5/9 – Gestión de riesgo (FIX PRODUCCIÓN REAL)
# ============================================================

from app.config import (
    MIN_CAPITAL,
    POSITION_PERCENT,
)

# ============================================================
# TP / SL DINÁMICOS – REALISTAS HYPERLIQUID
# ============================================================

def calculate_dynamic_tp_sl(strength: float):
    """
    TP / SL dinámicos basados en fuerza REAL (%).
    No inventa R/R imposible.
    """

    # Validación de tipo + clamp REAL
    try:
        strength = float(strength)
    except Exception:
        strength = 0.2

    strength = max(min(strength, 8.0), 0.2)

    if strength < 1.5:
        tp = 0.008      # 0.8%
        sl = 0.005      # 0.5%
    elif strength < 3:
        tp = 0.015      # 1.5%
        sl = 0.007      # 0.7%
    elif strength < 5:
        tp = 0.025      # 2.5%
        sl = 0.010      # 1.0%
    else:
        tp = 0.040      # 4.0%
        sl = 0.014      # 1.4%

    return round(tp, 4), round(sl, 4)


# ============================================================
# VALIDAR CONDICIONES + TAMAÑO DE POSICIÓN
# ============================================================

def validate_trade_conditions(balance: float, strength: float) -> dict:
    """
    Gestión de riesgo REAL.
    Nunca inventa capital.
    Nunca fuerza tamaño inválido.
    """

    # Validación de tipos
    try:
        balance = float(balance)
    except Exception:
        balance = 0.0

    try:
        strength = float(strength)
    except Exception:
        strength = 0.2

    # 1) Capital mínimo REAL (bloqueante)
    if balance < MIN_CAPITAL:
        return {
            "ok": False,
            "reason": f"Capital insuficiente ({balance:.2f} < {MIN_CAPITAL})"
        }

    # 2) Tamaño base de posición
    base_position = balance * POSITION_PERCENT

    # Escalado por fuerza
    if strength >= 5:
        position_size = base_position * 1.3
    elif strength >= 3:
        position_size = base_position * 1.15
    else:
        position_size = base_position

    # Clamp FINAL REALISTA
    position_size = max(round(position_size, 4), 0.0)

    if position_size <= 0:
        return {
            "ok": False,
            "reason": "Position size inválido"
        }

    # 3) TP / SL
    tp, sl = calculate_dynamic_tp_sl(strength)

    return {
        "ok": True,
        "tp": tp,
        "sl": sl,
        "position_size": position_size
      }
