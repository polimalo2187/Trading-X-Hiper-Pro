# ============================================================
# ARCHIVO: app/strategy.py
# ESTRATEGIA MTF (1H + 15M + 5M) – HYPERLIQUID NATIVO
# PRODUCCIÓN REAL – BANK GRADE (NO CRASHEA)
# Interfaz: get_entry_signal(symbol) -> dict SIEMPRE
# SIN DEPENDENCIAS (NO pandas / NO ta)
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

# Lookbacks
# (EMA200 necesita historia, pero no hace falta exagerar; esto es estable)
LOOKBACK_1H = 260
LOOKBACK_15M = 260
LOOKBACK_5M = 320

# Indicadores
EMA_TREND = 200

ADX_PERIOD = 14
ADX_MIN_TREND_1H = 25
ADX_MIN_TREND_15M = 20

BB_PERIOD = 20
BB_STD = 2.0

VOLUME_MA_PERIOD = 20
VOLUME_MULTIPLIER = 1.5

MAX_SCORE = 100
MIN_SCORE_TO_SIGNAL = 70

# Strength compatible con tu risk.py
STRENGTH_MAX = 8.0
STRENGTH_MIN = 0.2

# Cache para no spamear candleSnapshot
_CANDLE_CACHE: Dict[str, Any] = {}
CANDLE_CACHE_TTL = 2.0  # segundos


# =========================
# HELPERS TIEMPOS
# =========================

def _interval_ms(interval: str) -> int:
    m = {
        "1m": 60_000,
        "3m": 180_000,
        "5m": 300_000,
        "15m": 900_000,
        "30m": 1_800_000,
        "1h": 3_600_000,
        "2h": 7_200_000,
        "4h": 14_400_000,
        "8h": 28_800_000,
        "12h": 43_200_000,
        "1d": 86_400_000,
        "3d": 259_200_000,
        "1w": 604_800_000,
        "1M": 2_592_000_000,
    }
    return int(m.get(interval, 0))


def _fetch_candles(coin: str, interval: str, limit: int) -> List[dict]:
    """
    Hyperliquid candleSnapshot:
    POST /info { "type":"candleSnapshot", "req":{ coin, interval, startTime, endTime } }
    """
    coin = norm_coin(coin)
    if not coin:
        return []

    step = _interval_ms(interval)
    if step <= 0:
        return []

    now_s = time.time()
    now_ms = int(now_s * 1000)

    # Pedimos al menos "limit" velas, con buffer
    end_time = now_ms
    start_time = now_ms - (step * max(int(limit), 50))

    cache_key = f"{coin}:{interval}:{int(limit)}"
    cached = _CANDLE_CACHE.get(cache_key)
    if cached and (now_s - float(cached.get("ts", 0.0) or 0.0)) < CANDLE_CACHE_TTL:
        data = cached.get("data", [])
        return data if isinstance(data, list) else []

    payload = {
        "type": "candleSnapshot",
        "req": {
            "coin": coin,
            "interval": interval,
            "startTime": int(start_time),
            "endTime": int(end_time),
        }
    }

    r = make_request("/info", payload)
    if not isinstance(r, list) or not r:
        return []

    try:
        r.sort(key=lambda x: int(x.get("t", 0)))
    except Exception:
        pass

    if len(r) > limit:
        r = r[-limit:]

    _CANDLE_CACHE[cache_key] = {"ts": now_s, "data": r}
    return r


# =========================
# INDICADORES (SIN DEPENDENCIAS)
# =========================

def _extract_ohlcv(candles: List[dict]) -> Tuple[List[float], List[float], List[float], List[float], List[float]]:
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


def _sma(series: List[float], period: int) -> List[Optional[float]]:
    out: List[Optional[float]] = [None] * len(series)
    if period <= 0 or len(series) < period:
        return out
    s = 0.0
    for i in range(len(series)):
        s += float(series[i])
        if i >= period:
            s -= float(series[i - period])
        if i >= period - 1:
            out[i] = s / float(period)
    return out


