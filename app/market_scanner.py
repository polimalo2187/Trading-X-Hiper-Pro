# ============================================================
# MARKET SCANNER – Trading X Hyper Pro
# PRODUCCIÓN REAL Hyperliquid
# BANK-GRADE (sin auto-sabotaje) + ROTACIÓN TOP-K
# FIX PROD:
#  - Filtra por liquidez (24h notional + OI) para evitar NO_FILL
#  - Valida spread/top-of-book con l2Book (solo TOP-N para no spamear)
#  - Cache TTL (reduce 429/500)
# ============================================================

from __future__ import annotations

import time
from typing import Any, Dict, Optional, List, Set, Tuple

from app.hyperliquid_client import make_request
from app.config import SCANNER_DEPTH, VERBOSE_LOGS, PRODUCTION_MODE

# ============================================================
# LOG CONTROLADO
# ============================================================

def safe_log(*args):
    if VERBOSE_LOGS or not PRODUCTION_MODE:
        print(*args)

# ============================================================
# CONFIG PROD (liquidez real)
# ============================================================
# Notional 24h mínimo en USDC (dayNtlVlm)
MIN_24H_NOTIONAL = 2_000_000.0     # 2M (sube/baja según tu estilo)
# Open interest mínimo (openInterest) - evita pares "muertos"
MIN_OPEN_INTEREST = 250_000.0      # 250k
# Spread máximo permitido (bps). Si spread es grande, IOC casi siempre NO_FILL.
MAX_SPREAD_BPS = 25.0             # 0.25%
# Notional mínimo top-of-book (best bid/ask) para asegurar fills (aprox)
MIN_TOP_BOOK_NOTIONAL = 2_000.0    # 2k USDC

# Validación microestructura solo en shortlist para no llamar l2Book a todo
SHORTLIST_DEPTH_FOR_L2 = 25

# Cache TTLs
_STATS_CACHE_TTL = 5.0
_L2_CACHE_TTL = 1.5

_STATS_CACHE: Dict[str, Any] = {"ts": 0.0, "data": {}}
_L2_CACHE: Dict[str, Any] = {}  # key=symbol -> {"ts": float, "data": (bid, ask, bidSz, askSz)}

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
    if c.endswith("-PERP"):
        return c
    return f"{c}-PERP"

def _coin_from_symbol(symbol: str) -> str:
    s = (symbol or "").strip().upper()
    s = s.replace("-PERP", "").replace("_PERP", "").replace("PERP", "")
    return s

# ============================================================
# 0) L2 BOOK (spread + top of book) con cache
# ============================================================

def _get_l2_top(symbol: str) -> Optional[Tuple[float, float, float, float]]:
    """
    Devuelve (best_bid_px, best_ask_px, best_bid_sz, best_ask_sz)
    Usa /info type=l2Book req={coin, nLevels}
    """
    try:
        now = time.time()
        key = str(symbol).upper()
        cached = _L2_CACHE.get(key)
        if cached and (now - float(cached.get("ts", 0.0) or 0.0)) < _L2_CACHE_TTL:
            return cached.get("data")

        coin = _coin_from_symbol(symbol)
        if not coin:
            return None

        # nLevels pequeño para no cargar
        r = make_request("/info", {"type": "l2Book", "coin": coin, "nLevels": 2})
        if not isinstance(r, dict):
            return None

        levels = r.get("levels")
        if not isinstance(levels, list) or len(levels) < 2:
            return None

        bids = levels[0]  # [[px, sz], ...]
        asks = levels[1]

        if not isinstance(bids, list) or not bids or not isinstance(asks, list) or not asks:
            return None

        b0 = bids[0]
        a0 = asks[0]
        if not (isinstance(b0, list) and len(b0) >= 2 and isinstance(a0, list) and len(a0) >= 2):
            return None

        bid_px = float(b0[0])
        bid_sz = float(b0[1])
        ask_px = float(a0[0])
        ask_sz = float(a0[1])

        if bid_px <= 0 or ask_px <= 0:
            return None

        out = (bid_px, ask_px, bid_sz, ask_sz)
        _L2_CACHE[key] = {"ts": now, "data": out}
        return out

    except Exception:
        return None

def _spread_bps(bid: float, ask: float) -> float:
    try:
        mid = (float(bid) + float(ask)) / 2.0
        if mid <= 0:
            return 10_000.0
        return abs(float(ask) - float(bid)) / mid * 10_000.0
    except Exception:
        return 10_000.0

def _top_book_notional_ok(bid_px: float, ask_px: float, bid_sz: float, ask_sz: float) -> bool:
    try:
        # aproximación: notional de la mejor punta
        bid_ntl = float(bid_px) * max(0.0, float(bid_sz))
        ask_ntl = float(ask_px) * max(0.0, float(ask_sz))
        return (bid_ntl >= MIN_TOP_BOOK_NOTIONAL) and (ask_ntl >= MIN_TOP_BOOK_NOTIONAL)
    except Exception:
        return False

