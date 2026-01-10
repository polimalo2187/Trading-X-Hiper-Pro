# ============================================================
# RISK MANAGEMENT – Trading X Hyper Pro
# Archivo 5/9 – Gestión de riesgo (MODO GUERRA)
# ============================================================

from app.config import (
    MIN_CAPITAL,
    POSITION_PERCENT,
)

# ============================================================
# TP / SL DINÁMICOS – ESCALADOS PARA GANANCIA REAL
# ============================================================

def calculate_dynamic_tp_sl(strength: float):
    """
    Cálculo agresivo profesional basado en fuerza REAL.
    Diseñado para:
        - 4–6% diario (mercado regular)
        - 6–10% diario (mercado bueno)
        - 10–16%+ diario (mercado fuerte)
    """

    # Clamp de seguridad
    strength = max(min(strength, 8.0), 0.1)

    # 🔥 TP ESCALADO (AQUÍ ESTÁ EL DINERO)
    if strength < 1.5:
        tp = 0.006      # 0.6%
        sl = 0.004      # 0.4%
    elif strength < 3:
        tp = 0.012      # 1.2%
        sl = 0.006      # 0.6%
    elif strength < 5:
        tp = 0.020      # 2.0%
        sl = 0.009      # 0.9%
    else:
        tp = 0.035      # 3.5%
        sl = 0.012      # 1.2%

    return round(tp, 4), round(sl, 4)


# ============================================================
# VALIDAR CONDICIONES + TAMAÑO DE POSICIÓN
# ============================================================

def validate_trade_conditions(balance: float, strength: float) -> dict:
    """
    Gestión de riesgo agresiva pero controlada.
    Capitales pequeños friendly.
    """

    # 1) Capital mínimo
    if balance < MIN_CAPITAL:
        return {"ok": False, "reason": "Capital insuficiente."}

    # 2) POSITION SIZE BASE
    base_position = balance * POSITION_PERCENT

    # 🔥 ESCALADO POR FUERZA
    if strength >= 5:
        position_size = base_position * 1.4
    elif strength >= 3:
        position_size = base_position * 1.2
    else:
        position_size = base_position

    position_size = round(position_size, 4)

    if position_size <= 0:
        return {"ok": False, "reason": "Posición inválida."}

    # 3) TP / SL DINÁMICOS
    tp, sl = calculate_dynamic_tp_sl(strength)

    return {
        "ok": True,
        "tp": tp,
        "sl": sl,
        "position_size": position_size
    }
