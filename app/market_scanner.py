# ============================================================
# MARKET SCANNER – Trading X Hyper Pro
# PRODUCCIÓN REAL – FAILSAFE
# ============================================================

from __future__ import annotations

import time
from typing import Dict, List, Optional, Set

from app.config import PRODUCTION_MODE, SCANNER_DEPTH, VERBOSE_LOGS
from app.hyperliquid_client import make_request


# ============================================================
# LOG
# ============================================================

def safe_log(*args):
    if VERBOSE_LOGS or not PRODUCTION_MODE:
        print(*args)


# ============================================================
# CACHE FAILSAFE
# ============================================================

_LAST_GOOD_RESULTS: List[dict] = []
_LAST_UPDATE_TS: float = 0.0
MAX_CACHE_AGE = 300  # 5 minutos


# ============================================================
# ROTACIÓN / ANTI-REPETICIÓN
# ============================================================
# Evita quedarse clavado en el mismo símbolo.
RECENT_TTL_SECONDS = 15 * 60
_recent_picks: dict[str, float] = {}
_rr_index: int = 0


def _prune_recent(now: float) -> None:
    dead = [s for s, ts in _recent_picks.items() if (now - ts) > (RECENT_TTL_SECONDS * 2)]
    for s in dead:
        _recent_picks.pop(s, None)


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
# OBTENER MERCADOS
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
# RESULTADOS SCANNER
# ============================================================

def _get_live_results(exclude_symbols: Set[str]) -> List[dict]:
    markets = _fetch_markets()
    results: List[dict] = []

    for symbol, info in markets.items():
        if symbol in exclude_symbols:
            continue
        parsed = _score_symbol(symbol, info)
        if parsed:
            results.append(parsed)

    if not results:
        return []

    results.sort(key=lambda x: x["score"], reverse=True)
    if SCANNER_DEPTH and len(results) > SCANNER_DEPTH:
        results = results[:SCANNER_DEPTH]
    return results


def _get_scored_results(exclude_symbols: Set[str]) -> List[dict]:
    global _LAST_GOOD_RESULTS, _LAST_UPDATE_TS

    results = _get_live_results(exclude_symbols)
    if results:
        _LAST_GOOD_RESULTS = results
        _LAST_UPDATE_TS = time.time()
        return results

    if _LAST_GOOD_RESULTS:
        age = time.time() - _LAST_UPDATE_TS
        if age <= MAX_CACHE_AGE:
            safe_log("⚠️ Scanner usando cache FAILSAFE")
            return [r for r in _LAST_GOOD_RESULTS if str(r.get("symbol") or "") not in exclude_symbols]

    safe_log("❌ Scanner sin mercados válidos (ni live ni cache)")
    return []


# ============================================================
# ORDENACIÓN DE CANDIDATOS
# ============================================================

def _ordered_candidates(results: List[dict], exclude_symbols: Set[str]) -> List[dict]:
    if not results:
        return []

    now = time.time()
    _prune_recent(now)

    filtered = [r for r in results if str(r.get("symbol") or "") not in exclude_symbols]
    if not filtered:
        return []

    n = len(filtered)
    start = _rr_index % n if n > 0 else 0
    rotated = filtered[start:] + filtered[:start]

    fresh: List[dict] = []
    recent: List[dict] = []
    for item in rotated:
        sym = str(item.get("symbol") or "")
        if not sym:
            continue
        last = _recent_picks.get(sym, 0.0)
        if (now - last) >= RECENT_TTL_SECONDS:
            fresh.append(item)
        else:
            recent.append(item)

    return fresh + recent


# ============================================================
# API PRINCIPAL
# ============================================================

def get_ranked_symbols(exclude_symbols: Optional[Set[str]] = None, limit: Optional[int] = None) -> List[dict]:
    exclude_symbols = exclude_symbols or set()
    results = _get_scored_results(exclude_symbols)
    ordered = _ordered_candidates(results, exclude_symbols)

    if limit is not None and limit > 0:
        ordered = ordered[: int(limit)]

    if ordered and VERBOSE_LOGS:
        preview = ", ".join(f"{r.get('symbol')}:{r.get('score')}" for r in ordered[:5])
        safe_log(f"🔎 Scanner shortlist={preview}")

    return ordered


def mark_symbol_recent(symbol: str) -> None:
    global _rr_index

    sym = str(symbol or "").strip().upper()
    if not sym:
        return

    now = time.time()
    _prune_recent(now)
    _recent_picks[sym] = now
    _rr_index = (_rr_index + 1) % 1_000_000


# ============================================================
# COMPATIBILIDAD
# ============================================================

def get_best_symbol(exclude_symbols: Optional[Set[str]] = None) -> Optional[dict]:
    ranked = get_ranked_symbols(exclude_symbols=exclude_symbols, limit=1)
    if not ranked:
        return None
    picked = ranked[0]
    mark_symbol_recent(str(picked.get("symbol") or ""))
    if picked and VERBOSE_LOGS:
        safe_log(f"🔎 Scanner picked={picked.get('symbol')} score={picked.get('score')} (best-of-shortlist)")
    return picked
