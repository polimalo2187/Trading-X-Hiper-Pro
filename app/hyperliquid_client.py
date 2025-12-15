import time
import requests
from eth_account import Account
from eth_account.messages import encode_structured_data

from app.config import HYPER_BASE_URL
from app.database import (
    get_user_wallet,
    get_user_private_key,
)


# ============================================================
# REQUEST BASE (INFO / EXCHANGE)
# ============================================================

def make_request(endpoint, payload):
    url = f"{HYPER_BASE_URL}{endpoint}"
    headers = {"Content-Type": "application/json"}

    try:
        res = requests.post(url, json=payload, headers=headers, timeout=10)
        return res.json()
    except Exception as e:
        print("❌ Error comunicando con HyperLiquid:", e)
        return None


# ============================================================
# BALANCE REAL
# ============================================================

def get_balance(user_id):
    wallet = get_user_wallet(user_id)
    if not wallet:
        print("❌ Usuario sin wallet configurada.")
        return 0

    payload = {"type": "clearinghouseState", "user": wallet}
    r = make_request("/info", payload)

    try:
        return float(r["marginSummary"]["accountValue"])
    except:
        print("❌ Error leyendo balance:", r)
        return 0


# ============================================================
# PRECIO REAL
# ============================================================

def get_price(symbol):
    payload = {"type": "px", "sym": symbol}
    r = make_request("/info", payload)

    try:
        return float(r["price"])
    except:
        return None


# ============================================================
# FIRMA EIP-712 REAL
# ============================================================

def sign_order(private_key, order_data):

    typed_data = {
        "types": {
            "EIP712Domain": [{"name": "name", "type": "string"}],
            "Order": [
                {"name": "symbol", "type": "string"},
                {"name": "side", "type": "string"},
                {"name": "qty", "type": "uint256"},
                {"name": "nonce", "type": "uint256"},
            ],
        },
        "primaryType": "Order",
        "domain": {"name": "Hyperliquid"},
        "message": order_data,
    }

    encoded = encode_structured_data(typed_data)
    signed = Account.sign_message(encoded, private_key=private_key)

    return signed.signature.hex()


# ============================================================
# ORDEN REAL MARKET
# ============================================================

def place_market_order(user_id, symbol, side, qty):
    wallet = get_user_wallet(user_id)
    private_key = get_user_private_key(user_id)

    if not wallet:
        print("❌ Usuario NO tiene wallet configurada.")
        return None

    if not private_key:
        print("❌ Usuario NO tiene PRIVATE KEY configurada.")
        return None

    nonce = int(time.time() * 1000)

    order = {
        "symbol": symbol,
        "side": side,
        "qty": int(qty),
        "nonce": nonce
    }

    signature = sign_order(private_key, order)

    payload = {
        "type": "order",
        "order": order,
        "signature": signature,
        "wallet": wallet
    }

    r = make_request("/exchange", payload)

    if not r:
        print("❌ Respuesta vacía del exchange.")
        return None

    # Validar tipos de respuesta correcta
    if ("success" in r and r["success"] is True) or ("status" in r and r["status"] == "ok"):
        print(f"🟢 ORDEN REAL EJECUTADA → {side.upper()} {qty} {symbol}")
        return r

    print("❌ Exchange rechazó la orden:", r)
    return None


# ============================================================
# WRAPPERS
# ============================================================

def open_long(user_id, symbol, qty):
    return place_market_order(user_id, symbol, "buy", qty)


def open_short(user_id, symbol, qty):
    return place_market_order(user_id, symbol, "sell", qty)
