
import os
import time
from typing import Dict, Any, List, Optional, Tuple
from app.hyperliquid_client import make_request, norm_coin

TF_5M = "5m"
LOOKBACK_5M = 320

EMA_FAST = 20
EMA_MID = 50
EMA_SLOW = 200
ADX_PERIOD = 14
ATR_PERIOD = 14
EMA_SLOPE_LOOKBACK = 8

# Universo dinámico: por defecto permite cualquier par de calidad suficiente
# y bloquea memecoins probables. Si defines ALLOWED_TRADE_SYMBOLS, esa allowlist manda.
_ALLOWED_ENV = os.getenv("ALLOWED_TRADE_SYMBOLS", "").strip()
ALLOWED_SYMBOLS = {x.strip().upper() for x in _ALLOWED_ENV.split(",") if x.strip()}

_BLOCKED_MEME_ENV = os.getenv("BLOCKED_MEME_KEYWORDS", "").strip()
_DEFAULT_MEME_KEYWORDS = {
    "DOGE", "SHIB", "PEPE", "BONK", "FLOKI", "WIF", "POPCAT", "PENGU", "TURBO",
    "MOG", "BOME", "MYRO", "BRETT", "NEIRO", "MEME", "BABYDOGE", "KISHU", "WOJAK",
    "PONKE", "MEW", "TRUMP", "MAGA", "HARRYPOTTEROBAMA", "HYPE",
}
BLOCKED_MEME_KEYWORDS = {x.strip().upper() for x in _BLOCKED_MEME_ENV.split(",") if x.strip()} or _DEFAULT_MEME_KEYWORDS
MIN_CANDLES_REQUIRED = 260
MIN_NONZERO_VOLUME_RATIO = 0.92

ADX_MIN = 17.8
ATR_PCT_MIN = 0.0009
ATR_PCT_MAX = 0.0145
ATR_PCT_EXTREME = 0.0175

BREAKOUT_LOOKBACK = 24
BREAKOUT_MIN_ATR_FRAC = 0.10
BREAKOUT_CONFIRM_CLOSE_ATR = 0.14
BREAKOUT_MAX_AGE_BARS = 4
RETEST_TOL_ATR = 0.45
RETEST_HARD_FAIL_ATR = 1.05
MAX_CHASE_ATR = 1.10
MIN_BODY_RATIO = 0.30
BREAKOUT_MIN_BODY_RATIO = 0.34
BREAKOUT_MIN_RVOL = 1.05
TRIGGER_MIN_RVOL = 0.95
TRIGGER_CLOSE_POS_LONG_MIN = 0.60
TRIGGER_CLOSE_POS_SHORT_MAX = 0.40
TREND_STACK_MIN_PCT = 0.00075

ATR_SL_MULT = 1.10
ATR_SL_MIN_PCT = 0.0058
ATR_SL_MAX_PCT = 0.0125
SWING_BUFFER_ATR = 0.22

MAX_SCORE = 100.0
MIN_SCORE_TO_SIGNAL = 78.0
STRENGTH_MIN = 0.20
STRENGTH_MAX = 0.97

LOG_SIGNAL_DIAGNOSTICS = True


def _log(msg: str):
    try:
        print(f"[STRATEGY {time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime())}] {msg}")
    except Exception:
        pass


def _interval_ms(interval: str) -> int:
    return {"5m": 300_000}.get(interval, 0)


def _parse_candle(x: dict) -> Optional[dict]:
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

    try:
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
        resp = make_request("/info", payload)
    except Exception:
        return [], "API_FAIL"

    if resp == {} or resp is None:
        return [], "API_FAIL"
    if not isinstance(resp, list) or not resp:
        return [], "EMPTY"

    candles: List[dict] = []
    for row in resp:
        if isinstance(row, dict):
            item = _parse_candle(row)
            if item:
                candles.append(item)

    if not candles:
        return [], "EMPTY"

    try:
        candles.sort(key=lambda x: int(x.get("t", 0)))
    except Exception:
        pass

    if len(candles) > limit:
        candles = candles[-limit:]
    return candles, "OK"


def _extract(candles):
    o, h, l, c, v = [], [], [], [], []
    for x in candles:
        o.append(float(x["o"]))
        h.append(float(x["h"]))
        l.append(float(x["l"]))
        c.append(float(x["c"]))
        v.append(float(x["v"]))
    return o, h, l, c, v


