# ============================================================
# TRADING ENGINE – Trading X Hyper Pro
# PRODUCCIÓN REAL – MODO RESPONSABLE (BANK GRADE)
# ============================================================

import time
from datetime import datetime, timedelta, date

from app.market_scanner import get_best_symbol
from app.strategy import get_entry_signal
from app.risk import validate_trade_conditions
from app.hyperliquid_client import place_market_order, get_price, get_balance

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

BLACKLIST_MINUTES = 10
SYMBOL_COOLDOWN_SECONDS = 30

# ✅ MODO RESPONSABLE
MIN_TRADE_STRENGTH = 0.18            # solo ejecuta si strength >= esto
USER_TRADE_COOLDOWN_SECONDS = 300    # 5 minutos sin re-entrar tras un trade
MAX_TRADES_PER_HOUR = 2
MAX_TRADES_PER_DAY = 10

symbol_blacklist = {}
symbol_cooldown = {}
user_last_symbol = {}

user_next_trade_time = {}            # user_id -> datetime
user_trade_counter = {}              # user_id -> {"hour_key": str, "hour_count": int, "day": date, "day_count": int}


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
# RATE LIMIT (por usuario)
# ============================================================

def _hour_key(now: datetime) -> str:
    return now.strftime("%Y-%m-%d-%H")

def _can_trade_now(user_id: int) -> tuple[bool, str]:
    now = datetime.utcnow()

    # Cooldown duro por usuario
    next_time = user_next_trade_time.get(user_id)
    if next_time and now < next_time:
        secs = int((next_time - now).total_seconds())
        return False, f"Cooldown usuario activo ({secs}s)"

    state = user_trade_counter.get(user_id)
    if not state:
        user_trade_counter[user_id] = {
            "hour_key": _hour_key(now),
            "hour_count": 0,
            "day": date.today(),
            "day_count": 0,
        }
        state = user_trade_counter[user_id]

    # Reset por hora
    hk = _hour_key(now)
    if state["hour_key"] != hk:
        state["hour_key"] = hk
        state["hour_count"] = 0

    # Reset por día
    today = date.today()
    if state["day"] != today:
        state["day"] = today
        state["day_count"] = 0

    if state["hour_count"] >= MAX_TRADES_PER_HOUR:
        return False, f"Límite por hora alcanzado ({MAX_TRADES_PER_HOUR})"

    if state["day_count"] >= MAX_TRADES_PER_DAY:
        return False, f"Límite por día alcanzado ({MAX_TRADES_PER_DAY})"

    return True, "OK"

def _register_trade_attempt(user_id: int):
    now = datetime.utcnow()
    state = user_trade_counter.setdefault(user_id, {
        "hour_key": _hour_key(now),
        "hour_count": 0,
        "day": date.today(),
        "day_count": 0,
    })

    hk = _hour_key(now)
    if state["hour_key"] != hk:
        state["hour_key"] = hk
        state["hour_count"] = 0

    today = date.today()
    if state["day"] != today:
        state["day"] = today
        state["day_count"] = 0

    state["hour_count"] += 1
    state["day_count"] += 1

    # set cooldown post-trade
    user_next_trade_time[user_id] = now + timedelta(seconds=USER_TRADE_COOLDOWN_SECONDS)


# ============================================================
# COOLDOWN (símbolos)
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
        log(f"Blacklist liberada {symbol}")
        return False
    return True

