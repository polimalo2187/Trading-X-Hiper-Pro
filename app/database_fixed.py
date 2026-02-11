# ============================================================
# DATABASE – TRADING X HIPER PRO
# Sistema profesional MongoDB Atlas
# PRODUCCIÓN REAL – BLINDADO
# + INTERÉS COMPUESTO (capital Telegram se actualiza automático)
#
# PLANES (SIN FEES / SIN REFERIDOS):
#   - PRUEBA 5 días (vence a medianoche Cuba)
#   - PREMIUM 30 días (vence a medianoche Cuba)
# ============================================================

from datetime import datetime, timedelta
from pymongo import MongoClient
import os
import sys
import pytz

# ============================================================
# CONEXIÓN MONGODB
# ============================================================

MONGO_URI = os.getenv("MONGO_URL")
DB_NAME = "TRADING_X_HIPER_PRO"

client = MongoClient(MONGO_URI)
db = client[DB_NAME]

users_col = db["users"]
trades_col = db["trades"]

# ============================================================
# ZONA HORARIA (CUBA) – vencimientos por medianoche
# ============================================================

CUBA_TZ = pytz.timezone("America/Havana")

def _now_utc() -> datetime:
    return datetime.utcnow()

def _now_cuba() -> datetime:
    return datetime.now(CUBA_TZ)

def _midnight_cuba_after_days(days: int) -> datetime:
    """
    Retorna la medianoche (00:00) de Cuba para (hoy + days), convertida a UTC naive.
    Ej:
      si hoy es 2026-02-04 (Cuba), days=5 => 2026-02-09 00:00 (Cuba).
    """
    now_cuba = _now_cuba()
    target_date = now_cuba.date() + timedelta(days=int(days))
    midnight_local = CUBA_TZ.localize(datetime(target_date.year, target_date.month, target_date.day, 0, 0, 0))
    # Guardamos en UTC (naive) para consistencia
    return midnight_local.astimezone(pytz.UTC).replace(tzinfo=None)

def _parse_dt(x):
    if not x:
        return None
    if isinstance(x, datetime):
        return x
    try:
        return datetime.fromisoformat(str(x))
    except Exception:
        return None

# ============================================================
# LOG EN VIVO (SERVIDOR)
# ============================================================

def db_log(msg: str):
    ts = _now_utc().isoformat()
    print(f"[DB {ts}] {msg}", file=sys.stdout, flush=True)

# ============================================================
# UTILIDADES (blindaje)
# ============================================================

def _safe_float(x, default: float = 0.0) -> float:
    try:
        if x is None:
            return float(default)
        return float(x)
    except Exception:
        return float(default)

def _clamp_non_negative(x: float) -> float:
    try:
        return x if x >= 0 else 0.0
    except Exception:
        return 0.0

# ============================================================
# USUARIOS
# ============================================================

def create_user(user_id: int, username: str):
    if not users_col.find_one({"user_id": int(user_id)}):
        users_col.insert_one({
            "user_id": int(user_id),
            "username": username,
            "wallet": None,
            "private_key": None,
            "capital": 0.0,
            "trading_status": "inactive",

            # ✅ Planes (trial/premium)
            "plan": "none",                 # none | trial | premium
            "plan_expires_at": None,        # datetime UTC naive
            "trial_used": False,            # trial una sola vez
            "expiry_notified_on": None,     # YYYY-MM-DD (Cuba) para evitar spam

            # ✅ Referidos (solo conteo de válidos)
            "referrer": None,                # user_id del referidor
            "referral_valid_count": 0,       # contador en el referidor
            "referral_counted": False,       # marca si este usuario ya contó como válido
        })
        db_log(f"👤 Usuario creado {user_id}")

def is_user_registered(user_id: int) -> bool:
    return users_col.find_one({"user_id": int(user_id)}, {"_id": 1}) is not None

def get_all_users():
    return list(users_col.find({}, {"_id": 0, "user_id": 1}))


def _reset_user_trading_state_on_cred_change(user_id: int):
    """Resetea estado sensible cuando cambian credenciales (wallet o private_key).
    Mantiene plan/referidos, pero evita operar con capital/config previa.
    """
    users_col.update_one(
        {"user_id": int(user_id)},
        {
            "$set": {"capital": 0.0, "trading_status": "inactive"},
            "$unset": {"last_open": "", "last_close": "", "last_open_at": "", "last_close_at": ""},
        },
    )

def save_user_wallet(user_id: int, wallet: str):
    user_id = int(user_id)
    wallet = (wallet or "").strip()

    # Si cambia la wallet, reseteamos capital/estado para evitar arrastrar config anterior.
    prev = users_col.find_one({"user_id": user_id}, {"_id": 0, "wallet": 1}) or {}
    prev_wallet = (prev.get("wallet") or "").strip()

    users_col.update_one({"user_id": user_id}, {"$set": {"wallet": wallet}})

    if wallet and prev_wallet and wallet.lower() != prev_wallet.lower():
        _reset_user_trading_state_on_cred_change(user_id)

