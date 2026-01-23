# ============================================================
# TRADING ENGINE – Trading X Hyper Pro
# Limpio / Production
#  - Scanner vive en market_scanner.py
#  - Cliente HL es responsable de devolver: {"ok": bool, "filled": bool, "reason": str, ...}
#  - Engine NO “adivina” fills: usa open_resp["filled"]
#  - qty_coin se calcula con best bid/ask (no con mid)
# ============================================================

import time
from datetime import datetime, timedelta, date
from typing import Optional, Tuple

from app.market_scanner import get_best_symbol
from app.strategy import get_entry_signal
from app.risk import validate_trade_conditions

# ✅ Importa best bid/ask para calcular qty con precio ejecutable
from app.hyperliquid_client import (
    place_market_order,
    get_price,
    get_balance,
    get_best_bid_ask,  # <-- asegúrate de exponerlo en el cliente (wrapper público)
)

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

# Rate limit del engine (NO del scanner)
MIN_TRADE_STRENGTH = 0.18
USER_TRADE_COOLDOWN_SECONDS = 300
MAX_TRADES_PER_HOUR = 2
MAX_TRADES_PER_DAY = 10

# Cooldown por símbolo cuando hay NO_FILL o reject suave
SYMBOL_NOFILL_COOLDOWN_SECONDS = 90  # recomendado 60–120s

# Estado en memoria
user_next_trade_time: dict[int, datetime] = {}
user_trade_counter: dict[int, dict] = {}
user_symbol_cooldowns: dict[int, dict[str, datetime]] = {}

# ============================================================
# LOG
# ============================================================

def log(msg: str, level: str = "INFO"):
    print(f"[ENGINE {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}] {level} {msg}")

# ============================================================
# UTILS
# ============================================================

def _norm_coin(symbol: str) -> str:
    """Normaliza CC-PERP / CC_PERP / CC -> CC"""
    s = (symbol or "").strip().upper()
    s = s.replace("-PERP", "").replace("_PERP", "").replace("PERP", "")
    if "/" in s:
        s = s.split("/", 1)[0].strip()
    return s

def _resp_ok(resp: dict) -> bool:
    return bool(resp.get("ok")) if isinstance(resp, dict) else False

def _resp_reason(resp: dict) -> str:
    if not isinstance(resp, dict):
        return ""
    return str(resp.get("reason") or resp.get("status") or resp.get("error") or resp.get("err") or "")

# ============================================================
# COOLDOWN POR SÍMBOLO
# ============================================================

def _get_excluded_symbols(user_id: int) -> set[str]:
    now = datetime.utcnow()
    m = user_symbol_cooldowns.get(user_id) or {}

    alive: dict[str, datetime] = {}
    exclude: set[str] = set()

    for sym, exp in m.items():
        if exp and now < exp:
            alive[sym] = exp
            exclude.add(sym)

    user_symbol_cooldowns[user_id] = alive
    return exclude

def _cooldown_symbol(user_id: int, symbol: str, seconds: int = SYMBOL_NOFILL_COOLDOWN_SECONDS):
    sym = str(symbol or "").upper()
    if not sym:
        return
    m = user_symbol_cooldowns.setdefault(user_id, {})
    m[sym] = datetime.utcnow() + timedelta(seconds=int(seconds))

# ============================================================
# RATE LIMIT (por usuario)
# ============================================================

def _hour_key(now: datetime) -> str:
    return now.strftime("%Y-%m-%d-%H")

def _can_trade_now(user_id: int) -> Tuple[bool, str]:
    now = datetime.utcnow()

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

    hk = _hour_key(now)
    if state["hour_key"] != hk:
        state["hour_key"] = hk
        state["hour_count"] = 0

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

    user_next_trade_time[user_id] = now + timedelta(seconds=USER_TRADE_COOLDOWN_SECONDS)

# ============================================================
# CICLO PRINCIPAL
# ============================================================

