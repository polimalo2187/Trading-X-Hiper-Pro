# ============================================================
# MARKET SCANNER – TRADING X HIPER PRO
# Escáner REAL de mercado para seleccionar el MEJOR PAR
# Usa datos reales de HyperLiquid (24h stats)
# ============================================================

from app.hyperliquid_client import make_request


# ============================================================
# OBTENER ESTADÍSTICAS REALES 24H
# ============================================================

def get_all_24h_stats():
    """
    Pide a HyperLiquid las estadísticas 24h de TODOS los pares PERP.
    Devuelve un diccionario: { "BTC": {...}, "ETH": {...}, ... }
    con los datos crudos del exchange.
    """

    payload = {"type": "all24hStats"}
    r = make_request("/info", payload)

    if not r or "all24hStats" not in r:
        print("❌ No se pudo obtener all24hStats desde HyperLiquid:", r)
        return {}

    stats_map = {}

    # Formato típico: lista de objetos con campo 'coin' o 'symbol'
    for item in r["all24hStats"]:
        symbol = item.get("coin") or item.get("symbol")
        if not symbol:
            continue
        stats_map[symbol] = item

    return stats_map


# ============================================================
# ANALIZAR UN PAR USANDO SOLO DATOS REALES
# ============================================================

def analyze_symbol(symbol: str, stats: dict) -> dict | None:
    """
    Analiza un símbolo usando ÚNICAMENTE datos reales:
      - volumenUsd (volumen 24h)
      - openInterestUsd (OI 24h)
      - priceChange24h (variación % 24h)
      - markPx / midPx / last (precio actual)
    Calcula un score para clasificar el par.
    """

    info = stats.get(symbol)
    if not info:
        return None

    # Precio actual (prioridad: markPx -> midPx -> last)
    price = (
        info.get("markPx")
        or info.get("midPx")
        or info.get("last")
        or info.get("lastPx")
    )

    try:
        price = float(price)
    except (TypeError, ValueError):
        return None

    if price <= 0:
        return None

    # Datos reales de actividad
    volume_usd = float(info.get("volumeUsd", 0) or 0)
    oi_usd = float(info.get("openInterestUsd", 0) or 0)
    change_24h = float(info.get("priceChange24h", 0) or 0)  # en %

    # Normalizaciones simples (0–1) para construir el score
    # Ajusta estos denominadores si quieres hacerlo más/menos exigente.
    vol_score = min(volume_usd / 1_000_000, 1.0)         # 1M+ USD = máximo
    oi_score = min(oi_usd / 5_000_000, 1.0)              # 5M+ USD = máximo

    if change_24h >= 0:
        # 0% → 0.5    5% o más → ~1.0
        trend_score = min(0.5 + (change_24h / 10), 1.0)
    else:
        # Caídas fuertes penalizan el score (hasta 0)
        trend_score = max(0.5 + (change_24h / 20), 0.0)

    # Score final 100% real (sin random)
    score = (vol_score * 0.5) + (oi_score * 0.3) + (trend_score * 0.2)

    return {
        "symbol": symbol,
        "price": round(price, 6),
        "volume_usd": round(volume_usd, 2),
        "open_interest_usd": round(oi_usd, 2),
        "change_24h": round(change_24h, 4),
        "score": round(score, 4),
    }


# ============================================================
# SELECCIONAR EL MEJOR PAR DEL MERCADO
# ============================================================

def get_best_symbol() -> dict | None:
    """
    Escanea TODOS los pares del exchange y devuelve
    el que tenga el score más alto según:
      - Alto volumen real
      - Alto open interest real
      - Buen comportamiento de precio 24h

    Retorna un dict con info del mejor par, o None si falla.
    """

    stats_map = get_all_24h_stats()
    if not stats_map:
        print("❌ No hay datos 24h disponibles para escanear el mercado.")
        return None

    results = []

    for symbol in stats_map.keys():
        analysis = analyze_symbol(symbol, stats_map)
        if analysis:
            results.append(analysis)

    if not results:
        print("❌ Ningún par válido después del análisis.")
        return None

    # Ordenar por score descendente
    results.sort(key=lambda x: x["score"], reverse=True)
    best = results[0]

    print(
        f"🔥 Mejor par detectado: {best['symbol']} | "
        f"Score: {best['score']} | "
        f"Vol24h: {best['volume_usd']} USD | "
        f"OI: {best['open_interest_usd']} USD | "
        f"Cambio24h: {best['change_24h']}%"
    )

    return best
