# ============================================================
# RISK MANAGEMENT – Trading X Hyper Pro
# Archivo 5/9 – Gestión de riesgo (PROD REAL)
# SL POR FUERZA + TP MIN (ACTIVA TRAIL EN ENGINE) + trailing_pct (compat)
# POSICIÓN = 100% DEL CAPITAL (SEGÚN config.py)
# ============================================================

from app.config import (
    MIN_CAPITAL,
    POSITION_PERCENT,
)

# ============================================================
# PARÁMETROS OFICIALES (PRODUCCIÓN REAL)
# ============================================================

# ✅ TP mínimo para activar trailing (coherente con engine: +1.0% ROE)
TP_MIN_FIXED = 0.010      # 1.0%

# ✅ SL por fuerza (coherente con lo acordado: normal 1.0% / fuerte 1.5%)
SL_MIN = 0.010            # 1.0% (normal)
SL_MAX = 0.015            # 1.5% (fuerte)

# ✅ trailing_pct SOLO por compatibilidad (si el engine lo lee).
# IMPORTANTE: aquí NO existe ningún "máximo" ni valores tipo 0.060.
TRAILING_WEAK = 0.020     # 2.0%
TRAILING_MED  = 0.035     # 3.5%
TRAILING_STR  = 0.035     # 3.5% (fuerte también, SIN 6%)


# ============================================================
# SL POR FUERZA
# ============================================================

def sl_pct_by_strength(strength: float) -> float:
    """
    SL dinámico según fuerza:
    - normal -> 1.0%
    - fuerte -> 1.5%
    """
    try:
        strength = float(strength)
    except Exception:
        strength = 0.2

    # Se mantiene el umbral "fuerte" que ya usabas
    if strength < 0.70:
        return SL_MIN
    return SL_MAX


# ============================================================
# trailing_pct POR FUERZA (SOLO COMPATIBILIDAD)
# ============================================================

def trailing_pct_by_strength(strength: float) -> float:
    """
    trailing_pct se expone para compatibilidad del engine.
    NO hay máximos, NO hay 0.060, y NO hay TP aquí.
    """
    try:
        strength = float(strength)
    except Exception:
        strength = 0.2

    if strength < 0.35:
        return TRAILING_WEAK
    if strength < 0.70:
        return TRAILING_MED
    return TRAILING_STR


# ============================================================
# VALIDAR CONDICIONES + TAMAÑO DE POSICIÓN
# ============================================================

def validate_trade_conditions(balance: float, strength: float) -> dict:
    """
    Gestión de riesgo REAL:
    - SL por fuerza (1.0% a 1.5%)
    - TP mínimo (1.0%) para habilitar trailing en el engine
    - trailing_pct por fuerza (compatibilidad)
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

    # 2) Tamaño de posición = % del balance
    base_position = balance * float(POSITION_PERCENT or 0.0)

    # ✅ FIX: no permitir nunca exceder el balance real
    position_size = min(base_position, balance)

    # Clamp FINAL REALISTA
    position_size = max(round(position_size, 4), 0.0)

    if position_size <= 0:
        return {
            "ok": False,
            "reason": "Position size inválido"
        }

    # 3) SL + TP mínimo + trailing_pct (compat)
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
