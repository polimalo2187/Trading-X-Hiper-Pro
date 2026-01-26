# ============================================================
# PARAMETROS OFICIALES (PRODUCCIÓN REAL)
# ============================================================

# ✅ TP mínimo para activar trailing (coherente con engine: +1.0%)
TP_MIN_FIXED = 0.010      # 1.0%

# ============================================================
# ✅ SL DINÁMICO POR ATR (COHERENTE CON ENGINE ATR SL)
# ============================================================
# El engine calcula el SL con ATR% * MULT y luego clampa a [MIN, MAX]
SL_ATR_MULT = 1.8         # multiplicador ATR (ej: 1.8)
SL_MIN_PCT = 0.012        # 1.2% mínimo
SL_MAX_PCT = 0.025        # 2.5% máximo

def sl_pct_from_atr(atr_value: float, entry_price: float) -> float:
    """
    SL dinámico basado en ATR (en % de precio):
      raw = (ATR / entry_price) * SL_ATR_MULT
      sl  = clamp(raw, SL_MIN_PCT, SL_MAX_PCT)
    """
    try:
        atr_value = float(atr_value)
        entry_price = float(entry_price)
    except Exception:
        return float(SL_MIN_PCT)

    if entry_price <= 0 or atr_value <= 0:
        return float(SL_MIN_PCT)

    raw = (atr_value / entry_price) * float(SL_ATR_MULT)

    # clamp
    if raw < SL_MIN_PCT:
        return float(SL_MIN_PCT)
    if raw > SL_MAX_PCT:
        return float(SL_MAX_PCT)
    return float(raw)

# ============================================================
# ✅ TRAILING (RISK) – SOLO COMPATIBILIDAD
# ============================================================
# Nota: el cierre por trailing lo controla el ENGINE (TP dinámico sin tope).
# Este valor se mantiene sólo por compatibilidad con validate_trade_conditions
# (si algún módulo lo espera), pero no impone techos ni TP máximo.

TRAILING_PCT_DEFAULT = 0.035  # 3.5% (valor neutro/compatible)

def trailing_pct_by_strength(strength: float) -> float:
    """
    Compatibilidad:
    No fija TP máximo. El engine manda el trailing real.
    """
    try:
        _ = float(strength)
    except Exception:
        pass
    return float(TRAILING_PCT_DEFAULT)
