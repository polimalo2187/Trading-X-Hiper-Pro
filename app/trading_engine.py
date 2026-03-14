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
import json
import threading
import traceback
from datetime import datetime, timedelta, date
from typing import Any, Optional
from collections import deque

from app.market_scanner import get_best_symbol
from app.strategy import get_entry_signal, get_trade_management_params
from app.risk import validate_trade_conditions
from app.hyperliquid_client import place_market_order, place_stop_loss, cancel_all_orders_for_symbol, get_price, get_balance, has_open_position, get_position_entry_price, get_open_position_size, make_request, get_recent_closed_pnl, get_last_closed_pnl

from app.database import (
    user_is_ready,
    register_trade,
    add_daily_admin_fee,
    add_weekly_ref_fee,
    get_user_referrer,
    get_user_wallet,
)
import app.database as database_module

from app.config import OWNER_FEE_PERCENT, REFERRAL_FEE_PERCENT

# ============================================================
# CONFIG
# ============================================================

PRICE_CHECK_INTERVAL = 0.4

MIN_TRADE_STRENGTH = 0.18
USER_TRADE_COOLDOWN_SECONDS = 600
# ============================================================
# RISK GOVERNOR (participation control)
# - No toca estrategia ni TP/SL.
# - Solo bloquea NUEVAS entradas cuando el rendimiento reciente es malo.
# ============================================================

USER_RISK_WINDOW = 10
USER_RISK_MAX_CONSEC_LOSSES = 4
USER_RISK_COOLDOWN_SECONDS = 120 * 60  # 2h

USER_RISK_MIN_PF = 0.90  # sobre ventana corta
USER_RISK_PF_WINDOW = 10
USER_RISK_PF_COOLDOWN_SECONDS = 90 * 60  # 1.5h

GLOBAL_RISK_WINDOW = 20
GLOBAL_RISK_MAX_CONSEC_LOSSES = 8
GLOBAL_RISK_COOLDOWN_SECONDS = 45 * 60  # 45m

GLOBAL_RISK_MIN_PF = 0.85
GLOBAL_RISK_PF_WINDOW = 20
GLOBAL_RISK_PF_COOLDOWN_SECONDS = 60 * 60  # 1h

# in-memory state (se reinicia con deploy; suficiente para MVP).
# Persistencia principal en MongoDB; archivo local solo como fallback de emergencia.
_user_risk_state: dict[int, dict[str, Any]] = {}
_global_risk_state: dict[str, Any] = {
    "results": deque(maxlen=GLOBAL_RISK_WINDOW),  # list of (profit: float)
    "consec_losses": 0,
    "cooldown_until": 0.0,
}
_risk_lock = threading.Lock()


def _risk_pf(results: deque) -> float:
    gains = 0.0
    losses = 0.0
    for p in results:
        if p > 0:
            gains += float(p)
        elif p < 0:
            losses += abs(float(p))
    if losses <= 0:
        return float("inf") if gains > 0 else 0.0
    return gains / losses


def _risk_record_close(user_id: int, profit: float) -> None:
    now_ts = time.time()
    with _risk_lock:
        st = _user_risk_state.get(user_id)
        if not st:
            st = {
                "results": deque(maxlen=USER_RISK_WINDOW),
                "consec_losses": 0,
                "cooldown_until": 0.0,
                "cooldown_reason": "",
            }
            _user_risk_state[user_id] = st

        st["results"].append(float(profit))
        if profit < 0:
            st["consec_losses"] = int(st.get("consec_losses", 0)) + 1
        else:
            st["consec_losses"] = 0

        # update global
        _global_risk_state["results"].append(float(profit))
        if profit < 0:
            _global_risk_state["consec_losses"] = int(_global_risk_state.get("consec_losses", 0)) + 1
        else:
            _global_risk_state["consec_losses"] = 0

        # user triggers
        if st["consec_losses"] >= USER_RISK_MAX_CONSEC_LOSSES:
            st["cooldown_until"] = max(float(st.get("cooldown_until") or 0.0), now_ts + USER_RISK_COOLDOWN_SECONDS)
            st["cooldown_reason"] = f"USER_CONSEC_LOSSES_{st['consec_losses']}"
        else:
            # PF trigger only when we have enough samples
            if len(st["results"]) >= USER_RISK_PF_WINDOW:
                pf = _risk_pf(st["results"])
                if pf < USER_RISK_MIN_PF:
                    st["cooldown_until"] = max(float(st.get("cooldown_until") or 0.0), now_ts + USER_RISK_PF_COOLDOWN_SECONDS)
                    st["cooldown_reason"] = f"USER_PF_{pf:.2f}_WIN{len(st['results'])}"

        # global triggers
        if int(_global_risk_state.get("consec_losses", 0)) >= GLOBAL_RISK_MAX_CONSEC_LOSSES:
            _global_risk_state["cooldown_until"] = max(float(_global_risk_state.get("cooldown_until") or 0.0), now_ts + GLOBAL_RISK_COOLDOWN_SECONDS)
            _global_risk_state["cooldown_reason"] = f"GLOBAL_CONSEC_LOSSES_{_global_risk_state['consec_losses']}"
        else:
            if len(_global_risk_state["results"]) >= GLOBAL_RISK_PF_WINDOW:
                pf_g = _risk_pf(_global_risk_state["results"])
                if pf_g < GLOBAL_RISK_MIN_PF:
                    _global_risk_state["cooldown_until"] = max(float(_global_risk_state.get("cooldown_until") or 0.0), now_ts + GLOBAL_RISK_PF_COOLDOWN_SECONDS)
                    _global_risk_state["cooldown_reason"] = f"GLOBAL_PF_{pf_g:.2f}_WIN{len(_global_risk_state['results'])}"


def _risk_governor_allows_new_entries(user_id: int) -> tuple[bool, str]:
    now_ts = time.time()
    with _risk_lock:
        # global first
        g_until = float(_global_risk_state.get("cooldown_until") or 0.0)
        if now_ts < g_until:
            secs = int(g_until - now_ts)
            reason = str(_global_risk_state.get("cooldown_reason") or "GLOBAL_COOLDOWN")
            return False, f"RISK_GOV_GLOBAL_COOLDOWN ({secs}s) {reason}"

        st = _user_risk_state.get(user_id)
        if st:
            u_until = float(st.get("cooldown_until") or 0.0)
            if now_ts < u_until:
                secs = int(u_until - now_ts)
                reason = str(st.get("cooldown_reason") or "USER_COOLDOWN")
                return False, f"RISK_GOV_USER_COOLDOWN ({secs}s) {reason}"

    return True, "OK"


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



# Gestión técnica del manager.
# La lógica de trading (TP dinámico, retrace y pérdida de fuerza)
# la define strategy.py y el engine solo la ejecuta.
TP_FORCE_CHECK_INTERVAL = 15.0      # segundos entre re-evaluaciones de fuerza

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

# ✅ Manager threads por usuario (para NO bloquear el ciclo durante horas)
# Mantiene un watcher por usuario mientras exista una posición abierta.
_user_manager_threads: dict[int, threading.Thread] = {}
_user_manager_meta: dict[int, dict] = {}
_user_manager_guard = threading.Lock()

# Estado en memoria de trades activos para reconciliación post-cierre.
# Esto NO reemplaza la DB; solo evita perder el registro si el manager muere
# o si el exchange cierra la posición fuera del flujo normal del bot.
_user_active_trades: dict[int, dict[str, Any]] = {}
_user_active_trade_guard = threading.Lock()

POSITION_SYNC_INTERVAL = 2.0
ADOPT_EMERGENCY_SL_PCT_RAW = float(os.getenv("ADOPT_EMERGENCY_SL_PCT", "0.012"))  # valor solicitado para ADOPT antes del cap del engine
ADOPT_EMERGENCY_SL_PCT = float(ADOPT_EMERGENCY_SL_PCT_RAW)
ADOPT_STOP_BUFFER_PCT = float(os.getenv("ADOPT_STOP_BUFFER_PCT", "0.003"))  # buffer mínimo vs precio actual para SL adoptado/recuperado
ACTIVE_TRADE_STATE_DIR = os.getenv("ACTIVE_TRADE_STATE_DIR", "runtime_state/active_trades")
ACTIVE_TRADES_COLLECTION = os.getenv("ACTIVE_TRADES_COLLECTION", "active_trades")
ACTIVE_TRADE_STATE_FALLBACK_DIR = os.getenv("ACTIVE_TRADE_STATE_FALLBACK_DIR", ACTIVE_TRADE_STATE_DIR)
ADOPT_RELOG_SECONDS = float(os.getenv("ADOPT_RELOG_SECONDS", "300"))
ADOPT_SL_RECHECK_SECONDS = float(os.getenv("ADOPT_SL_RECHECK_SECONDS", "120"))
STOP_TRIGGER_DECIMALS_FALLBACK = int(os.getenv("STOP_TRIGGER_DECIMALS_FALLBACK", "6"))
STOP_TRIGGER_DECIMALS_MIN = int(os.getenv("STOP_TRIGGER_DECIMALS_MIN", "4"))
STOP_TRIGGER_DECIMALS_MAX = int(os.getenv("STOP_TRIGGER_DECIMALS_MAX", "8"))


# ===============================
# Auditoría de niveles de trade
# ===============================
def _pct_to_abs_price(entry_price: float, pct_value: float, direction: str, *, kind: str) -> float:
    try:
        entry = float(entry_price or 0.0)
        pct = float(pct_value or 0.0)
    except Exception:
        return 0.0
    if entry <= 0 or pct <= 0:
        return 0.0
    d = str(direction or "").lower()
    if kind == "sl":
        return entry * (1.0 - pct) if d == "long" else entry * (1.0 + pct)
    if kind in {"tp_activate", "force_min_profit"}:
        return entry * (1.0 + pct) if d == "long" else entry * (1.0 - pct)
    return 0.0