def _stddev(series: List[float], period: int, sma_list: List[Optional[float]]) -> List[Optional[float]]:
    out: List[Optional[float]] = [None] * len(series)
    if period <= 1 or len(series) < period:
        return out
    for i in range(period - 1, len(series)):
        mu = sma_list[i]
        if mu is None:
            continue
        acc = 0.0
        for j in range(i - period + 1, i + 1):
            d = float(series[j]) - float(mu)
            acc += d * d
        out[i] = (acc / float(period)) ** 0.5
    return out


def _ema(series: List[float], period: int) -> List[Optional[float]]:
    out: List[Optional[float]] = [None] * len(series)
    if period <= 0 or len(series) < period:
        return out

    k = 2.0 / (float(period) + 1.0)

    # seed con SMA inicial
    seed = 0.0
    for i in range(period):
        seed += float(series[i])
    ema_prev = seed / float(period)
    out[period - 1] = ema_prev

    for i in range(period, len(series)):
        ema_prev = (float(series[i]) - ema_prev) * k + ema_prev
        out[i] = ema_prev

    return out


def _rma(series: List[float], period: int) -> List[Optional[float]]:
    """
    Wilder smoothing (RMA). Usado para ADX.
    """
    out: List[Optional[float]] = [None] * len(series)
    if period <= 0 or len(series) < period:
        return out

    seed = 0.0
    for i in range(period):
        seed += float(series[i])
    prev = seed / float(period)
    out[period - 1] = prev

    for i in range(period, len(series)):
        prev = (prev * (float(period) - 1.0) + float(series[i])) / float(period)
        out[i] = prev

    return out


def _adx(high: List[float], low: List[float], close: List[float], period: int) -> List[Optional[float]]:
    """
    ADX clásico (Wilder):
    - TR, +DM, -DM
    - RMA(TR), RMA(+DM), RMA(-DM)
    - +DI, -DI
    - DX = 100*|+DI - -DI|/(+DI + -DI)
    - ADX = RMA(DX)
    """
    n = len(close)
    out: List[Optional[float]] = [None] * n
    if period <= 0 or n < (period * 2):
        return out

    tr: List[float] = [0.0] * n
    pdm: List[float] = [0.0] * n
    mdm: List[float] = [0.0] * n

    for i in range(1, n):
        up = float(high[i]) - float(high[i - 1])
        dn = float(low[i - 1]) - float(low[i])

        pdm[i] = up if (up > dn and up > 0) else 0.0
        mdm[i] = dn if (dn > up and dn > 0) else 0.0

        hl = float(high[i]) - float(low[i])
        hc = abs(float(high[i]) - float(close[i - 1]))
        lc = abs(float(low[i]) - float(close[i - 1]))
        tr[i] = max(hl, hc, lc)

    atr = _rma(tr, period)
    pdi_s = _rma(pdm, period)
    mdi_s = _rma(mdm, period)

    dx: List[float] = [0.0] * n
    for i in range(n):
        if atr[i] is None or pdi_s[i] is None or mdi_s[i] is None:
            continue
        atr_i = float(atr[i])
        if atr_i <= 0:
            continue

        pdi = 100.0 * float(pdi_s[i]) / atr_i
        mdi = 100.0 * float(mdi_s[i]) / atr_i
        den = (pdi + mdi)
        if den <= 0:
            continue
        dx[i] = 100.0 * abs(pdi - mdi) / den

    adx_list = _rma(dx, period)
    for i in range(n):
        out[i] = adx_list[i]
    return out


def _bollinger(close: List[float], period: int, std_mult: float) -> Tuple[List[Optional[float]], List[Optional[float]], List[Optional[float]]]:
    mid = _sma(close, period)
    sd = _stddev(close, period, mid)
    high: List[Optional[float]] = [None] * len(close)
    low: List[Optional[float]] = [None] * len(close)
    for i in range(len(close)):
        if mid[i] is None or sd[i] is None:
            continue
        high[i] = float(mid[i]) + float(std_mult) * float(sd[i])
        low[i] = float(mid[i]) - float(std_mult) * float(sd[i])
    return high, low, mid


