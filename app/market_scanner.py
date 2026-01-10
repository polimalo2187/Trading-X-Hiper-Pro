# ============================================================
# MARKET SCANNER – Trading X Hyper Pro
# Archivo 6/9 – Producción REAL Hyperliquid (MODO GUERRA)
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
    Devuelve un mapa de activos reales de Hyperliquid.
    IMPORTANTE:
    - Hyperliquid usa símbolos SIMPLES: BTC, ETH, SOL, etc.
    - USDC es implícito (moneda de margen)
    """

    r = make_request("/info", {"type": "metaAndAssetCtxs"})

    if not r or not isinstance(r, list) or len(r) < 2:
        safe_log("❌ Respuesta inválida de Hyperliquid metaAndAssetCtxs")
        return {}

    asset_ctxs = r[1]
    stats_map = {}

    for item in asset_ctxs:
        symbol = item.get("coin")
        if not symbol:
            continue

        symbol = symbol.upper()

        # ⚠️ NO FILTRAMOS USDC (Hyperliquid NO usa BTC-USDC en API)
        stats_map[symbol] = item

    return stats_map


# ============================================================
# 2. ANALIZAR ACTIVO (SCORE AGRESIVO – MODO GUERRA)
# ============================================================

def analyze_symbol(symbol: str, stats: dict) -> dict | None:

    info = stats.get(symbol)
    if not info:
        return None

    try:
        price = float(info.get("markPx", 0))
        if price <= 0:
            return None
    except Exception:
        return None

    volume = float(info.get("volumeUsd", 0) or 0)
    oi = float(info.get("openInterestUsd", 0) or 0)
    change = float(info.get("priceChange24h", 0) or 0)

    bid = float(info.get("bidPx", price))
    ask = float(info.get("askPx", price))
    spread = max(ask - bid, 0)

    # ========================================================
    # SCORE AGRESIVO (BUSCA MOVIMIENTO, NO CONSERVADOR)
    # ========================================================

    vol_score = min(volume / 1_200_000, 1.0)
    oi_score = min(oi / 5_000_000, 1.0)
    trend_score = max(min((change / 5) + 0.5, 1.0), 0.0)
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
        "change_24h": round(change, 4),
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

    # 🔥 Ordenar por actividad REAL (volumen + open interest)
    ordered = sorted(
        stats_map.keys(),
        key=lambda s: (
            stats_map[s].get("volumeUsd", 0) +
            stats_map[s].get("openInterestUsd", 0)
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
        safe_log("❌ No se pudo analizar ningún activo")
        return None

    best = max(results, key=lambda x: x["score"])

    safe_log(
        f"🔥 MODO GUERRA | {best['symbol']} | "
        f"Score {best['score']} | "
        f"Vol {best['volume_usd']} | "
        f"OI {best['open_interest_usd']}"
    )

    return best
