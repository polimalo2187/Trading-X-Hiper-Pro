# ============================================================
# HYPERLIQUID CLIENT – Trading X Hyper Pro
# Archivo 3/9 – Conexión real con el exchange
# ============================================================

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

def make_request(endpoint: str, payload: dict):
    """
    Envía cualquier solicitud a la API oficial de HyperLiquid.
    """
    url = f"{HYPER_BASE_URL}{endpoint}"
    headers = {"Content-Type": "application/json"}

    try:
        res = requests.post(url, json=payload, headers=headers, timeout=8)
        return res.json()
    except Exception as e:
        print("❌ Error comunicando con HyperLiquid:", e)
        return None


# ============================================================
# OBTENER TODOS LOS PARES DISPONIBLES (REAL - PERPETUAL)
# ============================================================

def get_all_symbols():
    """
    Devuelve una lista de TODOS los pares existentes en HyperLiquid PERP.
    Necesario para el Market Scanner.
    """

    payload = {"type": "allMids"}
    r = make_request("/info", payload)

    if not r or "mids" not in r:
        print("❌ No se pudo obtener lista de pares.")
        return []

    return list(r["mids"].keys())


# ============================================================
# OBTENER BALANCE REAL DEL USUARIO
# ============================================================

def get_balance(user_id: int) -> float:
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
# PRECIO REAL DE UN PAR
# ============================================================

def get_price(symbol: str):
    payload = {"type": "px", "sym": symbol}
    r = make_request("/info", payload)

    try:
        return float(r["price"])
    except:
        return None


# ============================================================
# FIRMA EIP-712 REGLAMENTARIA PARA ÓRDENES REALES
# ============================================================

def sign_order(private_key: str, order_data: dict) -> str:

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
# ORDEN REAL MARKET (ENTRAR / SALIR)
# ============================================================

def place_market_order(user_id: int, symbol: str, side: str, qty: float):
    """
    Ejecuta una orden de mercado REAL en HyperLiquid.
    """

    wallet = get_user_wallet(user_id)
    private_key = get_user_private_key(user_id)

    if not wallet:
        print("❌ Sin wallet.")
        return None

    if not private_key:
        print("❌ Sin private key.")
        return None

    # qty DECIMAL REAL (no convertir a int)
    qty = float(qty)

    nonce = int(time.time() * 1000)

    order = {
        "symbol": symbol,
        "side": side,    # buy / sell
        "qty": qty,
        "nonce": nonce
    }

    signature = sign_order(private_key, order)

    payload = {
        "type": "order",
        "order": order,
        "signature": signature,
        "wallet": wallet,
    }

    r = make_request("/exchange", payload)

    if not r:
        print("❌ Exchange no respondió.")
        return None

    # Respuestas correctas del exchange
    if ("success" in r and r["success"] is True) or \
       ("status" in r and r["status"] == "ok"):
        print(f"🟢 ORDEN EJECUTADA → {side.upper()} {qty} {symbol}")
        return r

    # Manejo profesional de errores reales
    if "error" in r:
        print("❌ Error del exchange:", r["error"])
    else:
        print("❌ Orden rechazada:", r)

    return None


# ============================================================
# WRAPPERS
# ============================================================

def open_long(user_id: int, symbol: str, qty: float):
    return place_market_order(user_id, symbol, "buy", qty)


def open_short(user_id: int, symbol: str, qty: float):
    return place_market_order(user_id, symbol, "sell", qty)
