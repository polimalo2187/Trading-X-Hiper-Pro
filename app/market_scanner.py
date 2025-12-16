# ============================================================
# MARKET SCANNER – Trading X Hiper Pro
# Archivo 6/9 – Versión banca / producción real
# ============================================================

from app.hyperliquid_client import make_request
from app.config import SCANNER_DEPTH, VERBOSE_LOGS, PRODUCTION_MODE


def safe_log(*args):
    if VERBOSE_LOGS and not PRODUCTION_MODE:
        print(*args)


# ============================================================
# 1. Obtener estadísticas 24h reales
# ============================================================

def get_all_24h_stats():
    """Devuelve mapa limpio de stats reales."""

    r = make_request("/info", {"type": "all24hStats"})

    if not r or "all24hStats" not in r:
        safe_log("❌ No se pudo obtener estadísticas 24h.")
        return {}

    stats_map = {}

    for item in r["all24hStats"]:

        symbol = item.get("coin") or item.get("symbol")
        if not symbol:
            continue

        # Formato final de par
        symbol = symbol.upper()

        # Filtrar únicamente pares válidos
        if "USDC" not in symbol:
            continue

        stats_map[symbol] = item

    return stats_map


# ============================================================
# 2. Analizar un par (score profesional)
# ============================================================

def analyze_symbol(symbol: str, stats: dict) -> dict | None:

    info = stats.get(symbol)
    if not info:
        return None

    # Precios reales
    price = (
        info.get("markPx")
        or info.get("midPx")
        or info.get("lastPx")
        or info.get("last")
    )

    try:
        price = float(price)
        if price <= 0:
            return None
    except:
        return None

    volume = float(info.get("volumeUsd", 0) or 0)
    oi = float(info.get("openInterestUsd", 0) or 0)
    change = float(info.get("priceChange24h", 0) or 0)

    # Spread real → usar markPx vs midPx como fallback
    bid = float(info.get("bidPx", price))
    ask = float(info.get("askPx", price))
    spread = max(ask - bid, 0)

    # ===================
    # SCORE PROFESIONAL
    # ===================

    vol_score = min(volume / 3_000_000, 1.0)
    oi_score = min(oi / 12_000_000, 1.0)

    trend_score = max(min((change / 6) + 0.5, 1.0), 0.0)

    spread_score = 1 - min(spread / (price * 0.0015), 1.0)

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
        "change_24h": round(change, 4),
        "spread": round(spread, 8),
        "score": round(score, 4),
    }


# ============================================================
# 3. Seleccionar el mejor par del mercado
# ============================================================

def get_best_symbol() -> dict | None:

    stats_map = get_all_24h_stats()
    if not stats_map:
        safe_log("❌ No hay estadísticas válidas.")
        return None

    # Ordenamos los pares por volumen real
    ordered = sorted(
        stats_map.keys(),
        key=lambda s: stats_map[s].get("volumeUsd", 0),
        reverse=True
    )

    top = ordered[:SCANNER_DEPTH]

    results = []

    for symbol in top:
        parsed = analyze_symbol(symbol, stats_map)
        if parsed:
            results.append(parsed)

    if not results:
        safe_log("❌ No se pudo analizar ningún par válido.")
        return None

    best = max(results, key=lambda x: x["score"])

    safe_log(
        f"🔥 Mejor par: {best['symbol']} | Score {best['score']} | "
        f"Vol24h: {best['volume_usd']} | OI: {best['open_interest_usd']}"
    )

    return best