def _ema(series, period):
    if not series:
        return []
    out = [float(series[0])]
    k = 2.0 / (float(period) + 1.0)
    for i in range(1, len(series)):
        out.append((float(series[i]) * k) + (out[-1] * (1.0 - k)))
    return out


def _rma(series, period):
    if not series:
        return []
    period = max(1, int(period))
    if len(series) < period:
        avg = sum(float(x) for x in series) / len(series)
        return [avg for _ in series]
    out = [0.0] * len(series)
    first = sum(float(x) for x in series[:period]) / period
    out[period - 1] = first
    for i in range(period, len(series)):
        out[i] = ((out[i - 1] * (period - 1)) + float(series[i])) / period
    for i in range(period - 1):
        out[i] = out[period - 1]
    return out


def _adx(h, l, c, period):
    if len(h) < period + 2 or len(l) < period + 2 or len(c) < period + 2:
        return []
    plus_dm, minus_dm, tr = [0.0], [0.0], [0.0]
    for i in range(1, len(c)):
        up = float(h[i]) - float(h[i - 1])
        down = float(l[i - 1]) - float(l[i])
        plus_dm.append(up if up > down and up > 0 else 0.0)
        minus_dm.append(down if down > up and down > 0 else 0.0)
        tr.append(max(float(h[i]) - float(l[i]), abs(float(h[i]) - float(c[i - 1])), abs(float(l[i]) - float(c[i - 1]))))
    atr = _rma(tr, period)
    plus = [100.0 * (p / a) if a else 0.0 for p, a in zip(_rma(plus_dm, period), atr)]
    minus = [100.0 * (m / a) if a else 0.0 for m, a in zip(_rma(minus_dm, period), atr)]
    dx = [100.0 * abs(p - m) / (p + m) if (p + m) else 0.0 for p, m in zip(plus, minus)]
    return _rma(dx, period)


def _last(x):
    return x[-1] if x else None


def _atr(h, l, c, period=14):
    if len(h) < 2:
        return 0.0
    tr = [0.0]
    for i in range(1, len(c)):
        tr.append(max(float(h[i]) - float(l[i]), abs(float(h[i]) - float(c[i - 1])), abs(float(l[i]) - float(c[i - 1]))))
    return float(_last(_rma(tr, period)) or 0.0)


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _pct_change(now: float, prev: float) -> float:
    if prev == 0:
        return 0.0
    return (now - prev) / prev


def _median(values: List[float]) -> float:
    vals = sorted(float(x) for x in values if x is not None)
    if not vals:
        return 0.0
    mid = len(vals) // 2
    if len(vals) % 2:
        return float(vals[mid])
    return float((vals[mid - 1] + vals[mid]) / 2.0)


def _relative_volume(volumes: List[float], idx: int, lookback: int = 20) -> float:
    if idx < 0 or idx >= len(volumes):
        return 1.0
    start = max(0, idx - max(lookback, 8))
    window = [max(float(x), 0.0) for x in volumes[start:idx]]
    nonzero = [x for x in window if x > 0.0]
    baseline = _median(nonzero or window)
    if baseline <= 0.0:
        return 1.0
    return max(0.0, float(volumes[idx]) / baseline)


def _close_position_in_range(o: float, h: float, l: float, c: float) -> float:
    rng = max(h - l, 1e-12)
    return _clamp((c - l) / rng, 0.0, 1.0)


def _lower_wick_ratio(o: float, h: float, l: float, c: float) -> float:
    rng = max(h - l, 1e-12)
    return _clamp((min(o, c) - l) / rng, 0.0, 1.0)


def _upper_wick_ratio(o: float, h: float, l: float, c: float) -> float:
    rng = max(h - l, 1e-12)
    return _clamp((h - max(o, c)) / rng, 0.0, 1.0)


def _is_stale(candles: List[dict], interval: str) -> Tuple[bool, float, int]:
    if not candles:
        return True, 9e9, 0
    last_t = int(candles[-1]["t"])
    age_s = max(0.0, (time.time() * 1000.0 - last_t) / 1000.0)
    interval_s = _interval_ms(interval) / 1000.0
    return age_s > (interval_s * 3.0), age_s, last_t




def _base_coin(symbol: str) -> str:
    s = str(symbol or "").upper()
    for suffix in ("-PERP", "-USDC", "-USD", "-USDT"):
        if s.endswith(suffix):
            s = s[: -len(suffix)]
    return s


