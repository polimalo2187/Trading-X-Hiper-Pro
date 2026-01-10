# ============================================================
# TRADING ENGINE – PRODUCCIÓN
# ============================================================

from app.strategy import get_entry_signal, calculate_targets
from app.hyperliquid_client import place_market_order, get_price, get_balance
from app.database import get_user_symbol, set_user_position

# ============================================================
# EXECUTE TRADE
# ============================================================

def execute_trade(user_id: int):
    symbol = get_user_symbol(user_id)
    if not symbol:
        return None

    balance = get_balance(user_id)
    if balance <= 0:
        return None

    signal = get_entry_signal(symbol)
    if not signal:
        return None

    side = signal["side"]
    price = signal["price"]

    qty = round(balance * 0.95 / price, 4)
    if qty <= 0:
        return None

    order = place_market_order(
        user_id=user_id,
        symbol=symbol,
        side=side,
        qty=qty,
    )

    tp, sl = calculate_targets(price)

    set_user_position(
        user_id=user_id,
        symbol=symbol,
        side=side,
        entry=price,
        qty=qty,
        tp=tp,
        sl=sl,
    )

    return {
        "event": "OPEN",
        "open": {
            "message": (
                f"📈 *TRADE ABIERTO*\n"
                f"Par: `{symbol}`\n"
                f"Lado: `{side}`\n"
                f"Entrada: `{price}`\n"
                f"TP: `{tp}`\n"
                f"SL: `{sl}`"
            )
        }
    }
