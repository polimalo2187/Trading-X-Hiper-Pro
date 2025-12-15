# ============================================================
# TRADING ENGINE – TRADING X HYPER PRO
# Maneja: scanner → señal → riesgo → entrada → salida → registro
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
    register_fee,
    get_user_referrer
)


# ============================================================
# EJECUTAR UNA OPERACIÓN COMPLETA AUTOMÁTICAMENTE
# ============================================================

def execute_trade(user_id: int):
    """
    Ejecuta una operación completa:
    - Escanea el mercado → mejor par
    - Genera señal → valida señal
    - Valida riesgo
    - Abre posición real
    - Cierra posición real
    - Registra profit y fees
    """

    # 1. Usuario listo
    if not user_is_ready(user_id):
        return "⚠️ El usuario no está listo para operar."

    balance = get_user_capital(user_id)

    # 2. Validación de riesgo
    risk = validate_trade_conditions(balance, user_id)

    if not risk["ok"]:
        return f"⛔ {risk['reason']}"

    position_size = round(balance * 0.20, 2)
    tp = risk["tp"]
    sl = risk["sl"]

    # 3. Escanear mercado y elegir MEJOR PAR
    best = get_best_symbol()

    if not best:
        return "❌ No se pudo seleccionar un par óptimo."

    symbol = best["symbol"]

    # 4. Señal de entrada según estrategia
    signal = get_entry_signal(symbol)

    if not signal["signal"]:
        return f"⛔ Señal débil en {symbol}."

    entry_price = signal["entry_price"]
    direction = signal["direction"]
    side = "buy" if direction == "long" else "sell"

    # 5. ORDEN REAL DE ENTRADA
    entry = place_market_order(user_id, symbol, side, position_size)

    if not entry:
        return "❌ Error ejecutando entrada real."

    time.sleep(0.5)  # sincronía con HyperLiquid

    # 6. Calcular salida TP
    targets = calculate_targets(entry_price, tp, sl, direction)
    exit_price = targets["tp"]

    opposite_side = "sell" if side == "buy" else "buy"

    # 7. ORDEN REAL DE SALIDA
    exit_order = place_market_order(user_id, symbol, opposite_side, position_size)

    if not exit_order:
        return "❌ Error ejecutando cierre real."

    # 8. Calcular ganancia
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

    # 9. Fees automáticos
    owner_fee = round(profit * 0.15, 4)
    ref_fee = 0

    referrer = get_user_referrer(user_id)
    if referrer:
        ref_fee = round(owner_fee * 0.05, 4)
        owner_fee = round(owner_fee * 0.95, 4)

    register_fee(user_id, owner_fee, ref_fee)

    # 10. Mensaje final
    return f"""
🟢 **Operación REAL completada**
Par seleccionado: {symbol}
Dirección: {side.upper()}

Entrada: {entry_price}
Salida (TP): {exit_price}

Capital usado: {position_size} USDC
Ganancia real: {profit} USDC

Fee administrador: {owner_fee} USDC
Fee referido: {ref_fee} USDC
"""