def save_user_private_key(user_id: int, pk: str):
    user_id = int(user_id)
    pk = (pk or "").strip()

    # Si cambia la private key, reseteamos capital/estado para evitar arrastrar config anterior.
    prev = users_col.find_one({"user_id": user_id}, {"_id": 0, "private_key": 1}) or {}
    prev_pk = (prev.get("private_key") or "").strip()

    users_col.update_one({"user_id": user_id}, {"$set": {"private_key": pk}})

    if pk and prev_pk and pk != prev_pk:
        _reset_user_trading_state_on_cred_change(user_id)

def save_user_capital(user_id: int, capital: float):
    capital = _clamp_non_negative(_safe_float(capital, 0.0))
    users_col.update_one({"user_id": int(user_id)}, {"$set": {"capital": capital}})

def set_trading_status(user_id: int, status: str):
    users_col.update_one({"user_id": int(user_id)}, {"$set": {"trading_status": status}})


# ============================================================
# REFERIDOS (SOLO CONTEO DE VÁLIDOS)
# ============================================================

def set_referrer(user_id: int, referrer_id: int):
    """
    Asigna el referidor una sola vez (si no existe ya).
    No permite auto-referido.
    """
    try:
        user_id = int(user_id)
        referrer_id = int(referrer_id)
        if user_id == referrer_id:
            return

        users_col.update_one(
            {"user_id": user_id, "$or": [{"referrer": None}, {"referrer": {"$exists": False}}]},
            {"$set": {"referrer": referrer_id}}
        )
    except Exception as e:
        db_log(f"❌ Error set_referrer user={user_id}: {e}")

def get_user_referrer(user_id: int):
    u = users_col.find_one({"user_id": int(user_id)}, {"_id": 0, "referrer": 1})
    return (u or {}).get("referrer")

def get_referral_valid_count(referrer_id: int) -> int:
    u = users_col.find_one({"user_id": int(referrer_id)}, {"_id": 0, "referral_valid_count": 1})
    try:
        return int((u or {}).get("referral_valid_count", 0) or 0)
    except Exception:
        return 0

def _mark_referral_valid(target_user_id: int):
    """
    Cuando un usuario activa Premium por primera vez:
    - si tiene referrer y aún no fue contado, incrementa referral_valid_count en el referidor
    - marca referral_counted=True en el usuario
    """
    try:
        target_user_id = int(target_user_id)
        u = users_col.find_one(
            {"user_id": target_user_id},
            {"_id": 0, "referrer": 1, "referral_counted": 1}
        )
        if not u:
            return

        if bool(u.get("referral_counted", False)):
            return

        referrer_id = u.get("referrer")
        if not referrer_id:
            # igual marcamos counted para no reintentar en el futuro
            users_col.update_one({"user_id": target_user_id}, {"$set": {"referral_counted": True}})
            return

        # 1) marcar counted solo si aún es False (evita doble conteo)
        res = users_col.update_one(
            {"user_id": target_user_id, "$or": [{"referral_counted": False}, {"referral_counted": {"$exists": False}}]},
            {"$set": {"referral_counted": True}}
        )
        if res.modified_count != 1:
            return

        # 2) incrementar contador en el referidor
        users_col.update_one(
            {"user_id": int(referrer_id)},
            {"$inc": {"referral_valid_count": 1}}
        )
        db_log(f"👥 Referido válido contado: referrer={referrer_id} user={target_user_id}")

    except Exception as e:
        db_log(f"❌ Error _mark_referral_valid user={target_user_id}: {e}")


def get_user_wallet(user_id: int):
    u = users_col.find_one({"user_id": int(user_id)})
    return u.get("wallet") if u else None

def get_user_private_key(user_id: int):
    u = users_col.find_one({"user_id": int(user_id)})
    return u.get("private_key") if u else None

def get_user_capital(user_id: int):
    u = users_col.find_one({"user_id": int(user_id)})
    return _safe_float(u.get("capital", 0.0), 0.0) if u else 0.0

def _plan_is_active(u: dict) -> bool:
    plan = (u or {}).get("plan") or "none"
    exp = _parse_dt((u or {}).get("plan_expires_at"))
    if plan not in ("trial", "premium"):
        return False
    if not exp:
        return False
    return _now_utc() < exp

