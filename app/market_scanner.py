# ============================================================
# MARKET SCANNER – Trading X Hyper Pro
# PRODUCCIÓN REAL – FAILSAFE
# NUNCA devuelve None si existe mercado válido
# ============================================================

from __future__ import annotations
from typing import Dict, Optional, List, Set
import time

from app.hyperliquid_client import make_request
from app.config import SCANNER_DEPTH, VERBOSE_LOGS, PRODUCTION_MODE

# ============================================================
# LOG
# ============================================================

def safe_log(*args):
    if VERBOSE_LOGS or not PRODUCTION_MODE:
        print(*args)

# ============================================================
# CACHE FAILSAFE (CRÍTICO)
# ============================================================

_LAST_GOOD_RESULTS: List[dict] = []
_LAST_UPDATE_TS: float = 0.0
MAX_CACHE_AGE = 300  # 5 minutos

# ============================================================
# UTIL
# ============================================================

def _as_perp_symbol(coin: str) -> str:
    c = (coin or "").strip().upper()
    if not c:
        return ""
    if c.endswith("-PERP"):
        return c
    return f"{c}-PERP"

# ============================================================
# OBTENER MERCADOS (ROBUSTO)
# ============================================================

def _fetch_markets() -> Dict[str, dict]:
    r = make_request("/info", {"type": "metaAndAssetCtxs"})
    if not r or not isinstance(r, list) or len(r) < 2:
        return {}

    meta, asset_ctxs = r
    universe = meta.get("universe", []) if isinstance(meta, dict) else []

    out: Dict[str, dict] = {}

    for i, asset in enumerate(asset_ctxs):
        if not isinstance(asset, dict):
            continue

        symbol = asset.get("coin")
        if not symbol and i < len(universe):
            symbol = universe[i].get("name")

        if not symbol:
            continue

        try:
            price = float(asset.get("markPx", 0))
            volume = float(asset.get("dayNtlVlm", 0))
        except Exception:
            continue

        if price <= 0 or volume <= 0:
            continue

        out[_as_perp_symbol(symbol)] = asset

    return out

# ============================================================
# SCORE SIMPLE (NO BLOQUEANTE)
# ============================================================

def _score_symbol(symbol: str, info: dict) -> Optional[dict]:
    try:
        price = float(info.get("markPx", 0))
        prev = float(info.get("prevDayPx", price))
        vol = float(info.get("dayNtlVlm", 0))
        oi = float(info.get("openInterest", 0))
    except Exception:
        return None

    if price <= 0 or vol <= 0:
        return None

    change = ((price - prev) / prev * 100) if prev > 0 else 0.0

    vol_score = min(vol / 1_000_000, 1.0)
    oi_score = min(oi / 10_000_000, 1.0) if oi > 0 else 0.3
    trend_score = max(min((change / 5.0) + 0.5, 1.0), 0.0)

    score = (vol_score * 0.5) + (oi_score * 0.3) + (trend_score * 0.2)

    return {
        "symbol": symbol,
        "price": round(price, 6),
        "score": round(score, 4),
        "volume": round(vol, 2),
        "oi": round(oi, 2),
        "change_24h": round(change, 2),
    }

# ============================================================
# API PRINCIPAL – NUNCA DEVUELVE None
# ============================================================

def get_best_symbol(exclude_symbols: Optional[Set[str]] = None) -> Optional[dict]:
    global _LAST_GOOD_RESULTS, _LAST_UPDATE_TS

    exclude_symbols = exclude_symbols or set()
    markets = _fetch_markets()

    results: List[dict] = []

    for symbol, info in markets.items():
        if symbol in exclude_symbols:
            continue
        parsed = _score_symbol(symbol, info)
        if parsed:
            results.append(parsed)

    if results:
        results.sort(key=lambda x: x["score"], reverse=True)

        if SCANNER_DEPTH and len(results) > SCANNER_DEPTH:
            results = results[:SCANNER_DEPTH]

        _LAST_GOOD_RESULTS = results
        _LAST_UPDATE_TS = time.time()

        return results[0]

    # --------------------------------------------------------
    # 🔥 FAILSAFE: usar último snapshot válido
    # --------------------------------------------------------
    if _LAST_GOOD_RESULTS:
        age = time.time() - _LAST_UPDATE_TS
        if age <= MAX_CACHE_AGE:
            safe_log("⚠️ Scanner usando cache FAILSAFE")
            return _LAST_GOOD_RESULTS[0]

    safe_log("❌ Scanner sin mercados válidos (ni live ni cache)")
    return None
