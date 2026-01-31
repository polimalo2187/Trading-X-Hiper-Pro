# ============================================================
# RISK MANAGEMENT – Trading X Hyper Pro
# app/risk.py
#
# OPCIÓN A – ESTABLE / COMPATIBLE
# ------------------------------------------------------------
# - NO define TP máximo
# - NO define trailing
# - NO usa ROE
# - SOLO valida capital y tamaño de posición
# - EXPONE validate_trade_conditions() (CRÍTICO)
# ============================================================

from app.config import (
    POSITION_PERCENT,
)
# ============================================================
# VALIDACIÓN DE RIESGO BÁSICA (ENGINE DEPENDE DE ESTO)
# ============================================================

def validate_trade_conditions(balance: float, strength: float) -> dict:
    """
    Función mínima y segura.
    El engine SOLO necesita que exista y devuelva:
      - ok
      - position_size

    Toda la lógica de SL / TP / trailing
    se maneja en strategy.py y trading_engine.py
    """

    # Sanitizar inputs
    try:
        balance = float(balance)
    except Exception:
        balance = 0.0

    try:
        strength = float(strength)
    except Exception:
        strength = 0.0
    # --------------------------------------------------------
    # 1) Capital mínimo (DESHABILITADO)
    # --------------------------------------------------------
    # Se permite operar con cualquier capital configurado por el usuario.

    # --------------------------------------------------------
    # 2) Tamaño de posición
    # --------------------------------------------------------
    try:
        pct = float(POSITION_PERCENT)
    except Exception:
        pct = 0.0

    position_size = balance * pct

    # Nunca permitir > balance real
    position_size = min(position_size, balance)

    # Clamp final
    position_size = round(position_size, 6)

    if position_size <= 0:
        return {
            "ok": False,
            "reason": "Position size inválido"
        }

    # --------------------------------------------------------
    # OK
    # --------------------------------------------------------
    return {
        "ok": True,
        "position_size": position_size
  }
