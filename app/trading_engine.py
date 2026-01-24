# ============================================================
# TRADING ENGINE – Trading X Hyper Pro
# PRODUCCIÓN REAL – BANK GRADE
# SL + TP MIN + TRAILING
# Cuenta trades SOLO si hubo FILL real
# FIX:
#   - 1 trade a la vez por usuario (LOCK)
#   - No abre si ya hay posición abierta en el exchange
#   - Sizing: usa 100% del capital Telegram como margen con apalancamiento X3
#   - ✅ NO CIERRA POR TIEMPO: solo SL o TRAIL
# ============================================================

import time
import threading
from datetime import datetime, timedelta, date
from typing import Any

from app.market_scanner import get_best_symbol
from app.strategy import get_entry_signal
from app.risk import validate_trade_conditions
from app.hyperliquid_client import place_market_order, get_price, get_balance, has_open_position

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

# ✅ Desactivado: NO se cierra por tiempo
# MAX_TRADE_DURATION_SECONDS = 360

PRICE_CHECK_INTERVAL = 0.4

MIN_TRADE_STRENGTH = 0.18
USER_TRADE_COOLDOWN_SECONDS = 300
MAX_TRADES_PER_HOUR = 2
MAX_TRADES_PER_DAY = 10

SYMBOL_NOFILL_COOLDOWN_SECONDS = 90

# ✅ Sizing (NO toca strategy)
MARGIN_USE_PCT = 1.0   # 100% del capital de Telegram
LEVERAGE = 3.0         # X3 (tu elección)

user_next_trade_time = {}   # user_id -> datetime
user_trade_counter = {}     # user_id -> {"hour_key": str, "hour_count": int, "day": date, "day_count": int}

# user_id -> { "CC-PERP": expiry_dt, ... }
user_symbol_cooldowns: dict[int, dict[str, datetime]] = {}

# ✅ Lock por usuario
_user_locks: dict[int, threading.Lock] = {}

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
# DETECTOR DE FILL (compatible con cliente dict: ok/filled)
# ============================================================

def _has_positive_fill(obj: Any) -> bool:
    try:
        if isinstance(obj, dict) and "filled" in obj:
            return bool(obj.get("filled"))

        if isinstance(obj, dict):
            for k, v in obj.items():
                lk = str(k).lower()

                if lk in ("filledsz", "fillsz", "filledsize", "filled", "fill"):
                    try:
                        if float(v) > 0:
                            return True
                    except Exception:
                        pass

                if lk in ("status", "state"):
                    sv = str(v).lower()
                    if "filled" in sv:
                        return True

                if _has_positive_fill(v):
                    return True

        elif isinstance(obj, list):
            for it in obj:
                if _has_positive_fill(it):
                    return True

        return False
    except Exception:
        return False

def _is_filled_exchange_response(resp: Any) -> bool:
    if not resp:
        return False
    return _has_positive_fill(resp)

def _resp_ok(resp: Any) -> bool:
    if isinstance(resp, dict) and "ok" in resp:
        return bool(resp.get("ok"))
    return bool(resp)

def _resp_reason(resp: Any) -> str:
    if isinstance(resp, dict):
        r = resp.get("reason") or resp.get("status") or resp.get("error") or resp.get("err") or ""
        return str(r)
    return ""

# ============================================================
# COOLDOWN POR SÍMBOLO (por usuario)
# ============================================================

def _get_excluded_symbols(user_id: int) -> set[str]:
    now = datetime.utcnow()
    m = user_symbol_cooldowns.get(user_id) or {}

    alive: dict[str, datetime] = {}
    exclude: set[str] = set()

    for sym, exp in m.items():
        try:
            if exp and now < exp:
                alive[sym] = exp
                exclude.add(sym)
        except Exception:
            continue

    user_symbol_cooldowns[user_id] = alive
    return exclude

def _cooldown_symbol(user_id: int, symbol: str, seconds: int = SYMBOL_NOFILL_COOLDOWN_SECONDS):
    try:
        sym = str(symbol or "").upper()
        if not sym:
            return
        m = user_symbol_cooldowns.setdefault(user_id, {})
        m[sym] = datetime.utcnow() + timedelta(seconds=int(seconds))
    except Exception:
        pass

# ============================================================
# RATE LIMIT (por usuario)
# ============================================================

def _hour_key(now: datetime) -> str:
    return now.strftime("%Y-%m-%d-%H")

def _can_trade_now(user_id: int) -> tuple[bool, str]:
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

