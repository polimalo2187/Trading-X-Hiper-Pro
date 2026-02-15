import time
from typing import Dict, Any, List, Optional, Tuple
from app.hyperliquid_client import make_request, norm_coin
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
TIMING_EMA_PERIOD_5M = 20
TIMING_ATR_PERIOD_5M = 14
TIMING_IMPULSE_ATR_MULT = 1.2
TIMING_MAX_RETRACE = 0.50
TIMING_LOOKBACK_5M = 60
TIMING_CONFIRM_BARS_5M = 3

# =========================
# NUEVOS FILTROS (entrada)
# =========================
# 1) Régimen/expansión: evita operar en compresión/lateral (5m)
REGIME_ATR_SHORT_5M = 7
REGIME_ATR_LONG_5M = 40
REGIME_ATR_RATIO_MIN = 0.85  # si ATR corto < ATR largo*ratio => bloquear
REGIME_ATR_LOOKBACK_5M = 120  # velas 5m usadas para el cálculo

# 2) Vela con intención: evita indecisión (5m)
MIN_BODY_TO_RANGE = 0.55  # cuerpo/rango mínimo para permitir entrada

# 3) Bandas de Bollinger (5m): evita operar en "squeeze" y exige posición favorable
BB_REGIME_PERIOD_5M = 20
BB_REGIME_STD_5M = 2.0
BB_MIN_BANDWIDTH = 0.012  # (upper-lower)/mid mínimo. 0.012 = 1.2%
BB_POS_MIN = 0.60         # posición mínima dentro del canal (0..1). 0.60 = top/bottom 40%

MAX_SCORE = 100
MIN_SCORE_TO_SIGNAL = 70
STRENGTH_MAX = 8.0
STRENGTH_MIN = 0.2
_CANDLE_CACHE: Dict[str, Any] = {}
CANDLE_CACHE_TTL = 2.0
LOG_SIGNAL_DIAGNOSTICS = True
STALE_MULTIPLIER = 3.0
def _log(msg: str):
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
def _fetch_candles(coin: str, interval: str, limit: int):
    coin = norm_coin(coin)
    if not coin:
        return [], "BAD_SYMBOL"
    step = _interval_ms(interval)
    if step <= 0:
        return [], "BAD_INTERVAL"
    now = int(time.time() * 1000)
    start = now - step * max(int(limit), 50)
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
    if len(parsed) > limit:
        parsed = parsed[-limit:]
    return parsed, "OK"
def _extract(c):
    o, h, l, cl, v = [], [], [], [], []
    for x in c:
        try:
            o.append(float(x.get("o", 0)))
            h.append(float(x.get("h", 0)))
            l.append(float(x.get("l", 0)))
            cl.append(float(x.get("c", 0)))
            v.append(float(x.get("v", 0)))
        except Exception:
            continue
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
def _bbands(series: List[float], period: int = 20, std_mult: float = 2.0) -> Tuple[float, float, float]:
    """Devuelve (mid, upper, lower) de Bandas de Bollinger usando SMA y desviación estándar."""
    try:
        n = len(series)
        if n < int(period) or int(period) <= 1:
            return 0.0, 0.0, 0.0
        window = series[-int(period):]
        mid = sum(window) / float(period)
        var = sum((x - mid) ** 2 for x in window) / float(period)
        sd = (var ** 0.5)
        upper = mid + float(std_mult) * sd
        lower = mid - float(std_mult) * sd
        return float(mid), float(upper), float(lower)
    except Exception:
        return 0.0, 0.0, 0.0

def _is_stale(candles: List[dict], interval: str) -> Tuple[bool, float, int]:
    """
    Devuelve (stale, age_seconds, last_t_ms).
    stale si el último candle está demasiado viejo.
    """
    try:
        if not candles:
            return True, 999999.0, 0
        step = _interval_ms(interval)
        if step <= 0:
            return False, 0.0, int(candles[-1].get("t", 0) or 0)
        last_t = int(candles[-1].get("t", 0) or 0)
        now_ms = int(time.time() * 1000)
        age_ms = max(0, now_ms - last_t)
        age_s = age_ms / 1000.0
        threshold_ms = step * float(STALE_MULTIPLIER)
        return (age_ms > threshold_ms), age_s, last_t
    except Exception:
        return False, 0.0, 0