def _is_probable_meme_symbol(symbol: str) -> bool:
    base = _base_coin(symbol)
    if not base:
        return False
    return any(key in base for key in BLOCKED_MEME_KEYWORDS)


def _validate_symbol_quality(coin: str, candles: List[dict]) -> Tuple[bool, str, Dict[str, Any]]:
    if ALLOWED_SYMBOLS and coin.upper() not in ALLOWED_SYMBOLS:
        return False, "SYMBOL_NOT_ALLOWED", {"coin": coin}
    if _is_probable_meme_symbol(coin):
        return False, "MEME_SYMBOL_BLOCKED", {"coin": coin, "base": _base_coin(coin)}
    if not candles or len(candles) < MIN_CANDLES_REQUIRED:
        return False, "NO_CANDLES", {"bars": len(candles) if candles else 0, "min_bars": MIN_CANDLES_REQUIRED}
    valid = [x for x in candles if float(x.get("c", 0.0) or 0.0) > 0.0 and float(x.get("h", 0.0) or 0.0) >= float(x.get("l", 0.0) or 0.0)]
    if len(valid) < MIN_CANDLES_REQUIRED:
        return False, "BAD_CANDLES_PARSE", {"valid_bars": len(valid), "min_bars": MIN_CANDLES_REQUIRED}
    recent = valid[-MIN_CANDLES_REQUIRED:]
    nonzero_vol_ratio = sum(1 for x in recent if float(x.get("v", 0.0) or 0.0) > 0.0) / max(len(recent), 1)
    if nonzero_vol_ratio < MIN_NONZERO_VOLUME_RATIO:
        return False, "LOW_ACTIVITY_SYMBOL", {"nonzero_vol_ratio": round(nonzero_vol_ratio, 4)}
    return True, "OK", {"base": _base_coin(coin), "bars": len(valid), "nonzero_vol_ratio": round(nonzero_vol_ratio, 4)}

def _volatility_regime_from_atr_pct(atr_pct: float) -> str:
    if atr_pct <= 0.0030:
        return "low"
    if atr_pct <= 0.0075:
        return "normal"
    if atr_pct <= 0.0120:
        return "high"
    return "extreme"


def _body_ratio(o: float, h: float, l: float, c: float) -> float:
    rng = max(h - l, 1e-12)
    return abs(c - o) / rng