def execute_trade_cycle(user_id: int) -> Optional[dict]:
    log(f"Usuario {user_id} — inicio ciclo")

    if not user_is_ready(user_id):
        log(f"Usuario {user_id} no listo")
        return None

    # Capital configurado por Telegram (NO el total del exchange)
    capital = float(get_user_capital(user_id) or 0.0)
    log(f"Capital (Telegram): {capital}")

    # Solo verificamos que el exchange esté con balance > 0 (wallet conectada)
    real_balance = float(get_balance(user_id) or 0.0)
    if real_balance <= 0:
        log("Balance real en exchange = 0 (no se ejecuta trading)", "WARN")
        return None

    ok_trade, reason_trade = _can_trade_now(user_id)
    if not ok_trade:
        log(f"Bloqueo responsable: {reason_trade}", "INFO")
        return None

    # Pedimos un símbolo al scanner excluyendo cooldowns
    exclude = _get_excluded_symbols(user_id)
    best = get_best_symbol(exclude_symbols=exclude)

    if not best or not best.get("symbol"):
        log("Scanner no devolvió símbolo", "WARN")
        return None

    symbol = str(best["symbol"]).upper()
    symbol_for_exec = _norm_coin(symbol)
    log(f"Símbolo elegido (scanner): {symbol}")

    # Señal
    signal = get_entry_signal(symbol)
    if not isinstance(signal, dict):
        log(f"Señal inválida {symbol}", "ERROR")
        return None

    if not signal.get("signal"):
        reason = signal.get("reason")
        window = signal.get("window")
        strength = signal.get("strength")
        if reason and window:
            log(f"Sin señal {symbol} reason={reason} window={window}")
        elif reason and strength is not None:
            log(f"Sin señal {symbol} reason={reason} strength={strength}")
        elif reason:
            log(f"Sin señal {symbol} reason={reason}")
        else:
            log(f"Sin señal válida {symbol}")
        return None

    strength = float(signal.get("strength", 0.0) or 0.0)
    if strength < MIN_TRADE_STRENGTH:
        log(f"Señal débil bloqueada: strength={strength:.4f} < {MIN_TRADE_STRENGTH}", "INFO")
        return None

    direction = str(signal.get("direction") or "").lower()
    if direction not in ("long", "short"):
        log(f"Dirección inválida en señal: {direction}", "ERROR")
        return None

    side = "buy" if direction == "long" else "sell"
    opposite = "sell" if side == "buy" else "buy"

    log(f"SEÑAL CONFIRMADA {symbol} {direction.upper()} strength={signal.get('strength')} score={signal.get('score')}")

    # Risk usa capital de Telegram
    risk = validate_trade_conditions(capital, strength)
    if not risk.get("ok"):
        log(f"Trade cancelado: {risk.get('reason')}", "WARN")
        return None

    # position_size se interpreta como NOTIONAL en USDC
    qty_usdc = float(risk.get("position_size") or 0.0)
    if qty_usdc <= 0:
        log("Position size inválido (USDC<=0)", "ERROR")
        return None

    tp_min = float(risk.get("tp_min", risk.get("tp", 0.035)) or 0.035)
    sl_pct = float(risk.get("sl", 0.025) or 0.025)
    trailing_pct = float(risk.get("trailing_pct", 0.02) or 0.02)

    # ✅ qty_coin basado en precio ejecutable (bid/ask), NO en mid
    bid, ask = get_best_bid_ask(symbol_for_exec)
    px_exec = ask if side == "buy" else bid
    if px_exec <= 0:
        px_exec = float(get_price(symbol_for_exec) or 0.0)
    if px_exec <= 0:
        log("No se pudo obtener precio para calcular qty_coin", "ERROR")
        return None

    qty_coin = round(qty_usdc / px_exec, 8)
    if qty_coin <= 0:
        log("qty_coin inválido tras conversión", "ERROR")
        return None

    # --------------------------------------------------------
    # OPEN
    # --------------------------------------------------------
    log(f"Ejecutando orden {symbol} {side} qty_coin={qty_coin} (notional~{qty_usdc} USDC)")
    open_resp = place_market_order(user_id, symbol_for_exec, side, qty_coin)

    if not isinstance(open_resp, dict) or not open_resp:
        log("Orden OPEN sin respuesta/empty del exchange — abortando trade", "ERROR")
        _cooldown_symbol(user_id, symbol, SYMBOL_NOFILL_COOLDOWN_SECONDS)
        return None

    # Reject/error exchange
    if not _resp_ok(open_resp):
        reason = _resp_reason(open_resp) or "EXCHANGE_REJECTED"
        log(f"OPEN no OK (reason={reason}) -> cooldown {SYMBOL_NOFILL_COOLDOWN_SECONDS}s para {symbol}", "ERROR")
        _cooldown_symbol(user_id, symbol, SYMBOL_NOFILL_COOLDOWN_SECONDS)
        return None

    # ✅ NO_FILL real: usamos "filled" directamente del cliente
    if not bool(open_resp.get("filled")):
        reason = _resp_reason(open_resp) or "NO_FILL"
        log(f"OPEN sin FILL (reason={reason}) -> cooldown {SYMBOL_NOFILL_COOLDOWN_SECONDS}s para {symbol}", "WARN")
        _cooldown_symbol(user_id, symbol, SYMBOL_NOFILL_COOLDOWN_SECONDS)
        return None

    # ✅ Solo cuenta trade si hubo fill real
    _register_trade_attempt(user_id)

    # Precio de entrada: con mid (ok para PnL aproximado). Si quieres exacto, usa open_resp["px"] si lo guardas.
    entry_price = float(get_price(symbol_for_exec) or 0.0)
    if entry_price <= 0:
        log("Precio de entrada inválido", "ERROR")
        return None

    # --------------------------------------------------------
    # SL + TP mínimo + trailing
    # --------------------------------------------------------
    if direction == "long":
        sl_price = entry_price * (1 - sl_pct)
        tp_min_price = entry_price * (1 + tp_min)
    else:
        sl_price = entry_price * (1 + sl_pct)
        tp_min_price = entry_price * (1 - tp_min)

    trailing_active = False
    best_price = entry_price
    trailing_stop = None

    start = time.time()
    exit_price = entry_price
    exit_reason = "TIME"

    while True:
        price = float(get_price(symbol_for_exec) or 0.0)
        if price <= 0:
            time.sleep(PRICE_CHECK_INTERVAL)
            continue

        elapsed = time.time() - start
        if elapsed > MAX_TRADE_DURATION_SECONDS:
            exit_price = price
            exit_reason = "TIME"
            break

        # SL
        if direction == "long" and price <= sl_price:
            exit_price = price
            exit_reason = "SL"
            break
        if direction == "short" and price >= sl_price:
            exit_price = price
            exit_reason = "SL"
            break

        # activar trailing al llegar TP mínimo
        if not trailing_active:
            if direction == "long" and price >= tp_min_price:
                trailing_active = True
                best_price = price
                trailing_stop = best_price * (1 - trailing_pct)
                exit_reason = "TRAIL"
            elif direction == "short" and price <= tp_min_price:
                trailing_active = True
                best_price = price
                trailing_stop = best_price * (1 + trailing_pct)
                exit_reason = "TRAIL"
        else:
            if direction == "long":
                if price > best_price:
                    best_price = price
                    trailing_stop = best_price * (1 - trailing_pct)
                if trailing_stop is not None and price <= trailing_stop:
                    exit_price = price
                    exit_reason = "TRAIL"
                    break
            else:
                if price < best_price:
                    best_price = price
                    trailing_stop = best_price * (1 + trailing_pct)
                if trailing_stop is not None and price >= trailing_stop:
                    exit_price = price
                    exit_reason = "TRAIL"
                    break

        time.sleep(PRICE_CHECK_INTERVAL)

    # --------------------------------------------------------
    # CLOSE
    # --------------------------------------------------------
    log(f"Cerrando trade {symbol} reason={exit_reason}")
    close_resp = place_market_order(user_id, symbol_for_exec, opposite, qty_coin)

    if not isinstance(close_resp, dict) or not close_resp:
        log("Orden CLOSE sin respuesta/empty del exchange — NO se registra cierre/PnL", "CRITICAL")
        return {
            "event": "OPEN",
            "open": {
                "message": (
                    f"🟡 Trade abierto {symbol} ({direction.upper()})\n"
                    f"⚠️ Advertencia: cierre NO confirmado por el exchange. Revisa la posición en Hyperliquid."
                )
            },
        }

    if not _resp_ok(close_resp):
        reason = _resp_reason(close_resp) or "EXCHANGE_REJECTED"
        log(f"CLOSE no OK (reason={reason}) — NO se registra cierre/PnL", "CRITICAL")
        return {
            "event": "OPEN",
            "open": {
                "message": (
                    f"🟡 Trade abierto {symbol} ({direction.upper()})\n"
                    f"⚠️ Advertencia: cierre RECHAZADO por el exchange ({reason}). Revisa la posición en Hyperliquid."
                )
            },
        }

    if not bool(close_resp.get("filled")):
        reason = _resp_reason(close_resp) or "NO_FILL"
        log(f"CLOSE sin FILL (reason={reason}) — NO se registra cierre/PnL", "CRITICAL")
        return {
            "event": "OPEN",
            "open": {
                "message": (
                    f"🟡 Trade abierto {symbol} ({direction.upper()})\n"
                    f"⚠️ Advertencia: cierre sin FILL confirmado ({reason}). Revisa la posición en Hyperliquid."
                )
            },
        }

    # PnL en USDC usando NOTIONAL (qty_usdc)
    profit = round(
        ((exit_price - entry_price) / entry_price * qty_usdc)
        if direction == "long"
        else ((entry_price - exit_price) / entry_price * qty_usdc),
        6
    )

    log(f"Trade cerrado {symbol} PnL={profit}")

    register_trade(
        user_id=user_id,
        symbol=symbol,
        side=side.upper(),
        entry_price=entry_price,
        exit_price=exit_price,
        qty=qty_coin,  # size real en coin
        profit=profit,
        best_score=float(best.get("score", 0.0) or 0.0),
    )

    admin_fee = max(profit, 0.0) * float(OWNER_FEE_PERCENT or 0.0)
    referrer_id = get_user_referrer(user_id)

    if referrer_id and admin_fee > 0:
        ref_fee = admin_fee * float(REFERRAL_FEE_PERCENT or 0.0)
        add_weekly_ref_fee(referrer_id, ref_fee)
        admin_fee -= ref_fee

    if admin_fee > 0:
        add_daily_admin_fee(user_id, admin_fee)

    return {
        "event": "BOTH",
        "open": {"message": f"🟢 Trade abierto {symbol} ({direction.upper()})"},
        "close": {"message": f"🔴 Trade cerrado {symbol}\nPnL: {profit} USDC"},
      }
