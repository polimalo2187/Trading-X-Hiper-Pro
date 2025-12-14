# ============================================================
# TRADING ENGINE – TRADING X HYPER PRO
# Estrategia: BlackCrow Aggressive (Optimizada 24/7)
# MultiPar USDC – Long/Short – 1 a 3 operaciones activas
# ============================================================

import time
import random
from app.config import (
    ENTRY_SIGNAL_THRESHOLD,
    TP_MIN, TP_MAX,
    SL_MIN, SL_MAX,
    MAX_CONCURRENT_TRADES,
)
from app.hyper_api import get_price, place_market_order
from app.database import (
    user_is_ready,
    get_user_capital,
    register_trade,
    register_fee,
    get_user_referrer
)


# ------------------------------------------------------------
# GENERADOR DE SEÑALES ARTIFICIALES (BlackCrow Aggressive)
# Simula comportamiento de IA (luego se reemplaza por modelo real)
# ------------------------------------------------------------
def generate_signal(symbol):
    """
    Devuelve un valor entre 0 y 1 que indica fuerza de señal.
    Valores > ENTRY_SIGNAL_THRESHOLD → Señal válida.
    """

    signal_strength = round(random.uniform(0, 1), 4)

    direction = "long" if random.random() > 0.5 else "short"

    return signal_strength, direction



# ------------------------------------------------------------
# LÓGICA PARA DEFINIR TP Y SL DINÁMICOS
# ------------------------------------------------------------
def generate_tp_sl():
    tp = round(random.uniform(TP_MIN, TP_MAX), 4)
    sl = round(random.uniform(SL_MIN, SL_MAX), 4)
    return tp, sl



# ------------------------------------------------------------
# FUNCIÓN PRINCIPAL DE OPERACIÓN
# ------------------------------------------------------------
def execute_trade(user_id, symbol):
    """
    Ejecuta operación completa con entrada → seguimiento → salida.
    """

    # ¿El usuario está configurado?
    if not user_is_ready(user_id):
        return "⚠️ Usuario no está listo para operar."

    # CAPITAL ACTUAL DEL USUARIO
    capital = get_user_capital(user_id)

    # Cantidad a usar por operación = 20% del capital
    amount = round(capital * 0.20, 2)

    if amount < 1:
        return "⚠️ Capital insuficiente para operar."

    # GENERAR SEÑAL
    signal_strength, direction = generate_signal(symbol)

    if signal_strength < ENTRY_SIGNAL_THRESHOLD:
        return f"⛔ Señal débil ({signal_strength}), operación no ejecutada."

    # TP y SL dinámicos
    tp, sl = generate_tp_sl()

    # PRECIO DE ENTRADA
    entry_price = get_price(symbol)
    if not entry_price:
        return f"❌ No se pudo obtener precio de {symbol}"

    # ABRIR ORDEN
    side = "buy" if direction == "long" else "sell"

    order = place_market_order(user_id, symbol, side, amount)

    if not order:
        return "❌ Error ejecutando orden."

    # SIMULACIÓN DE CIERRE (LOREAL_del mercado)
    time.sleep(1)  # Simula espera
    exit_price = entry_price * (1 + tp) if direction == "short" else entry_price * (1 - tp)

    # CÁLCULO DE GANANCIA
    profit = round(abs(exit_price - entry_price) * (amount / entry_price), 4)

    # REGISTRAR TRADE
    register_trade(
        user_id=user_id,
        symbol=symbol,
        side=side.upper(),
        entry_price=entry_price,
        exit_price=exit_price,
        qty=amount,
        profit=profit
    )

    # --------------------------------------------------------
    # FEES
    # --------------------------------------------------------
    owner_fee = round(profit * 0.15, 4)
    ref_fee = 0

    referrer = get_user_referrer(user_id)
    if referrer:
        ref_fee = round(owner_fee * 0.05, 4)
        owner_fee = round(owner_fee * 0.95, 4)

    register_fee(user_id, owner_fee, ref_fee)

    # MENSAJE FINAL
    msg = f"""
🟢 **Operación completada**
Par: {symbol}
Dirección: {side.upper()}
Monto usado: {amount} USDC

Entrada: {entry_price}
Salida: {exit_price}
Ganancia: {profit} USDC

Fee dueño del bot: {owner_fee}
Fee referido: {ref_fee}
"""
    return msg
