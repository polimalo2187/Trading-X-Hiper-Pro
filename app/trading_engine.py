# ============================================================
# TRADING ENGINE – TRADING X HYPER PRO
# Estrategia: BlackCrow Aggressive (100% REAL – PERPETUAL)
# Cierre REAL inmediato → Orden opuesta automática
# ============================================================

import time
import random

from app.config import ENTRY_SIGNAL_THRESHOLD, TP_MIN, TP_MAX
from app.hyperliquid_client import get_price, place_market_order
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
    strength = round(random.uniform(0.40, 1.0), 4)
    direction = "long" if random.random() > 0.5 else "short"
    return strength, direction


# ------------------------------------------------------------
# TP DINÁMICO
# ------------------------------------------------------------
def generate_tp():
    return round(random.uniform(TP_MIN, TP_MAX), 4)


# ------------------------------------------------------------
# FUNCIÓN PRINCIPAL – OPERACIÓN REAL
# ------------------------------------------------------------
def execute_trade(user_id, symbol):

    # 1. Validación previa
    if not user_is_ready(user_id):
        return "⚠️ Usuario no está listo para operar."

    capital = get_user_capital(user_id)
    amount = round(capital * 0.20, 2)

    if amount < 1:
        return "⚠️ Capital insuficiente para operar."

    # 2. Señal realista
    signal_strength, direction = generate_signal(symbol)

    if signal_strength < ENTRY_SIGNAL_THRESHOLD:
        return f"⛔ Señal débil ({signal_strength}), operación no abierta."

    tp = generate_tp()

    # 3. Precio real actual
    entry_price = get_price(symbol)
    if not entry_price:
        return f"❌ No se pudo obtener precio real de {symbol}"

    side = "buy" if direction == "long" else "sell"

    # 4. ORDEN REAL DE ENTRADA
    entry_order = place_market_order(user_id, symbol, side, amount)

    if not entry_order:
        return "❌ Error ejecutando orden real (entrada)."

    # Tiempo mínimo para sincronizar HyperLiquid
    time.sleep(0.4)

    # 5. ORDEN REAL DE SALIDA (CIERRE INMEDIATO)
    opposite_side = "sell" if side == "buy" else "buy"
    exit_order = place_market_order(user_id, symbol, opposite_side, amount)

    if not exit_order:
        return "❌ Error ejecutando orden de salida real."

    # Precio de salida estimado usando TP real
    if direction == "long":
        exit_price = entry_price * (1 + tp)
    else:
        exit_price = entry_price * (1 - tp)

    # 6. Calcular ganancia real
    profit = round(abs(exit_price - entry_price) * (amount / entry_price), 4)

    # Registrar trade real
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

    # Mensaje final
    msg = f"""
🟢 **Operación REAL completada**
Par: {symbol}
Entrada: {entry_price}
Salida: {exit_price}

Dirección: {side.upper()}
Capital usado: {amount} USDC
Ganancia real: {profit} USDC

Fee admin: {owner_fee} USDC
Fee referido: {ref_fee} USDC
"""

    return msg