def _detect_breakout_retest_long(
    o: List[float], h: List[float], l: List[float], c: List[float], v: List[float], ema20: List[float], ema50: List[float], atr: float
) -> Tuple[bool, str, Dict[str, Any]]:
    if len(c) < max(BREAKOUT_LOOKBACK + BREAKOUT_MAX_AGE_BARS + 4, 80):
        return False, "NOT_ENOUGH_BARS", {}
    breakout_idx = None
    breakout_level = None
    breakout_rvol = 1.0
    breakout_body = 0.0
    breakout_close_dist_atr = 0.0
    breakout_buffer = atr * BREAKOUT_MIN_ATR_FRAC
    start = len(c) - BREAKOUT_MAX_AGE_BARS - 2
    end = len(c) - 1
    for i in range(start, end):
        left_start = max(0, i - BREAKOUT_LOOKBACK)
        if i - left_start < 8:
            continue
        level = max(h[left_start:i])
        candle_body = _body_ratio(o[i], h[i], l[i], c[i])
        candle_rvol = _relative_volume(v, i, 20)
        close_dist_atr = (c[i] - level) / max(atr, 1e-12)
        if (
            c[i] > level + breakout_buffer
            and h[i] > level + breakout_buffer
            and c[i] > ema20[i]
            and c[i] > ema50[i]
            and candle_body >= BREAKOUT_MIN_BODY_RATIO
            and candle_rvol >= BREAKOUT_MIN_RVOL
            and close_dist_atr >= BREAKOUT_CONFIRM_CLOSE_ATR
        ):
            breakout_idx = i
            breakout_level = level
            breakout_rvol = candle_rvol
            breakout_body = candle_body
            breakout_close_dist_atr = close_dist_atr
    if breakout_idx is None or breakout_level is None:
        return False, "NO_BREAKOUT", {}
    if breakout_idx >= len(c) - 1:
        return False, "NO_RETEST_BAR", {"breakout_idx": breakout_idx}

    i = len(c) - 1
    retest_low = l[i]
    trigger_rvol = _relative_volume(v, i, 20)
    trigger_close_pos = _close_position_in_range(o[i], h[i], l[i], c[i])
    trigger_lower_wick = _lower_wick_ratio(o[i], h[i], l[i], c[i])

    touched = retest_low <= breakout_level + (atr * RETEST_TOL_ATR)
    hard_fail = retest_low < breakout_level - (atr * RETEST_HARD_FAIL_ATR)
    close_ok = c[i] > breakout_level and c[i] > o[i] and c[i] > ema20[i]
    body_ok = _body_ratio(o[i], h[i], l[i], c[i]) >= MIN_BODY_RATIO
    chase_ok = (c[i] - breakout_level) <= atr * MAX_CHASE_ATR
    close_loc_ok = trigger_close_pos >= TRIGGER_CLOSE_POS_LONG_MIN
    trigger_rvol_ok = trigger_rvol >= TRIGGER_MIN_RVOL
    wick_support_ok = trigger_lower_wick >= 0.12 or trigger_close_pos >= 0.72
    post_break_lows = min(l[breakout_idx + 1 : i + 1]) if i > breakout_idx else l[i]
    retained_structure = post_break_lows >= breakout_level - (atr * RETEST_HARD_FAIL_ATR)

    diag = {
        "breakout_level": round(float(breakout_level), 8),
        "breakout_idx": int(breakout_idx),
        "bars_since_breakout": int(i - breakout_idx),
        "touched": bool(touched),
        "hard_fail": bool(hard_fail),
        "close_ok": bool(close_ok),
        "body_ratio": round(_body_ratio(o[i], h[i], l[i], c[i]), 4),
        "breakout_body_ratio": round(float(breakout_body), 4),
        "breakout_rvol": round(float(breakout_rvol), 4),
        "trigger_rvol": round(float(trigger_rvol), 4),
        "trigger_close_pos": round(float(trigger_close_pos), 4),
        "trigger_lower_wick": round(float(trigger_lower_wick), 4),
        "close_dist_atr": round(float(breakout_close_dist_atr), 4),
        "chase_atr": round((c[i] - breakout_level) / max(atr, 1e-12), 4),
        "retest_gap_atr": round((retest_low - breakout_level) / max(atr, 1e-12), 4),
    }

    if hard_fail or not retained_structure:
        return False, "RETEST_TOO_DEEP", diag
    if not touched:
        return False, "NO_RETEST_TOUCH", diag
    if not close_ok:
        return False, "RETEST_CLOSE_BAD", diag
    if not body_ok:
        return False, "TRIGGER_BODY_WEAK", diag
    if not close_loc_ok:
        return False, "TRIGGER_CLOSE_LOCATION_BAD", diag
    if not trigger_rvol_ok:
        return False, "RETEST_VOLUME_WEAK", diag
    if not wick_support_ok:
        return False, "TRIGGER_REJECTION_WEAK", diag
    if not chase_ok:
        return False, "TOO_EXTENDED_AFTER_RETEST", diag
    return True, "OK", diag


