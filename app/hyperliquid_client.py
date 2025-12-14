import time
import json
import requests
from eth_account import Account
from eth_account.messages import encode_typed_data
from app.config import HYPER_BASE_URL
from app.database import get_user_wallet


# ============================================================
# BASE REQUEST – HYPERLIQUID PERPETUAL
# ============================================================

def make_request(payload):
    """
    Envia una solicitud al endpoint '/info' de HyperLiquid.
    """
    url = f"{HYPER_BASE_URL}/info"
    headers = {"Content-Type": "application/json"}

    try:
        res = requests.post(url, json=payload, headers=headers, timeout=10)
        return res.json()
    except Exception as e:
        print("❌ Error comunicando con HyperLiquid:", e)
        return None


# ============================================================
# CONSULTAR BALANCE USDC (PERPETUAL)
# ============================================================

def get_balance(user_id):
    wallet = get_user_wallet(user_id)

    if not wallet:
        print("❌ Usuario sin wallet configurada.")
        return 0

    payload = {
        "type": "clearinghouseState",
        "user": wallet
    }

    r = make_request(payload)

    if not r or "marginSummary" not in r:
        print("❌ Error leyendo balance:", r)
        return 0

    return float(r["marginSummary"]["accountValue"])


# ============================================================
# CONSULTAR PRECIO DE UN PAR PERPETUAL
# ============================================================

def get_price(symbol):
    payload = {
        "type": "px",
        "sym": symbol
    }

    r = make_request(payload)

    if not r or "price" not in r:
        return None

    return float(r["price"])


# ============================================================
# FIRMA DE ÓRDENES – EIP-712
# ============================================================

def sign_order(private_key, order_data):
    """
    Firma EIP-712 requerida por HyperLiquid para órdenes PERP.
    """

    typed_data = {
        "types": {
            "EIP712Domain": [
                {"name": "name", "type": "string"}
            ],
            "Order": [
                {"name": "symbol", "type": "string"},
                {"name": "side", "type": "string"},
                {"name": "qty", "type": "uint256"},
                {"name": "nonce", "type": "uint256"},
            ]
        },
        "primaryType": "Order",
        "domain": {"name": "Hyperliquid"},
        "message": order_data
    }

    encoded = encode_typed_data(full_message=typed_data)
    signed = Account.sign_message(encoded, private_key=private_key)

    return signed.signature.hex()


# ============================================================
# ENVIAR ORDEN PERP MARKET
# ============================================================

def place_market_order(user_id, symbol, side, qty, private_key):
    wallet = get_user_wallet(user_id)

    if not wallet:
        print("❌ Usuario sin wallet configurada.")
        return None

    # Crear nonce único
    nonce = int(time.time() * 1000)

    order = {
        "symbol": symbol,
        "side": side,       # "buy" o "sell"
        "qty": int(qty),
        "nonce": nonce
    }

    sig = sign_order(private_key, order)

    payload = {
        "type": "order",
        "order": order,
        "signature": sig,
        "wallet": wallet
    }

    r = make_request(payload)

    if not r or "success" not in r:
        print("❌ Error ejecutando orden:", r)
        return None

    print(f"🟢 ORDEN MARKET EJECUTADA: {side.upper()} {qty} {symbol}")
    return r


# ============================================================
# WRAPPERS
# ============================================================

def open_long(user_id, symbol, qty, private_key):
    return place_market_order(user_id, symbol, "buy", qty, private_key)


def open_short(user_id, symbol, qty, private_key):
    return place_market_order(user_id, symbol, "sell", qty, private_key)
