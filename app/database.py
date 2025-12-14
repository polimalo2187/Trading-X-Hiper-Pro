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
        "wallet": None,            # billetera del usuario
        "capital": 0,              # capital asignado
        "status": "inactive",      # trading ON / OFF
        "referrer": None,          # ID quien lo refirió
        "created_at": datetime.datetime.utcnow(),
        "updated_at": datetime.datetime.utcnow()
    }

    users_col.insert_one(new_user)
    return new_user



# =======================================================
# GUARDAR WALLET DEL USUARIO (HYPERLIQUID TB)
# =======================================================

def save_user_wallet(user_id, wallet):
    users_col.update_one(
        {"user_id": user_id},
        {
            "$set": {
                "wallet": wallet,
                "updated_at": datetime.datetime.utcnow()
            }
        }
    )
    return True


def get_user_wallet(user_id):
    user = users_col.find_one({"user_id": user_id})
    if not user:
        return None
    return user.get("wallet")



# =======================================================
# CAPITAL DEL USUARIO
# =======================================================

def save_user_capital(user_id, capital):
    users_col.update_one(
        {"user_id": user_id},
        {
            "$set": {
                "capital": float(capital),
                "updated_at": datetime.datetime.utcnow()
            }
        }
    )
    return True


def get_user_capital(user_id):
    user = users_col.find_one({"user_id": user_id})
    if not user:
        return 0
    return float(user.get("capital", 0))



# =======================================================
# ESTADO DE TRADING
# =======================================================

def set_trading_status(user_id, state):
    """
    state = 'active' o 'inactive'
    """
    users_col.update_one(
        {"user_id": user_id},
        {
            "$set": {
                "status": state,
                "updated_at": datetime.datetime.utcnow()
            }
        }
    )
    return True


def user_is_ready(user_id):
    """
    Verifica si el usuario tiene todo para operar.
    """
    user = users_col.find_one({"user_id": user_id})

    if not user:
        return False

    # Wallet configurada
    if not user.get("wallet"):
        return False

    # Capital asignado
    if float(user.get("capital", 0)) < 5:
        return False

    # Estado activo
    if user.get("status") != "active":
        return False

    return True



# =======================================================
# SISTEMA DE REFERIDOS
# =======================================================

def set_referrer(user_id, referrer_id):
    """
    Guarda el usuario que invitó a otro.
    """
    if user_id == referrer_id:
        return False  # no puede referirse a sí mismo

    users_col.update_one(
        {"user_id": user_id},
        {"$set": {"referrer": referrer_id}}
    )

    # Registrar en la tabla de referidos
    referrals_col.insert_one({
        "referrer": referrer_id,
        "referred": user_id,
        "timestamp": datetime.datetime.utcnow()
    })

    return True


def get_user_referrer(user_id):
    user = users_col.find_one({"user_id": user_id})
    if not user:
        return None
    return user.get("referrer")



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
        "profit": profit,  # ganancia total en USDC
        "timestamp": datetime.datetime.utcnow()
    }

    trades_col.insert_one(trade)
    return trade


def get_user_trades(user_id):
    return list(trades_col.find({"user_id": user_id}).sort("timestamp", -1))



# =======================================================
# FEES: GANANCIA DEL BOT Y REFERIDOS
# =======================================================

def register_fee(user_id, owner_fee, ref_fee):
    """
    Guarda la ganancia del dueño del bot y el fee del referido si existe.
    """

    referrer = get_user_referrer(user_id)

    fees_col.insert_one({
        "user_id": user_id,
        "owner_fee": owner_fee,     # fee del dueño del bot
        "ref_fee": ref_fee,         # fee para el referido
        "referrer": referrer,
        "timestamp": datetime.datetime.utcnow()
    })

    return True


def get_owner_total_fees():
    """
    Total acumulado del dueño del bot.
    """
    total = 0
    for f in fees_col.find():
        total += float(f.get("owner_fee", 0))
    return total


def get_referrer_total_fees(referrer_id):
    """
    Ganancia total de un referido.
    """
    total = 0
    for f in fees_col.find({"referrer": referrer_id}):
        total += float(f.get("ref_fee", 0))
    return total