def blacklist_symbol(symbol: str):
    symbol_blacklist[symbol] = datetime.utcnow() + timedelta(minutes=BLACKLIST_MINUTES)
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

    # --------------------------------------------------------
    # FIX CRÍTICO (PROD REAL):
    # Si el balance REAL del exchange es 0, NO intentamos operar.
    # Evita trades fantasma y rechazos por margen.
    # --------------------------------------------------------
    real_balance = get_balance(user_id)
    if real_balance <= 0:
        log("Balance real en exchange = 0 (no se ejecuta trading)", "WARN")
        return None
    # --------------------------------------------------------

    # Freno responsable (cooldown + rate limit)
    ok_trade, reason_trade = _can_trade_now(user_id)
    if not ok_trade:
        log(f"Bloqueo responsable: {reason_trade}", "INFO")
        return None

    exclude_symbols = {s for s in list(symbol_cooldown.keys()) if _is_in_cooldown(s)}
    exclude_symbols |= set(symbol_blacklist.keys())

    preferred = user_last_symbol.get(user_id)
    if preferred and preferred not in exclude_symbols and not is_blacklisted(preferred):
        best = {"symbol": preferred, "score": 0.0}
    else:
        best = get_best_symbol(exclude_symbols=exclude_symbols)
        if not best:
            log("No se encontró símbolo")
            return None

    raw_symbol = best["symbol"]
    symbol = raw_symbol if raw_symbol.endswith("-PERP") else f"{raw_symbol}-PERP"
    user_last_symbol[user_id] = symbol

    symbol_for_exec = _norm_coin(symbol)

    log(f"Símbolo elegido: {symbol}")

    if is_blacklisted(symbol):
        log(f"Símbolo {symbol} en blacklist")
        return None

    if _is_in_cooldown(symbol):
        log(f"Símbolo {symbol} en cooldown")
        return None

    signal = get_entry_signal(symbol)
    if not isinstance(signal, dict):
        log(f"Señal inválida {symbol}", "ERROR")
        return None

    if not signal.get("signal"):
        reason = signal.get("reason")

        if reason and signal.get("window"):
            log(f"Sin señal {symbol} reason={reason} window={signal.get('window')}")
        elif reason and signal.get("strength") is not None:
            log(f"Sin señal {symbol} reason={reason} strength={signal.get('strength')}")
        elif reason:
            log(f"Sin señal {symbol} reason={reason}")
        else:
            log(f"Sin señal válida {symbol}")

        # Solo rotar si ya evaluó y NO pasó umbral (THRESHOLD)
        if reason in ("THRESHOLD",):
            _set_cooldown(symbol)
            user_last_symbol.pop(user_id, None)

        return None

    # ✅ GATE RESPONSABLE: aunque haya señal, solo operamos si strength es fuerte
    strength = float(signal.get("strength", 0.0) or 0.0)
    if strength < MIN_TRADE_STRENGTH:
        log(f"Señal débil bloqueada: strength={strength:.4f} < {MIN_TRADE_STRENGTH}", "INFO")
        _set_cooldown(symbol)
        user_last_symbol.pop(user_id, None)
        return None

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

    # --------------------------------------------------------
    # FIX CRÍTICO (PROD REAL):
    # Ejecutar orden y VALIDAR que Hyperliquid la aceptó.
    # Si falla, NO hay trade: no registramos, no calculamos PnL, no cobramos fees.
    # --------------------------------------------------------
    log(f"Ejecutando orden {symbol} {side} qty={qty}")
    open_resp = place_market_order(user_id, symbol_for_exec, side, qty)

    if not open_resp:
        log("Orden OPEN rechazada/no confirmada por Hyperliquid — abortando trade", "ERROR")
        _set_cooldown(symbol)
        return None
    # --------------------------------------------------------

    # ✅ Registramos operación para rate limit + cooldown SOLO si hubo OPEN real
    _register_trade_attempt(user_id)

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
    close_resp = place_market_order(user_id, symbol_for_exec, opposite, qty)

    # --------------------------------------------------------
    # FIX CRÍTICO (PROD REAL):
    # Si CLOSE no es confirmado, NO registramos el trade como cerrado ni calculamos PnL.
    # (Evita inconsistencias contables y "cierres fantasmas")
    # --------------------------------------------------------
    if not close_resp:
        log("Orden CLOSE rechazada/no confirmada por Hyperliquid — NO se registra cierre/PnL", "CRITICAL")
        return {
            "event": "OPEN",
            "open": {"message": f"🟡 Trade abierto {symbol} ({direction.upper()})\n⚠️ Advertencia: cierre NO confirmado por el exchange. Revisa la posición en Hyperliquid."},
        }
    # --------------------------------------------------------

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