def _last_valid(x: List[Optional[float]]) -> Optional[float]:
    for i in range(len(x) - 1, -1, -1):
        if x[i] is not None:
            return float(x[i])
    return None


def _score_to_strength(score: float) -> float:
    try:
        score = float(score)
    except Exception:
        score = 0.0
    score = max(0.0, min(score, float(MAX_SCORE)))
    strength = (score / float(MAX_SCORE)) * float(STRENGTH_MAX)
    strength = max(float(STRENGTH_MIN), min(float(STRENGTH_MAX), float(strength)))
    return round(strength, 4)

# =========================
# LÓGICA MTF
# =========================

def _market_has_strength(adx_last: Optional[float], min_adx: float) -> bool:
    try:
        return float(adx_last or 0.0) >= float(min_adx)
    except Exception:
        return False


def _trend_direction(close_last: float, ema_last: Optional[float]) -> Optional[str]:
    try:
        ema_v = float(ema_last or 0.0)
        if ema_v <= 0:
            return None
        if float(close_last) > ema_v:
            return "LONG"
        if float(close_last) < ema_v:
            return "SHORT"
        return None
    except Exception:
        return None


def _breakout_confirmation(
    close_last: float,
    vol_last: float,
    vol_ma_last: Optional[float],
    bb_high_last: Optional[float],
    bb_low_last: Optional[float],
    direction: str,
) -> bool:
    try:
        vma = float(vol_ma_last or 0.0)
        if vma <= 0:
            return False
        if float(vol_last) < vma * float(VOLUME_MULTIPLIER):
            return False

        if direction == "LONG":
            return (bb_high_last is not None) and (float(close_last) > float(bb_high_last))
        return (bb_low_last is not None) and (float(close_last) < float(bb_low_last))
    except Exception:
        return False


def _pullback_confirmation(
    close_last: float,
    bb_mid_last: Optional[float],
    ema_last: Optional[float],
    adx_last: Optional[float],
    direction: str,
    min_adx: float,
) -> bool:
    try:
        bbm = float(bb_mid_last or 0.0)
        ema = float(ema_last or 0.0)
        adx = float(adx_last or 0.0)
        if bbm <= 0 or ema <= 0:
            return False
        if adx < float(min_adx):
            return False

        if direction == "LONG":
            return (float(close_last) >= bbm) and (float(close_last) > ema)
        return (float(close_last) <= bbm) and (float(close_last) < ema)
    except Exception:
        return False


# =========================
# ENTRY SIGNAL (MTF)
# =========================

