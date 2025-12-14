import time
import hmac
import hashlib
import requests
import json
from app.config import HYPER_BASE_URL
from app.database import get_user_wallet


# ============================================================
# FUNCIONES BASE DE HYPERLIQUID (SPOT SYNTHETIC)
# ============================================================

def make_request(endpoint, payload):
    """
    Envia solicitud a HyperLiquid.
    Se usa el endpoint universal /info que recibe instrucciones JSON.
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
# CONSULTAR BALANCE USDC
# ============================================================

def get_balance(user_id):
    """
    Obtiene el balance disponible del usuario en HyperLiquid.
    HyperLiquid trabaja con wallets directamente → se conecta vía dictado on-chain.
    """

    wallet = get_user_wallet(user_id)

    if not wallet:
        print("❌ Usuario sin wallet configurada.")
        return 0

    payload = {
        "type": "spot",
        "user": wallet
    }

    r = make_request("/balance", payload)

    if not r or "balances" not in r:
        print("❌ Error leyendo balance:", r)
        return 0

    balances = r["balances"]

    if "USDC" not in balances:
        return 0

    return float(balances["USDC"])


# ============================================================
# PRECIO DEL PAR (Ejemplo BTC-USDC)
# ============================================================

def get_price(symbol):
    payload = {
        "type": "px",
        "sym": symbol
    }

    r = make_request("/price", payload)

    if not r or "price" not in r:
        return None

    return float(r["price"])


# ============================================================
# COLOCAR ORDEN MARKET
# ============================================================

def place_market_order(user_id, symbol, side, amount):
    """
    side = "buy" o "sell"
    amount = cantidad en USDC o cantidad en asset dependiendo del par
    """

    wallet = get_user_wallet(user_id)

    if not wallet:
        print("❌ Usuario sin wallet configurada.")
        return None

    order = {
        "type": "order",
        "action": "market",
        "sym": symbol,
        "side": side,
        "sz": amount,
        "wallet": wallet
    }

    r = make_request("/trade", order)

    if not r or "success" not in r:
        print("❌ Error ejecutando orden:", r)
        return None

    print(f"🟢 Orden ejecutada en {symbol}: {side.upper()} - Cantidad: {amount}")
    return r


# ============================================================
# BUY MARKET (Wrapper)
# ============================================================

def market_buy(user_id, symbol, amount):
    return place_market_order(user_id, symbol, "buy", amount)


# ============================================================
# SELL MARKET (Wrapper)
# ============================================================

def market_sell(user_id, symbol, amount):
    return place_market_order(user_id, symbol, "sell", amount)