def _trail_exit_price_from_price(peak_or_trough_price: float, retrace_pct: float, direction: str) -> float:
    try:
        px = float(peak_or_trough_price or 0.0)
        retr = float(retrace_pct or 0.0)
    except Exception:
        return 0.0
    if px <= 0 or retr <= 0:
        return 0.0
    d = str(direction or "").lower()
    return (px * (1.0 - retr)) if d == "long" else (px * (1.0 + retr))


def _log_trade_plan(*, context: str, user_id: int, symbol: str, direction: str, entry_price: float, sl_price_pct: float, tp_activate_price: float, trail_retrace_price: float, force_min_profit_price: float, force_min_strength: float, qty_coin: float = 0.0, notional_usdc: float = 0.0, bucket: str = "") -> None:
    sl_abs = _pct_to_abs_price(entry_price, sl_price_pct, direction, kind="sl")
    tp_abs = _pct_to_abs_price(entry_price, tp_activate_price, direction, kind="tp_activate")
    force_abs = _pct_to_abs_price(entry_price, force_min_profit_price, direction, kind="force_min_profit")
    log(
        f"TRADE_PLAN[{context}] user={user_id} symbol={symbol} dir={direction} "
        f"entry={float(entry_price):.8f} qty_coin={float(qty_coin):.8f} notional~={float(notional_usdc):.4f} "
        f"sl_pct={float(sl_price_pct):.6f} sl_price={sl_abs:.8f} "
        f"tp_activation_pct={float(tp_activate_price):.6f} tp_activation_price={tp_abs:.8f} "
        f"trail_retrace_pct={float(trail_retrace_price):.6f} force_min_profit_pct={float(force_min_profit_price):.6f} "
        f"force_min_profit_price={force_abs:.8f} force_min_strength={float(force_min_strength):.4f} bucket={bucket or 'n/a'}",
        "WARN",
    )



def _active_trade_state_path(user_id: int) -> str:
    safe_user_id = str(int(user_id))
    return os.path.join(ACTIVE_TRADE_STATE_FALLBACK_DIR, f"{safe_user_id}.json")


def _safe_jsonable_dict(payload: Optional[dict[str, Any]]) -> dict[str, Any]:
    base = dict(payload or {})
    try:
        return json.loads(json.dumps(base, ensure_ascii=False, default=str))
    except Exception:
        cleaned: dict[str, Any] = {}
        for k, v in base.items():
            try:
                json.dumps(v, ensure_ascii=False, default=str)
                cleaned[k] = v
            except Exception:
                cleaned[k] = str(v)
        return cleaned


def _resolve_active_trades_collection():
    db_obj = None
    for attr_name in ("db", "database", "mongo_db"):
        candidate = getattr(database_module, attr_name, None)
        if candidate is not None:
            db_obj = candidate
            break

    if db_obj is None:
        for fn_name in ("get_db", "get_database", "get_mongo_db"):
            fn = getattr(database_module, fn_name, None)
            if callable(fn):
                try:
                    candidate = fn()
                    if candidate is not None:
                        db_obj = candidate
                        break
                except Exception as e:
                    log(f"active_trades mongo resolver {fn_name} error: {e}", "WARN")

    if db_obj is None:
        return None

    try:
        return db_obj[ACTIVE_TRADES_COLLECTION]
    except Exception:
        return getattr(db_obj, ACTIVE_TRADES_COLLECTION, None)


def _persist_active_trade_mongo(user_id: int, trade_data: dict[str, Any]) -> bool:
    collection = _resolve_active_trades_collection()
    if collection is None:
        return False
    payload = _safe_jsonable_dict(trade_data)
    payload["user_id"] = int(user_id)
    payload["persisted_at"] = datetime.utcnow().isoformat()
    try:
        collection.update_one(
            {"user_id": int(user_id)},
            {"$set": payload},
            upsert=True,
        )
        return True
    except Exception as e:
        log(f"persist_active_trade_mongo error user={user_id} err={e}", "ERROR")
        return False


def _load_persisted_active_trade_mongo(user_id: int) -> Optional[dict[str, Any]]:
    collection = _resolve_active_trades_collection()
    if collection is None:
        return None
    try:
        doc = collection.find_one({"user_id": int(user_id)})
        if not isinstance(doc, dict):
            return None
        doc.pop("_id", None)
        return _safe_jsonable_dict(doc)
    except Exception as e:
        log(f"load_persisted_active_trade_mongo error user={user_id} err={e}", "WARN")
        return None


def _delete_persisted_active_trade_mongo(user_id: int) -> None:
    collection = _resolve_active_trades_collection()
    if collection is None:
        return
    try:
        collection.delete_one({"user_id": int(user_id)})
    except Exception as e:
        log(f"delete_persisted_active_trade_mongo error user={user_id} err={e}", "WARN")


def _persist_active_trade_fallback_file(user_id: int, trade_data: dict[str, Any]) -> None:
    try:
        os.makedirs(ACTIVE_TRADE_STATE_FALLBACK_DIR, exist_ok=True)
        payload = _safe_jsonable_dict(trade_data)
        payload["user_id"] = int(user_id)
        payload["persisted_at"] = datetime.utcnow().isoformat()
        tmp_path = _active_trade_state_path(user_id) + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, separators=(",", ":"), default=str)
        os.replace(tmp_path, _active_trade_state_path(user_id))
    except Exception as e:
        log(f"persist_active_trade_fallback_file error user={user_id} err={e}", "ERROR")


def _load_persisted_active_trade_fallback_file(user_id: int) -> Optional[dict[str, Any]]:
    try:
        path = _active_trade_state_path(user_id)
        if not os.path.exists(path):
            return None
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return dict(data) if isinstance(data, dict) else None
    except Exception as e:
        log(f"load_persisted_active_trade_fallback_file error user={user_id} err={e}", "WARN")
        return None


def _delete_persisted_active_trade_fallback_file(user_id: int) -> None:
    try:
        path = _active_trade_state_path(user_id)
        if os.path.exists(path):
            os.remove(path)
    except Exception as e:
        log(f"delete_persisted_active_trade_fallback_file error user={user_id} err={e}", "WARN")


def _persist_active_trade_snapshot(user_id: int, trade_data: dict[str, Any]) -> None:
    persisted_in_mongo = _persist_active_trade_mongo(user_id, trade_data)
    if not persisted_in_mongo:
        log(f"active_trade persistence fallback=user={user_id} backend=file", "WARN")
    _persist_active_trade_fallback_file(user_id, trade_data)


def _load_persisted_active_trade_snapshot(user_id: int) -> Optional[dict[str, Any]]:
    mongo_state = _load_persisted_active_trade_mongo(user_id)
    if isinstance(mongo_state, dict):
        return mongo_state
    return _load_persisted_active_trade_fallback_file(user_id)


def _delete_persisted_active_trade_snapshot(user_id: int) -> None:
    _delete_persisted_active_trade_mongo(user_id)
    _delete_persisted_active_trade_fallback_file(user_id)


def _set_active_trade(user_id: int, trade_data: dict[str, Any]) -> None:
    snapshot = dict(trade_data or {})
    with _user_active_trade_guard:
        _user_active_trades[user_id] = snapshot
    _persist_active_trade_snapshot(user_id, snapshot)


def _update_active_trade_fields(user_id: int, **fields: Any) -> None:
    current = _get_active_trade(user_id) or {}
    current.update(fields)
    _set_active_trade(user_id, current)


def _get_active_trade(user_id: int) -> Optional[dict[str, Any]]:
    with _user_active_trade_guard:
        data = _user_active_trades.get(user_id)
        if isinstance(data, dict):
            return dict(data)

    persisted = _load_persisted_active_trade_snapshot(user_id)
    if isinstance(persisted, dict):
        with _user_active_trade_guard:
            _user_active_trades[user_id] = dict(persisted)
        return dict(persisted)

    return None


def _clear_active_trade(user_id: int) -> None:
    with _user_active_trade_guard:
        _user_active_trades.pop(user_id, None)
    _delete_persisted_active_trade_snapshot(user_id)

def _infer_price_decimals(*values: Any) -> int:
    decimals: list[int] = []
    for val in values:
        if val is None:
            continue
        try:
            s = f"{float(val):.12f}"
        except Exception:
            try:
                s = str(val)
            except Exception:
                continue
        if "e" in s.lower():
            try:
                s = f"{float(s):.12f}"
            except Exception:
                continue
        if "." not in s:
            continue
        frac = s.split(".", 1)[1].rstrip("0")
        if frac:
            decimals.append(len(frac))
    if not decimals:
        return max(STOP_TRIGGER_DECIMALS_MIN, min(STOP_TRIGGER_DECIMALS_MAX, STOP_TRIGGER_DECIMALS_FALLBACK))
    inferred = max(decimals)
    return max(STOP_TRIGGER_DECIMALS_MIN, min(STOP_TRIGGER_DECIMALS_MAX, inferred))


def _round_trigger_price(price: float, *, direction: str, decimals: int) -> float:
    factor = 10 ** int(decimals)
    px = float(price or 0.0)
    if px <= 0.0 or factor <= 0:
        return 0.0
    if str(direction).lower() == "short":
        return (int(px * factor + 0.999999999)) / factor
    return (int(px * factor)) / factor


