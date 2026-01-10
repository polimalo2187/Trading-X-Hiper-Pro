# ============================================================
# TRADING ENGINE – Trading X Hyper Pro
# Archivo 7/9 – Motor REAL producción (MODO GUERRA)
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
# CONFIGURACIÓN DE GUERRA
# ============================================================

MAX_TRADE_DURATION_SECONDS = 60 * 6
PRICE_CHECK_INTERVAL = 0.4
IDLE_RETRY_SECONDS = 15   # ⬅ NUEVO: reintento si no hay señal


# ============================================================
# LOOP PRINCIPAL DE EJECUCIÓN
# ============================================================

def execute_trade(user_id: int):

    while True:

        # 1) VALIDACIÓN
        if not user_is_ready(user_id):
            time.sleep(IDLE_RETRY_SECONDS)
            continue

        capital = get_user_capital(user_id)

        # 2) SCAN MERCADO
        best = get_best_symbol()
        if not best:
            time.sleep(IDLE_RETRY_SECONDS)
            continue

        symbol = best["symbol"]

        # 3) SEÑAL
        signal = get_entry_signal(symbol)
        if not signal or not signal.get("signal"):
            time.sleep(IDLE_RETRY_SECONDS)
            continue

        strength = signal["strength"]
        direction = signal["direction"]

        side = "buy" if direction == "long" else "sell"
        opposite_side = "sell" if side == "buy" else "buy"

        # 4) RIESGO
        risk = validate_trade_conditions(capital, strength)
        if not risk["ok"]:
            time.sleep(IDLE_RETRY_SECONDS)
            continue

        base_position = risk["position_size"]

        if strength >= 5:
            position_size = base_position * 1.4
        elif strength >= 3:
            position_size = base_position * 1.2
        else:
            position_size = base_position

        position_size = round(position_size, 6)

        tp_percent = risk["tp"]
        sl_percent = risk["sl"]

        # 5) ENTRADA
        try:
            place_market_order(user_id, symbol, side, position_size)
        except Exception as e:
            print("❌ ERROR AL ABRIR ORDEN", e)
            time.sleep(IDLE_RETRY_SECONDS)
            continue

        entry_price = get_price(symbol)
        if not entry_price:
            time.sleep(IDLE_RETRY_SECONDS)
            continue

        # 6) TP / SL
        targets = calculate_targets(entry_price, tp_percent, sl_percent, direction)
        tp_price = targets["tp"]
        sl_price = targets["sl"]

        start_time = time.time()
        exit_price = None
        exit_reason = None

        # 7) MONITOREO
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
            time.sleep(IDLE_RETRY_SECONDS)
            continue

        # 8) SALIDA
        try:
            place_market_order(user_id, symbol, opposite_side, position_size)
        except Exception as e:
            print("❌ ERROR AL CERRAR ORDEN", e)

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

        referrer = get_user_referrer(user_id)
        if referrer and admin_fee > 0:
            ref_fee = round(admin_fee * REFERRAL_FEE_PERCENT, 6)
            add_weekly_ref_fee(referrer, ref_fee)
            admin_fee -= ref_fee

        if admin_fee > 0:
            add_daily_admin_fee(user_id, admin_fee)

        # 🔁 Volver a buscar trade
        time.sleep(IDLE_RETRY_SECONDS)
