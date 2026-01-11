# ============================================================
# MARKET SCANNER – Trading X Hyper Pro
# PRODUCCIÓN REAL Hyperliquid (FIX DEFINITIVO)
# ============================================================

from app.hyperliquid_client import make_request
from app.config import SCANNER_DEPTH, VERBOSE_LOGS, PRODUCTION_MODE


def safe_log(*args):
    if VERBOSE_LOGS and not PRODUCTION_MODE:
        print(*args)


# ============================================================
# 1. OBTENER CONTEXTO REAL DE ACTIVOS (ROBUSTO)
# ============================================================

def get_all_24h_stats():

    r = make_request("/info", {"type": "metaAndAssetCtxs"})
    if not r or not isinstance(r, list) or len(r) < 2:
        safe_log("❌ Respuesta inválida metaAndAssetCtxs")
        return {}

    meta, asset_ctxs = r
    universe = meta.get("universe", [])

    stats_map = {}

    for asset in asset_ctxs:
        symbol = asset.get("coin")
        if not symbol:
            continue

        try:
            price = float(asset.get("markPx", 0))
            volume = float(asset.get("dayNtlVlm", 0))
            oi = float(asset.get("openInterest", 0))
        except Exception:
            continue

        # Filtros REALISTAS
        if price <= 0:
            continue
        if volume < 50_000:
            continue
        if oi < 100_000:
            continue

        stats_map[f"{symbol}-PERP"] = asset

    return stats_map


# ============================================================
# 2. ANALIZAR ACTIVO
# ============================================================

def analyze_symbol(symbol: str, stats: dict):

    info = stats.get(symbol)
    if not info:
        return None

    try:
        price = float(info["markPx"])
        prev_price = float(info.get("prevDayPx", price))
        volume = float(info["dayNtlVlm"])
        oi = float(info["openInterest"])
    except Exception:
        return None

    change_24h = ((price - prev_price) / prev_price * 100) if prev_price > 0 else 0

    vol_score = min(volume / 1_000_000, 1.0)
    oi_score = min(oi / 10_000_000, 1.0)
    trend_score = max(min((change_24h / 5) + 0.5, 1.0), 0.0)

    score = (
        vol_score * 0.45 +
        oi_score * 0.35 +
        trend_score * 0.20
    )

    return {
        "symbol": symbol,
        "price": round(price, 6),
        "volume_usd": round(volume, 2),
        "open_interest_usd": round(oi, 2),
        "change_24h": round(change_24h, 3),
        "score": round(score, 4),
    }


# ============================================================
# 3. SELECCIONAR MEJOR ACTIVO
# ============================================================

def get_best_symbol(exclude_symbols: set | None = None):

    exclude_symbols = exclude_symbols or set()
    stats = get_all_24h_stats()

    if not stats:
        safe_log("❌ Scanner sin mercados válidos")
        return None

    results = []

    for symbol in stats.keys():
        if symbol in exclude_symbols:
            continue

        parsed = analyze_symbol(symbol, stats)
        if parsed:
            results.append(parsed)

    if not results:
        safe_log("❌ Scanner sin resultados")
        return None

    results.sort(key=lambda x: x["score"], reverse=True)

    return results[0]