def _build_stop_trigger_candidates(*, raw_trigger: float, current_px: float, direction: str) -> list[float]:
    if raw_trigger <= 0.0:
        return []
    decimals_base = _infer_price_decimals(raw_trigger, current_px)
    candidates: list[float] = []
    seen: set[float] = set()
    for dec in [decimals_base, decimals_base - 1, decimals_base - 2, STOP_TRIGGER_DECIMALS_FALLBACK, 5, 4]:
        if dec < STOP_TRIGGER_DECIMALS_MIN:
            continue
        if dec > STOP_TRIGGER_DECIMALS_MAX:
            dec = STOP_TRIGGER_DECIMALS_MAX
        candidate = _round_trigger_price(raw_trigger, direction=direction, decimals=dec)
        if current_px > 0.0:
            step = 1.0 / (10 ** int(dec))
            buf = max(0.0005, float(ADOPT_STOP_BUFFER_PCT))
            if str(direction).lower() == "short":
                min_valid = float(current_px) * (1.0 + buf)
                if candidate <= min_valid:
                    candidate = _round_trigger_price(min_valid + step, direction=direction, decimals=dec)
            else:
                max_valid = float(current_px) * (1.0 - buf)
                if candidate >= max_valid:
                    candidate = _round_trigger_price(max_valid - step, direction=direction, decimals=dec)
        candidate = float(candidate)
        if candidate > 0.0 and candidate not in seen:
            seen.add(candidate)
            candidates.append(candidate)
    return candidates


def _same_live_position(active_trade: Optional[dict[str, Any]], *, symbol: str, direction: str, entry_price: float) -> bool:
    if not isinstance(active_trade, dict):
        return False
    if str(active_trade.get("symbol") or "") != str(symbol or ""):
        return False
    if str(active_trade.get("direction") or "").lower() != str(direction or "").lower():
        return False
    try:
        stored_entry = float(active_trade.get("entry_price") or 0.0)
        live_entry = float(entry_price or 0.0)
    except Exception:
        return False
    if stored_entry <= 0.0 or live_entry <= 0.0:
        return False
    diff_pct = abs(stored_entry - live_entry) / max(live_entry, 1e-12)
    return diff_pct <= 0.005


def _fetch_frontend_open_orders(user_id: int) -> list[dict[str, Any]]:
    """Lee órdenes abiertas del usuario desde Hyperliquid.
    Usamos frontendOpenOrders porque expone isTrigger/reduceOnly/triggerPx.
    """
    try:
        wallet = get_user_wallet(user_id)
        if not wallet:
            return []
        r = make_request("/info", {"type": "frontendOpenOrders", "user": wallet})
        if isinstance(r, list):
            return [x for x in r if isinstance(x, dict)]
        return []
    except Exception as e:
        log(f"frontendOpenOrders error user={user_id} err={e}", "WARN")
        return []


def _has_live_exchange_stop(user_id: int, symbol_for_exec: str, direction: str) -> bool:
    coin = _norm_coin(symbol_for_exec)
    expected_side = "A" if str(direction).lower() == "long" else "B"
    orders = _fetch_frontend_open_orders(user_id)
    for od in orders:
        try:
            if _norm_coin(str(od.get("coin") or "")) != coin:
                continue
            if not bool(od.get("isTrigger")):
                continue
            if not bool(od.get("reduceOnly")):
                continue
            if str(od.get("side") or "").upper() != expected_side:
                continue
            trig = float(od.get("triggerPx") or 0.0)
            if trig <= 0.0:
                continue
            return True
        except Exception:
            continue
    return False


def _ensure_exchange_stop_loss(
    *,
    user_id: int,
    symbol: str,
    symbol_for_exec: str,
    direction: str,
    entry_price: float,
    qty_coin: float,
    sl_price_pct: float,
    context: str,
) -> bool:
    try:
        if entry_price <= 0 or qty_coin <= 0 or sl_price_pct <= 0:
            log(
                f"{context}: parámetros inválidos para asegurar SL symbol={symbol} entry={entry_price} qty={qty_coin} sl_pct={sl_price_pct}",
                "ERROR",
            )
            return False

        if _has_live_exchange_stop(user_id, symbol_for_exec, direction):
            log(f"{context}: SL ya existe en exchange para {symbol}", "INFO")
            return True

        raw_entry_trigger = (float(entry_price) * (1.0 - float(sl_price_pct))) if direction == "long" else (float(entry_price) * (1.0 + float(sl_price_pct)))
        current_px = 0.0
        try:
            current_px = float(get_price(symbol_for_exec) or 0.0)
        except Exception:
            current_px = 0.0

        trigger_candidates = _build_stop_trigger_candidates(
            raw_trigger=float(raw_entry_trigger),
            current_px=float(current_px),
            direction=str(direction),
        )
        if not trigger_candidates:
            trigger_candidates = [float(raw_entry_trigger)]

        attempt_errors: list[str] = []
        for idx, sl_trigger in enumerate(trigger_candidates, start=1):
            sl_resp = place_stop_loss(
                user_id=user_id,
                symbol=symbol_for_exec,
                position_side=direction,
                qty=float(qty_coin),
                trigger_price=float(sl_trigger),
            )
            ok = bool(isinstance(sl_resp, dict) and sl_resp.get("ok"))
            if ok:
                log(
                    f"STOP_LOSS_HIT_PLAN[{context}] coin={symbol} dir={direction} entry={float(entry_price):.8f} sl_pct={float(sl_price_pct):.6f} "
                    f"sl_price={float(sl_trigger):.8f} qty={float(qty_coin):.8f} trigger={sl_resp.get('triggerPx')} "
                    f"status={sl_resp.get('reason')} current={current_px if current_px > 0 else 'n/a'} attempts={idx}",
                    "WARN",
                )
                return True

            reason = (sl_resp or {}).get("reason") if isinstance(sl_resp, dict) else "NO_RESP"
            err = (sl_resp or {}).get("error", "") if isinstance(sl_resp, dict) else ""
            attempt_errors.append(f"try{idx}:{float(sl_trigger):.8f}:{reason}:{err}")

        log(
            f"{context}: STOP NO colocado en exchange coin={symbol} dir={direction} trigger_candidates={trigger_candidates} "
            f"raw_entry_trigger~{raw_entry_trigger:.8f} current~{current_px:.8f} attempts={' | '.join(attempt_errors)}",
            "CRITICAL",
        )
        return False
    except Exception as e:
        log(f"{context}: STOP ERROR inesperado coin={symbol} dir={direction} err={e}", "CRITICAL")
        return False


def _manager_is_running(user_id: int) -> bool:
    with _user_manager_guard:
        th = _user_manager_threads.get(user_id)
        return bool(th and th.is_alive())

def _start_manager_thread(
    *,
    user_id: int,
    symbol: str,
    symbol_for_exec: str,
    direction: str,
    side: str,
    opposite: str,
    entry_price: float,
    qty_coin_for_log: float,
    qty_usdc_for_profit: float,
    best_score: float,
    entry_strength: float,
    mode: str,
    sl_price_pct: float = 0.0,
    mgmt: Optional[dict[str, Any]] = None,
) -> bool:
    """Arranca un manager en background si no existe uno vivo para el usuario.
    Retorna True si se creó, False si ya había uno corriendo.
    """
    with _user_manager_guard:
        existing = _user_manager_threads.get(user_id)
        if existing and existing.is_alive():
            # Ya hay manager corriendo
            return False

        def _runner():
            try:
                _user_manager_meta[user_id] = {
                    "symbol": symbol,
                    "mode": mode,
                    "started_at": datetime.utcnow().isoformat(),
                }
                _manage_trade_until_close(
                    user_id=user_id,
                    symbol=symbol,
                    symbol_for_exec=symbol_for_exec,
                    direction=direction,
                    side=side,
                    opposite=opposite,
                    entry_price=float(entry_price),
                    qty_coin_for_log=float(qty_coin_for_log),
                    qty_usdc_for_profit=float(qty_usdc_for_profit),
                    best_score=float(best_score),
                    entry_strength=float(entry_strength),
                    mode=mode,
                    sl_price_pct=float(sl_price_pct),
                    mgmt=mgmt,
                )
            except Exception as e:
                log(f"MANAGER THREAD error user={user_id} symbol={symbol} err={e}\n{traceback.format_exc()}", "CRITICAL")
            finally:
                with _user_manager_guard:
                    _user_manager_threads.pop(user_id, None)
                    _user_manager_meta.pop(user_id, None)

        _set_active_trade(user_id, {
            "symbol": symbol,
            "symbol_for_exec": symbol_for_exec,
            "direction": direction,
            "side": side,
            "opposite": opposite,
            "entry_price": float(entry_price),
            "qty_coin_for_log": float(qty_coin_for_log),
            "qty_usdc_for_profit": float(qty_usdc_for_profit),
            "best_score": float(best_score),
            "entry_strength": float(entry_strength),
            "mode": mode,
            "sl_price_pct": float(sl_price_pct),
            "started_at": datetime.utcnow().isoformat(),
            "tp_activation_price": float((mgmt or {}).get("tp_activate_price", (mgmt or {}).get("tp_activation_price", 0.0)) or 0.0),
            "trail_retrace_price": float((mgmt or {}).get("trail_retrace_price", 0.0) or 0.0),
            "force_min_profit_price": float((mgmt or {}).get("force_min_profit_price", 0.0) or 0.0),
            "force_min_strength": float((mgmt or {}).get("force_min_strength", 0.0) or 0.0),
            "partial_tp_activation_price": float((mgmt or {}).get("partial_tp_activation_price", 0.0) or 0.0),
            "partial_tp_close_fraction": float((mgmt or {}).get("partial_tp_close_fraction", 0.0) or 0.0),
            "break_even_activation_price": float((mgmt or {}).get("break_even_activation_price", 0.0) or 0.0),
            "break_even_offset_price": float((mgmt or {}).get("break_even_offset_price", 0.0) or 0.0),
            "bucket": str((mgmt or {}).get("bucket", "")),
            "partial_tp_taken": False,
            "break_even_armed": False,
            "trailing_active": False,
            "best_pnl_pct": 0.0,
            "trailing_stop_pnl": None,
            "peak_price": float(entry_price),
            "last_price": float(entry_price),
            "last_pnl_pct": 0.0,
            "strength_check_ts": 0.0,
            "manager_heartbeat_ts": time.time(),
            "close_in_progress": False,
            "close_finalized": False,
        })

        th = threading.Thread(target=_runner, name=f"mgr-{user_id}", daemon=True)
        _user_manager_threads[user_id] = th
        th.start()
        return True


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

