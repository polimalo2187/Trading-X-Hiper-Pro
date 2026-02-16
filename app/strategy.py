import time
from typing import Dict, Any, List, Optional, Tuple

from app.hyperliquid_client import make_request, norm_coin

# =========================
# Timeframes / lookbacks
# =========================
TF_1H = "1h"
TF_15M = "15m"
TF_5M = "5m"

LOOKBACK_1H = 260
LOOKBACK_15M = 260
LOOKBACK_5M = 320

# =========================
# Trend filters (higher TF)
# =========================
EMA_TREND = 200
ADX_PERIOD = 14

# (Ajuste leve: menos estricto para que opere, sin caer en rango puro)
ADX_MIN_TREND_1H = 20
ADX_MIN_TREND_15M = 16

# =========================
# Risk / SL (NO toco tu idea, solo lo dejo igual)
# =========================
ATR_PERIOD = 14
ATR_SL_MULT = 2.2
ATR_SL_MIN_PCT = 0.02
ATR_SL_MAX_PCT = 0.035

# =========================
# Continuation timing (5m)
# =========================
TIMING_EMA_PERIOD_5M = 20
TIMING_EMA_TOL_PCT_5M = 0.0005   # 0.05% tolerancia vs EMA20 (evita bloqueos por ticks)
TIMING_ATR_PERIOD_5M = 14

TIMING_IMPULSE_ATR_MULT = 1.15   # un poco menos estricto para no bloquear todo
TIMING_MIN_RETRACE_5M = 0.10     # pullback mínimo
TIMING_MAX_RETRACE = 0.55        # pullback máximo (más permisivo)
TIMING_MAX_EXT_ATR_5M = 1.05     # tolera un poco más de extensión vs EMA20
TIMING_SWING_WINDOW_5M = 24      # swing reciente
TIMING_BREAK_LOOKBACK_5M = 6     # ruptura de micro estructura (más sensible)

# =========================
# Regime filters (5m) - para evitar lateralidad
# =========================
REGIME_ATR_SHORT_5M = 7
REGIME_ATR_LONG_5M = 40
REGIME_ATR_LOOKBACK_5M = 120

# (Ajuste leve: 0.85 estaba bloqueando demasiado en muchos coins)
REGIME_ATR_RATIO_MIN = 0.75

# Vela con intención (Ajuste leve)
MIN_BODY_TO_RANGE = 0.45

# Bollinger regime (5m)
BB_REGIME_PERIOD_5M = 20
BB_REGIME_STD_5M = 2.0
BB_MIN_BANDWIDTH = 0.009  # 0.9% (antes 1.2%)
BB_POS_MIN = 0.55         # antes 0.60

# Volumen
VOLUME_MA_PERIOD = 20

# =========================
# TURBO Breakout (expansión)
# =========================
TURBO_BOX_BARS_15M = 20
TURBO_BOX_MAX_WIDTH_PCT = 0.012   # caja estrecha (1.2%)
TURBO_BREAK_BUFFER_PCT = 0.0015   # 0.15% buffer para evitar wick-break
TURBO_VOL_MULT = 1.8              # volumen spike 5m vs MA20
TURBO_MIN_BODY_TO_RANGE = 0.50    # vela de ruptura con intención

# =========================
# Misc
# =========================
MAX_SCORE = 100
MIN_SCORE_TO_SIGNAL = 70

STRENGTH_MAX = 8.0
STRENGTH_MIN = 0.2

_CANDLE_CACHE: Dict[str, Any] = {}
CANDLE_CACHE_TTL = 2.0

LOG_SIGNAL_DIAGNOSTICS = True
STALE_MULTIPLIER = 3.0


def _log(msg: str) -> None:
    try:
        print(f"[STRATEGY {time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime())}] {msg}")
    except Exception:
        pass


def _interval_ms(interval: str) -> int:
    m = {
        "5m": 300_000,
        "15m": 900_000,
        "1h": 3_600_000,
    }
    return int(m.get(interval, 0))


def _parse_candle(x: dict) -> Optional[dict]:
    """Parse seguro (evita crashes por datos raros)."""
    try:
        return {
            "t": int(x.get("t", 0)),
            "o": float(x.get("o", 0)),
            "h": float(x.get("h", 0)),
            "l": float(x.get("l", 0)),
            "c": float(x.get("c", 0)),
            "v": float(x.get("v", 0)),
        }
    except Exception:
        return None


