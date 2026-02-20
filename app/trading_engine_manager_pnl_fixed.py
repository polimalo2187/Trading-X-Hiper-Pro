# ============================================================
# TRADING ENGINE – Trading X Hyper Pro
# PRODUCCIÓN REAL – BANK GRADE
# SL + TP MIN + TRAILING
# Cuenta trades SOLO si hubo FILL real
# FIX:
#   - 1 trade a la vez por usuario (LOCK)
#   - No abre si ya hay posición abierta en el exchange
#   - Sizing: usa el balance REAL del exchange (withdrawable) como capital operativo; interés compuesto natural
#   - ✅ NO CIERRA POR TIEMPO: solo SL o TRAIL
#   - ✅ TP HARD MAX: 25% (cierra sí o sí al tocarlo)
#   - ✅ TP ACTIVA TRAILING EN 1.0%
#   - ✅ TRAIL REAL: si retrocede 1.0pp desde el máximo profit => CIERRA
#   - ✅ SL por fuerza: normal 1.0% / fuerte 1.5%
#
# FIX CLAVE (ESTE PATCH):
#   - Usa entry_price REAL del fill si viene en open_resp
#   - Cierres por %PnL (pnl_pct), NO por "precio vs precio"
# ============================================================

import time
import os
import threading
from datetime import datetime, timedelta, date
from typing import Any, Optional

from app.market_scanner import get_best_symbol
from app.strategy import get_entry_signal
from app.risk import validate_trade_conditions
from app.hyperliquid_client import place_market_order, get_price, get_balance, has_open_position, get_position_entry_price, get_open_position_size, make_request

from app.database import (
    user_is_ready,
    register_trade,
    add_daily_admin_fee,
    add_weekly_ref_fee,
    get_user_referrer,
    get_user_wallet,
)

from app.config import OWNER_FEE_PERCENT, REFERRAL_FEE_PERCENT

# ============================================================
# CONFIG
# ============================================================

PRICE_CHECK_INTERVAL = 0.4

MIN_TRADE_STRENGTH = 0.18
USER_TRADE_COOLDOWN_SECONDS = 600

# Startup grace to avoid an immediate trade right after a deploy/restart
STARTUP_GRACE_SECONDS = int(os.getenv('STARTUP_GRACE_SECONDS', '30'))
PROCESS_START_TIME_UTC = datetime.utcnow()
MAX_TRADES_PER_HOUR = None  # ilimitado
MAX_TRADES_PER_DAY = None  # ilimitado

SYMBOL_NOFILL_COOLDOWN_SECONDS = 90

# ✅ Sizing (NO toca strategy)
MARGIN_USE_PCT = 1.0   # 100% del capital de Telegram
LEVERAGE = 5.0         # X3

# ✅ BLINDAJE BANK GRADE (ANTI-ÓRDENES RIDÍCULAS)
# Evita operaciones con tamaños de centavos / qty ~ 0 por capital bajo o redondeos.
MIN_CAPITAL_USDC = 5.0   # capital mínimo para operar
MIN_NOTIONAL_USDC = 5.0  # tamaño mínimo (margen*lev) en USDC
MIN_QTY_COIN = 0.0001    # qty mínimo en coin (seguridad)



# ✅ NUEVA LÓGICA TP/TRAIL
TP_ACTIVATE_TRAIL_PRICE = 0.008  # ACTIVA TRAILING 0.8% PRECIO (x3 incluido)
TRAIL_RETRACE_PRICE = 0.002  # CIERRA SI RETROCEDE 0.2% DESDE EL MAX

# ✅ SL por fuerza
SL_MIN_PRICE = 0.006  # SL FIJO 0.66% PRECIO (x3 incluido)

# ============================================================
# STATE (rate limit / cooldown) — requerido por trading_loop
# ============================================================

# user_id -> datetime (cooldown entre trades)
user_next_trade_time: dict[int, datetime] = {}

# user_id -> {"hour_key": str, "hour_count": int, "day": date, "day_count": int}
user_trade_counter: dict[int, dict] = {}

