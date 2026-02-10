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
# AUDITORÍA / LOGS
# =========================
# Log SOLO cuando hay señal (para cazar problemas sin spamear)
LOG_SIGNAL_DIAGNOSTICS = True

# Si el último candle está viejo, NO se permite señal.
# Umbral conservador: 3 velas del timeframe.
STALE_MULTIPLIER = 3.0

# =========================
# TIMING 5M (ANTI-REBOTE / ENTRADA TARDE)
# =========================
# Estos filtros NO cambian tu core MTF (1H/15M). Solo bloquean entradas tardías en 5m.
EMA_ENTRY_5M = 20
IMPULSE_ATR_MULT_5M = 1.2        # mínimo impulso previo en múltiplos de ATR(5m)
MAX_RETRACE_FRAC = 0.50          # rebote/pullback no debe recuperar > 50% del impulso
BREAKOUT_LOOKBACK_5M = 10        # velas para detectar ruptura del extremo del pullback
EMA_BAND_FRAC = 0.0              # 0.0 = estricto (por debajo/encima de EMA20). Sube a 0.001 si quieres tolerancia.


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


def _swing_impulse_5m(h5: List[float], l5: List[float], cl5: List[float], direction: str, lookback: int = 80) -> Optional[Dict[str, Any]]:
    """
    Detecta un impulso reciente en 5m de forma robusta y simple (sin librerías).
    Devuelve dict con:
      - high, low, range
      - idx_high, idx_low (en arrays recortados)
      - retrace_frac (qué % del impulso se ha recuperado al último close)
    """
    try:
        n = len(cl5)
        if n < 30:
            return None

        lb = max(30, min(int(lookback), n))
        h = h5[-lb:]
        l = l5[-lb:]
        c = cl5[-lb:]

        # Buscar el extremo más reciente (low para shorts, high para longs)
        if direction == "short":
            idx_low = int(min(range(len(l)), key=lambda i: l[i]))
            low = float(l[idx_low])

            # High previo al low (si no hay, no hay impulso válido)
            if idx_low < 3:
                return None
            idx_high = int(max(range(0, idx_low), key=lambda i: h[i]))
            high = float(h[idx_high])

            rng = high - low
            if rng <= 0:
                return None

            retrace_frac = (float(c[-1]) - low) / rng  # 0 = en el low, 1 = volvió al high

        else:  # long
            idx_high = int(max(range(len(h)), key=lambda i: h[i]))
            high = float(h[idx_high])
            if idx_high < 3:
                return None
            idx_low = int(min(range(0, idx_high), key=lambda i: l[i]))
            low = float(l[idx_low])

            rng = high - low
            if rng <= 0:
                return None

            retrace_frac = (high - float(c[-1])) / rng  # 0 = en el high, 1 = volvió al low

        return {
            "high": high,
            "low": low,
            "range": rng,
            "idx_high": idx_high,
            "idx_low": idx_low,
            "retrace_frac": float(retrace_frac),
            "lb": lb,
        }
    except Exception:
        return None


def _passes_5m_timing_filters(direction: str, h5: List[float], l5: List[float], cl5: List[float]) -> Tuple[bool, str, Dict[str, Any]]:
    """
    Filtro anti-entrada-tarde:
      1) Impulso previo real (>= 1.2 * ATR)
      2) Rebote/pullback NO recupera > 50% del impulso
      3) Precio en el lado correcto de EMA20 (evita chop dentro de medias)
      4) Confirmación por ruptura del extremo reciente (no entrar en el primer rebote)

    Devuelve: (ok, reason, diag)
    """
    diag: Dict[str, Any] = {}
    try:
        if len(cl5) < max(EMA_ENTRY_5M, ATR_PERIOD) + 5:
            return False, "5M_NOT_ENOUGH_DATA", diag

        ema20 = _ema(cl5, EMA_ENTRY_5M)
        ema20_last = _last(ema20)
        if ema20_last is None or float(ema20_last) <= 0:
            return False, "EMA20_5M_NA", diag

        close = float(cl5[-1])
        prev_close = float(cl5[-2])
        ema20_last = float(ema20_last)

        # ATR 5m (misma función ya existente)
        atr5 = float(_atr(h5, l5, cl5, ATR_PERIOD) or 0.0)
        diag["atr5"] = atr5

        if atr5 <= 0:
            return False, "ATR5_NA", diag

        impulse = _swing_impulse_5m(h5, l5, cl5, direction=direction, lookback=80)
        if not impulse:
            return False, "NO_IMPULSE_5M", diag

        diag.update({
            "imp_high": round(float(impulse["high"]), 6),
            "imp_low": round(float(impulse["low"]), 6),
            "imp_range": round(float(impulse["range"]), 6),
            "retrace_frac": round(float(impulse["retrace_frac"]), 4),
        })

        # 1) Impulso real
        if float(impulse["range"]) < float(IMPULSE_ATR_MULT_5M) * atr5:
            return False, "WEAK_IMPULSE_5M", diag

        # 2) Rebote/pullback no demasiado profundo
        if float(impulse["retrace_frac"]) > float(MAX_RETRACE_FRAC):
            return False, "DEEP_RETRACE_5M", diag

        # 3) Lado correcto de EMA20
        band = float(EMA_BAND_FRAC) * ema20_last
        if direction == "short":
            if close > (ema20_last + band):
                diag["ema20"] = round(ema20_last, 6)
                return False, "ABOVE_EMA20_5M", diag
        else:
            if close < (ema20_last - band):
                diag["ema20"] = round(ema20_last, 6)
                return False, "BELOW_EMA20_5M", diag

        # 4) Confirmación por ruptura (no entrar en el primer rebote)
        k = max(6, int(BREAKOUT_LOOKBACK_5M))
        recent_high = max(float(x) for x in h5[-k:])
        recent_low = min(float(x) for x in l5[-k:])
        diag["recent_high_k"] = round(recent_high, 6)
        diag["recent_low_k"] = round(recent_low, 6)

        if direction == "short":
            # Ruptura del extremo inferior reciente
            if not (close < recent_low and prev_close >= recent_low):
                return False, "NO_BREAKDOWN_5M", diag
        else:
            if not (close > recent_high and prev_close <= recent_high):
                return False, "NO_BREAKOUT_5M", diag

        return True, "OK", diag

    except Exception as e:
        diag["err"] = str(e)[:120]
        return False, "TIMING_5M_EXCEPTION", diag

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

        if st1 in ("API_FAIL", "BAD_SYMBOL", "BAD_INTERVAL") or st15 in ("API_FAIL", "BAD_SYMBOL", "BAD_INTERVAL") or st5 in ("API_FAIL", "BAD_SYMBOL", "BAD_INTERVAL"):
            return {
                "signal": False,
                "reason": "CANDLES_FETCH_FAIL",
                "detail": {"1h": st1, "15m": st15, "5m": st5},
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
        _, h5, l5, cl5, v5 = _extract(c5)

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

# =========================
# 5M TIMING FILTER (ANTI-ENTRADA TARDE)
# =========================
ok5, reason5, diag5 = _passes_5m_timing_filters(
    direction=("short" if direction == "SHORT" else "long"),
    h5=h5,
    l5=l5,
    cl5=cl5,
)
if not ok5:
    if LOG_SIGNAL_DIAGNOSTICS:
        _log(
            f"BLOCK coin={coin} dir={'short' if direction=='SHORT' else 'long'} "
            f"reason={reason5} diag={diag5}"
        )
    return {"signal": False, "reason": reason5, "coin": coin, "diag5": diag5}

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