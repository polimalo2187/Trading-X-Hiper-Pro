# ============================================================
# ARCHIVO: app/strategy.py
# ESTRATEGIA MTF (1H + 15M + 5M) – HYPERLIQUID NATIVO
# PRODUCCIÓN REAL – BANK GRADE (NO CRASHEA)
# Interfaz: get_entry_signal(symbol) -> dict
# ============================================================

import time
from typing import Optional, Dict, Any, List

from app.hyperliquid_client import make_request, norm_coin

# =========================
# CONFIGURACIÓN MTF
# =========================

# Timeframes
TF_1H = "1h"
TF_15M = "15m"
TF_5M = "5m"

# Lookbacks (EMA200 necesita bastante historia)
LOOKBACK_1H = 260
LOOKBACK_15M = 260
LOOKBACK_5M = 320

# Indicadores (igual al bot de señales)
EMA_TREND = 200

ADX_PERIOD = 14
ADX_MIN_TREND_1H = 25
ADX_MIN_TREND_15M = 20

BB_PERIOD = 20
BB_STD = 2.0

VOLUME_MA_PERIOD = 20
VOLUME_MULTIPLIER = 1.5

MAX_SCORE = 100
MIN_SCORE_TO_SIGNAL = 70  # ejecuta solo si score >= 70

# Strength compatible con tu risk.py (clamp 0.2..8.0)
STRENGTH_MAX = 8.0

# Cache para no spamear /info candleSnapshot
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
    end_time = now_ms
    start_time = now_ms - (step * max(int(limit), 10))

    cache_key = f"{coin}:{interval}:{int(limit)}"
    cached = _CANDLE_CACHE.get(cache_key)
    if cached and (now_s - cached.get("ts", 0)) < CANDLE_CACHE_TTL:
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

    # Orden por tiempo
    try:
        r.sort(key=lambda x: int(x.get("t", 0)))
    except Exception:
        pass

    # Limitar a últimos N
    if len(r) > limit:
        r = r[-limit:]

    _CANDLE_CACHE[cache_key] = {"ts": now_s, "data": r}
    return r

def _to_df(candles: List[dict]):
    try:
        import pandas as pd
    except Exception:
        return None

    if not candles:
        return None

    rows = []
    for c in candles:
        try:
            rows.append({
                "time": int(c.get("t", 0)),
                "open": float(c.get("o", 0)),
                "high": float(c.get("h", 0)),
                "low": float(c.get("l", 0)),
                "close": float(c.get("c", 0)),
                "volume": float(c.get("v", 0)),
            })
        except Exception:
            continue

    if not rows:
        return None

    df = pd.DataFrame(rows)
    df = df.sort_values("time").reset_index(drop=True)
    return df

def _add_indicators(df):
    try:
        import ta
    except Exception:
        return None

    df = df.copy()
    try:
        df["ema_200"] = ta.trend.ema_indicator(df["close"], window=EMA_TREND)

        bb = ta.volatility.BollingerBands(
            close=df["close"],
            window=BB_PERIOD,
            window_dev=BB_STD,
        )
        df["bb_high"] = bb.bollinger_hband()
        df["bb_low"] = bb.bollinger_lband()
        df["bb_mid"] = bb.bollinger_mavg()

        df["adx"] = ta.trend.adx(df["high"], df["low"], df["close"], window=ADX_PERIOD)

        df["vol_ma"] = df["volume"].rolling(VOLUME_MA_PERIOD).mean()
    except Exception:
        return None

    return df

def _market_has_strength(df, min_adx: float) -> bool:
    try:
        last = df.iloc[-1]
        return float(last.get("adx", 0)) >= float(min_adx)
    except Exception:
        return False

def _trend_direction(df) -> Optional[str]:
    try:
        last = df.iloc[-1]
        close = float(last.get("close", 0))
        ema = float(last.get("ema_200", 0))
        if close > ema:
            return "LONG"
        if close < ema:
            return "SHORT"
        return None
    except Exception:
        return None

def _breakout_confirmation(df, direction: str) -> bool:
    try:
        last = df.iloc[-1]
        vol = float(last.get("volume", 0))
        vol_ma = float(last.get("vol_ma", 0))
        if vol_ma <= 0:
            return False
        if vol < vol_ma * VOLUME_MULTIPLIER:
            return False

        close = float(last.get("close", 0))
        bb_high = float(last.get("bb_high", 0))
        bb_low = float(last.get("bb_low", 0))

        if direction == "LONG":
            return close > bb_high
        return close < bb_low
    except Exception:
        return False