def user_is_ready(user_id: int) -> bool:
    u = users_col.find_one({"user_id": int(user_id)})
    if not u:
        return False

    # ✅ Debe tener plan activo (trial o premium)
    if not _plan_is_active(u):
        return False

    return bool(
        u.get("wallet") and
        u.get("private_key") and
        _safe_float(u.get("capital", 0.0), 0.0) > 0.0 and
        u.get("trading_status") == "active"
    )

# ============================================================
# PLANES (TRIAL / PREMIUM)
# ============================================================

def ensure_access_on_activate(user_id: int) -> dict:
    """
    Llamar cuando el usuario toca "Activar Trading".
    - Si tiene premium activo => allowed
    - Si tiene trial activo => allowed
    - Si no tiene plan activo y NO ha usado trial => inicia trial 5 días (vence medianoche Cuba)
    - Si ya usó trial y no tiene premium => bloqueado
    """
    u = users_col.find_one({"user_id": int(user_id)})
    if not u:
        return {"allowed": False, "message": "❌ Usuario no registrado."}

    # Premium activo
    if _plan_is_active(u) and (u.get("plan") == "premium"):
        return {"allowed": True, "plan_message": "🟢 *Trading ACTIVADO*\nPlan: *PREMIUM* ✅"}

    # Trial activo
    if _plan_is_active(u) and (u.get("plan") == "trial"):
        exp = _parse_dt(u.get("plan_expires_at"))
        if exp:
            exp_cuba = exp.replace(tzinfo=pytz.UTC).astimezone(CUBA_TZ)
            exp_str = exp_cuba.strftime("%Y-%m-%d 00:00 Cuba")
        else:
            exp_str = ""
        return {"allowed": True, "plan_message": f"🟢 *Trading ACTIVADO*\nPlan: *PRUEBA* ✅\nVence: *{exp_str}*"}

    # Iniciar trial (una sola vez)
    if not bool(u.get("trial_used", False)):
        exp_utc = _midnight_cuba_after_days(5)
        users_col.update_one(
            {"user_id": int(user_id)},
            {"$set": {"plan": "trial", "plan_expires_at": exp_utc, "trial_used": True}}
        )
        exp_cuba = exp_utc.replace(tzinfo=pytz.UTC).astimezone(CUBA_TZ)
        exp_str = exp_cuba.strftime("%Y-%m-%d 00:00 Cuba")
        db_log(f"✅ Trial iniciado user={user_id} exp={exp_utc.isoformat()}")
        return {"allowed": True, "plan_message": f"🟢 *Trading ACTIVADO*\nPlan: *PRUEBA* ✅\nVence: *{exp_str}*"}
    # Ya usó trial
    return {
        "allowed": False,
        "message": "⛔ Tu prueba terminó.\nPara seguir utilizando el bot, contacta al administrador."
    }

def activate_premium_plan(target_user_id: int) -> bool:
    """
    Activación manual por admin:
    - Premium 30 días (vence medianoche Cuba)
    """
    try:
        u = users_col.find_one({"user_id": int(target_user_id)})
        if not u:
            return False

        exp_utc = _midnight_cuba_after_days(30)
        users_col.update_one(
            {"user_id": int(target_user_id)},
            {"$set": {"plan": "premium", "plan_expires_at": exp_utc, "expiry_notified_on": None}}
        )
        db_log(f"💎 Premium activado user={target_user_id} exp={exp_utc.isoformat()}")
        # ✅ Marcar referido válido (una sola vez)
        _mark_referral_valid(int(target_user_id))
        return True
    except Exception as e:
        db_log(f"❌ Error activando premium user={target_user_id}: {e}")
        return False

def is_plan_expired(user_id: int) -> bool:
    u = users_col.find_one({"user_id": int(user_id)}, {"_id": 0, "plan": 1, "plan_expires_at": 1})
    if not u:
        return False
    plan = u.get("plan") or "none"
    exp = _parse_dt(u.get("plan_expires_at"))
    if plan not in ("trial", "premium") or not exp:
        return False
    return _now_utc() >= exp

def should_notify_expired(user_id: int) -> bool:
    """
    True si está vencido y no se notificó hoy (hora Cuba).
    """
    u = users_col.find_one({"user_id": int(user_id)}, {"_id": 0, "expiry_notified_on": 1})
    if not u:
        return False
    today_cuba = _now_cuba().strftime("%Y-%m-%d")
    return u.get("expiry_notified_on") != today_cuba

def mark_expiry_notified(user_id: int):
    today_cuba = _now_cuba().strftime("%Y-%m-%d")
    users_col.update_one({"user_id": int(user_id)}, {"$set": {"expiry_notified_on": today_cuba}})

# ============================================================
# TRADES + INTERÉS COMPUESTO
# ============================================================

