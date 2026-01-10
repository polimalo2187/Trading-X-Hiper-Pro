# ============================================================
# STRATEGY CORE
# ============================================================

from app.hyperliquid_client import get_price

# ============================================================
# ENTRY SIGNAL
# ============================================================

def get_entry_signal(symbol: str):
    price = get_price(symbol)
    if price is None:
        return None

    # EJEMPLO SIMPLE (tu lógica real puede ser más compleja)
    return {
        "side": "BUY",
        "price": price,
    }

# ============================================================
# TARGETS
# ============================================================

def calculate_targets(price: float):
    tp = price * 1.01
    sl = price * 0.99
    return tp, sl
