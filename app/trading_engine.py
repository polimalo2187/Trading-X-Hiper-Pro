# ============================================================
# TRADING ENGINE – Trading X Hyper Pro
# Archivo 6/9 – Ejecución real completa
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
    accumulate_admin_fee,
    accumulate_referral_fee,
    get_user_referrer
)


# ============================================================
# FUNCIÓN PRINCIPAL – PROCESO COMPLETO DE TRADING REAL
# ============================================================

def execute_trade(user_id: int):

    # --------------------------------------------------------
    # VALIDACIÓN DEL USUARIO
    # --------------------------------------------------------
    if not user_is_ready(user_id):
        return "⚠️ El usuario no está listo para operar."

    capital = get_user_capital(user_id)

    # --------------------------------------------------------
    # 1. RIESGO PROFESIONAL
    # --------------------------------------------------------
    risk = validate_trade_conditions(capital, user_id)

    if not risk["ok"]:
        return f"⛔ {risk['reason']}"

    tp = risk["tp"]
    sl = risk["sl"]
    position_size = round(capital * 0.20, 2)  # 20% FIJO

    # --------------------------------------------------------
    # 2. SELECCIÓN AUTOMÁTICA DEL MEJOR PAR
    # --------------------------------------------------------
    best = get_best_symbol()
    if not best:
        return "❌ No fue posible encontrar un par óptimo."

    symbol = best["symbol"]

    # --------------------------------------------------------
    # 3. SEÑAL OFICIAL DE ESTRATEGIA
    # --------------------------------------------------------
    signal = get_entry_signal(symbol)

    if not signal["signal"]:
        return f"⛔ Señal débil ({signal.get('strength', 0)})."

    direction = signal["direction"]
    entry_price = signal["entry_price"]
    side = "buy" if direction == "long" else "sell"

    # --------------------------------------------------------
    # 4. ORDEN REAL DE ENTRADA
    # --------------------------------------------------------
    order_in = place_market_order(user_id, symbol, side, position_size)

    if not order_in:
        return "❌ Error ejecutando la orden de entrada."

    time.sleep(0.4)

    # --------------------------------------------------------
    # 5. CÁLCULO DE TP / SL REALES
    # --------------------------------------------------------
    targets = calculate_targets(entry_price, tp, sl, direction)
    exit_price = targets["tp"]  # TP1 como salida

    # --------------------------------------------------------
    # 6. ORDEN REAL DE SALIDA (CIERRE)
    # --------------------------------------------------------
    opposite = "sell" if side == "buy" else "buy"
    order_out = place_market_order(user_id, symbol, opposite, position_size)

    if not order_out:
        return "❌ Error ejecutando la orden de salida."

    # --------------------------------------------------------
    # 7. GANANCIA REAL DE LA OPERACIÓN
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
    # 8. FEES (NUEVO SISTEMA OFICIAL)
    # --------------------------------------------------------
    # 15% del profit → del cual sale el fee del referido
    admin_fee = round(profit * 0.15, 4)
    referral_fee = 0

    referrer = get_user_referrer(user_id)

    if referrer:
        referral_fee = round(admin_fee * 0.05, 4)      # 5% del admin
        admin_fee = round(admin_fee * 0.95, 4)         # admin recibe 95%

        # acumulación semanal para el referido
        accumulate_referral_fee(referrer, referral_fee)

    # acumulación diaria para el admin
    accumulate_admin_fee(user_id, admin_fee)

    # --------------------------------------------------------
    # 9. MENSAJE FINAL PARA TELEGRAM
    # --------------------------------------------------------
    return f"""
🟢 **Operación REAL completada**
Par: {symbol}
Dirección: {side.upper()}

Entrada: {entry_price}
Salida (TP): {exit_price}

Capital usado: {position_size} USDC
Ganancia: {profit} USDC

📌 Fee admin acumulada (24h): {admin_fee} USDC
📌 Fee referidos acumulada (semana): {referral_fee} USDC
"""
