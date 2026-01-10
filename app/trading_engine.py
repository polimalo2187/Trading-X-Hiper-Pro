# ============================================================
# TRADING ENGINE – Trading X Hyper Pro
# Archivo 7/9 – Motor REAL producción (MODO GUERRA)
# ============================================================

import time
from datetime import datetime, timedelta

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

# 🔥 CONTROL ANTI-BUCLE (FIX REAL)
MAX_FAILED_SIGNALS = 3
BLACKLIST_MINUTES = 10

symbol_failures = {}    # { symbol: count }
symbol_blacklist = {}   # { symbol: datetime_until }


def log(msg: str):
    if VERBOSE_LOGS:
        print(f"[ENGINE {datetime.utcnow().isoformat()}] {msg}")


def is_blacklisted(symbol: str) -> bool:
    until = symbol_blacklist.get(symbol)
    if not until:
        return False

    if datetime.utcnow() >= until:
        symbol_blacklist.pop(symbol, None)
        symbol_failures.pop(symbol, None)
        log(f"♻️ Blacklist liberada para {symbol}")
        return False

    return True


def blacklist_symbol(symbol: str):
    symbol_blacklist[symbol] = datetime.utcnow() + timedelta(minutes=BLACKLIST_MINUTES)
    symbol_failures.pop(symbol, None)
    log(f"⛔ {symbol} bloqueado por {BLACKLIST_MINUTES} minutos")


# ============================================================
# LOOP PRINCIPAL
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

        # ====================================================
        # 2) SCANNER — ROTACIÓN REAL (FIX DEFINITIVO)
        # ====================================================

        best = None
        attempts = 0
        excluded_symbols = set()  # ⬅ CLAVE: exclusión por ciclo

        while attempts < 5:
            candidate = get_best_symbol()
            if not candidate:
                break

            symbol = candidate["symbol"]

            if symbol in excluded_symbols:
                attempts += 1
                continue

            if is_blacklisted(symbol):
                log(f"🔁 {symbol} está en blacklist, rotando...")
                excluded_symbols.add(symbol)
                attempts += 1
                continue

            best = candidate
            break

        if not best:
            log("🔍 Scanner sin oportunidades válidas")
            time.sleep(IDLE_RETRY_SECONDS)
            continue

        symbol = best["symbol"]
        log(f"📊 Mejor par detectado: {symbol}")

        # ====================================================
        # 3) SEÑAL
        # ====================================================

        signal = get_entry_signal(symbol)

        if not signal or not signal.get("signal"):
            log(f"⚠️ Sin señal válida en {symbol}")

            symbol_failures[symbol] = symbol_failures.get(symbol, 0) + 1
            log(f"📉 Fallos {symbol}: {symbol_failures[symbol]}")

            if symbol_failures[symbol] >= MAX_FAILED_SIGNALS:
                blacklist_symbol(symbol)

            time.sleep(IDLE_RETRY_SECONDS)
            continue

        symbol_failures.pop(symbol, None)

        strength = signal["strength"]
        direction = signal["direction"]
        log(f"📈 Señal OK | Dirección={direction} | Fuerza={strength}")

        side = "buy" if direction == "long" else "sell"
        opposite_side = "sell" if side == "buy" else "buy"

        # ====================================================
        # 4) RIESGO
        # ====================================================

        risk = validate_trade_conditions(capital, strength)
        if not risk["ok"]:
            log(f"🛑 Riesgo bloqueado: {risk.get('reason')}")
            time.sleep(IDLE_RETRY_SECONDS)
            continue

        position_size = round(risk["position_size"], 6)
        log(f"📦 Tamaño posición: {position_size}")

        tp_percent = risk["tp"]
        sl_percent = risk["sl"]

        # ====================================================
        # 5) ENTRADA
        # ====================================================

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

        # ====================================================
        # 6) TP / SL
        # ====================================================

        targets = calculate_targets(entry_price, tp_percent, sl_percent, direction)
        tp_price = targets["tp"]
        sl_price = targets["sl"]

        log(f"🎯 TP={tp_price} | 🛡 SL={sl_price}")

        start_time = time.time()
        exit_price = None
        exit_reason = None

        # ====================================================
        # 7) MONITOREO
        # ====================================================

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

        # ====================================================
        # 8) SALIDA
        # ====================================================

        try:
            place_market_order(user_id, symbol, opposite_side, position_size)
            log(f"📤 ORDEN CERRADA por {exit_reason}")
        except Exception as e:
            log(f"❌ ERROR AL CERRAR ORDEN: {e}")

        # ====================================================
        # 9) PnL
        # ====================================================

        profit = round(
            (exit_price - entry_price) * (position_size / entry_price)
            if direction == "long"
            else (entry_price - exit_price) * (position_size / entry_price),
            6
        )

        log(f"💵 PnL REAL: {profit} USDC")

        # ====================================================
        # 10) REGISTRO
        # ====================================================

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

        # ====================================================
        # 11) FEES
        # ====================================================

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
