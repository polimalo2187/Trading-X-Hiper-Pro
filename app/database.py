# ============================================================
# DATABASE – TRADING X HIPER PRO
# Archivo 2/9 – Sistema profesional con MongoDB Atlas
# Producción real – Estable
# ============================================================

from datetime import datetime
from pymongo import MongoClient
import os
import sys

# ============================================================
# CONEXIÓN MONGODB ATLAS
# ============================================================

MONGO_URI = os.getenv("MONGO_URL")
DB_NAME = "TRADING_X_HIPER_PRO"

client = MongoClient(MONGO_URI)
db = client[DB_NAME]

# Colecciones
users_col = db["users"]
trades_col = db["trades"]
admin_daily_fees_col = db["admin_daily_fees"]
referral_weekly_fees_col = db["referral_weekly_fees"]
fee_payments_col = db["fee_payments"]

# ============================================================
# LOG EN VIVO (VISIBLE EN SERVIDOR)
# ============================================================

def db_log(msg: str):
    ts = datetime.utcnow().isoformat()
    print(f"[DB {ts}] {msg}", file=sys.stdout, flush=True)

# ============================================================
# USUARIOS
# ============================================================

def create_user(user_id: int, username: str):
    if not users_col.find_one({"user_id": user_id}):
        users_col.insert_one({
            "user_id": user_id,
            "username": username,
            "wallet": None,
            "private_key": None,
            "capital": 0,
            "trading_status": "inactive",
            "referrer": None
        })
        db_log(f"👤 Usuario creado user={user_id}")

def get_all_users():
    return list(users_col.find({}, {"_id": 0, "user_id": 1}))

def save_user_wallet(user_id: int, wallet: str):
    users_col.update_one({"user_id": user_id}, {"$set": {"wallet": wallet}})
    db_log(f"🔐 Wallet guardada user={user_id}")

def save_user_private_key(user_id: int, pk: str):
    users_col.update_one({"user_id": user_id}, {"$set": {"private_key": pk}})
    db_log(f"🔑 Private key guardada user={user_id}")

def save_user_capital(user_id: int, capital: float):
    users_col.update_one({"user_id": user_id}, {"$set": {"capital": capital}})
    db_log(f"💰 Capital actualizado user={user_id} capital={capital}")

def set_trading_status(user_id: int, status: str):
    users_col.update_one({"user_id": user_id}, {"$set": {"trading_status": status}})
    db_log(f"⚙️ Trading status user={user_id} -> {status}")

def get_user_wallet(user_id: int):
    user = users_col.find_one({"user_id": user_id})
    return user.get("wallet") if user else None

def get_user_private_key(user_id: int):
    user = users_col.find_one({"user_id": user_id})
    return user.get("private_key") if user else None

def get_user_capital(user_id: int):
    user = users_col.find_one({"user_id": user_id})
    return float(user.get("capital", 0)) if user else 0

# ============================================================
# VALIDACIÓN CRÍTICA (LOGS EN VIVO)
# ============================================================

def user_is_ready(user_id: int) -> bool:
    user = users_col.find_one({"user_id": user_id})

    if not user:
        db_log(f"[READY] user={user_id} ❌ no existe")
        return False

    if not user.get("wallet"):
        db_log(f"[READY] user={user_id} ❌ wallet faltante")
        return False

    if not user.get("private_key"):
        db_log(f"[READY] user={user_id} ❌ private_key faltante")
        return False

    if user.get("capital", 0) <= 0:
        db_log(f"[READY] user={user_id} ❌ capital insuficiente")
        return False

    if user.get("trading_status") != "active":
        db_log(f"[READY] user={user_id} ❌ trading_status={user.get('trading_status')}")
        return False

    db_log(f"[READY] user={user_id} ✅ LISTO PARA TRADING")
    return True

# ============================================================
# REFERIDOS
# ============================================================

def set_referrer(user_id: int, referrer_id: int):
    users_col.update_one({"user_id": user_id}, {"$set": {"referrer": referrer_id}})
    db_log(f"🤝 Referrer asignado user={user_id} ref={referrer_id}")

def get_user_referrer(user_id: int):
    user = users_col.find_one({"user_id": user_id})
    return user.get("referrer") if user else None

# ============================================================
# TRADES
# ============================================================

def register_trade(user_id, symbol, side, entry_price, exit_price, qty, profit, best_score):
    trades_col.insert_one({
        "user_id": user_id,
        "symbol": symbol,
        "side": side,
        "entry_price": entry_price,
        "exit_price": exit_price,
        "qty": qty,
        "profit": profit,
        "best_score": best_score,
        "timestamp": datetime.utcnow()
    })
    db_log(f"📊 Trade registrado user={user_id} {symbol} PnL={profit}")

def get_user_trades(user_id: int):
    rows = trades_col.find(
        {"user_id": user_id},
        {"_id": 0}
    ).sort("timestamp", -1).limit(20)

    return list(rows)

# ============================================================
# FEES ADMIN (DIARIO)
# ============================================================

def add_daily_admin_fee(user_id: int, amount: float):
    today = datetime.utcnow().strftime("%Y-%m-%d")
    admin_daily_fees_col.insert_one({
        "user_id": user_id,
        "amount": amount,
        "date": today
    })
    db_log(f"🏦 Fee admin diario user={user_id} amount={amount}")

# ============================================================
# FEES REFERIDOS (SEMANAL)
# ============================================================

def add_weekly_ref_fee(referrer_id: int, amount: float):
    today = datetime.utcnow().strftime("%Y-%m-%d")
    referral_weekly_fees_col.insert_one({
        "referrer_id": referrer_id,
        "amount": amount,
        "date": today
    })
    db_log(f"💸 Fee referido ref={referrer_id} amount={amount}")

# ============================================================
# AUDITORÍA / ANTI DOBLE PAGO
# ============================================================

def payment_exists(payment_type: str, period_id: str, beneficiary_id: int | None = None) -> bool:
    query = {
        "payment_type": payment_type,
        "period_id": period_id
    }

    if beneficiary_id is not None:
        query["beneficiary_id"] = beneficiary_id

    return fee_payments_col.find_one(query) is not None

def log_fee_payment(payment_type: str,
                    period_id: str,
                    amount: float,
                    tx_hash: str,
                    beneficiary_id: int | None = None,
                    currency: str = "USDC"):

    fee_payments_col.insert_one({
        "payment_type": payment_type,
        "beneficiary_id": beneficiary_id,
        "amount": amount,
        "currency": currency,
        "period_id": period_id,
        "tx_hash": tx_hash,
        "status": "PAID",
        "created_at": datetime.utcnow()
    })
    db_log(f"🧾 Pago registrado type={payment_type} amount={amount}")
