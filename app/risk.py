# ============================================================
# RISK MANAGEMENT – Trading X Hyper Pro
# Archivo 5/9 – Gestión de riesgo (PROD REAL)
# SL DINÁMICO + TP MIN + TRAILING (OFICIAL)
# ============================================================

from app.config import (
    MIN_CAPITAL,
    POSITION_PERCENT,
)

# ============================================================
# PARAMETROS OFICIALES (PRODUCCIÓN REAL)
# ============================================================

TP_MIN_FIXED = 0.035      # 3.5% (mínimo para activar trailing)

SL_MIN = 0.025            # 2.5% (mínimo)
SL_MAX = 0.035            # 3.5% (máximo)

TRAILING_MIN = 0.020      # 2.0% (mínimo trailing)
TRAILING_MAX = 0.060      # 6.0% (máximo trailing)


# ============================================================
# SL POR FUERZA (RESPONSABLE, NO RUIDO)
# ============================================================

def sl_pct_by_strength(strength: float) -> float:
    """
    SL dinámico según fuerza:
    - débil  -> 2.5%
    - media  -> 3.0%
    - fuerte -> 3.5%

    Nota: strength en tu sistema suele ir 0.2..8.0
    """
    try:
        strength = float(strength)
    except Exception:
        strength = 0.2

    if strength < 0.35:
        return SL_MIN
    if strength < 0.70:
        return 0.030
    return SL_MAX


# ============================================================
# TRAILING POR FUERZA (CAPTURA TENDENCIAS)
# ============================================================

def trailing_pct_by_strength(strength: float) -> float:
    """
    Trailing dinámico para dejar correr tendencia:
    - débil  -> 2.0%
    - media  -> 3.5%
    - fuerte -> 6.0%

    Esto NO fija TP máximo. El cierre por "pérdida de fuerza"
    y el techo del TP dinámico (ej 25%) lo controla el engine/estrategia.
    """
    try:
        strength = float(strength)
    except Exception:
        strength = 0.2

    if strength < 0.35:
        return TRAILING_MIN
    if strength < 0.70:
        return 0.035
    return TRAILING_MAX


# ============================================================
# VALIDAR CONDICIONES + TAMAÑO DE POSICIÓN
# ============================================================

def validate_trade_conditions(balance: float, strength: float) -> dict:
    """
    Gestión de riesgo REAL (OFICIAL):
    - SL dinámico (2.5% a 3.5%)
    - TP mínimo (3.5%) para activar trailing
    - trailing % dinámico por fuerza

    Mantiene tu lógica original de position sizing.
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

    # 2) Tamaño base de posición (mantengo tu lógica original)
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

    # 3) SL + TP mínimo + trailing
    sl = float(sl_pct_by_strength(strength))
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
