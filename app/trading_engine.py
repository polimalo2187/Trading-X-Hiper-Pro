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

MAX_FAILED_SIGNALS = 3
BLACKLIST_MINUTES = 10

symbol_failures = {}
symbol_blacklist = {}

# ============================================================
# LOG
# ============================================================

def log(msg: str):
    if VERBOSE_LOGS:
        print(f"[ENGINE {datetime.utcnow().isoformat()}] {msg}")

# ============================================================
# BLACKLIST
# ============================================================

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
# EJECUCIÓN DE UN TRADE (UNA SOLA OPERACIÓN)
# ============================================================

def execute_trade(user_id: int):

    if not user_is_ready(user_id):
        return None

    capital = get_user_capital(user_id)
    log(f"💰 Capital detectado: {capital}")

    # =========================
    # SCANNER
    # =========================
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
        return None

    symbol = best["symbol"]
    log(f"📊 Mejor par: {symbol}")

    # =========================
    # SEÑAL
    # =========================
    signal = get_entry_signal(symbol)

    if not signal or not signal.get("signal"):
        symbol_failures[symbol] = symbol_failures.get(symbol, 0) + 1

        if symbol_failures[symbol] >= MAX_FAILED_SIGNALS:
            blacklist_symbol(symbol)

        return None

    symbol_failures.pop(symbol, None)

    strength = signal["strength"]
    direction = signal["direction"]

    side = "buy" if direction == "long" else "sell"
    opposite = "sell" if side == "buy" else "buy"

    # =========================
    # RIESGO
    # =========================
    risk = validate_trade_conditions(capital, strength)
    position_size = round(risk["position_size"], 6)

    # =========================
    # ENTRADA
    # =========================
    place_market_order(user_id, symbol, side, position_size)
    entry_price = get_price(symbol)

    if not entry_price:
        return None

    targets = calculate_targets(
        entry_price,
        risk["tp"],
        risk["sl"],
        direction
    )

    # =========================
    # MONITOREO
    # =========================
    start_time = time.time()
    exit_price = None
    exit_reason = None

    while True:
        if time.time() - start_time > MAX_TRADE_DURATION_SECONDS:
            exit_reason = "TIMEOUT"
            exit_price = get_price(symbol)
            break

        price = get_price(symbol)
        if not price:
            time.sleep(PRICE_CHECK_INTERVAL)
            continue

        if direction == "long":
            if price >= targets["tp"]:
                exit_reason = "TP"
                exit_price = price
                break
            if price <= targets["sl"]:
                exit_reason = "SL"
                exit_price = price
                break
        else:
            if price <= targets["tp"]:
                exit_reason = "TP"
                exit_price = price
                break
            if price >= targets["sl"]:
                exit_reason = "SL"
                exit_price = price
                break

        time.sleep(PRICE_CHECK_INTERVAL)

    # =========================
    # SALIDA
    # =========================
    place_market_order(user_id, symbol, opposite, position_size)

    profit = round(
        (exit_price - entry_price) * (position_size / entry_price)
        if direction == "long"
        else (entry_price - exit_price) * (position_size / entry_price),
        6
    )

    # =========================
    # REGISTRO
    # =========================
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

    # =========================
    # FEES
    # =========================
    admin_fee = round(max(profit, 0) * OWNER_FEE_PERCENT, 6)

    referrer = get_user_referrer(user_id)
    if referrer and admin_fee > 0:
        ref_fee = round(admin_fee * REFERRAL_FEE_PERCENT, 6)
        add_weekly_ref_fee(referrer, ref_fee)
        admin_fee -= ref_fee

    if admin_fee > 0:
        add_daily_admin_fee(user_id, admin_fee)

    # =========================
    # RETORNO PARA TELEGRAM LOOP
    # =========================
    return {
        "event": "BOTH",
        "open": {
            "message": f"📈 OPEN {symbol} | Fuerza {strength}"
        },
        "close": {
            "message": f"📉 CLOSE {symbol} | {exit_reason} | PnL {profit}"
        }
  }