def _ema_last(series, period: int) -> float:
    e = _ema(series, int(period))
    v = _last(e)
    return float(v) if v is not None else 0.0
def _passes_5m_timing_filters(
    direction: str,
    h5: List[float],
    l5: List[float],
    cl5: List[float],
    now_close: float,
) -> Tuple[bool, str, Dict[str, Any]]:
    """
    Bloqueador de entradas tardías.
    - Requiere impulso previo real (>= TIMING_IMPULSE_ATR_MULT * ATR5m)
    - Requiere retrace <= TIMING_MAX_RETRACE
    - Requiere que el precio esté del lado correcto de EMA20 (5m)
    - Confirmación mínima: rompe extremo reciente (evita entrar en el primer rebote)
    """
    diag: Dict[str, Any] = {}
    try:
        n = len(cl5)
        if n < 30:
            return False, "5M_TOO_SHORT", {"n": n}
        lb = min(int(TIMING_LOOKBACK_5M), n - 1)
        h = h5[-lb:]
        lo = l5[-lb:]
        c = cl5[-lb:]
        atr5 = float(_atr(h, lo, c, int(TIMING_ATR_PERIOD_5M)) or 0.0)
        if atr5 <= 0:
            return False, "ATR5_BAD", {"atr5": atr5}
        ema20 = float(_ema_last(c, int(TIMING_EMA_PERIOD_5M)) or 0.0)
        if ema20 <= 0:
            return False, "EMA20_BAD", {"ema20": ema20}
        diag.update({"atr5": round(atr5, 8), "ema20": round(ema20, 8)})
        dir_l = (direction or "").lower()
        if dir_l not in ("long", "short"):
            return False, "BAD_DIR", {"direction": direction}
        if dir_l == "long" and now_close < ema20:
            return False, "BELOW_EMA20", {"close": now_close, "ema20": ema20}
        if dir_l == "short" and now_close > ema20:
            return False, "ABOVE_EMA20", {"close": now_close, "ema20": ema20}
        if dir_l == "long":
            idx_high = max(range(len(h)), key=lambda i: h[i])
            idx_low = min(range(0, idx_high + 1), key=lambda i: lo[i])
            A = float(lo[idx_low])
            B = float(h[idx_high])
            impulse = B - A
            if impulse < float(TIMING_IMPULSE_ATR_MULT) * atr5:
                return False, "WEAK_IMPULSE", {"impulse": impulse, "need": float(TIMING_IMPULSE_ATR_MULT) * atr5}
            post_lows = lo[idx_high:] if idx_high < len(lo) else lo[-1:]
            C = float(min(post_lows)) if post_lows else float(c[-1])
            retrace = (B - C) / impulse if impulse > 0 else 1.0
            if retrace > float(TIMING_MAX_RETRACE):
                return False, "DEEP_PULLBACK", {"retrace": retrace}
            m = int(TIMING_CONFIRM_BARS_5M)
            recent_high = max(h[-m-1:-1]) if len(h) >= m + 1 else max(h[:-1])
            if now_close <= float(recent_high):
                return False, "NO_BREAK_HIGH", {"recent_high": recent_high, "m": m}
            diag.update({"impulse": round(impulse, 8), "retrace": round(retrace, 4), "recent_high": round(float(recent_high), 8)})
            return True, "OK", diag
        idx_low = min(range(len(lo)), key=lambda i: lo[i])
        idx_high = max(range(0, idx_low + 1), key=lambda i: h[i])
        A = float(h[idx_high])
        B = float(lo[idx_low])
        impulse = A - B
        if impulse < float(TIMING_IMPULSE_ATR_MULT) * atr5:
            return False, "WEAK_IMPULSE", {"impulse": impulse, "need": float(TIMING_IMPULSE_ATR_MULT) * atr5}
        post_highs = h[idx_low:] if idx_low < len(h) else h[-1:]
        C = float(max(post_highs)) if post_highs else float(c[-1])
        retrace = (C - B) / impulse if impulse > 0 else 1.0
        if retrace > float(TIMING_MAX_RETRACE):
            return False, "DEEP_REBOUND", {"retrace": retrace}
        m = int(TIMING_CONFIRM_BARS_5M)
        recent_low = min(lo[-m-1:-1]) if len(lo) >= m + 1 else min(lo[:-1])
        if now_close >= float(recent_low):
            return False, "NO_BREAK_LOW", {"recent_low": recent_low, "m": m}
        diag.update({"impulse": round(impulse, 8), "retrace": round(retrace, 4), "recent_low": round(float(recent_low), 8)})
        return True, "OK", diag
    except Exception as e:
        return False, "TIMING_EXCEPTION", {"error": str(e)[:180], **diag}