def _fetch_candles(coin: str, interval: str, limit: int) -> Tuple[List[dict], str]:
    # Cache ultra corto para no pegar la API muchas veces por loop
    try:
        coin = norm_coin(coin)
        if not coin:
            return [], "BAD_SYMBOL"

        key = f"{coin}:{interval}:{int(limit)}"
        now = time.time()
        cached = _CANDLE_CACHE.get(key)
        if cached and (now - float(cached.get("ts", 0))) < float(CANDLE_CACHE_TTL):
            return list(cached.get("data", [])), "OK_CACHE"
    except Exception:
        pass

    step = _interval_ms(interval)
    if step <= 0:
        return [], "BAD_INTERVAL"

    now_ms = int(time.time() * 1000)
    start = now_ms - step * max(int(limit), 50)

    payload = {
        "type": "candleSnapshot",
        "req": {
            "coin": coin,
            "interval": interval,
            "startTime": start,
            "endTime": now_ms,
        },
    }

    r = make_request("/info", payload)
    if r == {} or r is None:
        return [], "API_FAIL"
    if not isinstance(r, list) or not r:
        return [], "EMPTY"

    parsed: List[dict] = []
    for it in r:
        if isinstance(it, dict):
            c = _parse_candle(it)
            if c:
                parsed.append(c)

    if not parsed:
        return [], "EMPTY"

    try:
        parsed.sort(key=lambda x: int(x.get("t", 0)))
    except Exception:
        pass

    if len(parsed) > int(limit):
        parsed = parsed[-int(limit):]

    try:
        _CANDLE_CACHE[key] = {"ts": time.time(), "data": parsed}
    except Exception:
        pass

    return parsed, "OK"


def _extract(candles: List[dict]) -> Tuple[List[float], List[float], List[float], List[float], List[float]]:
    o, h, l, c, v = [], [], [], [], []
    for x in candles:
        try:
            o.append(float(x.get("o", 0)))
            h.append(float(x.get("h", 0)))
            l.append(float(x.get("l", 0)))
            c.append(float(x.get("c", 0)))
            v.append(float(x.get("v", 0)))
        except Exception:
            continue
    return o, h, l, c, v


def _last(xs: List[Optional[float]]) -> Optional[float]:
    for x in reversed(xs):
        if x is not None:
            return x
    return None


def _ema(series: List[float], period: int) -> List[Optional[float]]:
    if len(series) < period or period <= 1:
        return [None] * len(series)
    k = 2 / (period + 1)
    ema = sum(series[:period]) / period
    out: List[Optional[float]] = [None] * (period - 1) + [ema]
    for x in series[period:]:
        ema = x * k + ema * (1 - k)
        out.append(ema)
    return out


def _rma(series: List[float], period: int) -> List[Optional[float]]:
    if len(series) < period or period <= 1:
        return [None] * len(series)
    rma = sum(series[:period]) / period
    out: List[Optional[float]] = [None] * (period - 1) + [rma]
    for x in series[period:]:
        rma = (rma * (period - 1) + x) / period
        out.append(rma)
    return out


def _adx(h: List[float], l: List[float], c: List[float], period: int) -> List[Optional[float]]:
    n = len(c)
    if n < period + 2:
        return [None] * n

    tr = [0.0] * n
    pdm = [0.0] * n
    mdm = [0.0] * n

    for i in range(1, n):
        up = h[i] - h[i - 1]
        dn = l[i - 1] - l[i]
        pdm[i] = up if up > dn and up > 0 else 0.0
        mdm[i] = dn if dn > up and dn > 0 else 0.0
        tr[i] = max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1]))

    atr = _rma(tr, period)
    pdi = _rma(pdm, period)
    mdi = _rma(mdm, period)

    dx: List[float] = [0.0] * n
    for i in range(n):
        if atr[i] and pdi[i] and mdi[i]:
            den = float(pdi[i]) + float(mdi[i])
            if den > 0:
                dx[i] = 100.0 * abs(float(pdi[i]) - float(mdi[i])) / den

    return _rma(dx, period)


