# ============================================================
# MARKET SCANNER – Trading X Hyper Pro
# PRODUCCIÓN REAL Hyperliquid
# BANK-GRADE (sin auto-sabotaje) + ROTACIÓN TOP-K
# ============================================================

from __future__ import annotations

from typing import Any, Dict, Optional, List, Set

from app.hyperliquid_client import make_request
from app.config import SCANNER_DEPTH, VERBOSE_LOGS, PRODUCTION_MODE

# ============================================================
# LOG CONTROLADO
# ============================================================

def safe_log(*args):
    if VERBOSE_LOGS or not PRODUCTION_MODE:
        print(*args)

# ============================================================
# ROTACIÓN (evita quedarse pegado en 1 solo símbolo)
# ============================================================

_RR_INDEX = 0

def _next_index(mod: int) -> int:
    global _RR_INDEX
    if mod <= 0:
        return 0
    _RR_INDEX = (_RR_INDEX + 1) % mod
    return _RR_INDEX

def _as_perp_symbol(coin: str) -> str:
    c = (coin or "").strip().upper()
    if not c:
        return ""
    # evita doble "-PERP"
    if c.endswith("-PERP"):
        return c
    return f"{c}-PERP"

# ============================================================
# 1) OBTENER CONTEXTO REAL DE MERCADO (HYPERLIQUID)
# ============================================================

def get_all_24h_stats() -> Dict[str, dict]:
    """
    Devuelve un dict:
    {
        "BTC-PERP": asset_ctx,
        "ETH-PERP": asset_ctx,
        ...
    }

    Reglas:
    - No asumimos USD “perfecto”
    - No filtramos por OI como bloqueante
    - Filtros mínimos: price > 0 y volume > 0
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
    stats_map: Dict[str, dict] = {}

    for i, asset in enumerate(asset_ctxs):
        if not isinstance(asset, dict):
            continue

        symbol = asset.get("coin")

        # Fallback: si no viene "coin", usar meta.universe[i].name
        if not symbol and i < len(universe) and isinstance(universe[i], dict):
            symbol = universe[i].get("name")

        if not symbol:
            continue

        try:
            price = float(asset.get("markPx", 0) or 0)
            volume = float(asset.get("dayNtlVlm", 0) or 0)
        except Exception:
            continue

        if price <= 0 or volume <= 0:
            continue

        perp = _as_perp_symbol(str(symbol))
        if perp:
            stats_map[perp] = asset

    if not stats_map:
        safe_log("❌ Scanner: 0 mercados válidos tras filtros mínimos")

    return stats_map

# ============================================================
# 2) ANALIZAR UN SÍMBOLO
# ============================================================

def analyze_symbol(symbol: str, stats: Dict[str, dict]) -> Optional[dict]:
    info = stats.get(symbol)
    if not info:
        return None

    try:
        price = float(info.get("markPx", 0) or 0)
        prev_price = float(info.get("prevDayPx", price) or price)
        volume = float(info.get("dayNtlVlm", 0) or 0)
        oi = float(info.get("openInterest", 0) or 0)
    except Exception:
        return None

    if price <= 0 or volume <= 0:
        return None

    change_24h = ((price - prev_price) / prev_price * 100) if prev_price > 0 else 0.0

    # Scores normalizados (NO bloqueantes)
    vol_score = min(volume / 1_000_000, 1.0)                    # 0..1
    oi_score = min(oi / 10_000_000, 1.0) if oi > 0 else 0.2     # 0.2..1
    trend_score = max(min((change_24h / 5.0) + 0.5, 1.0), 0.0)  # 0..1

    score = (vol_score * 0.45) + (oi_score * 0.35) + (trend_score * 0.20)

    return {
        "symbol": symbol,
        "price": round(price, 6),
        "volume_notional": round(volume, 2),
        "open_interest": round(oi, 2),
        "change_24h": round(change_24h, 3),
        "score": round(score, 4),
    }

# ============================================================
# 3) SELECCIONAR SÍMBOLO (TOP-K + ROTACIÓN)
# ============================================================

def get_best_symbol(exclude_symbols: Optional[Set[str]] = None) -> Optional[dict]:
    """
    Retorna dict:
      {"symbol": "ONDO-PERP", "score": 0.1234, ...}

    Importante:
    - Aquí hacemos rotación Top-K para evitar “pegado” en 1 solo par.
    - El ENGINE NO hace lógica de escaneo.
    """
    exclude_symbols = exclude_symbols or set()

    stats = get_all_24h_stats()
    if not stats:
        return None

    results: List[dict] = []

    for symbol in stats.keys():
        if symbol in exclude_symbols:
            continue
        parsed = analyze_symbol(symbol, stats)
        if parsed:
            results.append(parsed)

    # fallback sin exclusión (por si exclude deja todo en 0)
    if not results:
        for symbol in stats.keys():
            parsed = analyze_symbol(symbol, stats)
            if parsed:
                results.append(parsed)

    if not results:
        return None

    results.sort(key=lambda x: float(x.get("score", 0.0) or 0.0), reverse=True)

    # profundidad (si aplica)
    if SCANNER_DEPTH and len(results) > int(SCANNER_DEPTH):
        results = results[: int(SCANNER_DEPTH)]

    # ROTACIÓN TOP-K
    top_k = min(10, len(results))
    idx = _next_index(top_k)
    return results[idx]
