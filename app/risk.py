# ============================================================
# RISK MANAGEMENT – Trading X Hyper Pro
# Archivo 5/9 – Gestión de riesgo (PROD REAL)
# SL DINÁMICO + TP MIN + TRAILING (OFICIAL)
# POSICIÓN = 100% DEL CAPITAL (SEGÚN config.py)
# ============================================================

from app.config import (
    MIN_CAPITAL,
    POSITION_PERCENT,
)

# ============================================================
# PARAMETROS OFICIALES (PRODUCCIÓN REAL)
# ============================================================

# ✅ TP mínimo para activar trailing (coherente con engine: +1.0%)
TP_MIN_FIXED = 0.010      # 1.0%

# ✅ SL por fuerza (coherente con lo acordado)
SL_MIN = 0.010            # 1.0% (normal)
SL_MAX = 0.015            # 1.5% (fuerte)

TRAILING_MIN = 0.020      # 2.0% (mínimo trailing)
TRAILING_MAX = 0.060      # 6.0% (máximo trailing)


# ============================================================
# SL POR FUERZA (RESPONSABLE, NO RUIDO)
# ============================================================

def sl_pct_by_strength(strength: float) -> float:
    """
    SL dinámico según fuerza:
    - normal -> 1.0%
    - fuerte -> 1.5%

    Nota: strength en tu sistema suele ir 0.2..8.0
    """
    try:
        strength = float(strength)
    except Exception:
        strength = 0.2

    # Se mantiene el mismo umbral que ya usabas como "fuerte"
    if strength < 0.70:
        return SL_MIN
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
    - SL dinámico por fuerza (1.0% a 1.5%)
    - TP mínimo (1.0%) para activar trailing
    - trailing % dinámico por fuerza

    ✅ POSICIÓN = balance * POSITION_PERCENT
       (Si POSITION_PERCENT = 1.0 => usa 100% del capital)
    ✅ SIN boosts por fuerza (para evitar intentar >100% del balance)
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

    # 2) Tamaño de posición = % del balance (100% si POSITION_PERCENT=1.0)
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
