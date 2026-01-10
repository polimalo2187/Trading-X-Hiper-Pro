# ============================================================
# MARKET SCANNER – Trading X Hyper Pro
# Archivo 6/9 – PRODUCCIÓN REAL Hyperliquid (MODO GUERRA)
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
# 1. OBTENER CONTEXTO REAL DE ACTIVOS (HYPERLIQUID)
# ============================================================

def get_all_24h_stats():
    """
    Devuelve un mapa REAL de activos de Hyperliquid.
    Usa:
      - meta.universe -> símbolos
      - assetCtxs     -> métricas reales
    """

    r = make_request("/info", {"type": "metaAndAssetCtxs"})

    if not r or not isinstance(r, list) or len(r) < 2:
        safe_log("❌ Respuesta inválida de Hyperliquid (metaAndAssetCtxs)")
        return {}

    meta = r[0]
    asset_ctxs = r[1]

    universe = meta.get("universe", [])
    if not universe or len(universe) != len(asset_ctxs):
        safe_log("❌ Universe y assetCtxs no coinciden")
        return {}

    stats_map = {}

    for idx, ctx in enumerate(asset_ctxs):
        symbol = universe[idx].get("name")
        if not symbol:
            continue

        try:
            mark_px = float(ctx.get("markPx", 0))
        except Exception:
            continue

        if mark_px <= 0:
            continue

        stats_map[symbol.upper()] = ctx

    return stats_map


# ============================================================
# 2. ANALIZAR ACTIVO (SCORE REAL – MODO GUERRA)
# ============================================================

def analyze_symbol(symbol: str, stats: dict) -> dict | None:

    info = stats.get(symbol)
    if not info:
        return None

    try:
        price = float(info.get("markPx", 0))
        prev_price = float(info.get("prevDayPx", price))
        volume = float(info.get("dayNtlVlm", 0))
        oi = float(info.get("openInterest", 0))
    except Exception:
        return None

    if price <= 0 or volume <= 0 or oi <= 0:
        return None

    # Cambio porcentual 24h REAL
    change_24h = (
        ((price - prev_price) / prev_price) * 100
        if prev_price > 0 else 0
    )

    # Spread usando impact prices reales
    impact = info.get("impactPxs") or []
    if len(impact) == 2:
        bid = float(impact[0])
        ask = float(impact[1])
        spread = max(ask - bid, 0)
    else:
        spread = 0

    # ========================================================
    # SCORE GUERRA REAL (SIN INVENTOS)
    # ========================================================

    vol_score = min(volume / 500_000, 1.0)
    oi_score = min(oi / 5_000_000, 1.0)
    trend_score = max(min((change_24h / 5) + 0.5, 1.0), 0.0)
    spread_score = 1 - min(spread / (price * 0.003), 1.0)

    score = (
        vol_score * 0.40 +
        oi_score * 0.30 +
        trend_score * 0.20 +
        spread_score * 0.10
    )

    return {
        "symbol": symbol,
        "price": round(price, 6),
        "volume_usd": round(volume, 2),
        "open_interest_usd": round(oi, 2),
        "change_24h": round(change_24h, 4),
        "spread": round(spread, 8),
        "score": round(score, 4),
    }


# ============================================================
# 3. SELECCIONAR EL MEJOR ACTIVO DEL MERCADO
# ============================================================

def get_best_symbol() -> dict | None:

    stats_map = get_all_24h_stats()
    if not stats_map:
        safe_log("❌ No hay estadísticas válidas")
        return None

    ordered = sorted(
        stats_map.keys(),
        key=lambda s: (
            stats_map[s].get("dayNtlVlm", 0) +
            stats_map[s].get("openInterest", 0)
        ),
        reverse=True
    )

    top = ordered[:SCANNER_DEPTH]
    results = []

    for symbol in top:
        parsed = analyze_symbol(symbol, stats_map)
        if parsed:
            results.append(parsed)

    if not results:
        safe_log("❌ Scanner sin activos analizables")
        return None

    best = max(results, key=lambda x: x["score"])

    safe_log(
        f"🔥 SCANNER REAL | {best['symbol']} | "
        f"Score={best['score']} | "
        f"Vol={best['volume_usd']} | "
        f"OI={best['open_interest_usd']}"
    )

    return best
