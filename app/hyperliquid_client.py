# ============================================================
# HYPERLIQUID CLIENT – Trading X Hyper Pro
# Archivo 3/9 – Cliente real de exchange (PRODUCCIÓN)
# ============================================================

import time
import httpx
from eth_account import Account
from eth_account.messages import encode_structured_data

from app.config import (
    HYPER_BASE_URL,
    REQUEST_TIMEOUT,
    VERBOSE_LOGS,
    PRODUCTION_MODE,
)

from app.database import (
    get_user_wallet,
    get_user_private_key,
)

# ============================================================
# LOG CONTROLADO (NO FILTRA INFO EN PRODUCCIÓN)
# ============================================================

def safe_log(*args):
    if VERBOSE_LOGS and not PRODUCTION_MODE:
        print(*args)


# ============================================================
# HTTP REQUEST SEGURO (SYNC – ESTABLE)
# ============================================================

def make_request(endpoint: str, payload: dict):
    url = f"{HYPER_BASE_URL}{endpoint}"

    try:
        with httpx.Client(
            timeout=REQUEST_TIMEOUT,
            headers={"Content-Type": "application/json"},
        ) as client:
            res = client.post(url, json=payload)
            res.raise_for_status()
            return res.json()

    except httpx.TimeoutException:
        safe_log("⏳ Timeout HyperLiquid:", endpoint)
        return None

    except Exception as e:
        safe_log("❌ Error HTTP HyperLiquid:", endpoint, e)
        return None


# ============================================================
# OBTENER TODOS LOS PARES DISPONIBLES
# ============================================================

def get_all_symbols():
    r = make_request("/info", {"type": "allMids"})

    if not r or "mids" not in r:
        safe_log("❌ No se pudieron obtener símbolos.")
        return []

    return list(r["mids"].keys())


# ============================================================
# BALANCE REAL DEL USUARIO
# ============================================================

def get_balance(user_id: int) -> float:
    wallet = get_user_wallet(user_id)

    if not wallet:
        return 0.0

    r = make_request(
        "/info",
        {
            "type": "clearinghouseState",
            "user": wallet,
        },
    )

    try:
        return float(r["marginSummary"]["accountValue"])
    except Exception:
        safe_log("❌ Error leyendo balance:", r)
        return 0.0


# ============================================================
# PRECIO ACTUAL DEL PAR (FIX 422)
# ============================================================

def get_price(symbol: str):
    r = make_request("/info", {"type": "allMids"})

    try:
        return float(r["mids"][symbol])
    except Exception:
        safe_log("❌ Precio no disponible para:", symbol)
        return None


# ============================================================
# FIRMA EIP-712 (ORDENES)
# ============================================================

def sign_order(private_key: str, order_data: dict) -> str:
    typed_data = {
        "types": {
            "EIP712Domain": [
                {"name": "name", "type": "string"},
            ],
            "Order": [
                {"name": "symbol", "type": "string"},
                {"name": "side", "type": "string"},
                {"name": "qty", "type": "uint256"},
                {"name": "nonce", "type": "uint256"},
            ],
        },
        "primaryType": "Order",
        "domain": {
            "name": "Hyperliquid",
        },
        "message": order_data,
    }

    encoded = encode_structured_data(typed_data)
    signed = Account.sign_message(encoded, private_key=private_key)

    return signed.signature.hex()


# ============================================================
# EJECUCIÓN DE ORDEN MARKET REAL
# ============================================================

def place_market_order(user_id: int, symbol: str, side: str, qty: float):
    wallet = get_user_wallet(user_id)
    private_key = get_user_private_key(user_id)

    if not wallet or not private_key:
        safe_log("❌ Usuario sin wallet o private key.")
        return None

    nonce = time.time_ns()
    qty = float(qty)

    order = {
        "symbol": symbol,
        "side": side,
        "qty": qty,
        "nonce": nonce,
        "orderType": "market",
        "isBuy": side == "buy",
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
        safe_log("❌ Exchange sin respuesta.")
        return None

    if r.get("success") or r.get("status") in ("ok", "accepted", "queued"):
        safe_log(f"🟢 ORDEN EJECUTADA: {side.upper()} {qty} {symbol}")
        return r

    safe_log("❌ Orden rechazada:", r)
    return None


# ============================================================
# WRAPPERS SIMPLES
# ============================================================

def open_long(user_id: int, symbol: str, qty: float):
    return place_market_order(user_id, symbol, "buy", qty)


def open_short(user_id: int, symbol: str, qty: float):
    return place_market_order(user_id, symbol, "sell", qty)
