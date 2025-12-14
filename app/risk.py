# ============================================================
# risk.py
# Módulo de Gestión de Riesgo – Trading X Hiper Pro
# Control de lotes, límites, pérdidas y protección avanzada
# ============================================================

from app.config import (
    MIN_CAPITAL,
    MAX_CONCURRENT_TRADES,
    BASE_LEVERAGE,
    USE_LEVERAGE,
    TP_MIN,
    TP_MAX,
    SL_MIN,
    SL_MAX,
)
from app.database import count_open_trades


# ------------------------------------------------------------
# CALCULAR TAMAÑO DE POSICIÓN
# ------------------------------------------------------------
def calculate_position_size(balance: float) -> float:
    """
    Calcula el tamaño ideal de la posición basándose en el balance disponible
    y la gestión recomendada.
    """

    if balance < MIN_CAPITAL:
        return 0  # No opera si no tiene capital mínimo

    # porcentaje básico del balance para la operación
    risk_percent = 0.12  # 12% del balance aprox
    size = balance * risk_percent

    if USE_LEVERAGE:
        size *= BASE_LEVERAGE

    return round(size, 4)


# ------------------------------------------------------------
# VALIDAR SI EL BOT PUEDE ABRIR OTRO TRADE
# ------------------------------------------------------------
def can_open_new_trade(user_id: int) -> bool:
    open_trades = count_open_trades(user_id)

    if open_trades >= MAX_CONCURRENT_TRADES:
        return False

    return True


# ------------------------------------------------------------
# GENERAR TAKE PROFIT Y STOP LOSS ALEATORIOS
# DENTRO DE RANGO DEFINIDO EN CONFIG
# ------------------------------------------------------------
import random

def generate_tp_sl():
    """
    Retorna un TP y SL aleatorio dentro de los rangos definidos en config.py
    para evitar patrones predecibles.
    """

    tp = round(random.uniform(TP_MIN, TP_MAX), 4)
    sl = round(random.uniform(SL_MIN, SL_MAX), 4)

    return tp, sl


# ------------------------------------------------------------
# VALIDAR QUE EL TRADE ES SEGURO
# ------------------------------------------------------------
def validate_trade_conditions(balance: float, user_id: int) -> dict:
    """
    Verifica todas las condiciones antes de abrir una operación.
    Retorna un dict con estatus y razones.
    """

    if balance < MIN_CAPITAL:
        return {"ok": False, "reason": "Balance insuficiente para operar."}

    if not can_open_new_trade(user_id):
        return {"ok": False, "reason": "Límite de trades simultáneos alcanzado."}

    size = calculate_position_size(balance)
    tp, sl = generate_tp_sl()

    return {
        "ok": True,
        "size": size,
        "tp": tp,
        "sl": sl,
        "leverage": BASE_LEVERAGE if USE_LEVERAGE else 1
    }
