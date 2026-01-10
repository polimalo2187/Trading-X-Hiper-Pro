# ============================================================
# MARKET SCANNER – Trading X Hyper Pro
# Archivo 6/9 – PRODUCCIÓN REAL Hyperliquid (MODO GUERRA)
# ============================================================

from app.hyperliquid_client import make_request, get_all_symbols
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

    r = make_request("/info", {"type": "metaAndAssetCtxs"})

    if not r or not isinstance(r, list) or len(r) < 2:
        safe_log("❌ Respuesta inválida de Hyperliquid")
        return {}

    meta, asset_ctxs = r
    universe = meta.get("universe", [])

    if len(universe) != len(asset_ctxs):
        return {}

    # 🔥 SÍMBOLOS REALES TRADEABLES (ALLMIDS)
    tradable_symbols = set(get_all_symbols())
    if not tradable_symbols:
        safe_log("❌ No se pudieron cargar símbolos tradeables")
        return {}

    stats_map = {}

    for i, ctx in enumerate(asset_ctxs):
        symbol = universe[i].get("name")
        if not symbol:
            continue

        symbol = symbol.upper()

        # ❌ DESCARTAR SI NO ES TRADEABLE REAL
        if symbol not in tradable_symbols:
            continue

        try:
            price = float(ctx.get("markPx", 0))
            volume = float(ctx.get("dayNtlVlm", 0))
            oi = float(ctx.get("openInterest", 0))
        except Exception:
            continue

        # 🔒 FILTROS REALES DE PRODUCCIÓN
        if price < 0.01:
            continue
        if volume < 200_000:
            continue
        if oi < 500_000:
            continue

        stats_map[symbol] = ctx

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

    change_24h = (
        ((price - prev_price) / prev_price) * 100
        if prev_price > 0 else 0
    )

    impact = info.get("impactPxs") or []
    if len(impact) == 2:
        bid, ask = map(float, impact)
        spread = max(ask - bid, 0)
    else:
        spread = 0

    vol_score = min(volume / 1_000_000, 1.0)
    oi_score = min(oi / 10_000_000, 1.0)
    trend_score = max(min((change_24h / 4) + 0.5, 1.0), 0.0)
    spread_score = 1 - min(spread / (price * 0.0025), 1.0)

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
# 3. SELECCIONAR MEJOR ACTIVO (SIN SÍMBOLOS ROTOS)
# ============================================================

def get_best_symbol(exclude_symbols: set | None = None):

    exclude_symbols = exclude_symbols or set()

    stats = get_all_24h_stats()
    if not stats:
        safe_log("❌ Scanner sin mercados válidos")
        return None

    ordered = sorted(
        stats.keys(),
        key=lambda s: (
            stats[s]["dayNtlVlm"] +
            stats[s]["openInterest"]
        ),
        reverse=True
    )

    results = []

    for symbol in ordered:
        if symbol in exclude_symbols:
            continue

        parsed = analyze_symbol(symbol, stats)
        if parsed:
            results.append(parsed)

        if len(results) >= SCANNER_DEPTH:
            break

    if not results:
        safe_log("❌ Scanner sin resultados tras exclusiones")
        return None

    best = max(results, key=lambda x: x["score"])

    safe_log(
        f"🔥 SCANNER | {best['symbol']} | "
        f"Score={best['score']} | "
        f"Vol={best['volume_usd']} | "
        f"OI={best['open_interest_usd']}"
    )

    return best