def _passes_regime_filters_5m(
    direction: str,
    o5: List[float],
    h5: List[float],
    l5: List[float],
    cl5: List[float],
) -> Tuple[bool, str, Dict[str, Any]]:
    """
    Gatekeepers para evitar operar en lateral/compresión y velas débiles.
    NO altera tu estrategia; solo bloquea entradas de baja calidad.

    Incluye:
    - ATR corto vs ATR largo (expansión)
    - Vela con intención (cuerpo/rango)
    - Bandas de Bollinger: evita squeeze y exige posición favorable dentro del canal
    """
    diag: Dict[str, Any] = {}
    try:
        n = len(cl5)
        min_n = max(int(REGIME_ATR_LONG_5M) + 5, int(BB_REGIME_PERIOD_5M) + 5, 60)
        if n < min_n:
            return False, "REGIME_TOO_SHORT", {"n": n, "need": min_n}

        # --- 1) Expansión de volatilidad (ATR corto vs largo) ---
        lb = min(int(REGIME_ATR_LOOKBACK_5M), n)
        o = o5[-lb:]
        h = h5[-lb:]
        lo = l5[-lb:]
        c = cl5[-lb:]

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

        # --- 2) Vela con intención (cuerpo/rango) ---
        o_last = float(o[-1])
        c_last = float(c[-1])
        h_last = float(h[-1])
        l_last = float(lo[-1])

        rng = max(0.0, h_last - l_last)
        body = abs(c_last - o_last)
        body_ratio = (body / rng) if rng > 0 else 0.0

        diag.update({
            "body": round(body, 10),
            "range": round(rng, 10),
            "body_ratio": round(body_ratio, 4),
            "min_body_ratio": float(MIN_BODY_TO_RANGE),
        })

        if rng <= 0:
            return False, "REGIME_RANGE_BAD", diag
        if body_ratio < float(MIN_BODY_TO_RANGE):
            return False, "WEAK_CANDLE", diag

        # --- 3) Bandas de Bollinger (squeeze + posición) ---
        mid, upper, lower = _bbands(c, int(BB_REGIME_PERIOD_5M), float(BB_REGIME_STD_5M))
        if mid <= 0 or upper <= 0 or lower <= 0:
            return False, "BB_BAD", {**diag, "bb_mid": mid, "bb_upper": upper, "bb_lower": lower}

        bandwidth = (upper - lower) / mid if mid > 0 else 0.0
        diag.update({
            "bb_mid": round(mid, 10),
            "bb_upper": round(upper, 10),
            "bb_lower": round(lower, 10),
            "bb_bw": round(bandwidth, 4),
            "bb_min_bw": float(BB_MIN_BANDWIDTH),
        })

        # Evita squeeze (lateral)
        if bandwidth < float(BB_MIN_BANDWIDTH):
            return False, "BB_SQUEEZE", diag

        # Exige posición favorable dentro del canal (continuación, no mean-reversion)
        dir_l = (direction or "").lower()
        if dir_l not in ("long", "short"):
            return False, "BAD_DIR", {**diag, "direction": direction}

        if dir_l == "long":
            # posición 0..1: 0=lower, 1=upper
            pos = (c_last - lower) / (upper - lower) if (upper - lower) > 0 else 0.0
            diag["bb_pos"] = round(pos, 4)
            diag["bb_pos_min"] = float(BB_POS_MIN)
            if pos < float(BB_POS_MIN):
                return False, "BB_POS_LOW", diag
        else:
            pos = (upper - c_last) / (upper - lower) if (upper - lower) > 0 else 0.0
            diag["bb_pos"] = round(pos, 4)
            diag["bb_pos_min"] = float(BB_POS_MIN)
            if pos < float(BB_POS_MIN):
                return False, "BB_POS_LOW", diag

        return True, "OK", diag

    except Exception as e:
        return False, "REGIME_EXCEPTION", {"error": str(e)[:180], **diag}