def _get_first_open_position_coin(user_id: int) -> Optional[str]:
    """Devuelve el primer coin con posición REAL abierta (szi != 0) en HL."""
    try:
        wallet = get_user_wallet(user_id)
        if not wallet:
            return None

        r = make_request("/info", {"type": "clearinghouseState", "user": wallet})
        if not isinstance(r, dict):
            return None

        aps = r.get("assetPositions") or []
        if not isinstance(aps, list):
            return None

        for ap in aps:
            if not isinstance(ap, dict):
                continue
            pos = ap.get("position")
            if not isinstance(pos, dict):
                continue

            coin = (pos.get("coin") or ap.get("coin") or "").strip().upper()
            if not coin:
                continue

            try:
                szi = float(pos.get("szi", 0) or 0.0)
            except Exception:
                szi = 0.0

            if szi == 0.0:
                continue

            # Filtro de polvo (best-effort): si no podemos estimar notional, igual lo devolvemos por seguridad.
            try:
                px = float(get_price(coin) or 0.0)
            except Exception:
                px = 0.0

            if px > 0:
                notional = abs(szi) * px
                # si es extremadamente pequeño, lo ignoramos (el cliente ya intenta limpiar dust)
                if notional < float(MIN_NOTIONAL_USDC) * 0.25:
                    continue

            return _norm_coin(coin)

        return None
    except Exception:
        return None



def _extract_strategy_management_params(src: Optional[dict[str, Any]]) -> Optional[dict[str, float]]:
    if not isinstance(src, dict):
        return None

    try:
        tp_activate = float(src.get("tp_activation_price", src.get("tp_activate_price", 0.0)) or 0.0)
        trail_retrace = float(src.get("trail_retrace_price", 0.0) or 0.0)
        force_min_profit = float(src.get("force_min_profit_price", 0.0) or 0.0)
        force_min_strength = float(src.get("force_min_strength", 0.0) or 0.0)
        partial_tp_activation = float(src.get("partial_tp_activation_price", 0.0) or 0.0)
        partial_tp_close_fraction = float(src.get("partial_tp_close_fraction", 0.0) or 0.0)
        break_even_activation = float(src.get("break_even_activation_price", 0.0) or 0.0)
        break_even_offset = float(src.get("break_even_offset_price", 0.0) or 0.0)
        bucket = str(src.get("mgmt_bucket") or src.get("bucket") or "strategy")
    except Exception:
        return None

    if tp_activate <= 0.0 or trail_retrace <= 0.0 or force_min_profit <= 0.0 or force_min_strength <= 0.0:
        return None

    if partial_tp_activation <= 0.0:
        partial_tp_activation = max(0.0, tp_activate * 0.84)
    if partial_tp_close_fraction <= 0.0:
        partial_tp_close_fraction = 0.42
    if break_even_activation <= 0.0:
        break_even_activation = max(partial_tp_activation + 0.0003, tp_activate * 0.96)
    if break_even_offset <= 0.0:
        break_even_offset = 0.0008

    return {
        "bucket": bucket,
        "tp_activate_price": tp_activate,
        "trail_retrace_price": trail_retrace,
        "force_min_profit_price": force_min_profit,
        "force_min_strength": force_min_strength,
        "partial_tp_activation_price": partial_tp_activation,
        "partial_tp_close_fraction": partial_tp_close_fraction,
        "break_even_activation_price": break_even_activation,
        "break_even_offset_price": break_even_offset,
    }


def _disabled_management_params() -> dict[str, float]:
    # Si no hay parámetros strategy-driven disponibles, el engine no inventa
    # una lógica de salida propia. Solo deja el SL del exchange como protección.
    return {
        "bucket": "exchange_only",
        "tp_activate_price": 999999.0,
        "trail_retrace_price": 0.0,
        "force_min_profit_price": 999999.0,
        "force_min_strength": 0.0,
        "partial_tp_activation_price": 999999.0,
        "partial_tp_close_fraction": 0.0,
        "break_even_activation_price": 999999.0,
        "break_even_offset_price": 0.0,
    }


def _coalesce_management_params(
    *,
    signal: Optional[dict[str, Any]] = None,
    active_trade: Optional[dict[str, Any]] = None,
    entry_strength: float = 0.0,
    best_score: float = 0.0,
) -> dict[str, float]:
    mgmt = _extract_strategy_management_params(signal)
    if mgmt is not None:
        return mgmt

    mgmt = _extract_strategy_management_params(active_trade)
    if mgmt is not None:
        return mgmt

    try:
        derived = get_trade_management_params(float(entry_strength or 0.0), float(best_score or 0.0))
    except Exception as e:
        log(f"coalesce_management_params derive error strength={entry_strength} score={best_score} err={e}", "WARN")
        derived = None

    mgmt = _extract_strategy_management_params(derived)
    if mgmt is not None:
        return mgmt

    return _disabled_management_params()


def _should_close_on_strength_loss(

    *,
    symbol: str,
    direction: str,
    pnl_pct: float,
    entry_strength: float,
    force_min_profit_price: float,
    force_min_strength: float,
    last_check_ts: float,
) -> tuple[bool, str, float, float]:
    """Re-evalúa la estrategia abierta con umbrales definidos por estrategia."""
    _ = entry_strength
    now_ts = time.time()
    if (now_ts - float(last_check_ts)) < float(TP_FORCE_CHECK_INTERVAL):
        return False, "", 0.0, last_check_ts

    if float(pnl_pct) < float(force_min_profit_price):
        return False, "", 0.0, now_ts

    sig = get_entry_signal(symbol)
    if not isinstance(sig, dict):
        return False, "", 0.0, now_ts

    same_dir = str(sig.get("direction") or "").lower() == str(direction or "").lower()
    live_strength = float(sig.get("strength", 0.0) or 0.0)
    min_strength = max(float(force_min_strength or 0.0), 0.0)

    if (not sig.get("signal")):
        reason = str(sig.get("reason") or "WEAKNESS")
        if reason.startswith("NO_TREND_1H") or reason.startswith("NO_STRUCTURE_1H") or reason.startswith("TIMING_5M"):
            return True, f"FORCE_LOSS_{reason}", live_strength, now_ts
        return False, "", live_strength, now_ts

    if not same_dir:
        return True, "FORCE_LOSS_DIRECTION_FLIP", live_strength, now_ts

    if live_strength <= min_strength:
        return True, f"FORCE_LOSS_STRENGTH_{live_strength:.4f}", live_strength, now_ts

    return False, "", live_strength, now_ts


def _read_last_realized_pnl(user_id: int, symbol: str) -> Optional[float]:
    try:
        diag_pnl = get_last_closed_pnl(user_id, symbol, lookback_ms=2 * 60 * 60 * 1000)
        net = float(diag_pnl.get("net") or 0.0)
        if abs(net) > 0.0:
            log(
                f"PnL_REAL {symbol}={round(net, 6)} (fills={diag_pnl.get('fills',0)} fees={diag_pnl.get('fees',0)})",
                "INFO",
            )
            return round(net, 6)
    except Exception as e:
        log(f"No se pudo leer PnL REAL para {symbol}: {e}", "WARN")
    return None


def _register_trade_safe(
    *,
    user_id: int,
    symbol: str,
    direction: str,
    side: str,
    entry_price: float,
    exit_price: float,
    qty: float,
    profit: float,
    exit_reason: str,
    best_score: float,
) -> None:
    errs = []
    try:
        register_trade(
            user_id=user_id,
            symbol=symbol,
            side=side.upper(),
            entry_price=float(entry_price),
            exit_price=float(exit_price),
            qty=float(qty),
            profit=float(profit),
            best_score=float(best_score),
        )
        return
    except Exception as e:
        errs.append(f"kw_sig:{e}")

    try:
        register_trade(
            user_id,
            symbol,
            direction,
            float(entry_price),
            float(exit_price),
            float(qty),
            float(profit),
            exit_reason,
        )
        return
    except Exception as e:
        errs.append(f"legacy_sig:{e}")

    raise RuntimeError(" | ".join(errs))


def _finalize_trade_close(
    *,
    user_id: int,
    symbol: str,
    direction: str,
    side: str,
    entry_price: float,
    exit_price: float,
    qty_coin: float,
    qty_usdc_for_profit: float,
    best_score: float,
    exit_reason: str,
    exit_pnl_pct: float,
    source: str,
) -> float:
    guard_snapshot = _try_begin_trade_finalize(user_id, source)
    if guard_snapshot is None:
        log(f"Skip duplicate trade close user={user_id} symbol={symbol} src={source}", "WARN")
        return 0.0

    profit = _read_last_realized_pnl(user_id, symbol)
    if profit is None:
        profit = round(float(exit_pnl_pct) * float(qty_usdc_for_profit), 6)
        log(
            f"Trade cerrado ({source}) {symbol} PnL_FALLBACK={profit} (pnl_pct={float(exit_pnl_pct)*100:.2f}% reason={exit_reason})",
            "WARN",
        )
    else:
        log(f"Trade cerrado ({source}) {symbol} PnL_REAL={profit} reason={exit_reason}", "INFO")

    try:
        _register_trade_safe(
            user_id=user_id,
            symbol=symbol,
            direction=direction,
            side=side,
            entry_price=float(entry_price),
            exit_price=float(exit_price),
            qty=float(qty_coin),
            profit=float(profit),
            exit_reason=str(exit_reason),
            best_score=float(best_score),
        )
    except Exception as e:
        log(f"register_trade error {symbol} src={source} err={e}", "ERROR")

    try:
        _risk_record_close(user_id, profit)
    except Exception as e:
        log(f"risk_record_close error {symbol} src={source} err={e}", "ERROR")

    _register_post_close_cooldown(user_id)

    try:
        admin_fee = max(float(profit), 0.0) * float(OWNER_FEE_PERCENT or 0.0)
        referrer_id = get_user_referrer(user_id)
        if referrer_id and admin_fee > 0:
            ref_fee = admin_fee * float(REFERRAL_FEE_PERCENT or 0.0)
            add_weekly_ref_fee(referrer_id, ref_fee)
            admin_fee -= ref_fee
        if admin_fee > 0:
            add_daily_admin_fee(user_id, admin_fee)
    except Exception as e:
        log(f"fee calc error {symbol} src={source} err={e}", "ERROR")

    try:
        _update_active_trade_fields(
            user_id,
            close_in_progress=False,
            close_finalized=True,
            close_finished_at=time.time(),
            close_reason=str(exit_reason),
            close_profit=float(profit),
        )
    except Exception as e:
        log(f"active_trade finalize mark error {symbol} src={source} err={e}", "WARN")

    _clear_active_trade(user_id)
    return float(profit)