def _detect_breakout_retest_short(
    o: List[float], h: List[float], l: List[float], c: List[float], v: List[float], ema20: List[float], ema50: List[float], atr: float
) -> Tuple[bool, str, Dict[str, Any]]:
    if len(c) < max(BREAKOUT_LOOKBACK + BREAKOUT_MAX_AGE_BARS + 4, 80):
        return False, "NOT_ENOUGH_BARS", {}
    breakout_idx = None
    breakout_level = None
    breakout_rvol = 1.0
    breakout_body = 0.0
    breakout_close_dist_atr = 0.0
    breakout_buffer = atr * BREAKOUT_MIN_ATR_FRAC
    start = len(c) - BREAKOUT_MAX_AGE_BARS - 2
    end = len(c) - 1
    for i in range(start, end):
        left_start = max(0, i - BREAKOUT_LOOKBACK)
        if i - left_start < 8:
            continue
        level = min(l[left_start:i])
        candle_body = _body_ratio(o[i], h[i], l[i], c[i])
        candle_rvol = _relative_volume(v, i, 20)
        close_dist_atr = (level - c[i]) / max(atr, 1e-12)
        if (
            c[i] < level - breakout_buffer
            and l[i] < level - breakout_buffer
            and c[i] < ema20[i]
            and c[i] < ema50[i]
            and candle_body >= BREAKOUT_MIN_BODY_RATIO
            and candle_rvol >= BREAKOUT_MIN_RVOL
            and close_dist_atr >= BREAKOUT_CONFIRM_CLOSE_ATR
        ):
            breakout_idx = i
            breakout_level = level
            breakout_rvol = candle_rvol
            breakout_body = candle_body
            breakout_close_dist_atr = close_dist_atr
    if breakout_idx is None or breakout_level is None:
        return False, "NO_BREAKDOWN", {}
    if breakout_idx >= len(c) - 1:
        return False, "NO_RETEST_BAR", {"breakout_idx": breakout_idx}

    i = len(c) - 1
    retest_high = h[i]
    trigger_rvol = _relative_volume(v, i, 20)
    trigger_close_pos = _close_position_in_range(o[i], h[i], l[i], c[i])
    trigger_upper_wick = _upper_wick_ratio(o[i], h[i], l[i], c[i])

    touched = retest_high >= breakout_level - (atr * RETEST_TOL_ATR)
    hard_fail = retest_high > breakout_level + (atr * RETEST_HARD_FAIL_ATR)
    close_ok = c[i] < breakout_level and c[i] < o[i] and c[i] < ema20[i]
    body_ok = _body_ratio(o[i], h[i], l[i], c[i]) >= MIN_BODY_RATIO
    chase_ok = (breakout_level - c[i]) <= atr * MAX_CHASE_ATR
    close_loc_ok = trigger_close_pos <= TRIGGER_CLOSE_POS_SHORT_MAX
    trigger_rvol_ok = trigger_rvol >= TRIGGER_MIN_RVOL
    wick_support_ok = trigger_upper_wick >= 0.12 or trigger_close_pos <= 0.28
    post_break_highs = max(h[breakout_idx + 1 : i + 1]) if i > breakout_idx else h[i]
    retained_structure = post_break_highs <= breakout_level + (atr * RETEST_HARD_FAIL_ATR)

    diag = {
        "breakout_level": round(float(breakout_level), 8),
        "breakout_idx": int(breakout_idx),
        "bars_since_breakout": int(i - breakout_idx),
        "touched": bool(touched),
        "hard_fail": bool(hard_fail),
        "close_ok": bool(close_ok),
        "body_ratio": round(_body_ratio(o[i], h[i], l[i], c[i]), 4),
        "breakout_body_ratio": round(float(breakout_body), 4),
        "breakout_rvol": round(float(breakout_rvol), 4),
        "trigger_rvol": round(float(trigger_rvol), 4),
        "trigger_close_pos": round(float(trigger_close_pos), 4),
        "trigger_upper_wick": round(float(trigger_upper_wick), 4),
        "close_dist_atr": round(float(breakout_close_dist_atr), 4),
        "chase_atr": round((breakout_level - c[i]) / max(atr, 1e-12), 4),
        "retest_gap_atr": round((breakout_level - retest_high) / max(atr, 1e-12), 4),
    }

    if hard_fail or not retained_structure:
        return False, "RETEST_TOO_DEEP", diag
    if not touched:
        return False, "NO_RETEST_TOUCH", diag
    if not close_ok:
        return False, "RETEST_CLOSE_BAD", diag
    if not body_ok:
        return False, "TRIGGER_BODY_WEAK", diag
    if not close_loc_ok:
        return False, "TRIGGER_CLOSE_LOCATION_BAD", diag
    if not trigger_rvol_ok:
        return False, "RETEST_VOLUME_WEAK", diag
    if not wick_support_ok:
        return False, "TRIGGER_REJECTION_WEAK", diag
    if not chase_ok:
        return False, "TOO_EXTENDED_AFTER_RETEST", diag
    return True, "OK", diag