def _atr(h: List[float], l: List[float], c: List[float], period: int = 14) -> float:
    if len(c) < period + 2:
        return 0.0
    trs: List[float] = []
    for i in range(1, len(c)):
        trs.append(max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1])))
    if len(trs) < period:
        return 0.0
    atr = sum(trs[:period]) / period
    for t in trs[period:]:
        atr = (atr * (period - 1) + t) / period
    return float(atr)


def _sma(series: List[float], period: int) -> float:
    if period <= 0 or len(series) < period:
        return 0.0
    w = series[-period:]
    return float(sum(w) / period)


def _stdev(series: List[float], period: int) -> float:
    if period <= 1 or len(series) < period:
        return 0.0
    w = series[-period:]
    m = sum(w) / period
    var = sum((x - m) ** 2 for x in w) / period
    return float(var ** 0.5)


def _bbands(series: List[float], period: int, std_mult: float) -> Tuple[float, float, float]:
    mid = _sma(series, period)
    if mid <= 0:
        return 0.0, 0.0, 0.0
    sd = _stdev(series, period)
    upper = mid + std_mult * sd
    lower = mid - std_mult * sd
    return float(mid), float(upper), float(lower)


def _is_stale(candles: List[dict], interval: str) -> Tuple[bool, float, int]:
    """Devuelve (stale, age_seconds, last_t_ms)."""
    try:
        if not candles:
            return True, 999999.0, 0
        step = _interval_ms(interval)
        last_t = int(candles[-1].get("t", 0) or 0)
        if step <= 0:
            return False, 0.0, last_t
        now_ms = int(time.time() * 1000)
        age_ms = max(0, now_ms - last_t)
        age_s = age_ms / 1000.0
        threshold_ms = step * float(STALE_MULTIPLIER)
        return (age_ms > threshold_ms), age_s, last_t
    except Exception:
        return False, 0.0, 0


def _body_to_range(o: float, h: float, l: float, c: float) -> float:
    rng = max(0.0, h - l)
    if rng <= 0:
        return 0.0
    return float(abs(c - o) / rng)