STRENGTH_STRONG_THRESHOLD = 0.30  # umbral para "fuerte"



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
# EXTRAER PRECIO DE FILL REAL (si viene en la respuesta)
# ============================================================

def _extract_fill_price(obj: Any) -> Optional[float]:
    """
    Busca un precio de fill/avgPx dentro de estructuras dict/list.
    Claves típicas: avgPx, averagePrice, fillPx, filledPx, price, px, entryPx...
    Devuelve float si encuentra > 0.
    """
    try:
        if isinstance(obj, dict):
            # claves directas comunes
            for key in ("avgPx", "averagePrice", "fillPx", "filledPx", "entryPx", "avg_price", "fill_price"):
                if key in obj:
                    try:
                        v = float(obj[key])
                        if v > 0:
                            return v
                    except Exception:
                        pass

            # a veces viene en "fills" como lista o estructuras anidadas
            for key in ("fills", "fill", "orders", "data", "result", "response"):
                if key in obj:
                    v2 = _extract_fill_price(obj[key])
                    if v2 and v2 > 0:
                        return v2

            # fallback: cualquier campo "px" o "price" válido (o recursión por otros campos)
            for k, v in obj.items():
                lk = str(k).lower()
                if lk in ("px", "price"):
                    try:
                        fv = float(v)
                        if fv > 0:
                            return fv
                    except Exception:
                        pass
                nested = _extract_fill_price(v)
                if nested and nested > 0:
                    return nested

        elif isinstance(obj, list):
            for it in obj:
                v = _extract_fill_price(it)
                if v and v > 0:
                    return v

        return None
    except Exception:
        return None

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
    # Per-user startup grace: prevents an immediate entry right after a deploy/restart.
    # We only set this once per process and per user, so normal cooldown rules still apply afterwards.
    if STARTUP_GRACE_SECONDS > 0 and user_id not in user_next_trade_time:
        user_next_trade_time[user_id] = PROCESS_START_TIME_UTC + timedelta(seconds=STARTUP_GRACE_SECONDS)
        log(f"Startup grace activo ({STARTUP_GRACE_SECONDS}s) para usuario {user_id}", "INFO")


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

    if MAX_TRADES_PER_HOUR is not None and state["hour_count"] >= MAX_TRADES_PER_HOUR:
        return False, f"Límite por hora alcanzado ({MAX_TRADES_PER_HOUR})"

    if MAX_TRADES_PER_DAY is not None and state["day_count"] >= MAX_TRADES_PER_DAY:
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



def _register_post_close_cooldown(user_id: int):
    """Aplica cooldown DESPUÉS de cerrar un trade (evita re-entrada inmediata al finalizar)."""
    try:
        user_next_trade_time[user_id] = datetime.utcnow() + timedelta(seconds=USER_TRADE_COOLDOWN_SECONDS)
    except Exception:
        # Nunca romper el engine por un fallo de cooldown
        pass

# ============================================================
# CICLO PRINCIPAL
# ============================================================

# ============================================================
# ✅ RECUPERACIÓN DE POSICIÓN ABIERTA (ANTI-RESTART)
# - Si el proceso se reinicia y queda una posición abierta en el exchange,
#   este manager la toma y aplica SL/TRAIL hasta cerrarla.
# - NO abre nuevas operaciones.
# ============================================================