def _dynamic_trade_management_params(strength: float, score: float, atr_pct: Optional[float] = None) -> Dict[str, Any]:
    atr_pct = float(atr_pct or 0.0)
    score = float(score or 0.0)
    strength = float(strength or 0.0)

    # Paso 4: rehacer la asimetría de salida.
    # Objetivo: dejar correr más el remanente ganador y recortar menos pronto,
    # sin convertir el trade en "todo o nada".
    if score >= 90.0:
        bucket = "strong"
        act = 0.0100
        retrace = 0.0054
        force = 0.0071
        partial_frac = 0.28
    elif score >= 83.0:
        bucket = "base"
        act = 0.0090
        retrace = 0.0048
        force = 0.0064
        partial_frac = 0.32
    else:
        bucket = "weak"
        act = 0.0081
        retrace = 0.0042
        force = 0.0058
        partial_frac = 0.35

    # Ajuste por volatilidad: subir ligeramente el nivel donde se activa el runner
    # y dar algo más de respiración al trailing en regímenes rápidos.
    vol_add = _clamp((atr_pct - 0.0050) * 0.16, -0.0005, 0.0008)
    act = _clamp(act + vol_add, 0.0078, 0.0112)
    retrace = _clamp(retrace + (vol_add * 0.85), 0.0038, 0.0059)
    force = _clamp(force + (vol_add * 0.45), 0.0052, 0.0082)

    # El partial TP queda más cerca de la activación del trailing y cierra menos tamaño.
    partial_tp = _clamp(max(act * 0.93, act - 0.00055), 0.0068, act - 0.0002)

    # El BE se arma más tarde: primero queremos confirmar extensión real del trade,
    # no cortar runners casi inmediatamente después de arrancar.
    break_even_activation = _clamp(max(act * 1.14, partial_tp + 0.0008), partial_tp + 0.0006, act + 0.0026)
    break_even_offset = _clamp(max(atr_pct * 0.10, act * 0.12), 0.0007, 0.0018)

    # Menos agresivo el cierre por pérdida de fuerza para no matar ganadores sanos.
    force_strength = _clamp(max(0.16, strength * 0.64), 0.16, 0.88)
    return {
        "bucket": bucket,
        "tp_activation_price": round(act, 6),
        "trail_retrace_price": round(retrace, 6),
        "force_min_profit_price": round(force, 6),
        "force_min_strength": round(force_strength, 4),
        "partial_tp_activation_price": round(partial_tp, 6),
        "partial_tp_close_fraction": round(partial_frac, 4),
        "break_even_activation_price": round(break_even_activation, 6),
        "break_even_offset_price": round(break_even_offset, 6),
        "vol_regime": _volatility_regime_from_atr_pct(atr_pct),
    }


def get_trade_management_params(strength: float, score: float, atr_pct: Optional[float] = None) -> Dict[str, Any]:
    return _dynamic_trade_management_params(strength, score, atr_pct)


