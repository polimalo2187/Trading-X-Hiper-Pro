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

    FIX CLAVE:
    - NO asumimos USD
    - NO filtramos por openInterest
    - NO filtramos por thresholds irreales
    """

    r = make_request("/info", {"type": "metaAndAssetCtxs"})
    if not r or not isinstance(r, list) or len(r) < 2:
        safe_log("❌ Respuesta inválida metaAndAssetCtxs")
        return {}

    meta, asset_ctxs = r

    if not isinstance(meta, dict) or not isinstance(asset_ctxs, list):
        safe_log("❌ metaAndAssetCtxs: estructuras inválidas")
        return {}

    universe = meta.get("universe") if isinstance(meta.get("universe"), list) else []

    stats_map = {}

    for i, asset in enumerate(asset_ctxs):
        if not isinstance(asset, dict):
            continue

        symbol = asset.get("coin")

        # Fallback: si no viene "coin" en el ctx, usar meta.universe[i].name
        if not symbol and i < len(universe) and isinstance(universe[i], dict):
            symbol = universe[i].get("name")

        if not symbol:
            safe_log("⚠ Asset sin coin/name key, se ignora")
            continue

        try:
            price = float(asset.get("markPx", 0))
            volume = float(asset.get("dayNtlVlm", 0))
        except Exception as e:
            safe_log(f"❌ Error parsing asset {symbol}: {e}")
            continue

        # 🔥 FILTROS MÍNIMOS REALES (NO AUTO-SABOTAJE)
        if price <= 0 or volume <= 0:
            continue

        # AHORA dejamos el símbolo tal cual la API devuelve,
        # agregamos -PERP **solo al final** para compatibilidad con el bot
        stats_map[f"{symbol}-PERP"] = asset

    if not stats_map:
        safe_log("❌ Scanner: todos los mercados fueron filtrados")

    return stats_map


# ============================================================
# 2. ANALIZAR UN SÍMBOLO
# ============================================================

def analyze_symbol(symbol: str, stats: dict):
    info = stats.get(symbol)
    if not info:
        safe_log(f"⚠ Symbol {symbol} no encontrado en stats")
        return None

    try:
        price = float(info.get("markPx", 0))
        prev_price = float(info.get("prevDayPx", price))
        volume = float(info.get("dayNtlVlm", 0))
        oi = float(info.get("openInterest", 0) or 0)
    except Exception as e:
        safe_log(f"❌ Error parsing symbol {symbol}: {e}")
        return None

    if price <= 0:
        return None

    # Variación 24h REAL
    change_24h = ((price - prev_price) / prev_price * 100) if prev_price > 0 else 0

    # Scores NORMALIZADOS (NO BLOQUEANTES)
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
        safe_log("❌ Scanner sin mercados válidos")
        return None

    results = []

    for symbol in stats.keys():
        if symbol in exclude_symbols:
            continue

        parsed = analyze_symbol(symbol, stats)
        if parsed:
            results.append(parsed)

    # Fallback: si excluir deja sin resultados, devolvemos el mejor sin exclusión
    if not results:
        safe_log("⚠ Scanner: exclusión dejó 0 resultados, fallback sin exclusión")
        exclude_symbols = set()
        for symbol in stats.keys():
            parsed = analyze_symbol(symbol, stats)
            if parsed:
                results.append(parsed)

    if not results:
        safe_log("❌ Scanner sin resultados analizables")
        return None

    # Ordenar por score descendente
    results.sort(key=lambda x: x["score"], reverse=True)

    # Limitar profundidad si aplica
    if SCANNER_DEPTH and len(results) > SCANNER_DEPTH:
        results = results[:SCANNER_DEPTH]

    return results[0]
