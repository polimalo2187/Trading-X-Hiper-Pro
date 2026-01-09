# ============================================================
# TRADING ENGINE – Trading X Hyper Pro
# Archivo 7/9 – Motor REAL producción nivel banco (FINAL)
# ============================================================

import time
from datetime import datetime

from app.market_scanner import get_best_symbol
from app.strategy import get_entry_signal, calculate_targets
from app.risk import validate_trade_conditions
from app.hyperliquid_client import place_market_order, get_price

from app.database import (
    user_is_ready,
    get_user_capital,
    register_trade,
    add_daily_admin_fee,
    add_weekly_ref_fee,
    get_user_referrer,
)

from app.config import (
    OWNER_FEE_PERCENT,
    REFERRAL_FEE_PERCENT,
)

# ============================================================
# CONFIGURACIÓN DE SEGURIDAD
# ============================================================

MAX_TRADE_DURATION_SECONDS = 60 * 10
PRICE_CHECK_INTERVAL = 0.5


# ============================================================
# EJECUCIÓN DEL TRADE
# ============================================================

def execute_trade(user_id: int):

    # 1) VALIDACIÓN BÁSICA
    if not user_is_ready(user_id):
        return {"event": None}

    capital = get_user_capital(user_id)

    # 2) MEJOR PAR
    best = get_best_symbol()
    if not best:
        return {"event": None}

    symbol = best["symbol"]

    # 3) SEÑAL
    signal = get_entry_signal(symbol)
    if not signal or not signal.get("signal"):
        return {"event": None}

    strength = signal["strength"]
    direction = signal["direction"]

    side = "buy" if direction == "long" else "sell"
    opposite_side = "sell" if side == "buy" else "buy"

    # 4) RIESGO
    risk = validate_trade_conditions(capital, strength)
    if not risk["ok"]:
        return {"event": None}

    position_size = risk["position_size"]
    tp_percent = risk["tp"]
    sl_percent = risk["sl"]

    # 5) ORDEN DE ENTRADA
    entry_order = place_market_order(user_id, symbol, side, position_size)
    if not entry_order:
        return {"event": None}

    entry_price = get_price(symbol)
    if not entry_price:
        return {"event": None}

    # 🔔 EVENTO: APERTURA
    open_event = {
        "event": "OPEN",
        "message": (
            f"📈 *Operación ABIERTA*\n\n"
            f"Par: `{symbol}`\n"
            f"Dirección: `{side.upper()}`\n\n"
            f"Consulta el menú *Operaciones* para más detalles."
        )
    }

    # 6) TP / SL
    targets = calculate_targets(entry_price, tp_percent, sl_percent, direction)
    tp_price = targets["tp"]
    sl_price = targets["sl"]

    # 7) MONITOREO
    start_time = time.time()
    exit_price = None
    exit_reason = None

    while True:
        if time.time() - start_time > MAX_TRADE_DURATION_SECONDS:
            exit_reason = "TIMEOUT"
            exit_price = get_price(symbol)
            break

        current_price = get_price(symbol)
        if not current_price:
            time.sleep(PRICE_CHECK_INTERVAL)
            continue

        if direction == "long":
            if current_price >= tp_price:
                exit_reason = "TP"
                exit_price = current_price
                break
            if current_price <= sl_price:
                exit_reason = "SL"
                exit_price = current_price
                break
        else:
            if current_price <= tp_price:
                exit_reason = "TP"
                exit_price = current_price
                break
            if current_price >= sl_price:
                exit_reason = "SL"
                exit_price = current_price
                break

        time.sleep(PRICE_CHECK_INTERVAL)

    if not exit_price:
        return {"event": None}

    # 8) ORDEN DE SALIDA
    exit_order = place_market_order(user_id, symbol, opposite_side, position_size)
    if not exit_order:
        return {"event": None}

    # 9) PnL
    profit = round(
        (exit_price - entry_price) * (position_size / entry_price)
        if direction == "long"
        else (entry_price - exit_price) * (position_size / entry_price),
        6
    )

    # 10) REGISTRO
    register_trade(
        user_id=user_id,
        symbol=symbol,
        side=side.upper(),
        entry_price=entry_price,
        exit_price=exit_price,
        qty=position_size,
        profit=profit,
        best_score=best["score"]
    )

    # 11) FEES
    admin_fee = round(max(profit, 0) * OWNER_FEE_PERCENT, 6)
    ref_fee = 0.0

    referrer = get_user_referrer(user_id)
    if referrer and admin_fee > 0:
        ref_fee = round(admin_fee * REFERRAL_FEE_PERCENT, 6)
        add_weekly_ref_fee(referrer, ref_fee)
        admin_fee = round(admin_fee - ref_fee, 6)

    if admin_fee > 0:
        add_daily_admin_fee(user_id, admin_fee)

    # 🔔 EVENTO: CIERRE
    close_event = {
        "event": "CLOSE",
        "message": (
            f"📉 *Operación CERRADA*\n\n"
            f"Par: `{symbol}`\n"
            f"Resultado: `{exit_reason}`\n"
            f"PnL: `{profit} USDC`\n\n"
            f"Consulta el menú *Operaciones* para el detalle completo."
        )
    }

    return {
        "event": "BOTH",
        "open": open_event,
        "close": close_event
      }