def get_entry_signal(symbol: str) -> dict:
    try:
        coin = norm_coin(symbol)
        if not coin:
            return {"signal": False, "reason": "BAD_SYMBOL"}

        c5, st5 = _fetch_candles(coin, TF_5M, LOOKBACK_5M)
        if st5 in ("API_FAIL", "BAD_SYMBOL", "BAD_INTERVAL"):
            return {"signal": False, "reason": "CANDLES_FETCH_FAIL", "detail": {"5m": st5}, "coin": coin}
        if not c5:
            return {"signal": False, "reason": "NO_CANDLES", "coin": coin}

        quality_ok, quality_reason, quality_diag = _validate_symbol_quality(coin, c5)
        if not quality_ok:
            return {"signal": False, "reason": quality_reason, "coin": coin, "diag": quality_diag}

        stale5, age5, t5 = _is_stale(c5, TF_5M)
        if stale5:
            return {"signal": False, "reason": "STALE_CANDLES", "coin": coin, "age_s": {"5m": round(age5, 1)}, "last_t": {"5m": t5}}

        o5, h5, l5, cl5, v5 = _extract(c5)
        if not cl5:
            return {"signal": False, "reason": "BAD_CANDLES_PARSE", "coin": coin}

        ema20 = _ema(cl5, EMA_FAST)
        ema50 = _ema(cl5, EMA_MID)
        ema200 = _ema(cl5, EMA_SLOW)
        if not ema20 or not ema50 or not ema200:
            return {"signal": False, "reason": "NO_TREND_DATA", "coin": coin}

        close5 = float(cl5[-1])
        adx5 = float(_last(_adx(h5, l5, cl5, ADX_PERIOD)) or 0.0)
        atr5 = float(_atr(h5, l5, cl5, ATR_PERIOD) or 0.0)
        atr_pct = atr5 / close5 if close5 > 0 else 0.0
        if atr_pct < ATR_PCT_MIN:
            return {"signal": False, "reason": "ATR_TOO_LOW", "coin": coin, "diag": {"atr_pct": round(atr_pct, 6)}}
        if atr_pct > ATR_PCT_MAX:
            return {"signal": False, "reason": "ATR_TOO_HIGH", "coin": coin, "diag": {"atr_pct": round(atr_pct, 6)}}
        if adx5 < ADX_MIN:
            return {"signal": False, "reason": "ADX_TOO_LOW", "coin": coin, "diag": {"adx5": round(adx5, 2)}}

        slope50 = _pct_change(float(ema50[-1]), float(ema50[max(0, len(ema50) - 1 - EMA_SLOPE_LOOKBACK)] or ema50[-1]))
        slope200 = _pct_change(float(ema200[-1]), float(ema200[max(0, len(ema200) - 1 - EMA_SLOPE_LOOKBACK)] or ema200[-1]))

        long_trend = ema20[-1] > ema50[-1] and close5 > ema50[-1] and slope50 > 0.0002 and slope200 > -0.0015
        short_trend = ema20[-1] < ema50[-1] and close5 < ema50[-1] and slope50 < -0.0002 and slope200 < 0.0015

        if long_trend:
            direction = "long"
            ok, reason5, diag5 = _detect_breakout_retest_long(o5, h5, l5, cl5, v5, ema20, ema50, atr5)
        elif short_trend:
            direction = "short"
            ok, reason5, diag5 = _detect_breakout_retest_short(o5, h5, l5, cl5, v5, ema20, ema50, atr5)
        else:
            return {"signal": False, "reason": "NO_TREND_STACK_5M", "coin": coin, "diag": {"slope50": round(slope50, 5), "slope200": round(slope200, 5)}}

        if not ok:
            if LOG_SIGNAL_DIAGNOSTICS:
                _log(f"BLOCK coin={coin} dir={direction} reason={reason5} diag={diag5}")
            return {"signal": False, "reason": f"BREAKOUT_RETEST_{reason5}", "coin": coin, "diag": diag5}

        if direction == "long":
            swing_low = min(l5[-10:])
            swing_dist_pct = max(0.0, (close5 - swing_low) / max(close5, 1e-12))
        else:
            swing_high = max(h5[-10:])
            swing_dist_pct = max(0.0, (swing_high - close5) / max(close5, 1e-12))

        sl_from_atr = atr_pct * ATR_SL_MULT
        sl_from_swing = swing_dist_pct + ((atr5 / max(close5, 1e-12)) * SWING_BUFFER_ATR)
        sl_pct = _clamp(max(sl_from_atr, sl_from_swing), ATR_SL_MIN_PCT, ATR_SL_MAX_PCT)

        breakout_rvol = float(diag5.get("breakout_rvol", 1.0) or 1.0)
        trigger_rvol = float(diag5.get("trigger_rvol", 1.0) or 1.0)
        trigger_close_pos = float(diag5.get("trigger_close_pos", 0.5) or 0.5)
        bars_since_breakout = int(diag5.get("bars_since_breakout", BREAKOUT_MAX_AGE_BARS) or BREAKOUT_MAX_AGE_BARS)
        ema_stack_pct = abs(float(ema20[-1]) - float(ema50[-1])) / max(close5, 1e-12)

        adx_quality = _clamp((adx5 - ADX_MIN) / 18.0, 0.0, 1.0)
        slope_quality = _clamp((abs(slope50) - 0.0002) / 0.0078, 0.0, 1.0)
        body_quality = _clamp(diag5.get("body_ratio", 0.0) / 0.72, 0.0, 1.0)
        breakout_body_quality = _clamp(diag5.get("breakout_body_ratio", 0.0) / 0.72, 0.0, 1.0)
        volume_quality = _clamp(((breakout_rvol - 0.90) / 0.85) * 0.58 + ((trigger_rvol - 0.85) / 0.70) * 0.42, 0.0, 1.0)
        retest_location_quality = _clamp(trigger_close_pos if direction == "long" else (1.0 - trigger_close_pos), 0.0, 1.0)
        retest_proximity_quality = _clamp(1.0 - (abs(diag5.get("retest_gap_atr", 0.0)) / max(RETEST_TOL_ATR, 1e-12)), 0.0, 1.0)
        trend_stack_quality = _clamp((ema_stack_pct - TREND_STACK_MIN_PCT) / 0.0038, 0.0, 1.0)
        extension_penalty = _clamp(abs(diag5.get("chase_atr", 0.0)) / MAX_CHASE_ATR, 0.0, 1.0)
        age_penalty = _clamp((bars_since_breakout - 1) / max(BREAKOUT_MAX_AGE_BARS - 1, 1), 0.0, 1.0)
        atr_regime_quality = 1.0 - _clamp((atr_pct - ATR_PCT_MIN) / max(ATR_PCT_MAX - ATR_PCT_MIN, 1e-12), 0.0, 1.0) * 0.22

        setup_quality = _clamp(
            (0.22 * adx_quality)
            + (0.17 * slope_quality)
            + (0.12 * body_quality)
            + (0.09 * breakout_body_quality)
            + (0.18 * volume_quality)
            + (0.10 * retest_location_quality)
            + (0.06 * retest_proximity_quality)
            + (0.10 * trend_stack_quality)
            + (0.06 * atr_regime_quality)
            - (0.06 * extension_penalty)
            - (0.04 * age_penalty),
            0.0,
            1.0,
        )
        score = round(min(MAX_SCORE, 64.0 + (36.0 * setup_quality)), 2)
        if score < MIN_SCORE_TO_SIGNAL:
            return {
                "signal": False,
                "reason": "SCORE_TOO_LOW",
                "coin": coin,
                "diag": {
                    "score": score,
                    "min_score": MIN_SCORE_TO_SIGNAL,
                    "breakout_rvol": round(breakout_rvol, 4),
                    "trigger_rvol": round(trigger_rvol, 4),
                    "bars_since_breakout": bars_since_breakout,
                    "ema_stack_pct": round(ema_stack_pct, 6),
                },
            }

        strength = _clamp(score / 100.0, STRENGTH_MIN, STRENGTH_MAX)
        mgmt = _dynamic_trade_management_params(strength, score, atr_pct)

        out = {
            "signal": True,
            "direction": direction,
            "strength": round(strength, 4),
            "score": float(score),
            "sl_price_pct": round(sl_pct, 6),
            "tp_activation_price": float(mgmt["tp_activation_price"]),
            "trail_retrace_price": float(mgmt["trail_retrace_price"]),
            "force_min_profit_price": float(mgmt["force_min_profit_price"]),
            "force_min_strength": float(mgmt["force_min_strength"]),
            "partial_tp_activation_price": float(mgmt["partial_tp_activation_price"]),
            "partial_tp_close_fraction": float(mgmt["partial_tp_close_fraction"]),
            "break_even_activation_price": float(mgmt["break_even_activation_price"]),
            "break_even_offset_price": float(mgmt["break_even_offset_price"]),
            "mgmt_bucket": str(mgmt["bucket"]),
            "vol_regime": str(mgmt.get("vol_regime", _volatility_regime_from_atr_pct(atr_pct))),
            "atr_pct": round(float(atr_pct), 6),
            "breakout_rvol": round(breakout_rvol, 4),
            "trigger_rvol": round(trigger_rvol, 4),
            "bars_since_breakout": int(bars_since_breakout),
            "ema_stack_pct": round(float(ema_stack_pct), 6),
            "coin": coin,
            "close_5": round(close5, 6),
            "last_candle_t_5m": int(t5),
            "ema20_5m": round(float(ema20[-1]), 6),
            "adx1": round(adx5, 2),   # compatibilidad con logs/engine actuales
            "adx15": round(adx5, 2),  # compatibilidad con logs/engine actuales
            "strategy_model": "breakout_retest_5m_v5_exit_asymmetry",
        }
        if LOG_SIGNAL_DIAGNOSTICS:
            _log(
                f"SIGNAL coin={coin} dir={out['direction']} close_5={out['close_5']} t5={out['last_candle_t_5m']} age5s={round(age5,1)} "
                f"adx5={round(adx5,2)} atr_pct={out['atr_pct']} vol_regime={out['vol_regime']} score={out['score']} "
                f"breakout_rvol={out['breakout_rvol']} trigger_rvol={out['trigger_rvol']} bars_since_breakout={out['bars_since_breakout']} ema_stack_pct={out['ema_stack_pct']} "
                f"breakout=OK sl_pct={out['sl_price_pct']} partial_tp={out['partial_tp_activation_price']} tp_act={out['tp_activation_price']} retrace={out['trail_retrace_price']} "
                f"be_act={out['break_even_activation_price']} be_offset={out['break_even_offset_price']} force_min_profit={out['force_min_profit_price']} "
                f"force_min_strength={out['force_min_strength']} bucket={out['mgmt_bucket']}"
            )
        return out
    except Exception as e:
        return {"signal": False, "reason": "STRATEGY_EXCEPTION", "error": str(e)[:180]}
