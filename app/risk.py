# ============================================================
# RISK MANAGEMENT – Trading X Hyper Pro
# Archivo 5/9 – Gestión de riesgo completa
# ============================================================

import random
from app.config import (
    MIN_CAPITAL,
    TP_MIN,
    TP_MAX,
    SL_MIN,
    SL_MAX,
)


# ============================================================
# VALIDAR SI EL USUARIO PUEDE OPERAR
# (capital mínimo + permisos)
# ============================================================

def validate_trade_conditions(balance: float, user_id: int) -> dict:
    """
    Valida el riesgo de la operación:
    - Capital mínimo
    - Genera TP y SL dinámicos
    - (Más adelante) Limitar trades simultáneos
    """

    # CAPITAL MÍNIMO GLOBAL
    if balance < MIN_CAPITAL:
        return {"ok": False, "reason": "Capital insuficiente para operar."}

    # Lógica de límites simultáneos se activará después:
    # if not can_open_new_trade(user_id):
    #     return {"ok": False, "reason": "Límite de operaciones simultáneas alcanzado."}

    # TP / SL generados aleatoriamente dentro de rango
    tp = round(random.uniform(TP_MIN, TP_MAX), 4)
    sl = round(random.uniform(SL_MIN, SL_MAX), 4)

    return {
        "ok": True,
        "tp": tp,
        "sl": sl
    }
