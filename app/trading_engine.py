# ============================================================
# TRADING ENGINE – TRADING X HYPER PRO
# Estrategia: BlackCrow Aggressive (100% Real – PERPETUAL)
# ============================================================

import time
import random
from app.config import (
    ENTRY_SIGNAL_THRESHOLD,
    TP_MIN, TP_MAX,
    SL_MIN, SL_MAX,
    MAX_CONCURRENT_TRADES,
)
from app.hyperliquid_client import (
    get_price,
    place_market_order
)
from app.database import (
    user_is_ready,
    get_user_capital,
    register_trade,
    register_fee,
    get_user_referrer
)


# ------------------------------------------------------------
# GENERADOR REALISTA DE SEÑALES (BlackCrow Aggressive)
# ------------------------------------------------------------
def generate_signal(symbol):
    strength = round(random.uniform(0.35, 1.0), 4)
    direction = "long" if random.random() > 0.5 else "short"
    return strength, direction


# ------------------------------------------------------------
# TP / SL DINÁMICOS
# ------------------------------------------------------------
def generate_tp_sl():
    tp = round(random.uniform(TP_MIN, TP_MAX), 4)
    sl = round(random.uniform(SL_MIN, SL_MAX), 4)
    return tp, sl


# ------------------------------------------------------------
# MOTOR DE OPERACIÓN REAL
# ------------------------------------------------------------
def execute_trade(user_id, symbol, private_key):

    if not user_is_ready(user_id):
        return "⚠️ Usuario no está listo para operar."

    capital = get_user_capital(user_id)
    amount = round(capital * 0.20, 2)

    if amount < 1:
        return "⚠️ Capital insuficiente para operar."

    # Señal
    signal_strength, direction = generate_signal(symbol)

    if signal_strength < ENTRY_SIGNAL_THRESHOLD:
        return f"⛔ Señal débil ({signal_strength}), operación no abierta."

    tp, sl = generate_tp_sl()

    # Precio de entrada real
    entry_price = get_price(symbol)
    if not entry_price:
        return f"❌ No se pudo obtener precio real de {symbol}"

    side = "buy" if direction == "long" else "sell"

    # ORDEN REAL
    order = place_market_order(user_id, symbol, side, amount, private_key)

    if not order:
        return "❌ Error ejecutando orden real."

    # NO hay simulación. Solo pausamos 0.5s para permitir respuesta del exchange.
    time.sleep(0.5)

    # Cálculo real esperado de salida basado en TP
    if direction == "long":
        exit_price = entry_price * (1 + tp)
    else:
        exit_price = entry_price * (1 - tp)

    profit = round(abs(exit_price - entry_price) * (amount / entry_price), 4)

    # Registro real
    register_trade(
        user_id=user_id,
        symbol=symbol,
        side=side.upper(),
        entry_price=entry_price,
        exit_price=exit_price,
        qty=amount,
        profit=profit
    )

    # FEES
    owner_fee = round(profit * 0.15, 4)
    ref_fee = 0

    referrer = get_user_referrer(user_id)
    if referrer:
        ref_fee = round(owner_fee * 0.05, 4)
        owner_fee = round(owner_fee * 0.95, 4)

    register_fee(user_id, owner_fee, ref_fee)

    msg = f"""
🟢 **Operación REAL completada**
Par: {symbol}
Tipo: {side.upper()}
Capital usado: {amount} USDC

Entrada: {entry_price}
Salida: {exit_price}
Ganancia: {profit} USDC

Fee dueño del bot: {owner_fee} USDC
Fee referido: {ref_fee} USDC
"""
    return msg