def _passes_5m_timing_continuation(
    direction: str,
    o5: List[float],
    h5: List[float],
    l5: List[float],
    c5: List[float],
) -> Tuple[bool, str, Dict[str, Any]]:
    """Filtro de timing para entradas de CONTINUACIÓN (pullback + reanudación)."""
    diag: Dict[str, Any] = {}
    try:
        n = len(c5)
        if n < 60:
            return False, "5M_TOO_SHORT", {"n": n}

        close = float(c5[-1])
        atr5 = float(_atr(h5, l5, c5, int(TIMING_ATR_PERIOD_5M)) or 0.0)
        if atr5 <= 0:
            return False, "ATR5_BAD", {"atr5": atr5}

        ema20 = _last(_ema(c5, int(TIMING_EMA_PERIOD_5M)))
        if ema20 is None or float(ema20) <= 0:
            return False, "EMA20_BAD", {"ema20": ema20}

        ema20f = float(ema20)
        tol = float(TIMING_EMA_TOL_PCT_5M)

        dir_l = (direction or "").lower()
        if dir_l == "long" and close < ema20f * (1.0 - tol):
            return False, "BELOW_EMA20", {"close": close, "ema20": ema20f, "tol": tol}
        if dir_l == "short" and close > ema20f * (1.0 + tol):
            return False, "ABOVE_EMA20", {"close": close, "ema20": ema20f, "tol": tol}

        # Swing reciente (impulso actual)
        sw = min(int(TIMING_SWING_WINDOW_5M), n - 3)
        hs = h5[-(sw + 1):-1]
        ls = l5[-(sw + 1):-1]

        if len(hs) < 10 or len(ls) < 10:
            return False, "SWING_TOO_SHORT", {"sw": sw}

        ext_max = float(TIMING_MAX_EXT_ATR_5M) * atr5
        diag.update({"atr5": round(atr5, 10), "ema20": round(ema20f, 10), "ext_max": round(ext_max, 10)})

        if dir_l == "long":
            idx_low = min(range(len(ls)), key=lambda i: ls[i])
            idx_high = max(range(idx_low, len(hs)), key=lambda i: hs[i])
            A = float(ls[idx_low])
            B = float(hs[idx_high])
            impulse = B - A
            need = float(TIMING_IMPULSE_ATR_MULT) * atr5
            if impulse < need:
                return False, "WEAK_IMPULSE", {"impulse": impulse, "need": need, **diag}

            post_lows = ls[idx_high:] if idx_high < len(ls) else [ls[-1]]
            C = float(min(post_lows)) if post_lows else float(c5[-2])
            retrace = (B - C) / impulse if impulse > 0 else 1.0

            if retrace < float(TIMING_MIN_RETRACE_5M):
                return False, "NO_PULLBACK", {"retrace": retrace, "min": float(TIMING_MIN_RETRACE_5M), **diag}
            if retrace > float(TIMING_MAX_RETRACE):
                return False, "DEEP_PULLBACK", {"retrace": retrace, "max": float(TIMING_MAX_RETRACE), **diag}

            if (close - ema20f) > ext_max:
                return False, "TOO_EXTENDED", {"dist": (close - ema20f), "max": ext_max, **diag}

            # Reanudación: cerrar por encima de max de las últimas 2 velas (excluyendo actual)
            prev2 = c5[-3:-1]
            ref = float(max(prev2)) if prev2 else float(c5[-2])
            if close <= ref:
                return False, "NO_RESUME", {"ref": ref, "close": close, **diag}

            m = int(TIMING_BREAK_LOOKBACK_5M)
            recent_high = float(max(h5[-m-1:-1])) if len(h5) >= m + 2 else float(max(h5[:-1]))
            if close <= recent_high:
                return False, "NO_BREAK", {"recent_high": recent_high, "close": close, "m": m, **diag}

            return True, "OK", {"impulse": round(impulse, 10), "retrace": round(retrace, 4), **diag}

        # SHORT
        idx_high = max(range(len(hs)), key=lambda i: hs[i])
        idx_low = min(range(idx_high, len(ls)), key=lambda i: ls[i])
        A = float(hs[idx_high])
        B = float(ls[idx_low])
        impulse = A - B
        need = float(TIMING_IMPULSE_ATR_MULT) * atr5
        if impulse < need:
            return False, "WEAK_IMPULSE", {"impulse": impulse, "need": need, **diag}

        post_highs = hs[idx_low:] if idx_low < len(hs) else [hs[-1]]
        C = float(max(post_highs)) if post_highs else float(c5[-2])
        retrace = (C - B) / impulse if impulse > 0 else 1.0

        if retrace < float(TIMING_MIN_RETRACE_5M):
            return False, "NO_REBOUND", {"retrace": retrace, "min": float(TIMING_MIN_RETRACE_5M), **diag}
        if retrace > float(TIMING_MAX_RETRACE):
            return False, "DEEP_REBOUND", {"retrace": retrace, "max": float(TIMING_MAX_RETRACE), **diag}

        if (ema20f - close) > ext_max:
            return False, "TOO_EXTENDED", {"dist": (ema20f - close), "max": ext_max, **diag}

        prev2 = c5[-3:-1]
        ref = float(min(prev2)) if prev2 else float(c5[-2])
        if close >= ref:
            return False, "NO_RESUME", {"ref": ref, "close": close, **diag}

        m = int(TIMING_BREAK_LOOKBACK_5M)
        recent_low = float(min(l5[-m-1:-1])) if len(l5) >= m + 2 else float(min(l5[:-1]))
        if close >= recent_low:
            return False, "NO_BREAK", {"recent_low": recent_low, "close": close, "m": m, **diag}

        return True, "OK", {"impulse": round(impulse, 10), "retrace": round(retrace, 4), **diag}

    except Exception as e:
        return False, "TIMING_EXCEPTION", {"error": str(e)[:180], **diag}


