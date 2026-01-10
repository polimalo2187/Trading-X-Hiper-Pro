from app.config import MIN_CAPITAL, POSITION_PERCENT

def calculate_dynamic_tp_sl(strength: float):
    strength = max(min(strength, 8.0), 0.15)

    if strength < 1.5:
        return 0.006, 0.004
    elif strength < 3:
        return 0.012, 0.006
    elif strength < 5:
        return 0.020, 0.009
    else:
        return 0.035, 0.012

def validate_trade_conditions(balance: float, strength: float):
    balance = max(balance, MIN_CAPITAL)
    base = balance * POSITION_PERCENT

    if strength >= 5:
        base *= 1.4
    elif strength >= 3:
        base *= 1.2

    base = max(round(base, 4), 1.0)
    tp, sl = calculate_dynamic_tp_sl(strength)

    return {
        "ok": True,
        "tp": tp,
        "sl": sl,
        "position_size": base,
    }
