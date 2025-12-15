# ============================================================
# DATABASE – TRADING X HYPER PRO
# Archivo 2/9 – Sistema TOTAL de usuarios, trades y fees
# ============================================================

import sqlite3
from datetime import datetime

DB_PATH = "database.db"


# ============================================================
# CREACIÓN DE TABLAS PRINCIPALES
# ============================================================

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # --------------------------------------------------------
    # Tabla de usuarios
    # --------------------------------------------------------
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            wallet TEXT,
            private_key TEXT,
            capital REAL DEFAULT 0,
            trading_status TEXT DEFAULT 'inactive',
            referrer INTEGER DEFAULT NULL
        )
    """)

    # --------------------------------------------------------
    # Trades REALES registrados
    # --------------------------------------------------------
    c.execute("""
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            symbol TEXT,
            side TEXT,
            entry_price REAL,
            exit_price REAL,
            qty REAL,
            profit REAL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # --------------------------------------------------------
    # Admin acumula fee DIARIO por usuario
    # --------------------------------------------------------
    c.execute("""
        CREATE TABLE IF NOT EXISTS daily_admin_fees (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            amount REAL,
            date TEXT
        )
    """)

    # --------------------------------------------------------
    # Referido acumula fee SEMANAL (suma diaria)
    # --------------------------------------------------------
    c.execute("""
        CREATE TABLE IF NOT EXISTS weekly_referral_fees (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            referrer_id INTEGER,
            amount REAL,
            date TEXT
        )
    """)

    # --------------------------------------------------------
    # Log de pagos
    # admin → diario
    # referidos → semanal
    # --------------------------------------------------------
    c.execute("""
        CREATE TABLE IF NOT EXISTS fee_payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            payment_type TEXT,
            amount REAL,
            date TEXT
        )
    """)

    conn.commit()
    conn.close()


# ============================================================
# FUNCIONES DE USUARIOS
# ============================================================

def create_user(user_id, username):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute("SELECT user_id FROM users WHERE user_id=?", (user_id,))
    exists = c.fetchone()

    if not exists:
        c.execute("""
            INSERT INTO users (user_id, username)
            VALUES (?, ?)
        """, (user_id, username))

    conn.commit()
    conn.close()


def get_all_users():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT user_id FROM users")
    rows = c.fetchall()
    conn.close()
    return [{"user_id": r[0]} for r in rows]


def save_user_wallet(user_id, wallet):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE users SET wallet=? WHERE user_id=?", (wallet, user_id))
    conn.commit()
    conn.close()


def save_user_private_key(user_id, pk):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE users SET private_key=? WHERE user_id=?", (pk, user_id))
    conn.commit()
    conn.close()


def save_user_capital(user_id, capital):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE users SET capital=? WHERE user_id=?", (capital, user_id))
    conn.commit()
    conn.close()


def get_user_wallet(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT wallet FROM users WHERE user_id=?", (user_id,))
    r = c.fetchone()
    conn.close()
    return r[0] if r else None


def get_user_private_key(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT private_key FROM users WHERE user_id=?", (user_id,))
    r = c.fetchone()
    conn.close()
    return r[0] if r else None


def get_user_capital(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT capital FROM users WHERE user_id=?", (user_id,))
    r = c.fetchone()
    conn.close()
    return float(r[0]) if r else 0


def set_trading_status(user_id, status):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE users SET trading_status=? WHERE user_id=?", (status, user_id))
    conn.commit()
    conn.close()


def user_is_ready(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        SELECT wallet, private_key, capital, trading_status
        FROM users WHERE user_id=?
    """, (user_id,))
    r = c.fetchone()
    conn.close()

    if r and r[0] and r[1] and r[2] > 0 and r[3] == "active":
        return True
    return False


# ============================================================
# REFERIDOS
# ============================================================

def set_referrer(user_id, referrer_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE users SET referrer=? WHERE user_id=?", (referrer_id, user_id))
    conn.commit()
    conn.close()


def get_user_referrer(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT referrer FROM users WHERE user_id=?", (user_id,))
    r = c.fetchone()
    conn.close()
    return r[0] if r else None


# ============================================================
# TRADES
# ============================================================

def register_trade(user_id, symbol, side, entry_price, exit_price, qty, profit):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        INSERT INTO trades (user_id, symbol, side, entry_price, exit_price, qty, profit)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (user_id, symbol, side, entry_price, exit_price, qty, profit))
    conn.commit()
    conn.close()


def get_user_trades(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        SELECT symbol, side, entry_price, exit_price, qty, profit, timestamp
        FROM trades
        WHERE user_id=?
        ORDER BY id DESC LIMIT 20
    """, (user_id,))
    rows = c.fetchall()
    conn.close()

    return [
        {
            "symbol": r[0],
            "side": r[1],
            "entry": r[2],
            "exit": r[3],
            "qty": r[4],
            "profit": r[5],
            "time": r[6]
        }
        for r in rows
    ]


# ============================================================
# FEES – NUEVA LÓGICA OFICIAL
# ============================================================

# ------------------------------------------------------------
# ADMIN → acumula fee DIARIO por usuario
# ------------------------------------------------------------
def add_daily_admin_fee(user_id, amount):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    today = datetime.now().strftime("%Y-%m-%d")
    c.execute("""
        INSERT INTO daily_admin_fees (user_id, amount, date)
        VALUES (?, ?, ?)
    """, (user_id, amount, today))
    conn.commit()
    conn.close()


def get_admin_daily_fees():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    today = datetime.now().strftime("%Y-%m-%d")
    c.execute("SELECT SUM(amount) FROM daily_admin_fees WHERE date=?", (today,))
    r = c.fetchone()
    conn.close()
    return r[0] if r[0] else 0


def reset_daily_fees():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM daily_admin_fees")
    conn.commit()
    conn.close()


# ------------------------------------------------------------
# REFERIDO → acumula fee SEMANAL del dueño
# ------------------------------------------------------------
def add_weekly_ref_fee(referrer_id, amount):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    today = datetime.now().strftime("%Y-%m-%d")
    c.execute("""
        INSERT INTO weekly_referral_fees (referrer_id, amount, date)
        VALUES (?, ?, ?)
    """, (referrer_id, amount, today))
    conn.commit()
    conn.close()


def get_referrer_weekly(referrer_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT SUM(amount) FROM weekly_referral_fees WHERE referrer_id=?", (referrer_id,))
    r = c.fetchone()
    conn.close()
    return r[0] if r[0] else 0


def reset_weekly_fees():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM weekly_referral_fees")
    conn.commit()
    conn.close()


# ------------------------------------------------------------
# REGISTRO DE PAGOS (admin / referidos)
# ------------------------------------------------------------
def log_fee_payment(payment_type, amount):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    today = datetime.now().strftime("%Y-%m-%d")
    c.execute("""
        INSERT INTO fee_payments (payment_type, amount, date)
        VALUES (?, ?, ?)
    """, (payment_type, amount, today))
    conn.commit()
    conn.close()