def _passes_regime_filters_5m(
    direction: str,
    o5: List[float],
    h5: List[float],
    l5: List[float],
    c5: List[float],
) -> Tuple[bool, str, Dict[str, Any]]:
    """Gatekeepers suaves para evitar lateralidad + velas sin intención."""
    diag: Dict[str, Any] = {}
    try:
        n = len(c5)
        min_n = max(int(REGIME_ATR_LONG_5M) + 5, int(BB_REGIME_PERIOD_5M) + 5, 60)
        if n < min_n:
            return False, "REGIME_TOO_SHORT", {"n": n, "need": min_n}

        # ATR ratio (expansión)
        lb = min(int(REGIME_ATR_LOOKBACK_5M), n)
        o = o5[-lb:]
        h = h5[-lb:]
        lo = l5[-lb:]
        c = c5[-lb:]

        atr_s = float(_atr(h, lo, c, int(REGIME_ATR_SHORT_5M)) or 0.0)
        atr_l = float(_atr(h, lo, c, int(REGIME_ATR_LONG_5M)) or 0.0)
        ratio = (atr_s / atr_l) if atr_l > 0 else 0.0

        diag.update({
            "atr_s": round(atr_s, 10),
            "atr_l": round(atr_l, 10),
            "atr_ratio": round(ratio, 4),
            "atr_min_ratio": float(REGIME_ATR_RATIO_MIN),
        })

        if atr_s <= 0 or atr_l <= 0:
            return False, "REGIME_ATR_BAD", diag
        if ratio < float(REGIME_ATR_RATIO_MIN):
            return False, "REGIME_ATR_COMPRESS", diag

        # Candle intention
        o_last, h_last, l_last, c_last = float(o[-1]), float(h[-1]), float(lo[-1]), float(c[-1])
        body_ratio = _body_to_range(o_last, h_last, l_last, c_last)
        diag.update({
            "body_ratio": round(body_ratio, 4),
            "min_body_ratio": float(MIN_BODY_TO_RANGE),
        })
        if body_ratio < float(MIN_BODY_TO_RANGE):
            return False, "WEAK_CANDLE", diag

        # Bollinger: evita squeeze
        mid, upper, lower = _bbands(c, int(BB_REGIME_PERIOD_5M), float(BB_REGIME_STD_5M))
        if mid <= 0 or upper <= 0 or lower <= 0:
            return False, "BB_BAD", {**diag, "bb_mid": mid, "bb_upper": upper, "bb_lower": lower}

        bandwidth = (upper - lower) / mid if mid > 0 else 0.0
        diag.update({
            "bb_mid": round(mid, 10),
            "bb_bw": round(bandwidth, 4),
            "bb_min_bw": float(BB_MIN_BANDWIDTH),
        })
        if bandwidth < float(BB_MIN_BANDWIDTH):
            return False, "BB_SQUEEZE", diag

        # Posición favorable dentro del canal
        dir_l = (direction or "").lower()
        if dir_l not in ("long", "short"):
            return False, "BAD_DIR", {**diag, "direction": direction}

        if (upper - lower) <= 0:
            return False, "BB_RANGE_BAD", diag

        if dir_l == "long":
            pos = (c_last - lower) / (upper - lower)
        else:
            pos = (upper - c_last) / (upper - lower)

        diag.update({"bb_pos": round(float(pos), 4), "bb_pos_min": float(BB_POS_MIN)})
        if float(pos) < float(BB_POS_MIN):
            return False, "BB_POS_LOW", diag

        return True, "OK", diag

    except Exception as e:
        return False, "REGIME_EXCEPTION", {"error": str(e)[:180], **diag}


