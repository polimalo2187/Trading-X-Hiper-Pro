# ============================================================
# risk.py
# Módulo de Gestión de Riesgo – Trading X Hyper Pro
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

# ⚠️ count_open_trades NO existe todavía en database.py
# Por ahora lo desactivamos para que NO rompa el bot.
# from app.database import count_open_trades


import random


# ------------------------------------------------------------
# CALCULAR TAMAÑO DE POSICIÓN
# ------------------------------------------------------------
def calculate_position_size(balance: float) -> float:
    """
    Calcula el tamaño ideal de la posición basándose en el balance disponible.
    Actualmente NO se usa porque trading_engine usa 20%.
    """

    if balance < MIN_CAPITAL:
        return 0

    risk_percent = 0.12  # 12%
    size = balance * risk_percent

    if USE_LEVERAGE:
        size *= BASE_LEVERAGE

    return round(size, 4)


# ------------------------------------------------------------
# VALIDAR SI SE PUEDE ABRIR OTRO TRADE
# ------------------------------------------------------------
def can_open_new_trade(user_id: int) -> bool:
    """
    Por ahora SIEMPRE devuelve True para evitar error,
    hasta que creemos la tabla de trades abiertos.
    """
    return True
    # Cuando activemos trades abiertos:
    # open_trades = count_open_trades(user_id)
    # return open_trades < MAX_CONCURRENT_TRADES


# ------------------------------------------------------------
# GENERAR TP y SL DINÁMICOS
# ------------------------------------------------------------
def generate_tp_sl():
    tp = round(random.uniform(TP_MIN, TP_MAX), 4)
    sl = round(random.uniform(SL_MIN, SL_MAX), 4)
    return tp, sl


# ------------------------------------------------------------
# VALIDACIÓN COMPLETA DE RIESGO
# ------------------------------------------------------------
def validate_trade_conditions(balance: float, user_id: int) -> dict:

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
