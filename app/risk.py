# ============================================================
# RISK MANAGEMENT – Trading X Hyper Pro
# Archivo 5/9 – Gestión de riesgo (PROD REAL)
# SL FIJO + TP MIN + TRAILING (RESPONSABLE)
# ============================================================

from app.config import (
    MIN_CAPITAL,
    POSITION_PERCENT,
)

# ============================================================
# PARAMETROS RESPONSABLES (ACORDADOS)
# ============================================================

SL_FIXED = 0.008          # 0.8% (fijo)
TP_MIN_FIXED = 0.012      # 1.2% (mínimo para activar trailing)
TRAILING_BASE = 0.007     # 0.7% base (se ajusta por strength)

# ============================================================
# TRAILING POR FUERZA (SIMPLE Y EFECTIVO)
# ============================================================

def trailing_pct_by_strength(strength: float) -> float:
    """
    Ajusta el trailing según fuerza:
    - débil: 0.5%
    - media: 0.7%
    - fuerte: 1.0%
    """
    try:
        strength = float(strength)
    except Exception:
        strength = 0.2

    # strength en tu sistema suele ir 0.2..8.0
    if strength < 0.35:
        return 0.005
    if strength < 0.70:
        return TRAILING_BASE  # 0.7%
    return 0.010

# ============================================================
# VALIDAR CONDICIONES + TAMAÑO DE POSICIÓN
# ============================================================

def validate_trade_conditions(balance: float, strength: float) -> dict:
    """
    Gestión de riesgo REAL.
    - SL fijo (0.8%)
    - TP mínimo (1.2%) para activar trailing
    - trailing % ajustado por strength
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

    # Escalado por fuerza (mantengo tu lógica original)
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

    # 3) SL fijo + TP mínimo + trailing
    sl = float(SL_FIXED)
    tp_min = float(TP_MIN_FIXED)
    trailing_pct = float(trailing_pct_by_strength(strength))

    return {
        "ok": True,
        # compatibilidad: mantenemos llaves tp/sl
        "tp": round(tp_min, 4),
        "sl": round(sl, 4),

        # llaves explícitas para el engine
        "tp_min": round(tp_min, 4),
        "trailing_pct": round(trailing_pct, 4),

        "position_size": position_size
  }
