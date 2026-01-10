# ============================================================
# TRADING ENGINE – Trading X Hyper Pro
# PRODUCCIÓN REAL – ESTABLE – LOGS EN VIVO
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
# CONFIG
# ============================================================

MAX_TRADE_DURATION_SECONDS = 60 * 6
PRICE_CHECK_INTERVAL = 0.4

MAX_FAILED_SIGNALS = 6
BLACKLIST_MINUTES = 10

symbol_failures = {}
symbol_blacklist = {}

# ============================================================
# LOGGING CENTRAL
# ============================================================

def log(msg: str):
    if VERBOSE_LOGS:
        print(f"[ENGINE {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)

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
        log(f"♻️ Blacklist liberada {symbol}")
        return False

    log(f"⛔ {symbol} sigue en blacklist")
    return True


def blacklist_symbol(symbol: str):
    symbol_blacklist[symbol] = datetime.utcnow() + timedelta(minutes=BLACKLIST_MINUTES)
    symbol_failures.pop(symbol, None)
    log(f"⛔ {symbol} bloqueado {BLACKLIST_MINUTES} min")

# ============================================================
# 🔁 CICLO ÚNICO (USADO POR trading_loop.py)
# ============================================================

def execute_trade_cycle(user_id: int) -> dict | None:

    log(f"👤 Usuario {user_id} — inicio ciclo")

    if not user_is_ready(user_id):
        log(f"⚠ Usuario {user_id} NO está listo")
        return None

    capital = get_user_capital(user_id)
    log(f"💰 Capital {capital}")

    # ================= SCANNER =================
    log("🔍 Buscando mejor símbolo")
    best = get_best_symbol()

    if not best:
        log("❌ Scanner no devolvió símbolo")
        return None

    symbol = best["symbol"]
    log(f"📊 Símbolo elegido: {symbol}")

    if is_blacklisted(symbol):
        return None

    # ================= SIGNAL ==================
    log(f"📈 Analizando señal {symbol}")
    signal = get_entry_signal(symbol)

    if not signal or not signal.get("signal"):
        log(f"❌ Sin señal válida {symbol}")
        symbol_failures[symbol] = symbol_failures.get(symbol, 0) + 1
        if symbol_failures[symbol] >= MAX_FAILED_SIGNALS:
            blacklist_symbol(symbol)
        return None

    symbol_failures.pop(symbol, None)

    direction = signal["direction"]
    strength = signal["strength"]
    side = "buy" if direction == "long" else "sell"
    opposite = "sell" if side == "buy" else "buy"

    log(f"✅ Señal {direction.upper()} | Fuerza {strength}")

    # ================= RISK ====================
    risk = validate_trade_conditions(capital, strength)
    position_size = round(risk["position_size"], 6)

    log(f"📐 Tamaño posición: {position_size}")

    # ================= ENTRY ===================
    log(f"🟢 Abriendo trade {symbol} {side.upper()}")
    place_market_order(user_id, symbol, side, position_size)
    entry_price = get_price(symbol)

    tp = risk["tp"]
    sl = risk["sl"]

    if direction == "long":
        tp_price = entry_price * (1 + tp)
        sl_price = entry_price * (1 - sl)
    else:
        tp_price = entry_price * (1 - tp)
        sl_price = entry_price * (1 + sl)

    log(f"🎯 TP: {tp_price:.6f} | 🛑 SL: {sl_price:.6f}")

    start = time.time()

    # ================= MONITOR =================
    log("⏳ Monitoreando precio...")
    while True:
        price = get_price(symbol)

        if time.time() - start > MAX_TRADE_DURATION_SECONDS:
            log("⏰ Tiempo máximo alcanzado")
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

    # ================= EXIT ====================
    log(f"🔴 Cerrando trade {symbol} {opposite.upper()}")
    place_market_order(user_id, symbol, opposite, position_size)

    profit = round(
        (exit_price - entry_price) * (position_size / entry_price)
        if direction == "long"
        else (entry_price - exit_price) * (position_size / entry_price),
        6
    )

    log(f"💵 PnL: {profit}")

    register_trade(
        user_id=user_id,
        symbol=symbol,
        side=side.upper(),
        entry_price=entry_price,
        exit_price=exit_price,
        qty=position_size,
        profit=profit,
        best_score=best["score"],
    )

    # ================= FEES ====================
    admin_fee = max(profit, 0) * OWNER_FEE_PERCENT
    ref = get_user_referrer(user_id)

    if ref and admin_fee > 0:
        ref_fee = admin_fee * REFERRAL_FEE_PERCENT
        add_weekly_ref_fee(ref, ref_fee)
        admin_fee -= ref_fee
        log(f"🤝 Fee referido: {ref_fee}")

    if admin_fee > 0:
        add_daily_admin_fee(user_id, admin_fee)
        log(f"🏦 Fee admin: {admin_fee}")

    log("✅ Ciclo completado")

    return {
        "event": "BOTH",
        "open": {"message": f"🟢 Trade abierto {symbol} ({direction.upper()})"},
        "close": {"message": f"🔴 Trade cerrado {symbol}\nPnL: {profit} USDC"}
  }
