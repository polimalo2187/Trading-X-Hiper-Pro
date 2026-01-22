# ============================================================
# TRADING ENGINE – Trading X Hyper Pro
# PRODUCCIÓN REAL – FIX DEFINITIVO (BLINDAJE)
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

# Cooldown para rotar símbolos cuando ya se evaluó y no cumple umbral
SYMBOL_COOLDOWN_SECONDS = 30

symbol_failures = {}
symbol_blacklist = {}
symbol_cooldown = {}
user_last_symbol = {}


# ============================================================
# LOG
# ============================================================

def log(msg: str, level: str = "INFO"):
    print(f"[ENGINE {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}] {level} {msg}")


# ============================================================
# NORMALIZADOR (coin para ejecución real)
# ============================================================

def _norm_coin(symbol: str) -> str:
    try:
        s = (symbol or "").strip().upper()
        s = s.replace("-PERP", "").replace("_PERP", "").replace("PERP", "")
        if "/" in s:
            s = s.split("/", 1)[0].strip()
        return s
    except Exception:
        return symbol


# ============================================================
# COOLDOWN
# ============================================================

def _is_in_cooldown(symbol: str) -> bool:
    until = symbol_cooldown.get(symbol)
    if not until:
        return False
    if datetime.utcnow() >= until:
        symbol_cooldown.pop(symbol, None)
        return False
    return True


def _set_cooldown(symbol: str):
    symbol_cooldown[symbol] = datetime.utcnow() + timedelta(seconds=SYMBOL_COOLDOWN_SECONDS)


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
    log(f"Símbolo bloqueado {symbol} por {BLACKLIST_MINUTES} min", "WARN")


# ============================================================
# CICLO PRINCIPAL
# ============================================================

def execute_trade_cycle(user_id: int) -> dict | None:

    log(f"Usuario {user_id} — inicio ciclo")

    if not user_is_ready(user_id):
        log(f"Usuario {user_id} no listo")
        return None

    capital = get_user_capital(user_id)
    log(f"Capital: {capital}")

    # Excluir símbolos en cooldown y blacklist (pero NO excluimos el último símbolo del usuario)
    exclude_symbols = {s for s in list(symbol_cooldown.keys()) if _is_in_cooldown(s)}
    exclude_symbols |= set(symbol_blacklist.keys())

    # Si ya teníamos un símbolo “sticky” para acumular ventana, lo priorizamos
    preferred = user_last_symbol.get(user_id)
    if preferred and preferred not in exclude_symbols and not is_blacklisted(preferred):
        raw_symbol = preferred
        best = {"symbol": raw_symbol, "score": 0.0}
    else:
        best = get_best_symbol(exclude_symbols=exclude_symbols)
        if not best:
            log("No se encontró símbolo")
            return None

    # --------------------------------------------------------
    # Símbolo interno (mantiene -PERP para compatibilidad del bot)
    # --------------------------------------------------------
    raw_symbol = best["symbol"]
    symbol = raw_symbol if raw_symbol.endswith("-PERP") else f"{raw_symbol}-PERP"
    # --------------------------------------------------------

    # Guardamos como sticky para acumular ventana
    user_last_symbol[user_id] = symbol

    # --------------------------------------------------------
    # Símbolo real para ejecución/precio (coin)
    # --------------------------------------------------------
    symbol_for_exec = _norm_coin(symbol)
    # --------------------------------------------------------

    log(f"Símbolo elegido: {symbol}")

    if is_blacklisted(symbol):
        log(f"Símbolo {symbol} en blacklist")
        return None

    if _is_in_cooldown(symbol):
        log(f"Símbolo {symbol} en cooldown")
        return None

    signal = get_entry_signal(symbol)

    if not isinstance(signal, dict):
        log(f"Señal inválida (no dict) {symbol}", "ERROR")
        symbol_failures[symbol] = symbol_failures.get(symbol, 0) + 1

        if symbol_failures[symbol] >= MAX_FAILED_SIGNALS:
            blacklist_symbol(symbol)

        return None

    if not signal.get("signal"):
        reason = signal.get("reason")

        # Log más claro si viene reason/window
        if reason and signal.get("window"):
            log(f"Sin señal {symbol} reason={reason} window={signal.get('window')}")
        elif reason and signal.get("strength") is not None:
            log(f"Sin señal {symbol} reason={reason} strength={signal.get('strength')}")
        elif reason:
            log(f"Sin señal {symbol} reason={reason}")
        else:
            log(f"Sin señal válida {symbol}")

        # CLAVE:
        # - Si aún no hay ventana (WINDOW/TIME), NO rotamos (dejamos sticky)
        # - Si ya evaluó y no pasa umbral (THRESHOLD), ahí sí ponemos cooldown para rotar
        if reason in ("THRESHOLD",):
            _set_cooldown(symbol)
            user_last_symbol.pop(user_id, None)

        return None

    symbol_failures.pop(symbol, None)
    user_last_symbol.pop(user_id, None)

    direction = signal["direction"]
    side = "buy" if direction == "long" else "sell"
    opposite = "sell" if side == "buy" else "buy"

    log(f"SEÑAL CONFIRMADA {symbol} {direction.upper()} strength={signal['strength']}")

    risk = validate_trade_conditions(capital, signal["strength"])
    if not risk.get("ok"):
        log(f"Trade cancelado: {risk.get('reason')}", "WARN")
        return None

    qty = round(risk["position_size"], 6)
    log(f"Ejecutando orden {symbol} {side} qty={qty}")
    place_market_order(user_id, symbol_for_exec, side, qty)

    entry_price = get_price(symbol_for_exec)
    if entry_price is None or entry_price <= 0:
        log("Precio de entrada inválido", "ERROR")
        return None

    tp, sl = risk["tp"], risk["sl"]
    tp_price = entry_price * (1 + tp) if direction == "long" else entry_price * (1 - tp)
    sl_price = entry_price * (1 - sl) if direction == "long" else entry_price * (1 + sl)

    start = time.time()
    exit_price = entry_price

    while True:
        price = get_price(symbol_for_exec)
        if price is None or price <= 0:
            time.sleep(PRICE_CHECK_INTERVAL)
            continue

        elapsed = time.time() - start
        if elapsed > MAX_TRADE_DURATION_SECONDS:
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
    place_market_order(user_id, symbol_for_exec, opposite, qty)

    profit = round(
        ((exit_price - entry_price) / entry_price * qty)
        if direction == "long"
        else ((entry_price - exit_price) / entry_price * qty),
        6
    )

    log(f"Trade cerrado {symbol} PnL={profit}")

    register_trade(
        user_id=user_id,
        symbol=symbol,
        side=side.upper(),
        entry_price=entry_price,
        exit_price=exit_price,
        qty=qty,
        profit=profit,
        best_score=best.get("score", 0.0),
    )

    admin_fee = max(profit, 0) * OWNER_FEE_PERCENT
    referrer_id = get_user_referrer(user_id)

    if referrer_id and admin_fee > 0:
        ref_fee = admin_fee * REFERRAL_FEE_PERCENT
        add_weekly_ref_fee(referrer_id, ref_fee)
        admin_fee -= ref_fee

    if admin_fee > 0:
        add_daily_admin_fee(user_id, admin_fee)

    return {
        "event": "BOTH",
        "open": {"message": f"🟢 Trade abierto {symbol} ({direction.upper()})"},
        "close": {"message": f"🔴 Trade cerrado {symbol}\nPnL: {profit} USDC"},
}
