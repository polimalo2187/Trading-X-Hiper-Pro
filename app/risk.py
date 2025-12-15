# ============================================================
# risk.py
# Gestión de Riesgo – Trading X Hyper Pro
# Compatible 100% con trading REAL en HyperLiquid
# ============================================================

import random
from app.config import (
    MIN_CAPITAL,
    TP_MIN, TP_MAX,
    SL_MIN, SL_MAX,
    USE_LEVERAGE,
    BASE_LEVERAGE,
)

# ============================================================
# NOTA IMPORTANTE
# ============================================================
# Actualmente NO se manejan "trades abiertos" porque
# todas las operaciones son entrada → salida inmediata.
#
# Cuando activemos posiciones persistentes, agregaremos:
# - tabla open_positions
# - función count_open_trades()
# ============================================================


# ------------------------------------------------------------
# CÁLCULO DE TAMAÑO DE POSICIÓN (RESERVADO PARA FUTURO)
# ------------------------------------------------------------
def calculate_position_size(balance: float) -> float:
    """
    Cálculo de tamaño de posición (actualmente no usado).
    Se deja por compatibilidad futura.
    """
    if balance < MIN_CAPITAL:
        return 0

    risk_percent = 0.12  # 12%
    size = balance * risk_percent

    if USE_LEVERAGE:
        size *= BASE_LEVERAGE

    return round(size, 4)


# ------------------------------------------------------------
# VALIDAR SI SE PUEDE ABRIR UNA OPERACIÓN
# ------------------------------------------------------------
def can_open_new_trade(user_id: int) -> bool:
    """
    Siempre TRUE por ahora.
    No existe límite porque cada trade se abre y se cierra
    instantáneamente en trading_engine.py.
    """
    return True


# ------------------------------------------------------------
# GENERAR TP y SL DINÁMICOS
# ------------------------------------------------------------
def generate_tp_sl():
    tp = round(random.uniform(TP_MIN, TP_MAX), 4)
    sl = round(random.uniform(SL_MIN, SL_MAX), 4)
    return tp, sl


# ------------------------------------------------------------
# VALIDACIÓN DE RIESGO COMPLETA
# ------------------------------------------------------------
def validate_trade_conditions(balance: float, user_id: int) -> dict:
    """
    Valida si el usuario puede operar. NO abre posiciones reales.
    Solo aprueba o deniega antes del motor real.
    """

    # 1. Capital mínimo
    if balance < MIN_CAPITAL:
        return {"ok": False, "reason": "Balance insuficiente para operar."}

    # 2. Límite de trades simultáneos (por ahora ilimitado)
    if not can_open_new_trade(user_id):
        return {"ok": False, "reason": "Límite de trades simultáneos alcanzado."}

    # 3. Generar targets dinámicos
    tp, sl = generate_tp_sl()

    response = {
        "ok": True,
        "tp": tp,
        "sl": sl,
        "leverage": BASE_LEVERAGE if USE_LEVERAGE else 1,

        # Este parámetro NO es usado por el motor real,
        # pero se deja listo para la futura expansión.
        "recommended_size": calculate_position_size(balance)
    }

    return response
