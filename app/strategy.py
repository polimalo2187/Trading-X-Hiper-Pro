# ============================================================
# STRATEGY – Trading X Hyper Pro
# Archivo 4/9 – Señales REALES nivel banco
# MODO GUERRA RENTABLE (ENTRADA POR CONTEXTO)
# ============================================================

from app.hyperliquid_client import make_request
from app.config import ENTRY_SIGNAL_THRESHOLD


# ============================================================
# OBTENER CONTEXTO DEL ACTIVO (DATOS REALES)
# ============================================================

def get_symbol_context(symbol: str) -> dict | None:
    """
    Obtiene contexto real del activo desde Hyperliquid.
    Se usa para señales basadas en momentum REAL,
    no en ticks inexistentes.
    """

    r = make_request("/info", {"type": "metaAndAssetCtxs"})
    if not r or not isinstance(r, list) or len(r) < 2:
        return None

    asset_ctxs = r[1]

    for item in asset_ctxs:
        if item.get("coin", "").upper() == symbol.upper():
            return item

    return None


# ============================================================
# SEÑAL DE ENTRADA – PRODUCCIÓN REAL (FIX DEFINITIVO)
# ============================================================

def get_entry_signal(symbol: str) -> dict:
    """
    Señal basada en CONTEXTO REAL:
    - priceChange24h
    - momentum institucional
    - dirección clara
    """

    ctx = get_symbol_context(symbol)
    if not ctx:
        return {"signal": False}

    try:
        change_24h = float(ctx.get("priceChange24h", 0))
        price = float(ctx.get("markPx", 0))
    except Exception:
        return {"signal": False}

    if price <= 0:
        return {"signal": False}

    # ========================================================
    # FUERZA REAL (NO DEPENDE DE TICKS)
    # ========================================================

    strength = abs(change_24h)

    # Clamp REALISTA
    strength = round(min(max(strength, 0.2), 12.0), 4)

    # Threshold efectivo (desbloquea trading)
    effective_threshold = max(
        ENTRY_SIGNAL_THRESHOLD * 0.5,
        0.25
    )

    if strength < effective_threshold:
        return {
            "signal": False,
            "strength": strength
        }

    direction = "long" if change_24h > 0 else "short"

    return {
        "signal": True,
        "strength": strength,
        "direction": direction,
        "entry_price": price
    }


# ============================================================
# TP / SL – COMPATIBLE CON ENGINE
# (SE MANTIENE PARA NO ROMPER IMPORTS)
# ============================================================

def calculate_targets(
    entry_price: float,
    tp_percent: float,
    sl_percent: float,
    direction: str
) -> dict:

    tp_percent = min(max(tp_percent, 0.0015), 0.045)
    sl_percent = min(max(sl_percent, 0.0009), 0.020)

    if direction == "long":
        tp_price = entry_price * (1 + tp_percent)
        sl_price = entry_price * (1 - sl_percent)
    else:
        tp_price = entry_price * (1 - tp_percent)
        sl_price = entry_price * (1 + sl_percent)

    return {
        "tp": round(tp_price, 6),
        "sl": round(sl_price, 6)
  }
