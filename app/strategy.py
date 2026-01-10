# ============================================================
# STRATEGY – Trading X Hyper Pro
# Archivo 4/9 – Señales REALES nivel banco
# MODO GUERRA (CON LOGS VISIBLES)
# ============================================================

from app.hyperliquid_client import make_request
from app.config import ENTRY_SIGNAL_THRESHOLD, VERBOSE_LOGS
from datetime import datetime


# ============================================================
# LOG CONTROLADO
# ============================================================

def log(msg: str):
    if VERBOSE_LOGS:
        print(f"[STRATEGY {datetime.utcnow().isoformat()}] {msg}")


# ============================================================
# CONTEXTO REAL DEL ACTIVO
# ============================================================

def get_symbol_context(symbol: str) -> dict | None:
    r = make_request("/info", {"type": "metaAndAssetCtxs"})
    if not r or not isinstance(r, list) or len(r) < 2:
        log("❌ Respuesta inválida de Hyperliquid")
        return None

    for item in r[1]:
        if item.get("coin", "").upper() == symbol.upper():
            return item

    log(f"❌ No se encontró contexto para {symbol}")
    return None


# ============================================================
# SEÑAL DE ENTRADA – PRODUCCIÓN REAL (DEBUG VISIBLE)
# ============================================================

def get_entry_signal(symbol: str) -> dict:

    ctx = get_symbol_context(symbol)
    if not ctx:
        return {"signal": False}

    try:
        price = float(ctx.get("markPx", 0))
        change_24h = float(ctx.get("priceChange24h", 0))
    except Exception:
        log(f"{symbol} ❌ Error parseando datos")
        return {"signal": False}

    if price <= 0:
        log(f"{symbol} ❌ Precio inválido")
        return {"signal": False}

    # ========================================================
    # FUERZA REAL
    # ========================================================

    strength = abs(change_24h)
    strength = round(min(max(strength, 0.2), 12.0), 4)

    threshold = max(ENTRY_SIGNAL_THRESHOLD * 0.5, 0.25)

    log(
        f"{symbol} | price={price} | "
        f"change24h={round(change_24h,4)} | "
        f"strength={strength} | threshold={threshold}"
    )

    if strength < threshold:
        log(f"{symbol} ❌ NO SIGNAL (fuerza insuficiente)")
        return {
            "signal": False,
            "strength": strength
        }

    direction = "long" if change_24h > 0 else "short"

    log(f"{symbol} ✅ SEÑAL OK → {direction.upper()}")

    return {
        "signal": True,
        "strength": strength,
        "direction": direction,
        "entry_price": price
    }


# ============================================================
# TP / SL – COMPATIBLE CON ENGINE
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