def get_entry_signal(symbol: str) -> dict:
    """
    SIEMPRE retorna dict:
    - {"signal": False, "reason": "...", ...}
    - {"signal": True, "direction": "long|short", "strength": float, "entry_price": float, ...}
    """
    try:
        coin = norm_coin(symbol)
        if not coin:
            return {"signal": False, "reason": "BAD_SYMBOL"}

        # Candles
        c1 = _fetch_candles(coin, TF_1H, LOOKBACK_1H)
        c15 = _fetch_candles(coin, TF_15M, LOOKBACK_15M)
        c5 = _fetch_candles(coin, TF_5M, LOOKBACK_5M)

        if not c1 or not c15 or not c5:
            return {"signal": False, "reason": "NO_CANDLES"}

        # Extraer OHLCV
        _, h1, l1, cl1, _ = _extract_ohlcv(c1)
        _, h15, l15, cl15, _ = _extract_ohlcv(c15)
        _, h5, l5, cl5, v5 = _extract_ohlcv(c5)

        if len(cl1) < (EMA_TREND + 10) or len(cl15) < (ADX_PERIOD * 2) or len(cl5) < (BB_PERIOD + 10):
            return {
                "signal": False,
                "reason": "INSUFFICIENT_DATA",
                "len_1h": len(cl1),
                "len_15m": len(cl15),
                "len_5m": len(cl5),
            }

        # 1H: EMA200 + ADX
        ema1 = _ema(cl1, EMA_TREND)
        adx1 = _adx(h1, l1, cl1, ADX_PERIOD)
        ema1_last = _last_valid(ema1)
        adx1_last = _last_valid(adx1)
        close_1h_last = float(cl1[-1])

        if not _market_has_strength(adx1_last, ADX_MIN_TREND_1H):
            return {"signal": False, "reason": "ADX_1H", "adx_1h": round(float(adx1_last or 0.0), 2)}

        direction = _trend_direction(close_1h_last, ema1_last)
        if not direction:
            return {"signal": False, "reason": "NO_TREND_1H"}

        # 15M: ADX filtro
        adx15 = _adx(h15, l15, cl15, ADX_PERIOD)
        adx15_last = _last_valid(adx15)
        if not _market_has_strength(adx15_last, ADX_MIN_TREND_15M):
            return {"signal": False, "reason": "ADX_15M", "adx_15m": round(float(adx15_last or 0.0), 2)}

        # 5M: BB + EMA200 (para pullback) + ADX + volMA
        ema5 = _ema(cl5, EMA_TREND)
        adx5 = _adx(h5, l5, cl5, ADX_PERIOD)
        vol_ma = _sma(v5, VOLUME_MA_PERIOD)
        bb_high, bb_low, bb_mid = _bollinger(cl5, BB_PERIOD, BB_STD)

        close_5_last = float(cl5[-1])
        vol_5_last = float(v5[-1])
        ema5_last = _last_valid(ema5)
        adx5_last = _last_valid(adx5)
        vol_ma_last = _last_valid(vol_ma)
        bb_high_last = _last_valid(bb_high)
        bb_low_last = _last_valid(bb_low)
        bb_mid_last = _last_valid(bb_mid)

        # Scoring (igual tu lógica)
        score = 0
        components: List[tuple] = []

        score += 35
        components.append(("trend_1h", 35))

        score += 25
        components.append(("strength_15m", 25))

        is_breakout = _breakout_confirmation(
            close_last=close_5_last,
            vol_last=vol_5_last,
            vol_ma_last=vol_ma_last,
            bb_high_last=bb_high_last,
            bb_low_last=bb_low_last,
            direction=direction,
        )

        is_pullback = _pullback_confirmation(
            close_last=close_5_last,
            bb_mid_last=bb_mid_last,
            ema_last=ema5_last,
            adx_last=adx5_last,
            direction=direction,
            min_adx=ADX_MIN_TREND_15M,
        )

        if not (is_breakout or is_pullback):
            return {
                "signal": False,
                "reason": "NO_SETUP_5M",
                "strength": _score_to_strength(score),
                "adx_5m": round(float(adx5_last or 0.0), 2),
            }

        if is_breakout:
            score += 30
            components.append(("breakout_5m", 30))
        else:
            score += 25
            components.append(("pullback_5m", 25))

        # Bonus ADX 5m fuerte
        try:
            if float(adx5_last or 0.0) >= 35.0:
                score += 5
                components.append(("adx_bonus", 5))
        except Exception:
            pass

        score = max(0, min(score, MAX_SCORE))

        if score < MIN_SCORE_TO_SIGNAL:
            return {
                "signal": False,
                "reason": "SCORE_LOW",
                "score": round(float(score), 2),
                "strength": _score_to_strength(score),
                "direction_hint": "long" if direction == "LONG" else "short",
            }

        return {
            "signal": True,
            "direction": "long" if direction == "LONG" else "short",
            "strength": _score_to_strength(score),
            "entry_price": round(float(close_5_last), 6),
            "score": round(float(score), 2),
            "components": components,
        }

    except Exception as e:
        # ✅ NUNCA devolvemos "inválida"; devolvemos dict seguro
        return {"signal": False, "reason": "STRATEGY_EXCEPTION", "error": str(e)[:180]}