def execute_trade_cycle(user_id: int) -> dict | None:
    lock = _user_locks.setdefault(user_id, threading.Lock())
    if not lock.acquire(blocking=False):
        log(f"Usuario {user_id} — ciclo ya en ejecución, se salta", "WARN")
        return None

    try:
        log(f"Usuario {user_id} — inicio ciclo")

        if not user_is_ready(user_id):
            log(f"Usuario {user_id} no listo")
            return None

        # Capital Telegram (base del compounding; aquí aún no lo actualizamos)
        capital = float(get_user_capital(user_id) or 0.0)
        log(f"Capital (Telegram): {capital}")

        # Balance real solo para saber que hay wallet conectada
        real_balance = float(get_balance(user_id) or 0.0)
        if real_balance <= 0:
            log("Balance real en exchange = 0 (no se ejecuta trading)", "WARN")
            return None

        # ✅ Anti-multi-position (regla de oro)
        if has_open_position(user_id):
            log("Ya hay una posición abierta en el exchange — NO se abre otra", "WARN")
            return None

        ok_trade, reason_trade = _can_trade_now(user_id)
        if not ok_trade:
            log(f"Bloqueo responsable: {reason_trade}", "INFO")
            return None

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
            if reason and signal.get("window"):
                log(f"Sin señal {symbol} reason={reason} window={signal.get('window')}")
            elif reason and signal.get("strength") is not None:
                log(f"Sin señal {symbol} reason={reason} strength={signal.get('strength')}")
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

        # ✅ NO tocamos strategy: esto solo valida condiciones (tp/sl/trailing salen de risk)
        risk = validate_trade_conditions(capital, strength)
        if not risk.get("ok"):
            log(f"Trade cancelado: {risk.get('reason')}", "WARN")
            return None

        tp_min = float(risk.get("tp_min", risk.get("tp", 0.035)) or 0.035)
        sl_pct = float(risk.get("sl", 0.025) or 0.025)
        trailing_pct = float(risk.get("trailing_pct", 0.02) or 0.02)

        # ✅ SIZING X3: 100% del capital como margen, X3 como notional
        qty_usdc = float(capital) * float(MARGIN_USE_PCT) * float(LEVERAGE)

        # Preview price
        entry_price_preview = float(get_price(symbol_for_exec) or 0.0)
        if entry_price_preview <= 0:
            log("No se pudo obtener precio para calcular qty_coin", "ERROR")
            return None

        qty_coin = round(qty_usdc / entry_price_preview, 8)
        if qty_coin <= 0:
            log("qty_coin inválido tras conversión", "ERROR")
            return None

        # OPEN
        log(f"Ejecutando orden {symbol} {side} qty_coin={qty_coin} (notional~{qty_usdc} USDC, lev={LEVERAGE}x)")
        open_resp = place_market_order(user_id, symbol_for_exec, side, qty_coin)

        if not open_resp:
            log("Orden OPEN sin respuesta/empty del exchange — abortando trade", "ERROR")
            _cooldown_symbol(user_id, symbol, SYMBOL_NOFILL_COOLDOWN_SECONDS)
            return None

        if not _resp_ok(open_resp):
            reason = _resp_reason(open_resp) or "EXCHANGE_REJECTED"
            log(f"OPEN no OK (reason={reason}) -> cooldown {SYMBOL_NOFILL_COOLDOWN_SECONDS}s para {symbol}", "ERROR")
            _cooldown_symbol(user_id, symbol, SYMBOL_NOFILL_COOLDOWN_SECONDS)
            return None

        if not _is_filled_exchange_response(open_resp):
            reason = _resp_reason(open_resp) or "NO_FILL"
            log(f"OPEN sin FIL (reason={reason}) -> cooldown {SYMBOL_NOFILL_COOLDOWN_SECONDS}s para {symbol}", "WARN")
            _cooldown_symbol(user_id, symbol, SYMBOL_NOFILL_COOLDOWN_SECONDS)
            return None

        _register_trade_attempt(user_id)

        entry_price = float(get_price(symbol_for_exec) or 0.0)
        if entry_price <= 0:
            log("Precio de entrada inválido", "ERROR")
            return None

        # SL + TP mínimo + trailing
        if direction == "long":
            sl_price = entry_price * (1 - sl_pct)
            tp_min_price = entry_price * (1 + tp_min)
        else:
            sl_price = entry_price * (1 + sl_pct)
            tp_min_price = entry_price * (1 - tp_min)

        trailing_active = False
        best_price = entry_price
        trailing_stop = None

        exit_price = entry_price
        exit_reason = "UNKNOWN"

        while True:
            price = float(get_price(symbol_for_exec) or 0.0)
            if price <= 0:
                time.sleep(PRICE_CHECK_INTERVAL)
                continue

            # ✅ SIN CIERRE POR TIEMPO (eliminado)

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

        # CLOSE
        log(f"Cerrando trade {symbol} reason={exit_reason}")
        close_resp = place_market_order(user_id, symbol_for_exec, opposite, qty_coin)

        if not close_resp:
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

        if not _is_filled_exchange_response(close_resp):
            reason = _resp_reason(close_resp) or "NO_FILL"
            log(f"CLOSE sin FIL (reason={reason}) — NO se registra cierre/PnL", "CRITICAL")
            return {
                "event": "OPEN",
                "open": {
                    "message": (
                        f"🟡 Trade abierto {symbol} ({direction.upper()})\n"
                        f"⚠️ Advertencia: cierre sin FIL confirmado ({reason}). Revisa la posición en Hyperliquid."
                    )
                },
            }

        # PnL estimado con notional (qty_usdc) — ahora sí “se ve” con X3
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
            qty=qty_coin,
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

    finally:
        try:
            lock.release()
        except Exception:
            pass