def _ensure_manager_watchdog(user_id: int) -> Optional[dict]:
    active = _get_active_trade(user_id)
    if not active:
        return None
    if _manager_is_running(user_id):
        return None

    try:
        still_open = bool(has_open_position(user_id))
    except Exception as e:
        log(f"WATCHDOG has_open_position error user={user_id} err={e}", "WARN")
        return None

    if not still_open:
        return None

    symbol = str(active.get("symbol") or "")
    symbol_for_exec = str(active.get("symbol_for_exec") or _norm_coin(symbol))
    direction = str(active.get("direction") or "")
    side = str(active.get("side") or "")
    opposite = str(active.get("opposite") or ("sell" if side == "buy" else "buy"))
    entry_price = float(active.get("entry_price") or 0.0)
    qty_coin_for_log = float(active.get("qty_coin_for_log") or 0.0)
    qty_usdc_for_profit = float(active.get("qty_usdc_for_profit") or 0.0)
    best_score = float(active.get("best_score") or 0.0)
    entry_strength = float(active.get("entry_strength") or 0.0)
    sl_price_pct = float(active.get("sl_price_pct") or 0.0)
    mgmt = _coalesce_management_params(active_trade=active, entry_strength=entry_strength, best_score=best_score)

    log(f"WATCHDOG: manager muerto; relanzando user={user_id} symbol={symbol}", "CRITICAL")
    started = _start_manager_thread(
        user_id=user_id,
        symbol=symbol,
        symbol_for_exec=symbol_for_exec,
        direction=direction,
        side=side,
        opposite=opposite,
        entry_price=entry_price,
        qty_coin_for_log=qty_coin_for_log,
        qty_usdc_for_profit=qty_usdc_for_profit,
        best_score=best_score,
        entry_strength=entry_strength,
        mode=str(active.get("mode") or "WATCHDOG"),
        sl_price_pct=sl_price_pct,
        mgmt=mgmt,
    )
    return {"event": "MANAGER_WATCHDOG", "manager": {"symbol": symbol, "started": started}}


def _reconcile_orphan_closed_trade(user_id: int) -> bool:
    active = _get_active_trade(user_id)
    if not active:
        return False

    try:
        still_open = bool(has_open_position(user_id))
    except Exception as e:
        log(f"No se pudo reconciliar has_open_position user={user_id} err={e}", "WARN")
        return False

    if still_open:
        return False

    symbol = str(active.get("symbol") or "")
    entry_price = float(active.get("entry_price") or 0.0)
    qty_usdc_for_profit = float(active.get("qty_usdc_for_profit") or 0.0)
    qty_coin_for_log = float(active.get("qty_coin_for_log") or 0.0)
    direction = str(active.get("direction") or "")
    side = str(active.get("side") or "")
    best_score = float(active.get("best_score") or 0.0)
    symbol_for_exec = str(active.get("symbol_for_exec") or _norm_coin(symbol))

    exit_price = float(get_price(symbol_for_exec) or entry_price or 0.0)
    exit_pnl_pct = 0.0
    if entry_price > 0 and exit_price > 0:
        if direction == "long":
            exit_pnl_pct = (exit_price - entry_price) / entry_price
        elif direction == "short":
            exit_pnl_pct = (entry_price - exit_price) / entry_price

    log(f"RECONCILE: posición cerrada en exchange sin cierre interno previo user={user_id} symbol={symbol}", "CRITICAL")
    _finalize_trade_close(
        user_id=user_id,
        symbol=symbol,
        direction=direction,
        side=side,
        entry_price=entry_price,
        exit_price=exit_price,
        qty_coin=float(qty_coin_for_log),
        qty_usdc_for_profit=float(qty_usdc_for_profit),
        best_score=best_score,
        exit_reason="EXCHANGE_SYNC_CLOSE",
        exit_pnl_pct=float(exit_pnl_pct),
        source="RECONCILE",
    )
    return True


def _attempt_partial_take_profit(*, user_id: int, symbol: str, symbol_for_exec: str, direction: str, opposite: str, close_fraction: float) -> bool:
    try:
        size_signed = float(get_open_position_size(user_id, symbol_for_exec) or 0.0)
    except Exception:
        size_signed = 0.0
    if size_signed == 0.0:
        return False
    qty = abs(size_signed) * float(close_fraction)
    qty = round(float(qty), 8)
    if qty < float(MIN_QTY_COIN):
        return False
    try:
        resp = place_market_order(user_id, symbol_for_exec, opposite, qty, reduce_only=True)
    except Exception as e:
        log(f"PARTIAL_TP error user={user_id} symbol={symbol} err={e}", "ERROR")
        return False
    if not resp or (not _resp_ok(resp)) or (not _is_filled_exchange_response(resp)):
        log(f"PARTIAL_TP no fill user={user_id} symbol={symbol} resp={resp}", "WARN")
        return False
    log(f"PARTIAL_TP_FILLED user={user_id} symbol={symbol} dir={direction} close_fraction={float(close_fraction):.4f} qty={qty:.8f}", "WARN")
    return True


def _arm_break_even_stop(*, user_id: int, symbol: str, symbol_for_exec: str, direction: str, entry_price: float, break_even_offset_price: float) -> bool:
    try:
        size_signed = float(get_open_position_size(user_id, symbol_for_exec) or 0.0)
    except Exception:
        size_signed = 0.0
    qty = abs(size_signed)
    if qty <= 0.0:
        return False
    try:
        cancel_all_orders_for_symbol(user_id, symbol_for_exec)
    except Exception:
        pass
    ok = _ensure_exchange_stop_loss(
        user_id=user_id,
        symbol=symbol,
        symbol_for_exec=symbol_for_exec,
        direction=direction,
        entry_price=float(entry_price),
        qty_coin=float(qty),
        sl_price_pct=float(break_even_offset_price),
        context="BREAK_EVEN",
    )
    if ok:
        be_abs = _pct_to_abs_price(entry_price, float(break_even_offset_price), direction, kind="force_min_profit")
        log(f"BREAK_EVEN_ARMED user={user_id} symbol={symbol} dir={direction} be_offset_pct={float(break_even_offset_price):.6f} break_even_price={be_abs:.8f}", "WARN")
    return ok


