# ============================================================
# STRATEGY – MOMENTUM ACUMULADO (PRODUCCIÓN REAL)
# ============================================================

from collections import deque
import time
from app.hyperliquid_client import get_price

PRICE_WINDOW = 6
ENTRY_SIGNAL_THRESHOLD = 0.25
PRICE_BUFFER_TTL = 15

price_buffer = {}
price_timestamp = {}

def update_price(symbol: str, price: float):
    now = time.time()

    if symbol not in price_buffer:
        price_buffer[symbol] = deque(maxlen=PRICE_WINDOW)

    if now - price_timestamp.get(symbol, 0) > PRICE_BUFFER_TTL:
        price_buffer[symbol].clear()

    price_buffer[symbol].append(price)
    price_timestamp[symbol] = now


def get_entry_signal(symbol: str) -> dict:
    price = get_price(symbol)
    if not price or price <= 0:
        return {"signal": False}

    update_price(symbol, price)

    prices = price_buffer.get(symbol)
    if not prices or len(prices) < PRICE_WINDOW:
        return {"signal": False}

    old_price = prices[0]
    change = (price - old_price) / old_price
    strength = abs(change) * 100

    if strength < ENTRY_SIGNAL_THRESHOLD:
        return {"signal": False, "strength": round(strength, 4)}

    return {
        "signal": True,
        "direction": "long" if change > 0 else "short",
        "strength": round(strength, 4),
        "entry_price": price
    }


def calculate_targets(entry_price: float, tp: float, sl: float, direction: str):
    if direction == "long":
        return {
            "tp": round(entry_price * (1 + tp), 6),
            "sl": round(entry_price * (1 - sl), 6),
        }
    else:
        return {
            "tp": round(entry_price * (1 - tp), 6),
            "sl": round(entry_price * (1 + sl), 6),
        }
