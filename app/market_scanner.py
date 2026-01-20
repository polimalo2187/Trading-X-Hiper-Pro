# ============================================================
# MARKET SCANNER – Trading X Hyper Pro
# PRODUCCIÓN REAL Hyperliquid
# FIX DEFINITIVO BANK-GRADE
# ============================================================

from app.hyperliquid_client import make_request
from app.config import SCANNER_DEPTH, VERBOSE_LOGS, PRODUCTION_MODE


# ============================================================
# LOG CONTROLADO
# ============================================================

def safe_log(*args):
    if VERBOSE_LOGS and not PRODUCTION_MODE:
        print(*args)


# ============================================================
# 1. OBTENER CONTEXTO REAL DE MERCADO (HYPERLIQUID)
# ============================================================

def get_all_24h_stats():
    """
    Devuelve un dict:
    {
        "BTC-PERP": asset_ctx,
        "ETH-PERP": asset_ctx,
        ...
    }

    FIX CRÍTICO REAL:
    - Usar assetCtxs (estable en Hyperliquid)
    - NO usar metaAndAssetCtxs (inestable)
    """

    r = make_request("/info", {"type": "assetCtxs"})
    if not r or not isinstance(r, list):
        safe_log("❌ Respuesta inválida assetCtxs")
        return {}

    stats_map = {}

    for asset in r:
        symbol = asset.get("coin")
        if not symbol:
            continue

        try:
            price = float(asset.get("markPx", 0))
            volume = float(asset.get("dayNtlVlm", 0))
        except Exception:
            continue

        # Filtros mínimos reales
        if price <= 0 or volume <= 0:
            continue

        # Hyperliquid usa formato PERP explícito
        stats_map[f"{symbol}-PERP"] = asset

    if not stats_map:
        safe_log("❌ Scanner: ningún mercado válido")

    return stats_map


# ============================================================
# 2. ANALIZAR UN SÍMBOLO
# ============================================================

def analyze_symbol(symbol: str, stats: dict):
    info = stats.get(symbol)
    if not info:
        return None

    try:
        price = float(info.get("markPx", 0))
        prev_price = float(info.get("prevDayPx", price))
        volume = float(info.get("dayNtlVlm", 0))
        oi = float(info.get("openInterest", 0) or 0)
    except Exception:
        return None

    if price <= 0:
        return None

    change_24h = ((price - prev_price) / prev_price * 100) if prev_price > 0 else 0

    vol_score = min(volume / 1_000_000, 1.0)
    oi_score = min(oi / 10_000_000, 1.0) if oi > 0 else 0.2
    trend_score = max(min((change_24h / 5) + 0.5, 1.0), 0.0)

    score = vol_score * 0.45 + oi_score * 0.35 + trend_score * 0.20

    return {
        "symbol": symbol,
        "price": round(price, 6),
        "volume_notional": round(volume, 2),
        "open_interest": round(oi, 2),
        "change_24h": round(change_24h, 3),
        "score": round(score, 4),
    }


# ============================================================
# 3. SELECCIONAR EL MEJOR SÍMBOLO
# ============================================================

def get_best_symbol(exclude_symbols: set | None = None):
    exclude_symbols = exclude_symbols or set()

    stats = get_all_24h_stats()
    if not stats:
        return None

    results = []

    for symbol in stats.keys():
        if symbol in exclude_symbols:
            continue

        parsed = analyze_symbol(symbol, stats)
        if parsed:
            results.append(parsed)

    if not results:
        return None

    results.sort(key=lambda x: x["score"], reverse=True)

    if SCANNER_DEPTH and len(results) > SCANNER_DEPTH:
        results = results[:SCANNER_DEPTH]

    return results[0]
