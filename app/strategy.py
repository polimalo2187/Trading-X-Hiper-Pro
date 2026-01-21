# ============================================================
# ARCHIVO: app/strategy.py
# ESTRATEGIA DE MOMENTUM ACUMULADO (FIX REAL)
# Hyperliquid – PRODUCCIÓN REAL
# ============================================================

from collections import deque
import time

from app.hyperliquid_client import get_price

# ======================
# CONFIGURACIÓN REALISTA
# ======================

PRICE_WINDOW = 12                 # ticks
MIN_ELAPSED_TIME = 4.0            # segundos mínimos
ENTRY_SIGNAL_THRESHOLD = 0.45     # % REAL (Hyperliquid)
PRICE_BUFFER_TTL = 20             # segundos

# ======================
# BUFFER DE PRECIOS
# ======================

price_buffer = {}
price_timestamp = {}
price_start_time = {}

# ======================
# NORMALIZADOR DE SÍMBOLOS
# ======================

def _norm_symbol(symbol: str) -> str:
    try:
        s = (symbol or "").strip().upper()
        s = s.replace("-PERP", "").replace("_PERP", "").replace("PERP", "")
        if "/" in s:
            s = s.split("/", 1)[0].strip()
        return s
    except Exception:
        return symbol

# ======================
# BUFFER UPDATE
# ======================

def update_price(symbol: str, price: float):
    try:
        now = time.time()
        symbol = _norm_symbol(symbol)

        if symbol not in price_buffer:
            price_buffer[symbol] = deque(maxlen=PRICE_WINDOW)
            price_timestamp[symbol] = now
            price_start_time[symbol] = now

        # Reset SOLO si está completamente muerto
        if now - price_timestamp[symbol] > PRICE_BUFFER_TTL:
            price_buffer[symbol].clear()
            price_start_time[symbol] = now

        price_buffer[symbol].append(price)
        price_timestamp[symbol] = now

    except Exception:
        # Nunca crasha, solo ignora error raro
        pass

# ======================
# ENTRY SIGNAL
# ======================

def get_entry_signal(symbol: str) -> dict:
    try:
        symbol = _norm_symbol(symbol)
        price = get_price(symbol)

        if price is None or price <= 0:
            return {"signal": False}

        update_price(symbol, price)

        prices = price_buffer.get(symbol)
        if not prices or len(prices) < PRICE_WINDOW:
            return {"signal": False}

        elapsed = time.time() - price_start_time.get(symbol, time.time())
        if elapsed < MIN_ELAPSED_TIME:
            return {"signal": False}

        old_price = prices[0]
        last_price = prices[-1]

        if old_price <= 0:
            return {"signal": False}

        change_pct = ((last_price - old_price) / old_price) * 100
        strength = abs(change_pct)

        if strength < ENTRY_SIGNAL_THRESHOLD:
            return {
                "signal": False,
                "strength": round(strength, 4)
            }

        direction = "long" if change_pct > 0 else "short"

        return {
            "signal": True,
            "direction": direction,
            "strength": round(strength, 4),
            "entry_price": round(last_price, 6),
        }

    except Exception:
        # Nunca crasha, devuelve False
        return {"signal": False}
