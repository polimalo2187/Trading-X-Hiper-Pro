# ============================================================
# ARCHIVO: app/strategy.py
# ESTRATEGIA MTF (1H + 15M + 5M) – HYPERLIQUID NATIVO
# PRODUCCIÓN REAL – BANK GRADE
# ============================================================

import time
from typing import Dict, Any, List, Optional, Tuple

from app.hyperliquid_client import make_request, norm_coin

# =========================
# CONFIGURACIÓN MTF
# =========================

TF_1H = "1h"
TF_15M = "15m"
TF_5M = "5m"

LOOKBACK_1H = 260
LOOKBACK_15M = 260
LOOKBACK_5M = 320

EMA_TREND = 200

ADX_PERIOD = 14
ADX_MIN_TREND_1H = 25
ADX_MIN_TREND_15M = 20

BB_PERIOD = 20
BB_STD = 2.0

VOLUME_MA_PERIOD = 20
VOLUME_MULTIPLIER = 1.5

ATR_PERIOD = 14
ATR_SL_MULT = 2.2
ATR_SL_MIN_PCT = 0.02
ATR_SL_MAX_PCT = 0.035

MAX_SCORE = 100
MIN_SCORE_TO_SIGNAL = 70

STRENGTH_MAX = 8.0
STRENGTH_MIN = 0.2

_CANDLE_CACHE: Dict[str, Any] = {}
CANDLE_CACHE_TTL = 2.0


# =========================
# HELPERS
# =========================

def _interval_ms(interval: str) -> int:
    m = {
        "5m": 300_000,
        "15m": 900_000,
        "1h": 3_600_000,
    }
    return int(m.get(interval, 0))


def _fetch_candles(coin: str, interval: str, limit: int):
    coin = norm_coin(coin)
    step = _interval_ms(interval)
    now = int(time.time() * 1000)
    start = now - step * max(limit, 50)

    payload = {
        "type": "candleSnapshot",
        "req": {
            "coin": coin,
            "interval": interval,
            "startTime": start,
            "endTime": now,
        },
    }

    r = make_request("/info", payload)
    if not isinstance(r, list) or not r:
        return [], "EMPTY"

    r.sort(key=lambda x: int(x.get("t", 0)))
    return r[-limit:], "OK"


def _extract(c):
    o, h, l, cl, v = [], [], [], [], []
    for x in c:
        o.append(float(x["o"]))
        h.append(float(x["h"]))
        l.append(float(x["l"]))
        cl.append(float(x["c"]))
        v.append(float(x["v"]))
    return o, h, l, cl, v


def _ema(series, period):
    if len(series) < period:
        return [None] * len(series)
    k = 2 / (period + 1)
    ema = sum(series[:period]) / period
    out = [None] * (period - 1) + [ema]
    for x in series[period:]:
        ema = x * k + ema * (1 - k)
        out.append(ema)
    return out


def _rma(series, period):
    if len(series) < period:
        return [None] * len(series)
    rma = sum(series[:period]) / period
    out = [None] * (period - 1) + [rma]
    for x in series[period:]:
        rma = (rma * (period - 1) + x) / period
        out.append(rma)
    return out


def _adx(h, l, c, period):
    n = len(c)
    tr, pdm, mdm = [0]*n, [0]*n, [0]*n
    for i in range(1, n):
        up = h[i] - h[i-1]
        dn = l[i-1] - l[i]
        pdm[i] = up if up > dn and up > 0 else 0
        mdm[i] = dn if dn > up and dn > 0 else 0
        tr[i] = max(h[i]-l[i], abs(h[i]-c[i-1]), abs(l[i]-c[i-1]))

    atr = _rma(tr, period)
    pdi = _rma(pdm, period)
    mdi = _rma(mdm, period)

    dx = [None]*n
    for i in range(n):
        if atr[i] and pdi[i] and mdi[i]:
            den = pdi[i] + mdi[i]
            if den > 0:
                dx[i] = 100 * abs(pdi[i] - mdi[i]) / den

    return _rma([x or 0 for x in dx], period)


def _last(x):
    for i in reversed(x):
        if i is not None:
            return i
    return None


def _atr(h, l, c, period=14):
    trs = []
    for i in range(1, len(c)):
        trs.append(max(h[i]-l[i], abs(h[i]-c[i-1]), abs(l[i]-c[i-1])))
    if len(trs) < period:
        return 0.0
    atr = sum(trs[:period]) / period
    for t in trs[period:]:
        atr = (atr * (period - 1) + t) / period
    return atr


# =========================
# ENTRY SIGNAL
# =========================

def get_entry_signal(symbol: str) -> dict:
    coin = norm_coin(symbol)

    c1, _ = _fetch_candles(coin, TF_1H, LOOKBACK_1H)
    c15, _ = _fetch_candles(coin, TF_15M, LOOKBACK_15M)
    c5, _ = _fetch_candles(coin, TF_5M, LOOKBACK_5M)

    if not c1 or not c15 or not c5:
        return {"signal": False, "reason": "NO_CANDLES"}

    _, h1, l1, cl1, _ = _extract(c1)
    _, h15, l15, cl15, _ = _extract(c15)
    _, h5, l5, cl5, v5 = _extract(c5)

    ema1 = _ema(cl1, EMA_TREND)
    adx1 = _adx(h1, l1, cl1, ADX_PERIOD)

    ema1_last = _last(ema1)
    adx1_last = _last(adx1)

    if not ema1_last or not adx1_last or adx1_last < ADX_MIN_TREND_1H:
        return {"signal": False, "reason": "NO_TREND_1H"}

    direction = "LONG" if cl1[-1] > ema1_last else "SHORT"

    adx15 = _adx(h15, l15, cl15, ADX_PERIOD)
    if _last(adx15) < ADX_MIN_TREND_15M:
        return {"signal": False, "reason": "ADX_15M"}

    score = 85.0
    strength = max(STRENGTH_MIN, min(STRENGTH_MAX, (score / 100) * STRENGTH_MAX))

    # ====== FIX CRÍTICO ======
    close_5 = cl5[-1]
    entry_price = (
        close_5 * 1.0006 if direction == "LONG"
        else close_5 * 0.9994
    )

    atr15 = _atr(h15, l15, cl15, ATR_PERIOD)
    atr_pct = atr15 / cl15[-1] if cl15[-1] > 0 else 0
    sl_pct = max(ATR_SL_MIN_PCT, min(atr_pct * ATR_SL_MULT, ATR_SL_MAX_PCT))

    return {
        "signal": True,
        "direction": "long" if direction == "LONG" else "short",
        "entry_price": round(entry_price, 6),
        "strength": round(strength, 4),
        "score": score,
        "sl_price_pct": round(sl_pct, 6),
  }
