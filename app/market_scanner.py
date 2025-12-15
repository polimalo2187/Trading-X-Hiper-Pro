# ============================================================
# MARKET SCANNER – TRADING X HYPER PRO
# Archivo 6/9 – Escáner REAL profesional
# ============================================================

from app.hyperliquid_client import make_request
from app.config import SCANNER_DEPTH


# ============================================================
# OBTENER ESTADÍSTICAS REALES 24H
# ============================================================

def get_all_24h_stats():
    """
    Pide las estadísticas REALES 24h de todos los pares PERP.
    Devuelve un diccionario limpio y seguro.
    """

    payload = {"type": "all24hStats"}
    r = make_request("/info", payload)

    if not r or "all24hStats" not in r:
        print("❌ Error: no se pudo obtener all24hStats.")
        return {}

    stats_map = {}

    for item in r["all24hStats"]:
        # Filtrar pares inválidos o sin símbolo correcto
        symbol = item.get("coin") or item.get("symbol")
        if not symbol:
            continue

        # HyperLiquid incluye activos no PERP → los filtramos
        if "-PERP" not in symbol.upper() and symbol.upper() not in ["BTC", "ETH", "SOL"]:
            continue

        stats_map[symbol] = item

    return stats_map


# ============================================================
# ANALIZAR UN PAR USANDO SOLO DATOS REALES
# ============================================================

def analyze_symbol(symbol: str, stats: dict) -> dict | None:
    info = stats.get(symbol)
    if not info:
        return None

    # Precio actual real
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

    # Datos reales del par
    volume_usd = float(info.get("volumeUsd", 0) or 0)
    oi_usd = float(info.get("openInterestUsd", 0) or 0)
    change_24h = float(info.get("priceChange24h", 0) or 0)
    spread = abs(float(info.get("markPx", price)) - float(info.get("midPx", price)))

    # Normalizaciones profesionales
    vol_score = min(volume_usd / 2_000_000, 1.0)
    oi_score = min(oi_usd / 10_000_000, 1.0)

    # Tendencia macro
    trend_score = max(min((change_24h / 8) + 0.5, 1.0), 0.0)

    # Spread: mientras menor mejor
    spread_score = 1.0 - min(spread / (price * 0.002), 1.0)

    # Score final profesional
    score = (
        vol_score * 0.35 +
        oi_score * 0.35 +
        trend_score * 0.20 +
        spread_score * 0.10
    )

    return {
        "symbol": symbol,
        "price": round(price, 6),
        "volume_usd": round(volume_usd, 2),
        "open_interest_usd": round(oi_usd, 2),
        "change_24h": round(change_24h, 4),
        "spread": round(spread, 8),
        "score": round(score, 4),
    }


# ============================================================
# OBTENER EL MEJOR PAR (TOP 1)
# ============================================================

def get_best_symbol() -> dict | None:
    stats_map = get_all_24h_stats()

    if not stats_map:
        print("❌ No hay datos válidos para escanear el mercado.")
        return None

    results = []

    # Limitar al SCANNER_DEPTH más alto en volumen
    top_symbols = sorted(
        stats_map.keys(),
        key=lambda s: stats_map[s].get("volumeUsd", 0),
        reverse=True
    )[:SCANNER_DEPTH]

    for symbol in top_symbols:
        analysis = analyze_symbol(symbol, stats_map)
        if analysis:
            results.append(analysis)

    if not results:
        print("❌ No se pudo analizar ningún par válido.")
        return None

    best = max(results, key=lambda x: x["score"])

    print(
        f"🔥 Mejor par: {best['symbol']} | Score {best['score']} | "
        f"Vol24h: {best['volume_usd']} | OI: {best['open_interest_usd']}"
    )

    return best