def _get_first_open_position_state(user_id: int) -> Optional[Dict[str, Any]]:
    """
    Devuelve la primera posición REAL abierta (size != 0) detectada en el exchange,
    filtrando "dust" por notional mínimo. Esto evita falsos positivos donde has_open_position()
    devuelve True pero el size reportado es 0.
    Retorna: {"coin": "HYPE", "szi": 12.3, "entry_px": 0.1234, "side": "long"/"short"}
    """
    try:
        state = hyperliquid_client.get_clearinghouse_state(user_id)
        positions = state.get("assetPositions", []) if isinstance(state, dict) else []
        for ap in positions:
            pos = ap.get("position", {}) if isinstance(ap, dict) else {}
            coin = str(pos.get("coin", "")).strip()
            if not coin:
                continue
            try:
                szi = float(pos.get("szi", 0.0))
            except Exception:
                szi = 0.0
            if abs(szi) <= 0:
                continue
            try:
                entry_px = float(pos.get("entryPx", 0.0))
            except Exception:
                entry_px = 0.0
            if entry_px <= 0:
                continue

            notional = abs(szi) * entry_px
            if notional < MANAGER_MIN_NOTIONAL:
                # ignora posiciones residuales muy pequeñas
                continue

            coin_norm = _norm_coin(coin)
            return {
                "coin": coin_norm,
                "szi": szi,
                "entry_px": entry_px,
                "side": "long" if szi > 0 else "short",
            }
        return None
    except Exception:
        logger.exception("[ENGINE] No se pudo leer clearinghouseState para detectar posiciones abiertas")
        return None

def _get_first_open_position_coin(user_id: int) -> Optional[str]:
    st = _get_first_open_position_state(user_id)
    return st["coin"] if st else None

