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
    VERBOSE_LOGS,
)

# ============================================================
# CONFIGURACIÓN DE GUERRA
# ============================================================

MAX_TRADE_DURATION_SECONDS = 60 * 6
PRICE_CHECK_INTERVAL = 0.4
IDLE_RETRY_SECONDS = 15


def log(msg: str):
    if VERBOSE_LOGS:
        print(f"[ENGINE {datetime.utcnow().isoformat()}] {msg}")


# ============================================================
# LOOP PRINCIPAL DE EJECUCIÓN
# ============================================================

def execute_trade(user_id: int):

    log(f"🚀 Trading Engine iniciado para user_id={user_id}")

    while True:

        # 1) VALIDACIÓN
        if not user_is_ready(user_id):
            log("⏸ Usuario no listo para tradear")
            time.sleep(IDLE_RETRY_SECONDS)
            continue

        capital = get_user_capital(user_id)
        log(f"💰 Capital detectado: {capital}")

        # 2) SCAN MERCADO
        best = get_best_symbol()
        if not best:
            log("🔍 Scanner sin oportunidades")
            time.sleep(IDLE_RETRY_SECONDS)
            continue

        symbol = best["symbol"]
        log(f"📊 Mejor par detectado: {symbol}")

        # 3) SEÑAL
        signal = get_entry_signal(symbol)
        if not signal or not signal.get("signal"):
            log(f"⚠️ Sin señal válida en {symbol}")
            time.sleep(IDLE_RETRY_SECONDS)
            continue

        strength = signal["strength"]
        direction = signal["direction"]
        log(f"📈 Señal OK | Dirección={direction} | Fuerza={strength}")

        side = "buy" if direction == "long" else "sell"
        opposite_side = "sell" if side == "buy" else "buy"

        # 4) RIESGO
        risk = validate_trade_conditions(capital, strength)
        if not risk["ok"]:
            log(f"🛑 Riesgo bloqueado: {risk.get('reason')}")
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
        log(f"📦 Tamaño posición: {position_size}")

        tp_percent = risk["tp"]
        sl_percent = risk["sl"]

        # 5) ENTRADA
        try:
            place_market_order(user_id, symbol, side, position_size)
            log(f"✅ ORDEN ABIERTA {side.upper()} {symbol}")
        except Exception as e:
            log(f"❌ ERROR AL ABRIR ORDEN: {e}")
            time.sleep(IDLE_RETRY_SECONDS)
            continue

        entry_price = get_price(symbol)
        if not entry_price:
            log("❌ Precio de entrada inválido")
            time.sleep(IDLE_RETRY_SECONDS)
            continue

        log(f"🎯 Precio entrada: {entry_price}")

        # 6) TP / SL
        targets = calculate_targets(entry_price, tp_percent, sl_percent, direction)
        tp_price = targets["tp"]
        sl_price = targets["sl"]

        log(f"🎯 TP={tp_price} | 🛡 SL={sl_price}")

        start_time = time.time()
        exit_price = None
        exit_reason = None

        # 7) MONITOREO
        while True:

            if time.time() - start_time > MAX_TRADE_DURATION_SECONDS:
                exit_reason = "TIMEOUT"
                exit_price = get_price(symbol)
                log("⏰ TIMEOUT alcanzado")
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

        # 8) SALIDA
        try:
            place_market_order(user_id, symbol, opposite_side, position_size)
            log(f"📤 ORDEN CERRADA por {exit_reason}")
        except Exception as e:
            log(f"❌ ERROR AL CERRAR ORDEN: {e}")

        # 9) PnL
        profit = round(
            (exit_price - entry_price) * (position_size / entry_price)
            if direction == "long"
            else (entry_price - exit_price) * (position_size / entry_price),
            6
        )

        log(f"💵 PnL REAL: {profit} USDC")

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

        log("🔁 Ciclo completado, buscando nuevo trade")
        time.sleep(IDLE_RETRY_SECONDS)
