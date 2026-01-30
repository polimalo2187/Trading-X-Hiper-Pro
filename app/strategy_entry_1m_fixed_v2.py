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

TF_1M = "1m"
LOOKBACK_1H = 260
LOOKBACK_15M = 260
LOOKBACK_5M = 320

LOOKBACK_1M = 600
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

# =========================
# IMPULSE TRIGGER (5M) - NUEVO
# =========================
IMPULSE_ATR_MULT_5M = 2.0
IMPULSE_CLOSE_STRENGTH_5M = 0.75


MAX_SCORE = 100
MIN_SCORE_TO_SIGNAL = 70

STRENGTH_MAX = 8.0
STRENGTH_MIN = 0.2

_CANDLE_CACHE: Dict[str, Any] = {}
CANDLE_CACHE_TTL = 2.0

# =========================
# AUDITORÍA / LOGS
# =========================
# Log SOLO cuando hay señal (para cazar problemas sin spamear)
LOG_SIGNAL_DIAGNOSTICS = True

# Si el último candle está viejo, NO se permite señal.
# Umbral conservador: 3 velas del timeframe.
STALE_MULTIPLIER = 3.0


def _log(msg: str):
    try:
        print(f"[STRATEGY {time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime())}] {msg}")
    except Exception:
        pass


# =========================
# HELPERS
# =========================

def _interval_ms(interval: str) -> int:
    m = {
        "1m": 60_000,
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

    # Si la API falla puede devolver {} o algo no-lista
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


# =========================
# IMPULSE TRIGGER (1M)
# =========================
def _impulse_trigger_1m(o, h, l, c, direction: str) -> bool:
    """Gatillo: opera solo si el último candle de 1m es un impulso real.
    Fail-safe: si algo falla, NO opera.
    """
    try:
        if not o or not h or not l or not c:
            return False

        o1 = float(o[-1]); h1 = float(h[-1]); l1 = float(l[-1]); c1 = float(c[-1])
        rng = h1 - l1
        if rng <= 0:
            return False

        atr = float(_atr(h, l, c, ATR_PERIOD) or 0.0)
        if atr <= 0:
            return False

        # Tamaño del velón vs ATR
        if rng < atr * float(IMPULSE_ATR_MULT_5M):
            return False

        # Color correcto
        if direction == "LONG" and c1 <= o1:
            return False
        if direction == "SHORT" and c1 >= o1:
            return False

        # Cierre fuerte (evitar mechas)
        close_pos = (c1 - l1) / rng  # 0..1
        if direction == "LONG":
            return close_pos >= float(IMPULSE_CLOSE_STRENGTH_5M)
        else:
            return close_pos <= (1.0 - float(IMPULSE_CLOSE_STRENGTH_5M))

    except Exception:
        return False

# Backward-compatible alias
_impulse_trigger_5m = _impulse_trigger_1m


# =========================
# ENTRY SIGNAL
# =========================

def get_entry_signal(symbol: str) -> dict:
    try:
        coin = norm_coin(symbol)
        if not coin:
            return {"signal": False, "reason": "BAD_SYMBOL"}

        c1, st1 = _fetch_candles(coin, TF_1H, LOOKBACK_1H)
        c15, st15 = _fetch_candles(coin, TF_15M, LOOKBACK_15M)
        c5, st5 = _fetch_candles(coin, TF_5M, LOOKBACK_5M)
        c1m, st1m = _fetch_candles(coin, TF_1M, LOOKBACK_1M)

        if st1 in ("API_FAIL", "BAD_SYMBOL", "BAD_INTERVAL") or st15 in ("API_FAIL", "BAD_SYMBOL", "BAD_INTERVAL") or st5 in ("API_FAIL", "BAD_SYMBOL", "BAD_INTERVAL"):
            return {
                "signal": False,
                "reason": "CANDLES_FETCH_FAIL",
                "detail": {"1h": st1, "15m": st15, "5m": st5,
                "1m": st1m},
                "coin": coin,
            }

        if not c1 or not c15 or not c5:
            return {"signal": False, "reason": "NO_CANDLES", "coin": coin}

        # Auditoría de frescura
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
        o1m, h1m, l1m, cl1m, v1m = _extract(c1m)

        if not cl1 or not cl15 or not cl5 or not cl1m:
            return {"signal": False, "reason": "BAD_CANDLES_PARSE", "coin": coin}

        ema1 = _ema(cl1, EMA_TREND)
        adx1 = _adx(h1, l1, cl1, ADX_PERIOD)

        ema1_last = _last(ema1)
        adx1_last = _last(adx1)

        if (ema1_last is None) or (adx1_last is None) or (float(adx1_last) < float(ADX_MIN_TREND_1H)):
            return {"signal": False, "reason": "NO_TREND_1H", "coin": coin}

        direction = "LONG" if float(cl1[-1]) > float(ema1_last) else "SHORT"

        # =====================
        # NUEVO: Impulse trigger 5M (velón disparado)
        # =====================
        if not _impulse_trigger_1m(o1m, h1m, l1m, cl1m, direction):
            return {
                "signal": False,
                "reason": "NO_IMPULSE_1M",
                "coin": coin,
            }


        adx15 = _adx(h15, l15, cl15, ADX_PERIOD)
        adx15_last = _last(adx15)
        if adx15_last is None or float(adx15_last) < float(ADX_MIN_TREND_15M):
            return {"signal": False, "reason": "ADX_15M", "coin": coin, "adx_15m": None if adx15_last is None else round(float(adx15_last), 2)}

        # Score / strength (sin tocar tu lógica actual)
        score = 85.0
        strength = max(STRENGTH_MIN, min(STRENGTH_MAX, (score / 100) * STRENGTH_MAX))

        # ✅ IMPORTANTE:
        # Ya NO devolvemos entry_price "inventado".
        # El precio real de entrada debe venir del FILL del exchange (cliente/engine).
        close_5 = float(cl5[-1])

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