def _turbo_breakout_signal(
    direction: str,
    h15: List[float],
    l15: List[float],
    o5: List[float],
    h5: List[float],
    l5: List[float],
    c5: List[float],
    v5: List[float],
) -> Tuple[bool, str, Dict[str, Any]]:
    """Modo TURBO: compresión 15m + ruptura 5m con volumen."""
    diag: Dict[str, Any] = {}
    try:
        dir_l = (direction or "").lower()
        if dir_l not in ("long", "short"):
            return False, "BAD_DIR", {"direction": direction}

        if len(h15) < (TURBO_BOX_BARS_15M + 2) or len(c5) < 60 or len(v5) < VOLUME_MA_PERIOD + 2:
            return False, "TOO_SHORT", {"n15": len(h15), "n5": len(c5)}

        # Caja (15m) excluyendo la vela actual 15m
        nbox = int(TURBO_BOX_BARS_15M)
        box_h = float(max(h15[-(nbox + 1):-1]))
        box_l = float(min(l15[-(nbox + 1):-1]))
        box_mid = (box_h + box_l) / 2.0 if (box_h + box_l) != 0 else 0.0
        width_pct = ((box_h - box_l) / box_mid) if box_mid > 0 else 999.0

        diag.update({
            "box_h": round(box_h, 10),
            "box_l": round(box_l, 10),
            "width_pct": round(width_pct, 4),
            "max_width": float(TURBO_BOX_MAX_WIDTH_PCT),
        })

        if width_pct > float(TURBO_BOX_MAX_WIDTH_PCT):
            return False, "NO_COMPRESSION", diag

        # Volumen spike 5m
        vol_ma = _sma(v5, int(VOLUME_MA_PERIOD))
        v_now = float(v5[-1])
        if vol_ma <= 0:
            return False, "VOL_MA_BAD", {**diag, "vol_ma": vol_ma}

        vol_mult = v_now / vol_ma
        diag.update({"v_now": round(v_now, 6), "vol_ma": round(vol_ma, 6), "vol_mult": round(vol_mult, 3)})

        if vol_mult < float(TURBO_VOL_MULT):
            return False, "NO_VOLUME_SPIKE", diag

        # Vela de ruptura con intención
        o_now, h_now, l_now, c_now = float(o5[-1]), float(h5[-1]), float(l5[-1]), float(c5[-1])
        body_ratio = _body_to_range(o_now, h_now, l_now, c_now)
        diag.update({"body_ratio": round(body_ratio, 4), "min_body": float(TURBO_MIN_BODY_TO_RANGE)})
        if body_ratio < float(TURBO_MIN_BODY_TO_RANGE):
            return False, "WEAK_BREAK_CANDLE", diag

        # Ruptura con buffer
        buf = float(TURBO_BREAK_BUFFER_PCT)
        if dir_l == "long":
            need = box_h * (1.0 + buf)
            if c_now <= need:
                return False, "NO_BREAK_UP", {**diag, "close": c_now, "need": need}
        else:
            need = box_l * (1.0 - buf)
            if c_now >= need:
                return False, "NO_BREAK_DOWN", {**diag, "close": c_now, "need": need}

        return True, "OK", diag

    except Exception as e:
        return False, "TURBO_EXCEPTION", {"error": str(e)[:180], **diag}


def _compute_sl_pct(h15: List[float], l15: List[float], c15: List[float]) -> float:
    """SL por ATR (por precio). Mantiene tu lógica original."""
    atr15 = float(_atr(h15, l15, c15, int(ATR_PERIOD)) or 0.0)
    last_close_15 = float(c15[-1]) if c15 and c15[-1] else 0.0
    atr_pct = (atr15 / last_close_15) if last_close_15 > 0 else 0.0
    sl_pct = max(float(ATR_SL_MIN_PCT), min(float(atr_pct) * float(ATR_SL_MULT), float(ATR_SL_MAX_PCT)))
    return float(sl_pct)


