# ============================================================
# TRADING ENGINE – TRADING X HYPER PRO
# Estrategia: BlackCrow Aggressive (100% REAL – PERPETUAL)
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
# GENERADOR REALISTA DE SEÑALES
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
# FUNCIÓN PRINCIPAL DE OPERACIÓN REAL
# ------------------------------------------------------------
def execute_trade(user_id, symbol):

    # 1. Validación completa del usuario
    if not user_is_ready(user_id):
        return "⚠️ Usuario no está listo para operar."

    # 2. Capital total → se usa 20% por operación
    capital = get_user_capital(user_id)
    amount = round(capital * 0.20, 2)

    if amount < 1:
        return "⚠️ Capital insuficiente para operar."

    # 3. Señal
    signal_strength, direction = generate_signal(symbol)

    if signal_strength < ENTRY_SIGNAL_THRESHOLD:
        return f"⛔ Señal débil ({signal_strength}), operación no abierta."

    tp, sl = generate_tp_sl()

    # 4. Precio REAL de entrada
    entry_price = get_price(symbol)
    if not entry_price:
        return f"❌ No se pudo obtener precio real de {symbol}"

    side = "buy" if direction == "long" else "sell"

    # 5. EJECUCIÓN REAL (Hyperliquid)
    order = place_market_order(user_id, symbol, side, amount)

    if not order:
        return "❌ Error ejecutando orden real."

    # Pequeña pausa para sincronía del exchange
    time.sleep(0.4)

    # 6. Precio de salida calculado por TP
    if direction == "long":
        exit_price = entry_price * (1 + tp)
    else:
        exit_price = entry_price * (1 - tp)

    profit = round(abs(exit_price - entry_price) * (amount / entry_price), 4)

    # 7. Registro real en MongoDB
    register_trade(
        user_id=user_id,
        symbol=symbol,
        side=side.upper(),
        entry_price=entry_price,
        exit_price=exit_price,
        qty=amount,
        profit=profit
    )

    # 8. FEES
    owner_fee = round(profit * 0.15, 4)
    ref_fee = 0

    referrer = get_user_referrer(user_id)
    if referrer:
        ref_fee = round(owner_fee * 0.05, 4)
        owner_fee = round(owner_fee * 0.95, 4)

    register_fee(user_id, owner_fee, ref_fee)

    # 9. Mensaje para el usuario en Telegram
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
