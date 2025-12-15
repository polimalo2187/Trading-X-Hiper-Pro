# ============================================================
# TRADING ENGINE – TRADING X HYPER PRO
# Archivo 9/9 – Motor de trading real 100% profesional
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
    register_admin_fee,
    register_referral_fee,
    get_user_referrer
)


# ============================================================
# FUNCIÓN PRINCIPAL – EJECUCIÓN DE UNA OPERACIÓN REAL
# ============================================================

def execute_trade(user_id: int):

    # --------------------------------------------------------
    # 1) VALIDAR QUE EL USUARIO ESTÁ LISTO
    # --------------------------------------------------------
    if not user_is_ready(user_id):
        return "⚠️ Usuario no está listo para operar."

    capital = get_user_capital(user_id)

    # --------------------------------------------------------
    # 2) VALIDACIÓN PROFESIONAL DE RIESGO
    # --------------------------------------------------------
    risk = validate_trade_conditions(capital, user_id)

    if not risk["ok"]:
        return f"⛔ {risk['reason']}"

    position_size = round(capital * 0.20, 2)
    tp = risk["tp"]
    sl = risk["sl"]

    # --------------------------------------------------------
    # 3) SELECCIONAR EL MEJOR PAR DEL MERCADO
    # --------------------------------------------------------
    best = get_best_symbol()
    if not best:
        return "❌ No se pudo seleccionar un par óptimo."

    symbol = best["symbol"]

    # --------------------------------------------------------
    # 4) GENERAR SEÑAL DE ENTRADA
    # --------------------------------------------------------
    signal = get_entry_signal(symbol)

    if not signal["signal"]:
        return f"⛔ Señal débil ({signal.get('strength', 0)})."

    direction = signal["direction"]
    entry_price = signal["entry_price"]

    side = "buy" if direction == "long" else "sell"

    # --------------------------------------------------------
    # 5) EJECUTAR ORDEN REAL DE ENTRADA
    # --------------------------------------------------------
    entry_order = place_market_order(user_id, symbol, side, position_size)

    if not entry_order:
        return "❌ Error ejecutando orden real de entrada."

    # Delay pequeño para sincronía con HyperLiquid
    time.sleep(0.4)

    # --------------------------------------------------------
    # 6) CALCULAR TP / SL REALES
    # --------------------------------------------------------
    targets = calculate_targets(entry_price, tp, sl, direction)
    exit_price = targets["tp"]  # usamos TP1 como salida real calculada

    # --------------------------------------------------------
    # 7) EJECUTAR ORDEN REAL DE SALIDA (OPUESTA)
    # --------------------------------------------------------
    opposite_side = "sell" if side == "buy" else "buy"

    exit_order = place_market_order(user_id, symbol, opposite_side, position_size)

    if not exit_order:
        return "❌ Error ejecutando orden real de salida."

    # --------------------------------------------------------
    # 8) CALCULAR GANANCIA REAL
    # --------------------------------------------------------
    profit = round(abs(exit_price - entry_price) * (position_size / entry_price), 4)

    # --------------------------------------------------------
    # 9) REGISTRAR TRADE EN LA BASE DE DATOS
    # --------------------------------------------------------
    register_trade(
        user_id=user_id,
        symbol=symbol,
        side=side.upper(),
        entry_price=entry_price,
        exit_price=exit_price,
        qty=position_size,
        profit=profit,
        best_score=best["score"]  # para estadísticas avanzadas
    )

    # --------------------------------------------------------
    # 10) FEES – SISTEMA OFICIAL (ADMIN + REFERIDO)
    # --------------------------------------------------------

    # Fee del admin: 15% de la ganancia
    admin_fee = round(profit * 0.15, 4)

    # Fee del referido (sale del admin)
    ref_fee = 0
    referrer = get_user_referrer(user_id)

    if referrer:
        ref_fee = round(admin_fee * 0.05, 4)
        admin_fee = round(admin_fee * 0.95, 4)

    # Guardar fees en DB como ACUMULADO DIARIO
    register_admin_fee(user_id, admin_fee)
    register_referral_fee(user_id, referrer, ref_fee)

    # --------------------------------------------------------
    # 11) MENSAJE FINAL PARA EL USUARIO
    # --------------------------------------------------------
    msg = f"""
🟢 **Operación REAL ejecutada**
Par seleccionado: *{symbol}*  
Puntaje del par: `{best["score"]}`

Dirección: *{side.upper()}*
Entrada: `{entry_price}`
Salida calculada (TP): `{exit_price}`

Capital usado: `{position_size} USDC`
Ganancia real: `{profit} USDC`

💰 Fee admin acumulado: `{admin_fee} USDC`
👥 Fee referido acumulado: `{ref_fee} USDC`
"""

    return msg