def _manage_trade_until_close(
    *,
    user_id: int,
    symbol: str,
    symbol_for_exec: str,
    direction: str,
    side: str,
    opposite: str,
    entry_price: float,
    qty_coin_for_log: float,
    qty_usdc_for_profit: float,
    best_score: float,
    entry_strength: float,
    mode: str,
    sl_price_pct: float | None = None,
    mgmt: Optional[dict[str, Any]] = None,
) -> None:
    """Gestiona una posición (SL + trailing) hasta cerrarla. Corre en thread daemon.
    mode: 'NEW' o 'ADOPT' para logs.
    """
    # Aceptamos sl_price_pct para compatibilidad con el launcher del manager.
    # El stop real sigue viviendo en el exchange; aquí no cambiamos la lógica de cierre.
    _ = sl_price_pct
    mgmt = _coalesce_management_params(active_trade=_get_active_trade(user_id), entry_strength=float(entry_strength), best_score=float(best_score)) if mgmt is None else _coalesce_management_params(signal=mgmt, entry_strength=float(entry_strength), best_score=float(best_score))
    tp_activate_price = float(mgmt["tp_activate_price"])
    trail_retrace_price = float(mgmt["trail_retrace_price"])
    strategy_managed = str(mgmt.get("bucket") or "") != "exchange_only"

    # El stop real vive en el exchange; el manager no usa un SL interno fijo para evitar inconsistencias.
    log(
        f"🧠 MANAGER[{mode}] start user={user_id} {symbol} dir={direction} "
        f"entry={entry_price} qty_coin~{qty_coin_for_log} notional~{qty_usdc_for_profit:.4f} "
        f"(bucket={mgmt['bucket']}, partial_tp={float(mgmt.get('partial_tp_activation_price', 0.0)):.6f}, TP_activa={tp_activate_price:.6f}, retrace={trail_retrace_price:.6f}, "
        f"be_act={float(mgmt.get('break_even_activation_price', 0.0)):.6f}, be_offset={float(mgmt.get('break_even_offset_price', 0.0)):.6f}, "
        f"force_min_profit={float(mgmt['force_min_profit_price']):.6f}, force_min_strength={float(mgmt['force_min_strength']):.4f})",
        "WARN",
    )
    _log_trade_plan(
        context=f"MANAGER_{mode}",
        user_id=user_id,
        symbol=symbol,
        direction=direction,
        entry_price=float(entry_price),
        sl_price_pct=float((_get_active_trade(user_id) or {}).get("sl_price_pct", sl_price_pct or 0.0) or 0.0),
        tp_activate_price=float(tp_activate_price),
        trail_retrace_price=float(trail_retrace_price),
        force_min_profit_price=float(mgmt["force_min_profit_price"]),
        force_min_strength=float(mgmt["force_min_strength"]),
        qty_coin=float(qty_coin_for_log),
        notional_usdc=float(qty_usdc_for_profit),
        bucket=str(mgmt.get("bucket", "")),
    )

    active_runtime = _get_active_trade(user_id) or {}
    trailing_active = bool(active_runtime.get("trailing_active", False))
    partial_tp_taken = bool(active_runtime.get("partial_tp_taken", False))
    break_even_armed = bool(active_runtime.get("break_even_armed", False))
    partial_tp_activation_price = float((active_runtime.get("partial_tp_activation_price", mgmt.get("partial_tp_activation_price", 0.0)) or 0.0))
    partial_tp_close_fraction = float((active_runtime.get("partial_tp_close_fraction", mgmt.get("partial_tp_close_fraction", 0.0)) or 0.0))
    break_even_activation_price = float((active_runtime.get("break_even_activation_price", mgmt.get("break_even_activation_price", 0.0)) or 0.0))
    break_even_offset_price = float((active_runtime.get("break_even_offset_price", mgmt.get("break_even_offset_price", 0.0)) or 0.0))
    best_pnl_pct = float(active_runtime.get("best_pnl_pct", 0.0) or 0.0)
    trailing_stop_pnl = active_runtime.get("trailing_stop_pnl", None)
    try:
        trailing_stop_pnl = float(trailing_stop_pnl) if trailing_stop_pnl is not None else None
    except Exception:
        trailing_stop_pnl = None
    peak_price = float(active_runtime.get("peak_price", entry_price) or entry_price)
    strength_check_ts = float(active_runtime.get("strength_check_ts", 0.0) or 0.0)
    last_pos_sync_ts = 0.0
    last_runtime_flush_ts = 0.0

    if trailing_active:
        log(
            f"MANAGER[{mode}] restored runtime user={user_id} symbol={symbol} trailing_active={trailing_active} "
            f"best_pnl_pct={best_pnl_pct:.6f} trailing_stop_pnl={float(trailing_stop_pnl or 0.0):.6f} peak_price={peak_price:.8f}",
            "WARN",
        )

    _update_active_trade_fields(
        user_id,
        trailing_active=bool(trailing_active),
        best_pnl_pct=float(best_pnl_pct),
        trailing_stop_pnl=trailing_stop_pnl,
        peak_price=float(peak_price),
        last_price=float(entry_price),
        last_pnl_pct=0.0,
        strength_check_ts=float(strength_check_ts),
        manager_heartbeat_ts=time.time(),
    )

    exit_price = entry_price
    exit_reason = "UNKNOWN"
    exit_pnl_pct = 0.0

    while True:
        now_ts = time.time()
        if (now_ts - float(last_pos_sync_ts)) >= float(POSITION_SYNC_INTERVAL):
            last_pos_sync_ts = now_ts
            try:
                live_size_signed = float(get_open_position_size(user_id, symbol_for_exec) or 0.0)
            except Exception as e:
                live_size_signed = None
                log(f"MANAGER[{mode}] sync size error {symbol} err={e}", "WARN")

            if live_size_signed == 0.0:
                exit_reason = "EXCHANGE_POSITION_CLOSED"
                exit_price = float(get_price(symbol_for_exec) or entry_price or 0.0)
                if entry_price > 0 and exit_price > 0:
                    if direction == "long":
                        exit_pnl_pct = (exit_price - entry_price) / entry_price
                    else:
                        exit_pnl_pct = (entry_price - exit_price) / entry_price
                sl_abs = _pct_to_abs_price(entry_price, float((_get_active_trade(user_id) or {}).get("sl_price_pct", sl_price_pct or 0.0) or 0.0), direction, kind="sl")
                log(
                    f"EXCHANGE_POSITION_CLOSED[{mode}] user={user_id} symbol={symbol} dir={direction} entry={float(entry_price):.8f} "
                    f"observed_exit_price={float(exit_price):.8f} observed_pnl_pct={float(exit_pnl_pct):.6f} configured_sl_price={sl_abs:.8f}",
                    "CRITICAL",
                )
                break

        price = float(get_price(symbol_for_exec) or 0.0)
        if price <= 0:
            time.sleep(PRICE_CHECK_INTERVAL)
            continue

        if direction == "long":
            pnl_pct = (price - entry_price) / entry_price
        else:
            pnl_pct = (entry_price - price) / entry_price

        if (now_ts - float(last_runtime_flush_ts)) >= float(max(POSITION_SYNC_INTERVAL, 2.0)):
            last_runtime_flush_ts = now_ts
            _update_active_trade_fields(
                user_id,
                last_price=float(price),
                last_pnl_pct=float(pnl_pct),
                trailing_active=bool(trailing_active),
                partial_tp_taken=bool(partial_tp_taken),
                break_even_armed=bool(break_even_armed),
                best_pnl_pct=float(best_pnl_pct),
                trailing_stop_pnl=(float(trailing_stop_pnl) if trailing_stop_pnl is not None else None),
                peak_price=float(peak_price),
                strength_check_ts=float(strength_check_ts),
                manager_heartbeat_ts=time.time(),
            )

        # El SL de emergencia está en el exchange. Aquí solo gestionamos TP dinámico / trailing.
        should_force_close = False
        force_reason = ""
        live_strength = 0.0
        if strategy_managed:
            should_force_close, force_reason, live_strength, strength_check_ts = _should_close_on_strength_loss(
                symbol=symbol,
                direction=direction,
                pnl_pct=float(pnl_pct),
                entry_strength=float(entry_strength),
                force_min_profit_price=float(mgmt["force_min_profit_price"]),
                force_min_strength=float(mgmt["force_min_strength"]),
                last_check_ts=float(strength_check_ts),
            )
            _update_active_trade_fields(
                user_id,
                strength_check_ts=float(strength_check_ts),
                last_price=float(price),
                last_pnl_pct=float(pnl_pct),
                manager_heartbeat_ts=time.time(),
            )
            if should_force_close:
                exit_price = price
                exit_pnl_pct = pnl_pct
                exit_reason = force_reason
                force_trigger_price = _pct_to_abs_price(entry_price, float(mgmt["force_min_profit_price"]), direction, kind="force_min_profit")
                log(
                    f"FORCE_EXIT[{mode}] user={user_id} symbol={symbol} dir={direction} entry={float(entry_price):.8f} current={float(price):.8f} "
                    f"pnl_pct={pnl_pct:.6f} live_strength={live_strength:.4f} trigger_profit_pct={float(mgmt['force_min_profit_price']):.6f} "
                    f"trigger_profit_price={force_trigger_price:.8f} min_strength={float(mgmt['force_min_strength']):.4f} reason={force_reason}",
                    "WARN",
                )
                break

        if strategy_managed and (not partial_tp_taken) and partial_tp_activation_price > 0.0 and pnl_pct >= partial_tp_activation_price:
            partial_done = _attempt_partial_take_profit(
                user_id=user_id,
                symbol=symbol,
                symbol_for_exec=symbol_for_exec,
                direction=direction,
                opposite=opposite,
                close_fraction=float(partial_tp_close_fraction),
            )
            if partial_done:
                partial_tp_taken = True
                _update_active_trade_fields(
                    user_id,
                    partial_tp_taken=True,
                    last_price=float(price),
                    last_pnl_pct=float(pnl_pct),
                    manager_heartbeat_ts=time.time(),
                )

        if strategy_managed and (not break_even_armed) and break_even_activation_price > 0.0 and pnl_pct >= break_even_activation_price:
            be_done = _arm_break_even_stop(
                user_id=user_id,
                symbol=symbol,
                symbol_for_exec=symbol_for_exec,
                direction=direction,
                entry_price=float(entry_price),
                break_even_offset_price=float(break_even_offset_price),
            )
            if be_done:
                break_even_armed = True
                _update_active_trade_fields(
                    user_id,
                    break_even_armed=True,
                    last_price=float(price),
                    last_pnl_pct=float(pnl_pct),
                    manager_heartbeat_ts=time.time(),
                )

        if strategy_managed and not trailing_active:
            if pnl_pct >= tp_activate_price:
                trailing_active = True
                best_pnl_pct = pnl_pct
                peak_price = float(price)
                trailing_stop_pnl = best_pnl_pct - float(trail_retrace_price)
                trailing_exit_price = _trail_exit_price_from_price(price, float(trail_retrace_price), direction)
                _update_active_trade_fields(
                    user_id,
                    trailing_active=True,
                    partial_tp_taken=bool(partial_tp_taken),
                    break_even_armed=bool(break_even_armed),
                    best_pnl_pct=float(best_pnl_pct),
                    trailing_stop_pnl=float(trailing_stop_pnl),
                    peak_price=float(peak_price),
                    last_price=float(price),
                    last_pnl_pct=float(pnl_pct),
                    strength_check_ts=float(strength_check_ts),
                    manager_heartbeat_ts=time.time(),
                )
                tp_activation_abs = _pct_to_abs_price(entry_price, float(tp_activate_price), direction, kind="tp_activate")
                log(
                    f"TP_ACTIVATED[{mode}] user={user_id} symbol={symbol} dir={direction} entry={float(entry_price):.8f} current={float(price):.8f} "
                    f"tp_activation_pct={float(tp_activate_price):.6f} tp_activation_price={tp_activation_abs:.8f} "
                    f"peak_price={float(price):.8f} trailing_exit_price={trailing_exit_price:.8f} retrace_pct={float(trail_retrace_price):.6f}",
                    "WARN",
                )
        elif strategy_managed:
            if pnl_pct > best_pnl_pct:
                best_pnl_pct = pnl_pct
                peak_price = float(price)
                trailing_stop_pnl = best_pnl_pct - float(trail_retrace_price)
                trailing_exit_price = _trail_exit_price_from_price(price, float(trail_retrace_price), direction)
                _update_active_trade_fields(
                    user_id,
                    trailing_active=True,
                    partial_tp_taken=bool(partial_tp_taken),
                    break_even_armed=bool(break_even_armed),
                    best_pnl_pct=float(best_pnl_pct),
                    trailing_stop_pnl=float(trailing_stop_pnl),
                    peak_price=float(peak_price),
                    last_price=float(price),
                    last_pnl_pct=float(pnl_pct),
                    strength_check_ts=float(strength_check_ts),
                    manager_heartbeat_ts=time.time(),
                )
                log(
                    f"TRAIL_UPDATE[{mode}] user={user_id} symbol={symbol} dir={direction} peak_price={float(price):.8f} "
                    f"best_pnl_pct={best_pnl_pct:.6f} retrace_pct={float(trail_retrace_price):.6f} trailing_exit_price={trailing_exit_price:.8f}",
                    "INFO",
                )

            if trailing_stop_pnl is not None and pnl_pct <= trailing_stop_pnl:
                exit_price = price
                exit_pnl_pct = pnl_pct
                exit_reason = "TRAIL"
                break

        time.sleep(PRICE_CHECK_INTERVAL)

    log(f"Cerrando posición (MANAGER[{mode}]) {symbol} reason={exit_reason}", "WARN")

    # Siempre intentamos cancelar órdenes pendientes (incluye el STOP en exchange si quedó resting).
    try:
        cancel_all_orders_for_symbol(user_id, symbol_for_exec)
    except Exception as e:
        log(f"MANAGER[{mode}] cancel_all_orders error {symbol} err={e}", "ERROR")

    try:
        size_signed_now = float(get_open_position_size(user_id, symbol_for_exec) or 0.0)
    except Exception:
        size_signed_now = 0.0

    # Si ya no hay size, asumimos que el exchange la cerró (por STOP/liq/manual) y registramos el trade.
    if size_signed_now == 0.0:
        log(f"MANAGER[{mode}] {symbol}: size=0 al cerrar — asumiendo ya cerrado en exchange", "WARN")
        _finalize_trade_close(
            user_id=user_id,
            symbol=symbol,
            direction=direction,
            side=side,
            entry_price=float(entry_price),
            exit_price=float(exit_price),
            qty_coin=float(qty_coin_for_log),
            qty_usdc_for_profit=float(qty_usdc_for_profit),
            best_score=float(best_score),
            exit_reason=str(exit_reason),
            exit_pnl_pct=float(exit_pnl_pct),
            source=f"MANAGER[{mode}]_EXCHANGE",
        )
        return

    close_qty = abs(size_signed_now)
    close_side = "sell" if size_signed_now > 0 else "buy"

    close_resp = place_market_order(user_id, symbol_for_exec, close_side, close_qty, reduce_only=True)

    if not close_resp or (not _resp_ok(close_resp)) or (not _is_filled_exchange_response(close_resp)):
        log(f"MANAGER[{mode}]: cierre NO confirmado por exchange ({symbol}) — revisa en Hyperliquid", "CRITICAL")
        return

    # Limpieza: cancelar órdenes pendientes (incluye STOP en exchange) para evitar 'órdenes colgadas'
    try:
        cxl = cancel_all_orders_for_symbol(user_id, symbol_for_exec)
        if isinstance(cxl, dict) and cxl.get("ok"):
            log(f"Órdenes canceladas en exchange para {symbol} (MANAGER[{mode}])", "INFO")
        else:
            log(f"No se pudieron cancelar órdenes para {symbol} (MANAGER[{mode}]) resp={cxl}", "WARN")
    except Exception as e:
        log(f"Error cancelando órdenes para {symbol} (MANAGER[{mode}]) err={e}", "WARN")

    _finalize_trade_close(
        user_id=user_id,
        symbol=symbol,
        direction=direction,
        side=side,
        entry_price=float(entry_price),
        exit_price=float(exit_price),
        qty_coin=float(close_qty),
        qty_usdc_for_profit=float(qty_usdc_for_profit),
        best_score=float(best_score),
        exit_reason=str(exit_reason),
        exit_pnl_pct=float(exit_pnl_pct),
        source=f"MANAGER[{mode}]",
    )