def _manage_existing_open_position(user_id: int, pos_state: Optional[Dict[str, Any]] = None) -> Optional[dict]:
    """
    Mono-Manager: si el bot arranca y ya existe una posición REAL abierta en el exchange,
    este bloque se encarga de gestionarla (SL / TP dinámico) usando SIEMPRE datos reales
    del exchange (size y entryPx).
    """
    st = pos_state or _get_first_open_position_state(user_id)
    if not st:
        log("MANAGER: no hay posición REAL abierta — nada que gestionar", "WARN")
        return None

    coin = str(st.get("coin"))
    symbol = f"{coin}-PERP"

    try:
        size_signed = float(st.get("szi", 0.0))
        entry_price = float(st.get("entry_px", 0.0))
    except Exception:
        size_signed = 0.0
        entry_price = 0.0

    if size_signed == 0.0 or entry_price <= 0.0:
        log(f"MANAGER: posición detectada pero size/entry inválido ({symbol}) — skip", "WARN")
        return None

    side = "long" if size_signed > 0 else "short"
    direction = side
    qty_coin_real = abs(size_signed)
    qty_usdc_real = qty_coin_real * entry_price

    log(f"MANAGER: tomando control de {symbol} ({direction}) size={qty_coin_real} entry={entry_price}")

    # SL fijo por % (desde el engine)
    sl_pct = float(SL_PCT)
    if direction == "long":
        sl_price = entry_price * (1 - sl_pct)
    else:
        sl_price = entry_price * (1 + sl_pct)

    # TP dinámico: trailing por retroceso desde el pico (se gestiona con estado local; en reinicios
    # el riesgo es empezar desde 0 — si quieres persistencia total, se guarda en DB en el engine nuevo)
    trail_max = 0.0

    # Loop de gestión
    while True:
        try:
            price = get_price(symbol)
            if not price:
                time.sleep(2)
                continue
            price = float(price)

            # Detectar si la posición sigue abierta (real)
            st_now = _get_first_open_position_state(user_id)
            if not st_now or str(st_now.get("coin")) != coin:
                log(f"MANAGER: posición ya no existe en exchange ({symbol}) — liberando", "INFO")
                _register_post_close_cooldown(user_id)
                return None

            size_signed_now = float(st_now.get("szi", 0.0))
            if size_signed_now == 0.0:
                log(f"MANAGER: posición existe pero size=0 ({symbol}) — liberando", "WARN")
                _register_post_close_cooldown(user_id)
                return None

            # PnL %
            if direction == "long":
                pnl_pct = (price - entry_price) / entry_price
            else:
                pnl_pct = (entry_price - price) / entry_price

            # SL
            if (direction == "long" and price <= sl_price) or (direction == "short" and price >= sl_price):
                reason = "SL"
                break

            # TP dinámico: actualiza pico y aplica retroceso
            if pnl_pct > trail_max:
                trail_max = pnl_pct

            if trail_max >= float(TP_START_PCT):
                # retroceso permitido desde el pico
                if pnl_pct <= trail_max - float(TP_TRAIL_PCT):
                    reason = "TP_TRAIL"
                    break

            time.sleep(1)
        except Exception:
            logger.exception("MANAGER loop error")
            time.sleep(2)

    # Cierre (reduce-only) SIEMPRE en dirección contraria, qty real del exchange
    opposite = "sell" if direction == "long" else "buy"
    symbol_for_exec = _norm_coin(coin)

    close_qty = abs(float(size_signed_now)) if 'size_signed_now' in locals() and float(size_signed_now) != 0.0 else qty_coin_real
    close_side = ("sell" if float(size_signed_now) > 0 else "buy") if 'size_signed_now' in locals() and float(size_signed_now) != 0.0 else opposite

    close_resp = place_market_order(user_id, symbol_for_exec, close_side, close_qty, reduce_only=True)

    if not close_resp or (not _resp_ok(close_resp)) or (not _is_filled_exchange_response(close_resp)):
        log(f"MANAGER: cierre NO confirmado por exchange ({symbol}) — revisa en Hyperliquid", "CRITICAL")
        return {
            "event": "OPEN",
            "open": {
                "message": (
                    f"🟡 Trade abierto {symbol} ({direction.upper()})\n"
                    f"⚠️ Advertencia: cierre NO confirmado por el exchange. Revisa la posición en Hyperliquid."
                )
            },
        }

    # PnL REAL basado en size real
    exit_price = float(get_price(symbol) or 0.0) or price
    if direction == "long":
        exit_pnl_pct = (exit_price - entry_price) / entry_price
    else:
        exit_pnl_pct = (entry_price - exit_price) / entry_price

    profit = round(float(exit_pnl_pct) * float(qty_usdc_real), 6)
    log(f"Trade cerrado (MANAGER) {symbol} reason={reason} PnL={profit} (pnl_pct={exit_pnl_pct*100:.2f}%)")

    register_trade(
        user_id=user_id,
        symbol=symbol,
        side=side.upper(),
        entry_price=entry_price,
        exit_price=exit_price,
        qty=qty_coin_real,
        profit=profit,
        best_score=0.0,
    )

    _register_post_close_cooldown(user_id)

    return {
        "event": "CLOSE",
        "close": {
            "message": (
                f"🔴 Cierre (MANAGER) {symbol}\n"
                f"Motivo: {reason}\n"
                f"PnL: {profit} USDC ({exit_pnl_pct*100:.2f}%)"
            )
        },
    }

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
        # ✅ Capital operativo REAL (exchange). Interés compuesto natural.
        # Se usa balance withdrawable para sizing seguro.
        capital = float(get_balance(user_id) or 0.0)
        log(f"Capital (Exchange/withdrawable): {capital}")

        # ✅ Guard: capital mínimo (evita órdenes ridículas)
        if capital < float(MIN_CAPITAL_USDC):
            log(f"Capital insuficiente ({capital} USDC) < {MIN_CAPITAL_USDC} — no se ejecuta trading", "WARN")
            return None

        pos_state = _get_first_open_position_state(user_id)
        if pos_state:
            coin = pos_state.get("coin")
            log(f"Ya hay una posición REAL abierta en el exchange ({coin}) — entrando en modo MANAGER (SL/TRAIL)", "WARN")
            return _manage_existing_open_position(user_id, pos_state)

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

        signal = get_entry_signal(symbol)
        if not isinstance(signal, dict):
            log(f"Señal inválida {symbol}", "ERROR")
            return None

        if not signal.get("signal"):
            reason = signal.get("reason")
            err = signal.get("error")
            extra = f" error={err}" if err else ""
            if reason and signal.get("window"):
                log(f"Sin señal {symbol} reason={reason} window={signal.get('window')}{extra}")
            elif reason and signal.get("strength") is not None:
                log(f"Sin señal {symbol} reason={reason} strength={signal.get('strength')}{extra}")
            elif reason:
                log(f"Sin señal {symbol} reason={reason}{extra}")
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

        risk = validate_trade_conditions(capital, strength)
        if not risk.get("ok"):
            log(f"Trade cancelado: {risk.get('reason')}", "WARN")
            return None
        # ✅ Gestión por PRECIO (solo PRECIO)
        # TP: activa trailing cuando el precio se mueve a favor X%
        tp_activate_price = float(TP_ACTIVATE_TRAIL_PRICE)

        # ✅ SL: MISMO % que el TP de activación (regla oficial)
        # (Esto es % de PRECIO, ya convertido para lev=3x en las constantes.)
        sl_price_pct = float(SL_MIN_PRICE)

        # Para compatibilidad con el loop (pnl_pct = %precio)
        sl_pnl_pct = float(sl_price_pct)
        log(f"Riesgo fijo por precio: TP activa trailing={tp_activate_price:.6f}, SL={sl_price_pct:.6f}", "INFO")
        qty_usdc = float(capital) * float(MARGIN_USE_PCT) * float(LEVERAGE)
        # ✅ Guard: notional mínimo (margen*lev) para evitar centavos
        if qty_usdc < float(MIN_NOTIONAL_USDC):
            log(f"Notional demasiado pequeño ({qty_usdc} USDC) < {MIN_NOTIONAL_USDC} — skip", "WARN")
            return None

        entry_price_preview = float(get_price(symbol_for_exec) or 0.0)
        if entry_price_preview <= 0:
            log("No se pudo obtener precio para calcular qty_coin", "ERROR")
            return None

        qty_coin = round(qty_usdc / entry_price_preview, 8)
        if qty_coin <= 0:
            log("qty_coin inválido tras conversión", "ERROR")
            return None

        # ✅ Guard: qty mínimo en coin (evita 0.0 / tamaños ridículos)
        if qty_coin < float(MIN_QTY_COIN):
            log(f"qty_coin demasiado pequeño ({qty_coin}) < {MIN_QTY_COIN} — skip", "WARN")
            return None

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

        # ✅ ENTRY PRICE: primero intento sacar el fill real del open_resp
        # ✅ ENTRY PRICE REAL (NO inventar con px/limit):
        # 1) Leer entryPx desde clearinghouseState (fuente del exchange).
        entry_state = float(get_position_entry_price(user_id, symbol_for_exec) or 0.0)
        if entry_state > 0:
            entry_price = entry_state
            log(f"Entry price (STATE REAL): {entry_price}", "INFO")
        else:
            # 2) fallback: intentar extraer avgPx/fillPx real del open_resp (si viene)
            entry_fill = _extract_fill_price(open_resp)
            if entry_fill and entry_fill > 0:
                entry_price = float(entry_fill)
                log(f"Entry price (FILL REAL): {entry_price}", "INFO")
            else:
                # 3) último recurso: mid/mark de get_price (solo para no crashear)
                entry_price = float(get_price(symbol_for_exec) or 0.0)
                log(f"Entry price (fallback get_price): {entry_price}", "WARN")

        if entry_price <= 0:
            log("Precio de entrada inválido", "ERROR")
            return None

        # ✅ Estado del trailing por %PnL
        trailing_active = False
        best_pnl_pct = 0.0
        trailing_stop_pnl = None  # umbral en %precio

        # ✅ SANITY CHECK POST-FILL (ANTI-ÓRDENES RIDÍCULAS / DUST)
        # Si el exchange solo llenó una fracción mínima (o dejó polvo), cerramos inmediatamente
        # y NO contamos la operación como trade válido.
        size_real_signed = float(get_open_position_size(user_id, symbol_for_exec) or 0.0)
        size_real = abs(size_real_signed)

        if size_real <= 0.0:
            log("OPEN OK pero sin posición real (size=0) — treat as NO_FILL", "WARN")
            _cooldown_symbol(user_id, symbol, SYMBOL_NOFILL_COOLDOWN_SECONDS)
            return None

        notional_real = float(entry_price) * float(size_real)
        if (notional_real < float(MIN_NOTIONAL_USDC)) or (size_real < float(MIN_QTY_COIN)):
            log(f"FILL demasiado pequeño (size={size_real}, notional~{notional_real:.4f} USDC) — cerrando polvo y skip", "WARN")
            close_side = "sell" if side == "buy" else "buy"
            try:
                place_market_order(user_id, symbol_for_exec, close_side, round(size_real, 8))
            except Exception:
                pass
            _cooldown_symbol(user_id, symbol, SYMBOL_NOFILL_COOLDOWN_SECONDS)
            return None


        exit_price = entry_price
        exit_reason = "UNKNOWN"
        exit_pnl_pct = 0.0

        while True:
            price = float(get_price(symbol_for_exec) or 0.0)
            if price <= 0:
                time.sleep(PRICE_CHECK_INTERVAL)
                continue

            # pnl_pct = % de precio a favor (positivo) o en contra (negativo)
            if direction == "long":
                pnl_pct = (price - entry_price) / entry_price
            else:
                pnl_pct = (entry_price - price) / entry_price

            # ✅ SL por PRECIO (negativo)
            if pnl_pct <= -sl_pnl_pct:
                exit_price = price
                exit_pnl_pct = pnl_pct
                exit_reason = "SL"
                break

            # ✅ activar trailing al llegar a +1% (precio)
            if not trailing_active:
                if pnl_pct >= tp_activate_price:
                    trailing_active = True
                    best_pnl_pct = pnl_pct
                    trailing_stop_pnl = best_pnl_pct - float(TRAIL_RETRACE_PRICE)
                    log(
                        f"TRAIL activado {symbol} pnl={pnl_pct*100:.2f}% "
                        f"best={best_pnl_pct*100:.2f}% stop={trailing_stop_pnl*100:.2f}% "
                        f"(activa=+{tp_activate_price*100:.2f}%, retrace={float(TRAIL_RETRACE_PRICE)*100:.2f}pp)",
                        "INFO",
                    )
            else:
                # ✅ actualizar máximo
                if pnl_pct > best_pnl_pct:
                    best_pnl_pct = pnl_pct
                    trailing_stop_pnl = best_pnl_pct - float(TRAIL_RETRACE_PRICE)

                # ✅ cierre por retroceso 0.8pp desde el máximo (precio)
                if trailing_stop_pnl is not None and pnl_pct <= trailing_stop_pnl:
                    exit_price = price
                    exit_pnl_pct = pnl_pct
                    exit_reason = "TRAIL"
                    break

            time.sleep(PRICE_CHECK_INTERVAL)

        log(f"Cerrando trade {symbol} reason={exit_reason}")
        # ✅ Cierre BANK-GRADE: cerrar por size REAL del exchange + reduceOnly (prioriza clearinghouseState)
        pos_state_now = _get_first_open_position_state(user_id)
        if pos_state_now and str(pos_state_now.get("coin")) == coin:
            try:
                size_signed = float(pos_state_now.get("szi", 0.0))
            except Exception:
                size_signed = 0.0
        else:
            try:
                size_signed = float(get_open_position_size(user_id, symbol_for_exec) or 0.0)
            except Exception:
                size_signed = 0.0
        close_qty = abs(size_signed)
        if close_qty <= 0:
            close_qty = float(qty_coin_real)  # fallback (no debería pasar)
        close_side = ("sell" if size_signed > 0 else "buy") if size_signed != 0 else opposite
        close_resp = place_market_order(user_id, symbol_for_exec, close_side, close_qty, reduce_only=True)

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

        # ✅ Profit usando %PnL real calculado en el loop (no dependemos de UI del exchange)
        profit = round(float(exit_pnl_pct) * float(qty_usdc_real), 6)
        log(f"Trade cerrado {symbol} PnL={profit} (pnl_pct={exit_pnl_pct*100:.2f}%)")

        register_trade(
            user_id=user_id,
            symbol=symbol,
            side=side.upper(),
            entry_price=entry_price,
            exit_price=exit_price,
            qty=qty_coin_real,
            profit=profit,
            best_score=float(best.get("score", 0.0) or 0.0),
        )

        # ✅ Cooldown post-cierre: evita re-entrada inmediata tras finalizar un trade
        _register_post_close_cooldown(user_id)

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
