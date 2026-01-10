# ============================================================
# DATABASE – TRADING X HIPER PRO
# Sistema profesional MongoDB Atlas
# PRODUCCIÓN REAL – BLINDADO
# ============================================================

from datetime import datetime
from pymongo import MongoClient
import os
import sys

# ============================================================
# CONEXIÓN MONGODB
# ============================================================

MONGO_URI = os.getenv("MONGO_URL")
DB_NAME = "TRADING_X_HIPER_PRO"

client = MongoClient(MONGO_URI)
db = client[DB_NAME]

users_col = db["users"]
trades_col = db["trades"]
admin_daily_fees_col = db["admin_daily_fees"]
referral_weekly_fees_col = db["referral_weekly_fees"]
fee_payments_col = db["fee_payments"]

# ============================================================
# LOG EN VIVO (SERVIDOR)
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
        db_log(f"👤 Usuario creado {user_id}")

def get_all_users():
    return list(users_col.find({}, {"_id": 0, "user_id": 1}))

def save_user_wallet(user_id: int, wallet: str):
    users_col.update_one({"user_id": user_id}, {"$set": {"wallet": wallet}})

def save_user_private_key(user_id: int, pk: str):
    users_col.update_one({"user_id": user_id}, {"$set": {"private_key": pk}})

def save_user_capital(user_id: int, capital: float):
    users_col.update_one({"user_id": user_id}, {"$set": {"capital": capital}})

def set_trading_status(user_id: int, status: str):
    users_col.update_one({"user_id": user_id}, {"$set": {"trading_status": status}})

def get_user_wallet(user_id: int):
    u = users_col.find_one({"user_id": user_id})
    return u.get("wallet") if u else None

def get_user_private_key(user_id: int):
    u = users_col.find_one({"user_id": user_id})
    return u.get("private_key") if u else None

def get_user_capital(user_id: int):
    u = users_col.find_one({"user_id": user_id})
    return float(u.get("capital", 0)) if u else 0

def user_is_ready(user_id: int) -> bool:
    u = users_col.find_one({"user_id": user_id})
    return bool(
        u and
        u.get("wallet") and
        u.get("private_key") and
        u.get("capital", 0) > 0 and
        u.get("trading_status") == "active"
    )

# ============================================================
# REFERIDOS
# ============================================================

def set_referrer(user_id: int, referrer_id: int):
    users_col.update_one({"user_id": user_id}, {"$set": {"referrer": referrer_id}})

def get_user_referrer(user_id: int):
    u = users_col.find_one({"user_id": user_id})
    return u.get("referrer") if u else None

def get_referrer_weekly(referrer_id: int):
    rows = referral_weekly_fees_col.find({"referrer_id": referrer_id})
    return sum(float(r.get("amount", 0)) for r in rows)

def get_referrers_with_balance():
    pipeline = [
        {"$group": {"_id": "$referrer_id", "total": {"$sum": "$amount"}}},
        {"$match": {"total": {"$gt": 0}}}
    ]
    return [
        {"referrer_id": r["_id"], "amount": float(r["total"])}
        for r in referral_weekly_fees_col.aggregate(pipeline)
    ]

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

def get_user_trades(user_id: int):
    return list(
        trades_col.find({"user_id": user_id}, {"_id": 0})
        .sort("timestamp", -1)
        .limit(20)
    )

# ============================================================
# FEES ADMIN
# ============================================================

def add_daily_admin_fee(user_id: int, amount: float):
    today = datetime.utcnow().strftime("%Y-%m-%d")
    admin_daily_fees_col.insert_one({
        "user_id": user_id,
        "amount": amount,
        "date": today
    })

def get_admin_daily_fees():
    today = datetime.utcnow().strftime("%Y-%m-%d")
    return sum(r["amount"] for r in admin_daily_fees_col.find({"date": today}))

def reset_daily_fees():
    today = datetime.utcnow().strftime("%Y-%m-%d")
    admin_daily_fees_col.delete_many({"date": today})

# ============================================================
# FEES REFERIDOS
# ============================================================

def add_weekly_ref_fee(referrer_id: int, amount: float):
    today = datetime.utcnow().strftime("%Y-%m-%d")
    referral_weekly_fees_col.insert_one({
        "referrer_id": referrer_id,
        "amount": amount,
        "date": today
    })

# ============================================================
# AUDITORÍA
# ============================================================

def payment_exists(payment_type: str, period_id: str, beneficiary_id: int | None = None) -> bool:
    q = {"payment_type": payment_type, "period_id": period_id}
    if beneficiary_id is not None:
        q["beneficiary_id"] = beneficiary_id
    return fee_payments_col.find_one(q) is not None

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
