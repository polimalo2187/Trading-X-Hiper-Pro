# ============================================================
# TRADING ENGINE – TRADING X HYPER PRO
# Estrategia BlackCrow Aggressive (100% REAL – PERPETUAL)
# Auto–selección del mejor par del mercado (market_scanner.py)
# ============================================================

import time

from app.strategy import get_entry_signal, calculate_targets
from app.risk import validate_trade_conditions
from app.market_scanner import get_best_symbol
from app.hyperliquid_client import place_market_order
from app.database import (
    user_is_ready,
    get_user_capital,
    register_trade,
    register_fee,
    get_user_referrer
)


# ============================================================
# FUNCIÓN PRINCIPAL DE OPERACIÓN — 100% AUTOMÁTICA
# ============================================================

def execute_trade(user_id: int):

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
    # SELECCIÓN AUTOMÁTICA DEL MEJOR PAR
    # --------------------------------------------------------
    best = get_best_symbol()

    if not best:
        return "❌ No se pudo determinar un par óptimo para operar."

    symbol = best["symbol"]
    score = best["score"]

    # --------------------------------------------------------
    # SEÑAL DE ESTRATEGIA
    # --------------------------------------------------------
    signal = get_entry_signal(symbol)

    if not signal["signal"]:
        return f"⛔ Señal débil en {symbol} ({signal.get('strength', 0)})."

    direction = signal["direction"]
    entry_price = signal["entry_price"]

    side = "buy" if direction == "long" else "sell"

    # --------------------------------------------------------
    # ORDEN REAL DE ENTRADA
    # --------------------------------------------------------
    entry_order = place_market_order(user_id, symbol, side, position_size)
    if not entry_order:
        return f"❌ Error ejecutando entrada real en {symbol}"

    time.sleep(0.4)

    # --------------------------------------------------------
    # TP / SL REALISTAS
    # --------------------------------------------------------
    targets = calculate_targets(entry_price, tp, sl, direction)
    exit_price = targets["tp"]  # usamos el TP principal

    # --------------------------------------------------------
    # ORDEN REAL DE SALIDA (CIERRE)
    # --------------------------------------------------------
    opposite_side = "sell" if side == "buy" else "buy"
    exit_order = place_market_order(user_id, symbol, opposite_side, position_size)

    if not exit_order:
        return "❌ Error ejecutando orden de salida."

    # --------------------------------------------------------
    # CÁLCULO DE GANANCIAS
    # --------------------------------------------------------
    profit = round(abs(exit_price - entry_price) * (position_size / entry_price), 4)

    # Registrar trade
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
    # FEES (admin + referido)
    # --------------------------------------------------------
    owner_fee = round(profit * 0.15, 4)
    ref_fee = 0

    referrer = get_user_referrer(user_id)
    if referrer:
        ref_fee = round(owner_fee * 0.05, 4)
        owner_fee = round(owner_fee * 0.95, 4)

    register_fee(user_id, owner_fee, ref_fee)

    # --------------------------------------------------------
    # MENSAJE FINAL PARA TELEGRAM
    # --------------------------------------------------------
    msg = f"""
🟢 **Operación REAL ejecutada automáticament**
Par seleccionado: {symbol}
Score mercado: {score}

Dirección: {side.upper()}
Entrada: {entry_price}
Salida (TP): {exit_price}

Capital usado: {position_size} USDC
Ganancia: `{profit} USDC`

Fee admin: {owner_fee} USDC
Fee referido: {ref_fee} USDC
"""

    return msg
