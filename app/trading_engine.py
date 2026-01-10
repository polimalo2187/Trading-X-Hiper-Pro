# ============================================================
# TRADING ENGINE – Trading X Hyper Pro
# Archivo – PRODUCCIÓN REAL (AJUSTADO)
# ============================================================

import time
from datetime import datetime, timedelta

from app.market_scanner import get_best_symbol
from app.strategy import get_entry_signal
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
# CONFIGURACIÓN DE PRODUCCIÓN
# ============================================================

MAX_TRADE_DURATION_SECONDS = 60 * 6
PRICE_CHECK_INTERVAL = 0.4
IDLE_RETRY_SECONDS = 2      # 🔥 Antes 15 — respuesta más rápida

# 🔥 CONTROL ANTI-BUCLE (AJUSTADO)
MAX_FAILED_SIGNALS = 6      # 🔥 Antes 3 — menos blacklist agresiva
BLACKLIST_MINUTES = 10

symbol_failures = {}     # { symbol: count }
symbol_blacklist = {}    # { symbol: datetime_until }


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
    log(f"⛔ {symbol} bloqueado {BLACKLIST_MINUTES} min")


# ============================================================
# LOOP PRINCIPAL
# ============================================================

def execute_trade(user_id: int):

    log(f"🚀 Trading Engine iniciado para user_id={user_id}")

    while True:

        # 1) VALIDACIÓN
        if not user_is_ready(user_id):
            log("⏸ Usuario no listo")
            time.sleep(IDLE_RETRY_SECONDS)
            continue

        capital = get_user_capital(user_id)
        log(f"💰 Capital: {capital}")

        # ====================================================
        # 2) SCANNER
        # ====================================================

        best = None
        attempts = 0
        excluded = set()

        while attempts < 5:
            candidate = get_best_symbol()
            if not candidate:
                break

            symbol = candidate["symbol"]

            if symbol in excluded or is_blacklisted(symbol):
                excluded.add(symbol)
                attempts += 1
                continue

            best = candidate
            break

        if not best:
            log("🔍 Sin oportunidades")
            time.sleep(IDLE_RETRY_SECONDS)
            continue

        symbol = best["symbol"]
        log(f"📊 Mejor par: {symbol}")

        # ====================================================
        # 3) SEÑAL
        # ====================================================

        signal = get_entry_signal(symbol)

        if not signal or not signal.get("signal"):
            symbol_failures[symbol] = symbol_failures.get(symbol, 0) + 1
            log(f"⚠️ Sin señal | {symbol} fallos={symbol_failures[symbol]}")

            if symbol_failures[symbol] >= MAX_FAILED_SIGNALS:
                blacklist_symbol(symbol)

            time.sleep(IDLE_RETRY_SECONDS)
            continue

        symbol_failures.pop(symbol, None)

        direction = signal["direction"]
        strength = signal["strength"]
        log(f"📈 Señal OK | {direction} | fuerza={strength}")

        side = "buy" if direction == "long" else "sell"
        opposite = "sell" if side == "buy" else "buy"

        # ====================================================
        # 4) RIESGO
        # ====================================================

        risk = validate_trade_conditions(capital, strength)
        position_size = round(risk["position_size"], 6)

        # ====================================================
        # 5) ENTRADA
        # ====================================================

        place_market_order(user_id, symbol, side, position_size)
        entry_price = get_price(symbol)

        # ====================================================
        # 6) TP / SL
        # ====================================================

        tp = risk["tp"]
        sl = risk["sl"]

        if direction == "long":
            tp_price = entry_price * (1 + tp)
            sl_price = entry_price * (1 - sl)
        else:
            tp_price = entry_price * (1 - tp)
            sl_price = entry_price * (1 + sl)

        start = time.time()

        # ====================================================
        # 7) MONITOREO
        # ====================================================

        while True:
            price = get_price(symbol)

            if time.time() - start > MAX_TRADE_DURATION_SECONDS:
                exit_price = price
                break

            if direction == "long":
                if price >= tp_price or price <= sl_price:
                    exit_price = price
                    break
            else:
                if price <= tp_price or price >= sl_price:
                    exit_price = price
                    break

            time.sleep(PRICE_CHECK_INTERVAL)

        # ====================================================
        # 8) CIERRE
        # ====================================================

        place_market_order(user_id, symbol, opposite, position_size)

        profit = round(
            (exit_price - entry_price) * (position_size / entry_price)
            if direction == "long"
            else (entry_price - exit_price) * (position_size / entry_price),
            6
        )

        # ====================================================
        # 9) REGISTRO
        # ====================================================

        register_trade(
            user_id,
            symbol,
            side.upper(),
            entry_price,
            exit_price,
            position_size,
            profit,
            best["score"],
        )

        # ====================================================
        # 10) FEES
        # ====================================================

        admin_fee = max(profit, 0) * OWNER_FEE_PERCENT
        ref = get_user_referrer(user_id)

        if ref and admin_fee > 0:
            ref_fee = admin_fee * REFERRAL_FEE_PERCENT
            add_weekly_ref_fee(ref, ref_fee)
            admin_fee -= ref_fee

        if admin_fee > 0:
            add_daily_admin_fee(user_id, admin_fee)

        log("🔁 Ciclo terminado")
        time.sleep(IDLE_RETRY_SECONDS)