# ============================================================
# 1) OBTENER CONTEXTO REAL DE MERCADO (HYPERLIQUID) con cache
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
    - Filtros mínimos: price > 0, volume > 0
    - Filtro liquidez PROD: dayNtlVlm >= MIN_24H_NOTIONAL y OI >= MIN_OPEN_INTEREST
    - Usa cache TTL para evitar 429/500
    """
    now = time.time()
    cached = _STATS_CACHE.get("data")
    if cached and (now - float(_STATS_CACHE.get("ts", 0.0) or 0.0)) < _STATS_CACHE_TTL:
        return cached if isinstance(cached, dict) else {}

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
            oi = float(asset.get("openInterest", 0) or 0)
        except Exception:
            continue

        if price <= 0 or volume <= 0:
            continue

        # ✅ Filtro liquidez para evitar pares sin fills
        if float(volume) < float(MIN_24H_NOTIONAL):
            continue
        if float(oi) < float(MIN_OPEN_INTEREST):
            continue

        perp = _as_perp_symbol(str(symbol))
        if perp:
            stats_map[perp] = asset

    if not stats_map:
        safe_log("❌ Scanner: 0 mercados válidos tras filtros de liquidez")

    _STATS_CACHE["ts"] = now
    _STATS_CACHE["data"] = stats_map
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
    # volumen: a partir de MIN_24H_NOTIONAL ya es "válido"; encima suma score
    vol_score = min(max(volume / 25_000_000.0, 0.0), 1.0)  # 0..1 (25M ya full)
    oi_score = min(max(oi / 10_000_000.0, 0.0), 1.0)       # 0..1
    trend_score = max(min((change_24h / 6.0) + 0.5, 1.0), 0.0)  # 0..1

    score = (vol_score * 0.50) + (oi_score * 0.35) + (trend_score * 0.15)

    return {
        "symbol": symbol,
        "price": round(price, 6),
        "volume_notional": round(volume, 2),
        "open_interest": round(oi, 2),
        "change_24h": round(change_24h, 3),
        "score": round(score, 6),
    }

# ============================================================
# 2.1) VALIDACIÓN L2 (spread + top-book) para reducir NO_FILL
# ============================================================

def _passes_l2_filters(symbol: str) -> bool:
    top = _get_l2_top(symbol)
    if not top:
        # si no pudimos leer book, mejor NO operar (evita NO_FILL/errores)
        return False

    bid_px, ask_px, bid_sz, ask_sz = top

    # spread
    sp = _spread_bps(bid_px, ask_px)
    if sp > float(MAX_SPREAD_BPS):
        return False

    # top-of-book notional (ambos lados)
    if not _top_book_notional_ok(bid_px, ask_px, bid_sz, ask_sz):
        return False

    return True

# ============================================================
# 3) SELECCIONAR SÍMBOLO (TOP-K + ROTACIÓN + FILTRO L2)
# ============================================================

def get_best_symbol(exclude_symbols: Optional[Set[str]] = None) -> Optional[dict]:
    """
    Retorna dict:
      {"symbol": "ONDO-PERP", "score": 0.1234, ...}

    Importante:
    - Rotación Top-K para evitar “pegado”.
    - Liquidez real + L2 filters para evitar NO_FILL.
    """
    exclude_symbols = exclude_symbols or set()

    stats = get_all_24h_stats()
    if not stats:
        return None

    results: List[dict] = []

    for symbol in stats.keys():
        sym = str(symbol).upper()
        if sym in exclude_symbols:
            continue
        parsed = analyze_symbol(sym, stats)
        if parsed:
            results.append(parsed)

    # fallback sin exclusión
    if not results:
        for symbol in stats.keys():
            parsed = analyze_symbol(str(symbol).upper(), stats)
            if parsed:
                results.append(parsed)

    if not results:
        return None

    # ordenar por score base (vol/oi/trend)
    results.sort(key=lambda x: float(x.get("score", 0.0) or 0.0), reverse=True)

    # profundidad (si aplica)
    if SCANNER_DEPTH and len(results) > int(SCANNER_DEPTH):
        results = results[: int(SCANNER_DEPTH)]

    # ✅ Shortlist para validar microestructura sin spamear la API
    shortlist = results[: min(int(SHORTLIST_DEPTH_FOR_L2), len(results))]

    liquid: List[dict] = []
    for item in shortlist:
        sym = str(item.get("symbol") or "").upper()
        if not sym:
            continue
        if _passes_l2_filters(sym):
            liquid.append(item)

    # Si no quedó nada tras L2, devolvemos None (evita NO_FILL en pares muertos)
    if not liquid:
        safe_log("⚠️ Scanner: shortlist sin mercados con spread/top-book OK")
        return None

    # Re-ordenar por score (se mantiene) y rotación TOP-K
    liquid.sort(key=lambda x: float(x.get("score", 0.0) or 0.0), reverse=True)

    top_k = min(10, len(liquid))
    idx = _next_index(top_k)
    return liquid[idx]