def _manage_existing_open_position(user_id: int) -> Optional[dict]:
    """Adopta una posición ya abierta en el exchange y asegura que el manager esté corriendo en background.
    Evita reprocesar ADOPT completo en cada ciclo cuando la misma posición ya está adoptada.
    """
    coin = _get_first_open_position_coin(user_id)
    if not coin:
        log("has_open_position=True pero no se pudo detectar coin/posición (probable dust) — skip", "WARN")
        return None

    symbol = f"{coin}-PERP"
    symbol_for_exec = _norm_coin(coin)

    try:
        size_signed = float(get_open_position_size(user_id, symbol_for_exec) or 0.0)
    except Exception:
        size_signed = 0.0

    if size_signed == 0.0:
        log(f"Posición detectada pero size=0 ({symbol}) — skip", "WARN")
        return None

    direction = "long" if size_signed > 0 else "short"
    side = "buy" if direction == "long" else "sell"
    opposite = "sell" if side == "buy" else "buy"

    entry_price = float(get_position_entry_price(user_id, symbol_for_exec) or 0.0)
    if entry_price <= 0:
        entry_price = float(get_price(symbol_for_exec) or 0.0)

    if entry_price <= 0:
        log(f"No se pudo determinar entry_price de la posición abierta ({symbol}) — skip", "ERROR")
        return None

    qty_coin_real = abs(float(size_signed))
    qty_usdc_real = float(entry_price) * float(qty_coin_real)

    active_trade = _get_active_trade(user_id)
    manager_running = _manager_is_running(user_id)
    same_position = _same_live_position(active_trade, symbol=symbol, direction=direction, entry_price=float(entry_price))

    adopt_signal = get_entry_signal(symbol)
    adopt_entry_strength = float((active_trade or {}).get("entry_strength", 0.0) or 0.0)
    adopt_best_score = float((active_trade or {}).get("best_score", 0.0) or 0.0)
    adopt_sl_price_pct = float((active_trade or {}).get("sl_price_pct", ADOPT_EMERGENCY_SL_PCT) or ADOPT_EMERGENCY_SL_PCT)
    adopt_mgmt = _coalesce_management_params(
        active_trade=active_trade,
        entry_strength=adopt_entry_strength,
        best_score=adopt_best_score,
    )

    if isinstance(adopt_signal, dict) and adopt_signal.get("signal") and str(adopt_signal.get("direction") or "").lower() == direction:
        adopt_entry_strength = float(adopt_signal.get("strength", adopt_entry_strength) or adopt_entry_strength or 0.0)
        adopt_best_score = float(adopt_signal.get("score", adopt_best_score) or adopt_best_score or 0.0)
        adopt_sl_price_pct = float(adopt_signal.get("sl_price_pct", adopt_sl_price_pct) or adopt_sl_price_pct)
        adopt_mgmt = _coalesce_management_params(
            signal=adopt_signal,
            active_trade=active_trade,
            entry_strength=adopt_entry_strength,
            best_score=adopt_best_score,
        )

    existing_started_at = (active_trade or {}).get("started_at")
    snapshot = {
        "symbol": symbol,
        "symbol_for_exec": symbol_for_exec,
        "direction": direction,
        "side": side,
        "opposite": opposite,
        "entry_price": float(entry_price),
        "qty_coin_for_log": float(qty_coin_real),
        "qty_usdc_for_profit": float(qty_usdc_real),
        "best_score": float(adopt_best_score),
        "entry_strength": float(adopt_entry_strength),
        "mode": "ADOPT",
        "sl_price_pct": float(adopt_sl_price_pct),
        "started_at": existing_started_at or datetime.utcnow().isoformat(),
        "tp_activation_price": float(adopt_mgmt.get("tp_activate_price", 0.0) or 0.0),
        "trail_retrace_price": float(adopt_mgmt.get("trail_retrace_price", 0.0) or 0.0),
        "force_min_profit_price": float(adopt_mgmt.get("force_min_profit_price", 0.0) or 0.0),
        "force_min_strength": float(adopt_mgmt.get("force_min_strength", 0.0) or 0.0),
        "partial_tp_activation_price": float(adopt_mgmt.get("partial_tp_activation_price", 0.0) or 0.0),
        "partial_tp_close_fraction": float(adopt_mgmt.get("partial_tp_close_fraction", 0.0) or 0.0),
        "break_even_activation_price": float(adopt_mgmt.get("break_even_activation_price", 0.0) or 0.0),
        "break_even_offset_price": float(adopt_mgmt.get("break_even_offset_price", 0.0) or 0.0),
        "bucket": str(adopt_mgmt.get("bucket", "")),
        "trailing_active": bool((active_trade or {}).get("trailing_active", False)),
        "best_pnl_pct": float((active_trade or {}).get("best_pnl_pct", 0.0) or 0.0),
        "trailing_stop_pnl": (active_trade or {}).get("trailing_stop_pnl", None),
        "peak_price": float((active_trade or {}).get("peak_price", entry_price) or entry_price),
        "last_price": float((active_trade or {}).get("last_price", entry_price) or entry_price),
        "last_pnl_pct": float((active_trade or {}).get("last_pnl_pct", 0.0) or 0.0),
        "strength_check_ts": float((active_trade or {}).get("strength_check_ts", 0.0) or 0.0),
        "manager_heartbeat_ts": float((active_trade or {}).get("manager_heartbeat_ts", 0.0) or 0.0),
        "adopt_last_seen_ts": time.time(),
        "adopt_plan_logged_at": float((active_trade or {}).get("adopt_plan_logged_at", 0.0) or 0.0),
        "adopt_sl_checked_at": float((active_trade or {}).get("adopt_sl_checked_at", 0.0) or 0.0),
        "sl_in_exchange": bool((active_trade or {}).get("sl_in_exchange", False)),
        "close_in_progress": False,
        "close_finalized": False,
    }
    _set_active_trade(user_id, snapshot)

    now_ts = time.time()
    last_plan_logged_at = float(snapshot.get("adopt_plan_logged_at", 0.0) or 0.0)
    should_log_plan = (not same_position) or (not manager_running) or ((now_ts - last_plan_logged_at) >= float(ADOPT_RELOG_SECONDS))
    if should_log_plan:
        _log_trade_plan(
            context="ADOPT",
            user_id=user_id,
            symbol=symbol,
            direction=direction,
            entry_price=float(entry_price),
            sl_price_pct=float(adopt_sl_price_pct),
            tp_activate_price=float(adopt_mgmt.get("tp_activate_price", 0.0) or 0.0),
            trail_retrace_price=float(adopt_mgmt.get("trail_retrace_price", 0.0) or 0.0),
            force_min_profit_price=float(adopt_mgmt.get("force_min_profit_price", 0.0) or 0.0),
            force_min_strength=float(adopt_mgmt.get("force_min_strength", 0.0) or 0.0),
            qty_coin=float(qty_coin_real),
            notional_usdc=float(qty_usdc_real),
            bucket=str(adopt_mgmt.get("bucket", "")),
        )
        _update_active_trade_fields(user_id, adopt_plan_logged_at=now_ts)

    last_sl_checked_at = float(snapshot.get("adopt_sl_checked_at", 0.0) or 0.0)
    sl_known_ok = bool(snapshot.get("sl_in_exchange", False))
    should_recheck_sl = (not sl_known_ok) or (not same_position) or ((now_ts - last_sl_checked_at) >= float(ADOPT_SL_RECHECK_SECONDS))

    adopt_sl_ok = sl_known_ok
    if should_recheck_sl:
        adopt_sl_ok = _ensure_exchange_stop_loss(
            user_id=user_id,
            symbol=symbol,
            symbol_for_exec=symbol_for_exec,
            direction=direction,
            entry_price=float(entry_price),
            qty_coin=float(qty_coin_real),
            sl_price_pct=float(adopt_sl_price_pct),
            context="ADOPT",
        )
        _update_active_trade_fields(
            user_id,
            sl_in_exchange=bool(adopt_sl_ok),
            adopt_sl_checked_at=now_ts,
        )
        if adopt_sl_ok:
            log(
                f"🛡️ ADOPT protección SL validada user={user_id} symbol={symbol} dir={direction} entry={float(entry_price):.8f} "
                f"sl_pct={float(adopt_sl_price_pct):.6f}",
                "WARN",
            )
        else:
            log(
                f"🛡️ ADOPT NO pudo validar/crear SL user={user_id} symbol={symbol} dir={direction} entry={float(entry_price):.8f} "
                f"sl_pct={float(adopt_sl_price_pct):.6f}",
                "CRITICAL",
            )

    if manager_running and same_position:
        _update_active_trade_fields(user_id, manager_heartbeat_ts=now_ts, adopt_last_seen_ts=now_ts)
        return {"event": "MANAGER", "manager": {"symbol": symbol, "started": False, "already_running": True}}

    started = _start_manager_thread(
        user_id=user_id,
        symbol=symbol,
        symbol_for_exec=symbol_for_exec,
        direction=direction,
        side=side,
        opposite=opposite,
        entry_price=entry_price,
        qty_coin_for_log=qty_coin_real,
        qty_usdc_for_profit=qty_usdc_real,
        best_score=float(adopt_best_score),
        entry_strength=float(adopt_entry_strength),
        mode="ADOPT",
        sl_price_pct=float(adopt_sl_price_pct),
        mgmt=adopt_mgmt,
    )

    if started:
        log(f"MANAGER adoptado en background para {symbol} (user={user_id})", "WARN")
    else:
        log(f"MANAGER ya estaba corriendo para user={user_id} (skip start)", "INFO")

    return {"event": "MANAGER", "manager": {"symbol": symbol, "started": started}}


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

        # Reconciliación defensiva: si el exchange ya no tiene posición pero el bot
        # conserva estado activo en memoria, registramos el cierre y activamos cooldown.
        try:
            if _reconcile_orphan_closed_trade(user_id):
                log(f"Usuario {user_id} — cierre reconciliado desde exchange", "CRITICAL")
                return {"event": "RECONCILE_CLOSED"}
        except Exception as e:
            log(f"Reconcile error user={user_id} err={e}\n{traceback.format_exc()}", "ERROR")

        watchdog_resp = _ensure_manager_watchdog(user_id)
        if watchdog_resp:
            return watchdog_resp

        # ✅ Capital operativo REAL (exchange). Interés compuesto natural.
        # Se usa balance withdrawable para sizing seguro
        capital = float(get_balance(user_id) or 0.0)
        log(f"Capital (Exchange/withdrawable): {capital}")

        # ✅ Si ya existe posición abierta en el exchange, SIEMPRE priorizamos modo MANAGER.
        # Importante: con posiciones abiertas el balance withdrawable puede verse bajo,
        # así que NO debemos bloquear por MIN_CAPITAL_USDC (si no, se pierde la reanudación).
        if has_open_position(user_id):
            log("Ya hay una posición abierta en el exchange — entrando en modo MANAGER (SL/TRAIL)", "WARN")
            return _manage_existing_open_position(user_id)

        # ✅ Guard: capital mínimo (evita órdenes ridículas) — solo aplica cuando NO hay posición abierta
        if capital < float(MIN_CAPITAL_USDC):
            log(f"Capital insuficiente ({capital} USDC) < {MIN_CAPITAL_USDC} — no se ejecuta trading", "WARN")
            return None


        ok_trade, reason_trade = _can_trade_now(user_id)
        if not ok_trade:
            log(f"Bloqueo responsable: {reason_trade}", "INFO")
            return None

        ok_risk, reason_risk = _risk_governor_allows_new_entries(user_id)
        if not ok_risk:
            log(f"Bloqueo responsable: {reason_risk}", "INFO")
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

        log(f"SEÑAL CONFIRMADA {symbol} {direction.upper()} strength={signal.get('strength')} score={signal.get('score')} model={signal.get('strategy_model', 'strategy')}")

        risk = validate_trade_conditions(capital, strength)
        if not risk.get("ok"):
            log(f"Trade cancelado: {risk.get('reason')}", "WARN")
            return None
        mgmt = _coalesce_management_params(signal=signal, entry_strength=float(strength), best_score=float(signal.get("score", 0.0) or 0.0))
        try:
            mgmt["strategy_model"] = str(signal.get("strategy_model", ""))
            mgmt["atr_pct"] = float(signal.get("atr_pct", 0.0) or 0.0)
        except Exception:
            pass
        tp_activate_price = float(mgmt["tp_activate_price"])
        strategy_sl_price_pct = float(signal.get("sl_price_pct", 0.0) or 0.0)
        if strategy_sl_price_pct <= 0.0:
            log("Señal sin sl_price_pct válido", "ERROR")
            return None

        sl_price_pct = float(strategy_sl_price_pct)

        log(
            f"Riesgo dinámico por trade: bucket={mgmt['bucket']} TP activa trailing={tp_activate_price:.6f}, "
            f"retrace={float(mgmt['trail_retrace_price']):.6f}, strategy_sl={strategy_sl_price_pct:.6f}, SL(exchange)={sl_price_pct:.6f}, "
            f"force_min_profit={float(mgmt['force_min_profit_price']):.6f}, force_min_strength={float(mgmt['force_min_strength']):.4f}",
            "INFO",
        )
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
        # ✅ SANITY CHECK POST-FILL (ANTI-ÓRDENES RIDÍCULAS / DUST)
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

        _log_trade_plan(
            context="OPEN",
            user_id=user_id,
            symbol=symbol,
            direction=direction,
            entry_price=float(entry_price),
            sl_price_pct=float(sl_price_pct),
            tp_activate_price=float(mgmt["tp_activate_price"]),
            trail_retrace_price=float(mgmt["trail_retrace_price"]),
            force_min_profit_price=float(mgmt["force_min_profit_price"]),
            force_min_strength=float(mgmt["force_min_strength"]),
            qty_coin=float(size_real),
            notional_usdc=float(notional_real),
            bucket=str(mgmt.get("bucket", "")),
        )

        # ✅ STOP LOSS REAL EN EXCHANGE (BANK GRADE):
        # Se calcula dinámicamente por trade y se coloca en el exchange al abrir.
        _ensure_exchange_stop_loss(
            user_id=user_id,
            symbol=symbol,
            symbol_for_exec=symbol_for_exec,
            direction=direction,
            entry_price=float(entry_price),
            qty_coin=float(size_real),
            sl_price_pct=float(sl_price_pct),
            context="OPEN",
        )

        # ✅ IMPORTANTÍSIMO:
        # No bloqueamos el ciclo gestionando el trade aquí (puede durar horas).
        # Arrancamos un MANAGER en background y devolvemos control al loop.
        started = _start_manager_thread(
            user_id=user_id,
            symbol=symbol,
            symbol_for_exec=symbol_for_exec,
            direction=direction,
            side=side,
            opposite=opposite,
            entry_price=entry_price,
            qty_coin_for_log=float(size_real),
            qty_usdc_for_profit=float(notional_real),
            best_score=float(signal.get("score", 0.0) or 0.0),
            entry_strength=float(strength),
            mode="NEW",
            sl_price_pct=float(sl_price_pct),
            mgmt=mgmt,
        )

        if started:
            log(f"MANAGER iniciado en background para {symbol} (user={user_id})", "WARN")
        else:
            log(f"MANAGER ya estaba corriendo para user={user_id} (skip start)", "INFO")

        return {
            "event": "OPEN",
            "open": {"message": f"🟢 Trade abierto {symbol} ({direction.upper()})"},
            "manager": {"started": started, "symbol": symbol},
        }

    finally:
        try:
            lock.release()
        except Exception:
            pass
