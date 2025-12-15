from pymongo import MongoClient
import datetime
from app.config import MONGO_URI

# =======================================================
# CONEXIÓN A MONGO
# =======================================================

client = MongoClient(MONGO_URI)
db = client["TradingX_HyperPro"]

users_col = db["users"]
trades_col = db["trades"]
fees_col = db["fees"]
referrals_col = db["referrals"]


# =======================================================
# CREAR USUARIO
# =======================================================

def create_user(user_id, username):
    user = users_col.find_one({"user_id": user_id})

    if user:
        return user

    new_user = {
        "user_id": user_id,
        "username": username,
        "wallet": None,             # Dirección HyperLiquid
        "private_key": None,        # 🔥 Private Key para firmar órdenes reales
        "capital": 0,
        "status": "inactive",
        "referrer": None,
        "created_at": datetime.datetime.utcnow(),
        "updated_at": datetime.datetime.utcnow()
    }

    users_col.insert_one(new_user)
    return new_user


# =======================================================
# WALLET DEL USUARIO
# =======================================================

def save_user_wallet(user_id, wallet):
    users_col.update_one(
        {"user_id": user_id},
        {"$set": {"wallet": wallet, "updated_at": datetime.datetime.utcnow()}}
    )
    return True


def get_user_wallet(user_id):
    user = users_col.find_one({"user_id": user_id})
    return user.get("wallet") if user else None


# =======================================================
# PRIVATE KEY DEL USUARIO (OPERACIÓN REAL)
# =======================================================

def save_user_private_key(user_id, private_key):
    """
    Guarda la PRIVATE KEY para firmar órdenes reales en HyperLiquid.
    """
    users_col.update_one(
        {"user_id": user_id},
        {"$set": {"private_key": private_key, "updated_at": datetime.datetime.utcnow()}}
    )
    return True


def get_user_private_key(user_id):
    user = users_col.find_one({"user_id": user_id})
    return user.get("private_key") if user else None


# =======================================================
# CAPITAL
# =======================================================

def save_user_capital(user_id, capital):
    users_col.update_one(
        {"user_id": user_id},
        {"$set": {"capital": float(capital), "updated_at": datetime.datetime.utcnow()}}
    )
    return True


def get_user_capital(user_id):
    user = users_col.find_one({"user_id": user_id})
    return float(user.get("capital", 0)) if user else 0


# =======================================================
# ESTADO TRADING
# =======================================================

def set_trading_status(user_id, state):
    users_col.update_one(
        {"user_id": user_id},
        {"$set": {"status": state, "updated_at": datetime.datetime.utcnow()}}
    )
    return True


def user_is_ready(user_id):
    """
    Verifica si el usuario tiene TODO para operar real.
    """
    user = users_col.find_one({"user_id": user_id})
    if not user:
        return False

    # Wallet configurada
    if not user.get("wallet"):
        return False

    # Private Key configurada
    if not user.get("private_key"):
        return False

    # Capital suficiente
    if float(user.get("capital", 0)) < 5:
        return False

    # Trading activado
    if user.get("status") != "active":
        return False

    return True


# =======================================================
# SISTEMA DE REFERIDOS
# =======================================================

def set_referrer(user_id, referrer_id):

    if user_id == referrer_id:
        return False

    users_col.update_one(
        {"user_id": user_id},
        {"$set": {"referrer": referrer_id}}
    )

    referrals_col.insert_one({
        "referrer": referrer_id,
        "referred": user_id,
        "timestamp": datetime.datetime.utcnow()
    })

    return True


def get_user_referrer(user_id):
    user = users_col.find_one({"user_id": user_id})
    return user.get("referrer") if user else None


# =======================================================
# REGISTRO DE OPERACIONES
# =======================================================

def register_trade(user_id, symbol, side, entry_price, exit_price, qty, profit):
    trade = {
        "user_id": user_id,
        "symbol": symbol,
        "side": side,
        "entry": entry_price,
        "exit": exit_price,
        "qty": qty,
        "profit": profit,
        "timestamp": datetime.datetime.utcnow()
    }
    trades_col.insert_one(trade)
    return trade


def get_user_trades(user_id):
    return list(trades_col.find({"user_id": user_id}).sort("timestamp", -1))


# =======================================================
# FEES
# =======================================================

def register_fee(user_id, owner_fee, ref_fee):

    referrer = get_user_referrer(user_id)

    fees_col.insert_one({
        "user_id": user_id,
        "owner_fee": owner_fee,
        "ref_fee": ref_fee,
        "referrer": referrer,
        "timestamp": datetime.datetime.utcnow()
    })

    return True


def get_owner_total_fees():
    total = 0
    for f in fees_col.find():
        total += float(f.get("owner_fee", 0))
    return total


def get_referrer_total_fees(referrer_id):
    total = 0
    for f in fees_col.find({"referrer": referrer_id}):
        total += float(f.get("ref_fee", 0))
    return total