def get_entry_signal(symbol: str) -> dict:
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
        ema1 = _ema(cl1, EMA_TREND)
        adx1 = _adx(h1, l1, cl1, ADX_PERIOD)
        ema1_last = _last(ema1)
        adx1_last = _last(adx1)
        if (ema1_last is None) or (adx1_last is None) or (float(adx1_last) < float(ADX_MIN_TREND_1H)):
            return {"signal": False, "reason": "NO_TREND_1H", "coin": coin}
        direction = "LONG" if float(cl1[-1]) > float(ema1_last) else "SHORT"
        adx15 = _adx(h15, l15, cl15, ADX_PERIOD)
        adx15_last = _last(adx15)
        if adx15_last is None or float(adx15_last) < float(ADX_MIN_TREND_15M):
            return {"signal": False, "reason": "ADX_15M", "coin": coin, "adx_15m": None if adx15_last is None else round(float(adx15_last), 2)}
        score = 85.0
        strength = max(STRENGTH_MIN, min(STRENGTH_MAX, (score / 100) * STRENGTH_MAX))
        close_5 = float(cl5[-1])

        # --- Timing 5m: evitar entradas tardías (rebote/pullback) ---
        out_dir = "long" if direction == "LONG" else "short"
        ok5, reason5, diag5 = _passes_5m_timing_filters(
            out_dir,
            h5, l5, cl5, close_5,
        )
        if not ok5:
            if LOG_SIGNAL_DIAGNOSTICS:
                _log(f"BLOCK coin={coin} dir={out_dir} reason={reason5} diag={diag5}")
            return {"signal": False, "reason": f"TIMING_5M_{reason5}", "coin": coin, "diag": diag5}


        # --- NUEVO: Régimen/expansión + vela con intención + Bollinger (5m) ---
        okr, rr, diagr = _passes_regime_filters_5m(out_dir, o5, h5, l5, cl5)
        if not okr:
            if LOG_SIGNAL_DIAGNOSTICS:
                _log(f"BLOCK coin={coin} dir={out_dir} reason={rr} diag={diagr}")
            return {"signal": False, "reason": f"REGIME_5M_{rr}", "coin": coin, "diag": diagr}

        # SL por ATR (por precio)
        atr15 = float(_atr(h15, l15, cl15, ATR_PERIOD) or 0.0)
        last_close_15 = float(cl15[-1]) if cl15[-1] else 0.0
        atr_pct = (atr15 / last_close_15) if last_close_15 > 0 else 0.0
        sl_pct = max(float(ATR_SL_MIN_PCT), min(float(atr_pct) * float(ATR_SL_MULT), float(ATR_SL_MAX_PCT)))

        out = {
            "signal": True,
            "direction": "long" if direction == "LONG" else "short",
            "strength": round(float(strength), 4),
            "score": float(score),
            "sl_price_pct": round(float(sl_pct), 6),

            # Diagnóstico mínimo (no cambia la estrategia)
            "coin": coin,
            "close_5": round(float(close_5), 6),
            "last_candle_t_5m": int(t5),
        }

        if LOG_SIGNAL_DIAGNOSTICS:
            _log(
                f"SIGNAL coin={coin} dir={out['direction']} "
                f"close_5={out['close_5']} "
                f"t5={out['last_candle_t_5m']} age5s={round(age5,1)} "
                f"sl_pct={out['sl_price_pct']}"
            )

        return out

    except Exception as e:
        return {"signal": False, "reason": "STRATEGY_EXCEPTION", "error": str(e)[:180]}