def _apply_compounding(user_id: int, profit: float) -> float:
    """
    Suma profit al capital (Telegram) de forma atómica.
    - profit puede ser negativo (pérdida)
    - nunca dejamos capital en negativo (si queda <0, lo ajustamos a 0)
    Devuelve el capital final.
    """
    profit = _safe_float(profit, 0.0)

    # 1) INC atómico (evita race conditions)
    users_col.update_one(
        {"user_id": int(user_id)},
        {"$inc": {"capital": profit}}
    )

    # 2) Clamp a 0 si por pérdida quedó negativo
    u = users_col.find_one({"user_id": int(user_id)}, {"_id": 0, "capital": 1})
    current = _safe_float((u or {}).get("capital", 0.0), 0.0)
    if current < 0:
        users_col.update_one({"user_id": int(user_id)}, {"$set": {"capital": 0.0}})
        current = 0.0

    return current

def register_trade(user_id, symbol, side, entry_price, exit_price, qty, profit, best_score):
    """
    Registra el trade y aplica interés compuesto:
      capital := capital + profit

    NOTA: No hay fees (admin/ref) en este modelo.
    """
    trades_col.insert_one({
        "user_id": int(user_id),
        "symbol": str(symbol),
        "side": str(side),
        "entry_price": _safe_float(entry_price, 0.0),
        "exit_price": _safe_float(exit_price, 0.0),
        "qty": _safe_float(qty, 0.0),
        "profit": _safe_float(profit, 0.0),
        "best_score": _safe_float(best_score, 0.0),
        "timestamp": datetime.utcnow()
    })

    new_capital = _apply_compounding(int(user_id), _safe_float(profit, 0.0))
    db_log(f"📈 Compounding aplicado user={user_id} profit={_safe_float(profit,0.0)} -> capital={new_capital}")

def get_user_trades(user_id: int):
    return list(
        trades_col.find({"user_id": int(user_id)}, {"_id": 0})
        .sort("timestamp", -1)
        .limit(20)
    )

# ============================================================
# ADMIN – INFORMACIÓN VISUAL (STATS)
# ============================================================

def get_admin_visual_stats() -> dict:
    """
    Retorna métricas globales para el panel admin:
    - total_users
    - free_old
    - premium_active
    - premium_expired
    """
    total_users = users_col.count_documents({})

    now = datetime.utcnow()

    premium_active = users_col.count_documents({
        "plan": "premium",
        "plan_expires_at": {"$gt": now}
    })

    premium_expired = users_col.count_documents({
        "plan": "premium",
        "plan_expires_at": {"$lte": now}
    })

    free_old = users_col.count_documents({
        "$or": [
            {"plan": {"$exists": False}},
            {"plan": None},
            {"plan": "trial"}
        ],
        "trial_used": True
    })

    return {
        "total_users": int(total_users),
        "free_old": int(free_old),
        "premium_active": int(premium_active),
        "premium_expired": int(premium_expired),
    }

# ============================================================
# OPERACIÓN ACTUAL / ÚLTIMA (INFO PARA BOT)
# ============================================================

def save_last_open(user_id: int, open_data: dict):
    """
    Guarda la información de la última operación ABIERTA.
    Se sobreescribe siempre (solo informativo).
    """
    users_col.update_one(
        {"user_id": int(user_id)},
        {"$set": {"last_open": open_data, "last_open_at": datetime.utcnow()}}
    )

def save_last_close(user_id: int, close_data: dict):
    """
    Guarda la información de la última operación CERRADA.
    Se sobreescribe siempre (solo informativo).
    """
    users_col.update_one(
        {"user_id": int(user_id)},
        {"$set": {"last_close": close_data, "last_close_at": datetime.utcnow()}}
    )

def get_last_operation(user_id: int) -> dict:
    """
    Retorna last_open y last_close para mostrar en el botón Información.
    """
    u = users_col.find_one(
        {"user_id": int(user_id)},
        {"_id": 0, "last_open": 1, "last_close": 1}
    )
    return u or {}

# ============================================================
# LEGACY – FEES (DESACTIVADO)
# Mantener SOLO para compatibilidad con imports en trading_engine.py
# NO afecta trading / estrategia.
# ============================================================

def add_daily_admin_fee(user_id: int, amount: float):
    """DEPRECATED: fees desactivadas. Se deja para no romper imports."""
    try:
        db_log(f"ℹ add_daily_admin_fee ignorado (fees desactivadas) user={user_id} amount={amount}")
    except Exception:
        pass
    return None

def add_weekly_ref_fee(referrer_id: int, amount: float):
    """DEPRECATED: fees desactivadas. Se deja para no romper imports."""
    try:
        db_log(f"ℹ add_weekly_ref_fee ignorado (fees desactivadas) referrer={referrer_id} amount={amount}")
    except Exception:
        pass
    return None
