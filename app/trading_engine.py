# ============================================================
# TRADING ENGINE – Trading X Hyper Pro
# PRODUCCION REAL – ESTABLE
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

from app.config import OWNER_FEE_PERCENT, REFERRAL_FEE_PERCENT


# ============================================================
# CONFIG
# ============================================================

MAX_TRADE_DURATION_SECONDS = 360
PRICE_CHECK_INTERVAL = 0.4

MAX_FAILED_SIGNALS = 6
BLACKLIST_MINUTES = 10

symbol_failures = {}
symbol_blacklist = {}


# ============================================================
# LOG
# ============================================================

def log(msg: str, level: str = "INFO"):
    print(f"[ENGINE {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}] {level} {msg}")


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
        log(f"Blacklist liberada {symbol}")
        return False

    return True


def blacklist_symbol(symbol: str):
    symbol_blacklist[symbol] = datetime.utcnow() + timedelta(minutes=BLACKLIST_MINUTES)
    symbol_failures.pop(symbol, None)
    log(f"Simbolo bloqueado {symbol} por {BLACKLIST_MINUTES} min", "WARN")


# ============================================================
# CICLO UNICO
# ============================================================

def execute_trade_cycle(user_id: int) -> dict | None:

    log(f"Usuario {user_id} — inicio ciclo")

    if not user_is_ready(user_id):
        log(f"Usuario {user_id} no listo")
        return None

    capital = get_user_capital(user_id)
    log(f"Capital: {capital}")

    log("Buscando mejor simbolo")
    best = get_best_symbol()
    if not best:
        log("No se encontro simbolo")
        return None

    symbol = best["symbol"]
    log(f"Simbolo elegido: {symbol}")

    if is_blacklisted(symbol):
        log(f"Simbolo {symbol} en blacklist")
        return None

    log(f"Analizando señal {symbol}")
    signal = get_entry_signal(symbol)

    if not signal or not signal.get("signal"):
        log(f"Sin señal valida {symbol}")
        symbol_failures[symbol] = symbol_failures.get(symbol, 0) + 1
        if symbol_failures[symbol] >= MAX_FAILED_SIGNALS:
            blacklist_symbol(symbol)
        return None

    symbol_failures.pop(symbol, None)

    direction = signal["direction"]
    side = "buy" if direction == "long" else "sell"
    opposite = "sell" if side == "buy" else "buy"

    log(f"Señal valida {symbol} direccion {direction}")

    risk = validate_trade_conditions(capital, signal["strength"])
    qty = round(risk["position_size"], 6)

    log(f"Ejecutando entrada {symbol} {side} qty {qty}")
    place_market_order(user_id, symbol, side, qty)
    entry_price = get_price(symbol)

    tp = risk["tp"]
    sl = risk["sl"]

    tp_price = entry_price * (1 + tp) if direction == "long" else entry_price * (1 - tp)
    sl_price = entry_price * (1 - sl) if direction == "long" else entry_price * (1 + sl)

    start = time.time()

    while True:
        price = get_price(symbol)

        if time.time() - start > MAX_TRADE_DURATION_SECONDS:
            log("Salida por tiempo")
            exit_price = price
            break

        if direction == "long" and (price >= tp_price or price <= sl_price):
            exit_price = price
            break

        if direction == "short" and (price <= tp_price or price >= sl_price):
            exit_price = price
            break

        time.sleep(PRICE_CHECK_INTERVAL)

    log(f"Cerrando trade {symbol}")
    place_market_order(user_id, symbol, opposite, qty)

    profit = round(
        (exit_price - entry_price) * (qty / entry_price)
        if direction == "long"
        else (entry_price - exit_price) * (qty / entry_price),
        6
    )

    log(f"Trade cerrado {symbol} PnL {profit}")

    register_trade(
        user_id=user_id,
        symbol=symbol,
        side=side.upper(),
        entry_price=entry_price,
        exit_price=exit_price,
        qty=qty,
        profit=profit,
        best_score=best["score"],
    )

    admin_fee = max(profit, 0) * OWNER_FEE_PERCENT
    ref = get_user_referrer(user_id)

    if ref and admin_fee > 0:
        ref_fee = admin_fee * REFERRAL_FEE_PERCENT
        add_weekly_ref_fee(ref, ref_fee)
        admin_fee -= ref_fee

    if admin_fee > 0:
        add_daily_admin_fee(user_id, admin_fee)

    return {
        "event": "BOTH",
        "open": {"message": f"🟢 Trade abierto {symbol} ({direction.upper()})"},
        "close": {"message": f"🔴 Trade cerrado {symbol}\nPnL: {profit} USDC"},
  }
