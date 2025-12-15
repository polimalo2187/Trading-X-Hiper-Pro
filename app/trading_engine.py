# ============================================================
# TRADING ENGINE – Trading X Hyper Pro
# Archivo 9/9 – Motor REAL de trading profesional
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
    get_user_referrer,
)

from app.config import OWNER_FEE_PERCENT, REFERRAL_FEE_PERCENT


# ============================================================
# FUNCIÓN PRINCIPAL – EJECUCIÓN DE UNA OPERACIÓN REAL
# ============================================================

def execute_trade(user_id: int):
    """
    Ejecuta una operación real completa:
      - Analiza mercado
      - Selecciona mejor par
      - Detecta señal real
      - Ejecuta entrada
      - Ejecuta salida
      - Calcula ganancia real
      - Registra el trade
      - Registra (acumula) fees para admin + referidos
    """

    # --------------------------------------------------------
    # 1) Validar usuario
    # --------------------------------------------------------
    if not user_is_ready(user_id):
        return "⚠️ Tu cuenta no está lista para operar."

    capital = get_user_capital(user_id)

    # --------------------------------------------------------
    # 2) Validación profesional de riesgo
    # --------------------------------------------------------
    risk = validate_trade_conditions(capital, user_id)
    if not risk["ok"]:
        return f"⛔ {risk['reason']}"

    position_size = round(capital * 0.20, 2)
    tp_percent = risk["tp"]
    sl_percent = risk["sl"]

    # --------------------------------------------------------
    # 3) Scanner real → mejor par del mercado
    # --------------------------------------------------------
    best = get_best_symbol()
    if not best:
        return "❌ Error: no se pudo obtener un par óptimo del mercado."

    symbol = best["symbol"]

    # --------------------------------------------------------
    # 4) Señal real (BlackCrow Aggressive Real)
    # --------------------------------------------------------
    signal = get_entry_signal(symbol)
    if not signal["signal"]:
        return f"⛔ Señal débil ({signal.get('strength', 0)}) en {symbol}"

    direction = signal["direction"]
    entry_price = signal["entry_price"]
    side = "buy" if direction == "long" else "sell"

    # --------------------------------------------------------
    # 5) Ejecución real de ENTRADA
    # --------------------------------------------------------
    entry_order = place_market_order(user_id, symbol, side, position_size)
    if not entry_order:
        return "❌ Error ejecutando orden de ENTRADA real."

    # pequeña pausa por sincronía del exchange
    time.sleep(0.3)

    # --------------------------------------------------------
    # 6) Calcular TP y SL reales
    # --------------------------------------------------------
    targets = calculate_targets(entry_price, tp_percent, sl_percent, direction)
    exit_price = targets["tp"]

    # --------------------------------------------------------
    # 7) Ejecución real de SALIDA
    # --------------------------------------------------------
    opposite_side = "sell" if side == "buy" else "buy"
    exit_order = place_market_order(user_id, symbol, opposite_side, position_size)

    if not exit_order:
        return "❌ Error ejecutando orden de SALIDA real."

    # --------------------------------------------------------
    # 8) Cálculo de ganancia real
    # --------------------------------------------------------
    profit = round(abs(exit_price - entry_price) * (position_size / entry_price), 6)

    # --------------------------------------------------------
    # 9) Registro del trade
    # --------------------------------------------------------
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
    # 10) FEES (sistema real)
    #     - Admin fee acumulado diario
    #     - Referral fee acumulado semanal
    # --------------------------------------------------------

    admin_fee = round(profit * OWNER_FEE_PERCENT, 6)
    ref_fee = 0

    referrer = get_user_referrer(user_id)

    if referrer:
        ref_fee = round(admin_fee * REFERRAL_FEE_PERCENT, 6)
        admin_fee = round(admin_fee * (1 - REFERRAL_FEE_PERCENT), 6)

    # Guardar fee en registro general
    register_fee(user_id, admin_fee, ref_fee)

    # --------------------------------------------------------
    # 11) Mensaje final al usuario
    # --------------------------------------------------------
    return f"""
🟢 **Operación REAL completada**

**Par:** {symbol}
**Dirección:** {side.upper()}

📈 Entrada: `{entry_price}`
📉 Salida (TP): `{exit_price}`

💰 Capital usado: `{position_size} USDC`
💵 Ganancia real: `{profit} USDC`

🏦 Fee admin acumulado hoy: `{admin_fee} USDC`
👥 Fee referido acumulado: `{ref_fee} USDC`

Par seleccionado según mercado:
• Volumen 24h: {best['volume_usd']} USD
• Open Interest: {best['open_interest_usd']} USD
• Cambio 24h: {best['change_24h']}%
• Score: {best['score']}
"""
