import time
import json
import requests
from eth_account import Account
from eth_account.messages import encode_typed_data

from app.config import HYPER_BASE_URL
from app.database import (
    get_user_wallet,
    get_user_private_key,
)


# ============================================================
# REQUEST BASE
# ============================================================

def make_request(endpoint, payload):
    """
    Envía solicitudes a HyperLiquid.
    '/info'  → precios, balances, mercado
    '/exchange' → ejecutar órdenes reales
    """
    url = f"{HYPER_BASE_URL}{endpoint}"
    headers = {"Content-Type": "application/json"}

    try:
        res = requests.post(url, json=payload, headers=headers, timeout=10)
        return res.json()
    except Exception as e:
        print("❌ Error comunicando con HyperLiquid:", e)
        return None


# ============================================================
# BALANCE (PERPETUAL)
# ============================================================

def get_balance(user_id):
    wallet = get_user_wallet(user_id)

    if not wallet:
        print("❌ Usuario sin wallet configurada.")
        return 0

    payload = {"type": "clearinghouseState", "user": wallet}
    r = make_request("/info", payload)

    if not r or "marginSummary" not in r:
        print("❌ Error leyendo balance:", r)
        return 0

    return float(r["marginSummary"]["accountValue"])


# ============================================================
# PRECIO DE UN PAR
# ============================================================

def get_price(symbol):
    payload = {"type": "px", "sym": symbol}
    r = make_request("/info", payload)

    if not r or "price" not in r:
        return None

    return float(r["price"])


# ============================================================
# FIRMA EIP-712 PARA ÓRDENES REALES
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

    encoded = encode_typed_data(full_message=typed_data)
    signed = Account.sign_message(encoded, private_key=private_key)

    return signed.signature.hex()


# ============================================================
# ORDEN MARKET REAL
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

    # Crear nonce único
    nonce = int(time.time() * 1000)

    order = {
        "symbol": symbol,
        "side": side,  # buy / sell
        "qty": int(qty),
        "nonce": nonce
    }

    # Firma real EIP-712
    sig = sign_order(private_key, order)

    # Construir payload final
    payload = {
        "type": "order",
        "order": order,
        "signature": sig,
        "wallet": wallet
    }

    # ORDEN REAL --> /exchange
    r = make_request("/exchange", payload)

    if not r or "success" not in r:
        print("❌ Error ejecutando orden:", r)
        return None

    print(f"🟢 ORDEN REAL EJECUTADA → {side.upper()} {qty} {symbol}")
    return r


# ============================================================
# WRAPPERS
# ============================================================

def open_long(user_id, symbol, qty):
    return place_market_order(user_id, symbol, "buy", qty)


def open_short(user_id, symbol, qty):
    return place_market_order(user_id, symbol, "sell", qty)
