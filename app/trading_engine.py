# ============================================================
# TRADING ENGINE – Trading X Hyper Pro
# Archivo 7/9 – Motor REAL producción nivel banco
# ============================================================

import time

from app.market_scanner import get_best_symbol
from app.strategy import get_entry_signal, calculate_targets
from app.risk import validate_trade_conditions
from app.hyperliquid_client import place_market_order

from app.database import (
    user_is_ready,
    get_user_capital,
    register_trade,
    add_daily_admin_fee,
    add_weekly_ref_fee,
    get_user_referrer,
)

from app.config import (
    OWNER_FEE_PERCENT,
    REFERRAL_FEE_PERCENT,
)


# ============================================================
# EJECUCIÓN COMPLETA DEL TRADE REAL
# ============================================================

def execute_trade(user_id: int):

    # 1) USUARIO LISTO
    if not user_is_ready(user_id):
        return "⚠️ Tu cuenta no está lista para operar."

    capital = get_user_capital(user_id)

    # 2) MEJOR PAR DEL MERCADO
    best = get_best_symbol()
    if not best:
        return "❌ No se pudo obtener un par óptimo."

    symbol = best["symbol"]

    # 3) SEÑAL REAL (fuerza → usada en risk management)
    signal = get_entry_signal(symbol)

    if not signal["signal"]:
        return f"⛔ Señal débil ({signal.get('strength', 0)}) en {symbol}"

    strength = signal["strength"]
    entry_price = signal["entry_price"]
    direction = signal["direction"]
    side = "buy" if direction == "long" else "sell"

    # 4) VALIDAR RIESGO ahora que ya tenemos strength
    risk = validate_trade_conditions(capital, strength)
    if not risk["ok"]:
        return f"⛔ {risk['reason']}"

    position_size = risk["position_size"]
    tp_percent = risk["tp"]
    sl_percent = risk["sl"]

    # 5) ENTRADA REAL
    entry_order = place_market_order(user_id, symbol, side, position_size)
    if not entry_order:
        return f"❌ Error ejecutando orden de entrada en {symbol}."

    time.sleep(0.35)

    # 6) TP/SL REAL
    targets = calculate_targets(entry_price, tp_percent, sl_percent, direction)
    exit_price = targets["tp"]

    # 7) SALIDA REAL
    opposite_side = "sell" if side == "buy" else "buy"
    exit_order = place_market_order(user_id, symbol, opposite_side, position_size)

    if not exit_order:
        return f"❌ Error ejecutando orden de salida en {symbol}."

    # 8) GANANCIA REAL
    profit = round(abs(exit_price - entry_price) * (position_size / entry_price), 6)

    # 9) REGISTRO DEL TRADE (incluye best_score)
    register_trade(
        user_id=user_id,
        symbol=symbol,
        side=side.upper(),
        entry_price=entry_price,
        exit_price=exit_price,
        qty=position_size,
        profit=profit,
        best_score=best["score"]
    )

    # 10) FEES
    admin_fee = round(profit * OWNER_FEE_PERCENT, 6)
    ref_fee = 0

    referrer = get_user_referrer(user_id)

    if referrer:
        ref_fee = round(admin_fee * REFERRAL_FEE_PERCENT, 6)
        add_weekly_ref_fee(referrer, ref_fee)
        admin_fee = round(admin_fee - ref_fee, 6)

    add_daily_admin_fee(user_id, admin_fee)

    # 11) MENSAJE FINAL
    return f"""
🟢 **Operación REAL completada**

**Par:** {symbol}
**Dirección:** {side.upper()}

📈 Entrada: `{entry_price}`
📉 Salida (TP): `{exit_price}`

💰 Capital usado: `{position_size} USDC`
💵 Ganancia real: `{profit} USDC`

🏦 Admin Fee: `{admin_fee} USDC`
👥 Referral Fee: `{ref_fee} USDC`
📊 Score del par: `{best['score']}`
"""