def _pullback_confirmation(df, direction: str, min_adx: float) -> bool:
    try:
        last = df.iloc[-1]
        close = float(last.get("close", 0))
        bb_mid = float(last.get("bb_mid", 0))
        ema = float(last.get("ema_200", 0))
        adx = float(last.get("adx", 0))

        if direction == "LONG":
            return (close >= bb_mid) and (close > ema) and (adx >= min_adx)
        return (close <= bb_mid) and (close < ema) and (adx >= min_adx)
    except Exception:
        return False

def _score_to_strength(score: float) -> float:
    try:
        score = float(score)
    except Exception:
        score = 0.0
    score = max(0.0, min(score, float(MAX_SCORE)))
    strength = (score / float(MAX_SCORE)) * float(STRENGTH_MAX)
    return round(strength, 4)

# =========================
# ENTRY SIGNAL (MTF)
# =========================

def get_entry_signal(symbol: str) -> dict:
    """
    Retorna:
    - {"signal": False, "reason": "..."} o
    - {"signal": True, "direction": "long|short", "strength": float, "entry_price": float, ...}
    """
    coin = norm_coin(symbol)

    # Dependencias obligatorias (pero sin crashear)
    try:
        import pandas as pd  # noqa: F401
        import ta  # noqa: F401
    except Exception:
        return {"signal": False, "reason": "MISSING_DEPS"}

    # Candles
    c1 = _fetch_candles(coin, TF_1H, LOOKBACK_1H)
    c15 = _fetch_candles(coin, TF_15M, LOOKBACK_15M)
    c5 = _fetch_candles(coin, TF_5M, LOOKBACK_5M)

    df_1h = _to_df(c1)
    df_15m = _to_df(c15)
    df_5m = _to_df(c5)

    if df_1h is None or df_15m is None or df_5m is None:
        return {"signal": False, "reason": "NO_CANDLES"}

    # Indicadores
    df_1h = _add_indicators(df_1h)
    df_15m = _add_indicators(df_15m)
    df_5m = _add_indicators(df_5m)

    if df_1h is None or df_15m is None or df_5m is None:
        return {"signal": False, "reason": "INDICATORS_FAIL"}

    score = 0
    components = []

    # 1H filtro duro
    if not _market_has_strength(df_1h, ADX_MIN_TREND_1H):
        return {"signal": False, "reason": "ADX_1H"}

    direction = _trend_direction(df_1h)
    if not direction:
        return {"signal": False, "reason": "NO_TREND_1H"}

    score += 35
    components.append(("trend_1h", 35))

    # 15M contexto
    if not _market_has_strength(df_15m, ADX_MIN_TREND_15M):
        return {"signal": False, "reason": "ADX_15M"}

    score += 25
    components.append(("strength_15m", 25))

    # 5M setup (breakout o pullback)
    is_breakout = _breakout_confirmation(df_5m, direction)
    is_pullback = _pullback_confirmation(df_5m, direction, ADX_MIN_TREND_15M)

    if not (is_breakout or is_pullback):
        return {"signal": False, "reason": "NO_SETUP_5M"}

    if is_breakout:
        score += 30
        components.append(("breakout_5m", 30))
    else:
        score += 25
        components.append(("pullback_5m", 25))

    # Bonus ADX 5m fuerte
    try:
        last5 = df_5m.iloc[-1]
        if float(last5.get("adx", 0)) >= 35:
            score += 5
            components.append(("adx_bonus", 5))
    except Exception:
        pass

    score = max(0, min(score, MAX_SCORE))

    # Gate por score (responsable)
    if score < MIN_SCORE_TO_SIGNAL:
        return {
            "signal": False,
            "reason": "SCORE_LOW",
            "score": round(score, 2),
            "strength": _score_to_strength(score),
        }

    # Señal OK
    try:
        last_close = float(df_5m.iloc[-1].get("close", 0))
    except Exception:
        last_close = 0.0

    return {
        "signal": True,
        "direction": "long" if direction == "LONG" else "short",
        "strength": _score_to_strength(score),
        "entry_price": round(last_close, 6),
        "score": round(score, 2),
        "components": components,
}
