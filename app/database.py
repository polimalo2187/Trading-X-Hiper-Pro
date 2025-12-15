# ============================================================
# DATABASE.PY – Trading X Hyper Pro
# Archivo 2/9 – Conexión Mongo + Modelos
# ============================================================

from pymongo import MongoClient
import datetime
from app.config import DB_NAME, MONGO_URI

# ============================================================
# CONEXIÓN A MONGO
# ============================================================

client = MongoClient(MONGO_URI)
db = client[DB_NAME]

# COLECCIONES
users_col = db["users"]
trades_col = db["trades"]
fees_daily_col = db["fees_daily"]        # fees del dueño acumuladas día por día
fees_referral_col = db["fees_referral"]  # fees del referido acumuladas día por día


# ============================================================
# CREAR USUARIO
# ============================================================

def create_user(user_id, username):
    user = users_col.find_one({"user_id": user_id})
    if user:
        return user

    new_user = {
        "user_id": user_id,
        "username": username,
        "wallet": None,
        "private_key": None,
        "capital": 0,
        "status": "inactive",  # active / inactive
        "referrer": None,
        "created_at": datetime.datetime.utcnow(),
        "updated_at": datetime.datetime.utcnow(),
    }

    users_col.insert_one(new_user)
    return new_user


# ============================================================
# WALLET
# ============================================================

def save_user_wallet(user_id, wallet):
    users_col.update_one(
        {"user_id": user_id},
        {"$set": {"wallet": wallet, "updated_at": datetime.datetime.utcnow()}}
    )
    return True

def get_user_wallet(user_id):
    user = users_col.find_one({"user_id": user_id})
    return user.get("wallet") if user else None


# ============================================================
# PRIVATE KEY
# ============================================================

def save_user_private_key(user_id, private_key):
    users_col.update_one(
        {"user_id": user_id},
        {"$set": {"private_key": private_key, "updated_at": datetime.datetime.utcnow()}}
    )
    return True

def get_user_private_key(user_id):
    user = users_col.find_one({"user_id": user_id})
    return user.get("private_key") if user else None


# ============================================================
# CAPITAL
# ============================================================

def save_user_capital(user_id, capital):
    users_col.update_one(
        {"user_id": user_id},
        {"$set": {"capital": float(capital), "updated_at": datetime.datetime.utcnow()}}
    )
    return True

def get_user_capital(user_id):
    user = users_col.find_one({"user_id": user_id})
    return float(user.get("capital", 0)) if user else 0


# ============================================================
# STATUS (ACTIVE / INACTIVE)
# ============================================================

def set_trading_status(user_id, status):
    users_col.update_one(
        {"user_id": user_id},
        {"$set": {"status": status, "updated_at": datetime.datetime.utcnow()}}
    )

def user_is_ready(user_id):
    """
    Un usuario está listo solo si:
    - Tiene wallet
    - Tiene private_key
    - Tiene capital >= 5 USDC
    - Estado = active
    """
    user = users_col.find_one({"user_id": user_id})
    if not user:
        return False

    if not user.get("wallet"):
        return False

    if not user.get("private_key"):
        return False

    if float(user.get("capital", 0)) < 5:
        return False

    return user.get("status") == "active"


# ============================================================
# REFERIDOS
# ============================================================

def set_referrer(user_id, referrer):
    if user_id == referrer:
        return False

    users_col.update_one(
        {"user_id": user_id},
        {"$set": {"referrer": referrer}}
    )
    return True

def get_user_referrer(user_id):
    user = users_col.find_one({"user_id": user_id})
    return user.get("referrer") if user else None


# ============================================================
# TRADES REALES
# ============================================================

def register_trade(user_id, symbol, side, entry_price, exit_price, qty, profit):
    trade = {
        "user_id": user_id,
        "symbol": symbol,
        "side": side,
        "entry": entry_price,
        "exit": exit_price,
        "qty": qty,
        "profit": profit,
        "timestamp": datetime.datetime.utcnow(),
    }
    trades_col.insert_one(trade)
    return trade

def get_user_trades(user_id, limit=20):
    return list(
        trades_col.find({"user_id": user_id}).sort("timestamp", -1).limit(limit)
    )


# ============================================================
# FEES – SISTEMA DIARIO (DUEÑO) Y SEMANAL (REFERIDOS)
# ============================================================

def register_daily_fee(user_id, amount):
    """
    Se registra la fee del dueño (15% real) cada vez que se genera.
    No se paga ahora, solo se acumula.
    """
    fees_daily_col.insert_one({
        "user_id": user_id,
        "amount": amount,
        "timestamp": datetime.datetime.utcnow()
    })

def register_referral_fee(referrer_id, amount):
    """
    Se descuenta de la fee del dueño y se acumula para pago semanal.
    """
    fees_referral_col.insert_one({
        "referrer_id": referrer_id,
        "amount": amount,
        "timestamp": datetime.datetime.utcnow()
    })


# ============================================================
# CONSULTAS DE FEE
# ============================================================

def get_total_daily_fees():
    total = 0
    for f in fees_daily_col.find():
        total += float(f["amount"])
    return total

def get_total_referral_fees(user_id):
    total = 0
    for f in fees_referral_col.find({"referrer_id": user_id}):
        total += float(f["amount"])
    return total


# ============================================================
# LISTA DE USUARIOS (TRADING LOOP)
# ============================================================

def get_all_users():
    return list(users_col.find({}))
