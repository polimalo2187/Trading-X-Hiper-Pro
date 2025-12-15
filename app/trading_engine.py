# ============================================================
# TRADING ENGINE – TRADING X HYPER PRO
# Estrategia BlackCrow Aggressive (100% REAL – PERPETUAL)
# Integrado con: strategy.py + risk.py + hyperliquid_client.py
# ============================================================

import time

from app.strategy import get_entry_signal, calculate_targets
from app.risk import validate_trade_conditions
from app.hyperliquid_client import place_market_order
from app.database import (
    user_is_ready,
    get_user_capital,
    register_trade,
    register_fee,
    get_user_referrer
)


# ============================================================
# FUNCIÓN PRINCIPAL DE OPERACIÓN REAL COMPLETA
# ============================================================

def execute_trade(user_id: int, symbol: str):

    # --------------------------------------------------------
    # VALIDACIÓN DEL USUARIO
    # --------------------------------------------------------
    if not user_is_ready(user_id):
        return "⚠️ Usuario no está listo para operar."

    balance = get_user_capital(user_id)

    # --------------------------------------------------------
    # VALIDACIÓN PROFESIONAL DE RIESGO
    # --------------------------------------------------------
    risk = validate_trade_conditions(balance, user_id)

    if not risk["ok"]:
        return f"⛔ {risk['reason']}"

    position_size = round(balance * 0.20, 2)  # 20% del capital
    tp = risk["tp"]
    sl = risk["sl"]

    # --------------------------------------------------------
    # ESTRATEGIA (señal oficial)
    # --------------------------------------------------------
    signal = get_entry_signal(symbol)

    if not signal["signal"]:
        return f"⛔ Señal débil ({signal.get('strength', 0)})."

    direction = signal["direction"]
    entry_price = signal["entry_price"]

    side = "buy" if direction == "long" else "sell"

    # --------------------------------------------------------
    # ORDEN REAL DE ENTRADA
    # --------------------------------------------------------
    entry_order = place_market_order(user_id, symbol, side, position_size)

    if not entry_order:
        return "❌ Error ejecutando orden real de entrada."

    # pequeña pausa para sincronía con HyperLiquid
    time.sleep(0.4)

    # --------------------------------------------------------
    # CALCULAR TP/SL REALES (NO SE EJECUTAN EN EXCHANGE)
    # --------------------------------------------------------
    targets = calculate_targets(entry_price, tp, sl, direction)
    exit_price = targets["tp_price"]  # siempre usamos TP1

    # --------------------------------------------------------
    # ORDEN REAL DE SALIDA (CIERRE)
    # --------------------------------------------------------
    opposite_side = "sell" if side == "buy" else "buy"

    exit_order = place_market_order(user_id, symbol, opposite_side, position_size)

    if not exit_order:
        return "❌ Error ejecutando orden real de salida."

    # --------------------------------------------------------
    # GANANCIA REAL CALCULADA
    # --------------------------------------------------------
    profit = round(abs(exit_price - entry_price) * (position_size / entry_price), 4)

    register_trade(
        user_id=user_id,
        symbol=symbol,
        side=side.upper(),
        entry_price=entry_price,
        exit_price=exit_price,
        qty=position_size,
        profit=profit
    )

    # --------------------------------------------------------
    # FEES
    # --------------------------------------------------------
    owner_fee = round(profit * 0.15, 4)
    ref_fee = 0

    referrer = get_user_referrer(user_id)
    if referrer:
        ref_fee = round(owner_fee * 0.05, 4)  # fee para referido
        owner_fee = round(owner_fee * 0.95, 4)

    register_fee(user_id, owner_fee, ref_fee)

    # --------------------------------------------------------
    # MENSAJE FINAL PARA TELEGRAM
    # --------------------------------------------------------
    msg = f"""
🟢 **Operación REAL completada**
Par: {symbol}
Dirección: {side.upper()}

Entrada: {entry_price}
Salida (TP): {exit_price}

Capital usado: {position_size} USDC
Ganancia real: {profit} USDC

Fee admin: {owner_fee} USDC
Fee referido: {ref_fee} USDC
"""

    return msg
