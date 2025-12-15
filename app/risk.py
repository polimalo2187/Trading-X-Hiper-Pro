# ============================================================
# RISK MANAGEMENT – Trading X Hyper Pro
# Archivo 5/9 – Gestión de riesgo completa
# ============================================================

import random
from app.config import (
    MIN_CAPITAL,
    POSITION_PERCENT,
    TP_MIN,
    TP_MAX,
    SL_MIN,
    SL_MAX,
)


# ============================================================
# GENERAR TP / SL DINÁMICOS
# ============================================================

def generate_tp_sl():
    tp = round(random.uniform(TP_MIN, TP_MAX), 4)
    sl = round(random.uniform(SL_MIN, SL_MAX), 4)
    return tp, sl


# ============================================================
# VALIDAR SI EL USUARIO PUEDE OPERAR + CALCULAR TAMAÑO
# ============================================================

def validate_trade_conditions(balance: float, user_id: int) -> dict:
    """
    Valida todo lo necesario antes de permitir una operación real:
      ✓ Capital mínimo
      ✓ TP y SL dinámicos
      ✓ Tamaño de posición recomendado
      ✓ (Listo para activar futuros límites de trades simultáneos)
    """

    # 1. CAPITAL MÍNIMO
    if balance < MIN_CAPITAL:
        return {"ok": False, "reason": "Capital insuficiente para operar."}

    # 2. GENERAR TP Y SL
    tp, sl = generate_tp_sl()

    # 3. TAMAÑO DE POSICIÓN (20% del capital por defecto)
    position_size = round(balance * POSITION_PERCENT, 4)

    if position_size <= 0:
        return {"ok": False, "reason": "Capital insuficiente para calcular posición."}

    # 4. RESPUESTA FINAL
    return {
        "ok": True,
        "tp": tp,
        "sl": sl,
        "position_size": position_size
    }
