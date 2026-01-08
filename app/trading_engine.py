# ============================================================
# TRADING ENGINE – Trading X Hyper Pro
# Archivo 7/9 – Motor REAL producción nivel banco (CORREGIDO)
# ============================================================

import time

from app.market_scanner import get_best_symbol
from app.strategy import get_entry_signal, calculate_targets
from app.risk import validate_trade_conditions
from app.hyperliquid_client import place_market_order, get_price

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

    # 1) VALIDAR USUARIO
    if not user_is_ready(user_id):
        return "⚠️ Tu cuenta no está lista para operar."

    capital = get_user_capital(user_id)

    # 2) MEJOR PAR DEL MERCADO
    best = get_best_symbol()
    if not best:
        return "❌ No se pudo obtener un par óptimo."

    symbol = best["symbol"]

    # 3) SEÑAL DE ENTRADA
    signal = get_entry_signal(symbol)
    if not signal["signal"]:
        return f"⛔ Señal débil ({signal.get('strength', 0)}) en {symbol}"

    strength = signal["strength"]
    entry_price = signal["entry_price"]
    direction = signal["direction"]

    side = "buy" if direction == "long" else "sell"
    opposite_side = "sell" if side == "buy" else "buy"

    # 4) GESTIÓN DE RIESGO
    risk = validate_trade_conditions(capital, strength)
    if not risk["ok"]:
        return f"⛔ {risk['reason']}"

    position_size = risk["position_size"]
    tp_percent = risk["tp"]
    sl_percent = risk["sl"]

    # 5) ORDEN DE ENTRADA REAL
    entry_order = place_market_order(user_id, symbol, side, position_size)
    if not entry_order:
        return f"❌ Error ejecutando orden de entrada en {symbol}."

    # 6) CALCULAR TP / SL REALES
    targets = calculate_targets(entry_price, tp_percent, sl_percent, direction)
    tp_price = targets["tp"]
    sl_price = targets["sl"]

    # 7) MONITOREO REAL DE PRECIO (TP / SL)
    exit_price = None
    exit_reason = None

    while True:
        current_price = get_price(symbol)
        if not current_price:
            time.sleep(0.5)
            continue

        if direction == "long":
            if current_price >= tp_price:
                exit_price = current_price
                exit_reason = "TP"
                break
            if current_price <= sl_price:
                exit_price = current_price
                exit_reason = "SL"
                break
        else:
            if current_price <= tp_price:
                exit_price = current_price
                exit_reason = "TP"
                break
            if current_price >= sl_price:
                exit_price = current_price
                exit_reason = "SL"
                break

        time.sleep(0.5)

    # 8) ORDEN DE SALIDA REAL
    exit_order = place_market_order(user_id, symbol, opposite_side, position_size)
    if not exit_order:
        return f"❌ Error ejecutando orden de salida en {symbol}."

    # 9) CÁLCULO REAL DE GANANCIA / PÉRDIDA
    profit = round(
        (exit_price - entry_price) * (position_size / entry_price)
        if direction == "long"
        else (entry_price - exit_price) * (position_size / entry_price),
        6
    )

    # 10) REGISTRO DEL TRADE
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

    # 11) FEES
    admin_fee = round(max(profit, 0) * OWNER_FEE_PERCENT, 6)
    ref_fee = 0.0

    referrer = get_user_referrer(user_id)
    if referrer and admin_fee > 0:
        ref_fee = round(admin_fee * REFERRAL_FEE_PERCENT, 6)
        add_weekly_ref_fee(referrer, ref_fee)
        admin_fee = round(admin_fee - ref_fee, 6)

    if admin_fee > 0:
        add_daily_admin_fee(user_id, admin_fee)

    # 12) MENSAJE FINAL
    return f"""
🟢 **Operación REAL completada**

**Par:** {symbol}
**Dirección:** {side.upper()}
**Resultado:** {exit_reason}

📈 Entrada: `{entry_price}`
📉 Salida: `{exit_price}`

💰 Capital usado: `{position_size} USDC`
💵 PnL real: `{profit} USDC`

🏦 Admin Fee: `{admin_fee} USDC`
👥 Referral Fee: `{ref_fee} USDC`
📊 Score del par: `{best['score']}`
"""