def get_entry_signal(symbol: str) -> dict:
    """
    Señal de entrada:
    1) Tendencia 1H (EMA200 + ADX)
    2) Confirmación 15M (ADX)
    3) Intenta TURBO breakout (compresión->expansión)
    4) Si no hay TURBO, usa Continuation (timing + régimen) suavizado
    """
    try:
        coin = norm_coin(symbol)
        if not coin:
            return {"signal": False, "reason": "BAD_SYMBOL"}

        c1, st1 = _fetch_candles(coin, TF_1H, LOOKBACK_1H)
        c15, st15 = _fetch_candles(coin, TF_15M, LOOKBACK_15M)
        c5, st5 = _fetch_candles(coin, TF_5M, LOOKBACK_5M)

        if st1 in ("API_FAIL", "BAD_SYMBOL", "BAD_INTERVAL") or st15 in ("API_FAIL", "BAD_SYMBOL", "BAD_INTERVAL") or st5 in ("API_FAIL", "BAD_SYMBOL", "BAD_INTERVAL"):
            return {
                "signal": False,
                "reason": "CANDLES_FETCH_FAIL",
                "detail": {"1h": st1, "15m": st15, "5m": st5},
                "coin": coin,
            }

        if not c1 or not c15 or not c5:
            return {"signal": False, "reason": "NO_CANDLES", "coin": coin}

        stale1, age1, t1 = _is_stale(c1, TF_1H)
        stale15, age15, t15 = _is_stale(c15, TF_15M)
        stale5, age5, t5 = _is_stale(c5, TF_5M)
        if stale1 or stale15 or stale5:
            return {
                "signal": False,
                "reason": "STALE_CANDLES",
                "coin": coin,
                "age_s": {"1h": round(age1, 1), "15m": round(age15, 1), "5m": round(age5, 1)},
                "last_t": {"1h": t1, "15m": t15, "5m": t5},
            }

        _, h1, l1, cl1, _ = _extract(c1)
        _, h15, l15, cl15, _ = _extract(c15)
        o5, h5, l5, cl5, v5 = _extract(c5)

        if not cl1 or not cl15 or not cl5:
            return {"signal": False, "reason": "BAD_CANDLES_PARSE", "coin": coin}

        # ===== 1H Trend =====
        ema1_last = _last(_ema(cl1, int(EMA_TREND)))
        adx1_last = _last(_adx(h1, l1, cl1, int(ADX_PERIOD)))
        if ema1_last is None or adx1_last is None:
            return {"signal": False, "reason": "NO_TREND_1H", "coin": coin}

        if float(adx1_last) < float(ADX_MIN_TREND_1H):
            return {"signal": False, "reason": "NO_TREND_1H", "coin": coin, "adx_1h": round(float(adx1_last), 2)}

        direction = "long" if float(cl1[-1]) > float(ema1_last) else "short"

        # ===== 15M confirmation =====
        adx15_last = _last(_adx(h15, l15, cl15, int(ADX_PERIOD)))
        if adx15_last is None or float(adx15_last) < float(ADX_MIN_TREND_15M):
            return {"signal": False, "reason": "ADX_15M", "coin": coin, "adx_15m": None if adx15_last is None else round(float(adx15_last), 2)}

        # ===== TURBO breakout =====
        ok_turbo, r_turbo, d_turbo = _turbo_breakout_signal(direction, h15, l15, o5, h5, l5, cl5, v5)
        if ok_turbo:
            score = 92.0
            strength = max(STRENGTH_MIN, min(STRENGTH_MAX, (score / 100.0) * STRENGTH_MAX))
            sl_pct = _compute_sl_pct(h15, l15, cl15)

            out = {
                "signal": True,
                "mode": "TURBO_BREAKOUT",
                "direction": direction,
                "strength": round(float(strength), 4),
                "score": float(score),
                "sl_price_pct": round(float(sl_pct), 6),
                "coin": coin,
                "close_5": round(float(cl5[-1]), 6),
                "last_candle_t_5m": int(t5),
                "diag": d_turbo,
            }
            if LOG_SIGNAL_DIAGNOSTICS:
                _log(f"TURBO coin={coin} dir={direction} close_5={out['close_5']} sl_pct={out['sl_price_pct']} diag={d_turbo}")
            return out

        # ===== Continuation =====
        ok5, reason5, diag5 = _passes_5m_timing_continuation(direction, o5, h5, l5, cl5)
        if not ok5:
            if LOG_SIGNAL_DIAGNOSTICS:
                _log(f"BLOCK coin={coin} dir={direction} reason=TIMING_{reason5} diag={diag5}")
            return {"signal": False, "reason": f"TIMING_5M_{reason5}", "coin": coin, "diag": diag5}

        okr, rr, diagr = _passes_regime_filters_5m(direction, o5, h5, l5, cl5)
        if not okr:
            if LOG_SIGNAL_DIAGNOSTICS:
                _log(f"BLOCK coin={coin} dir={direction} reason=REGIME_{rr} diag={diagr}")
            return {"signal": False, "reason": f"REGIME_5M_{rr}", "coin": coin, "diag": diagr}

        score = 85.0
        strength = max(STRENGTH_MIN, min(STRENGTH_MAX, (score / 100.0) * STRENGTH_MAX))

        sl_pct = _compute_sl_pct(h15, l15, cl15)

        out = {
            "signal": True,
            "mode": "CONTINUATION",
            "direction": direction,
            "strength": round(float(strength), 4),
            "score": float(score),
            "sl_price_pct": round(float(sl_pct), 6),
            "coin": coin,
            "close_5": round(float(cl5[-1]), 6),
            "last_candle_t_5m": int(t5),
        }

        if LOG_SIGNAL_DIAGNOSTICS:
            _log(
                f"SIGNAL coin={coin} dir={out['direction']} mode={out['mode']} "
                f"close_5={out['close_5']} t5={out['last_candle_t_5m']} age5s={round(age5, 1)} "
                f"sl_pct={out['sl_price_pct']}"
            )

        return out

    except Exception as e:
        return {"signal": False, "reason": "STRATEGY_EXCEPTION", "error": str(e)[:180]}
