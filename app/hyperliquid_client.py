# ============================================================
# HYPERLIQUID CLIENT – Trading X Hiper Pro
# Archivo 3/9 – Conexión real, versión producción nivel banco
# ============================================================

import time
import httpx
from eth_account import Account
from eth_account.messages import encode_structured_data

from app.config import (
    HYPER_BASE_URL,
    REQUEST_TIMEOUT,
    VERBOSE_LOGS,
    PRODUCTION_MODE
)

from app.database import (
    get_user_wallet,
    get_user_private_key,
)


# ============================================================
# CLIENTE HTTP PROFESIONAL (httpx)
# ============================================================

client = httpx.Client(
    timeout=REQUEST_TIMEOUT,
    headers={"Content-Type": "application/json"}
)


def safe_log(*args):
    """Controla logs según modo producción."""
    if VERBOSE_LOGS and not PRODUCTION_MODE:
        print(*args)


# ============================================================
# REQUEST SEGURO – INFO / EXCHANGE
# ============================================================

def make_request(endpoint: str, payload: dict):
    url = f"{HYPER_BASE_URL}{endpoint}"

    try:
        res = client.post(url, json=payload)
        res.raise_for_status()
        return res.json()

    except httpx.TimeoutException:
        safe_log("⏳ Timeout con HyperLiquid:", endpoint)
        return None

    except Exception as e:
        safe_log("❌ Error en request:", endpoint, e)
        return None


# ============================================================
# TODOS LOS PARES DISPONIBLES
# ============================================================

def get_all_symbols():
    payload = {"type": "allMids"}
    r = make_request("/info", payload)

    if not r or "mids" not in r:
        safe_log("❌ No se pudo obtener lista de pares.")
        return []

    return list(r["mids"].keys())


# ============================================================
# BALANCE DEL USUARIO
# ============================================================

def get_balance(user_id: int) -> float:
    wallet = get_user_wallet(user_id)

    if not wallet:
        safe_log("❌ Usuario sin wallet configurada.")
        return 0.0

    payload = {"type": "clearinghouseState", "user": wallet}
    r = make_request("/info", payload)

    try:
        return float(r["marginSummary"]["accountValue"])
    except:
        safe_log("❌ Error leyendo balance:", r)
        return 0.0


# ============================================================
# PRECIO REAL
# ============================================================

def get_price(symbol: str):
    payload = {"type": "px", "sym": symbol}
    r = make_request("/info", payload)

    try:
        return float(r["price"])
    except:
        return None


# ============================================================
# FIRMA OFICIAL EIP-712
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
# ENVIAR ORDEN REAL
# ============================================================

def place_market_order(user_id: int, symbol: str, side: str, qty: float):

    wallet = get_user_wallet(user_id)
    private_key = get_user_private_key(user_id)

    if not wallet:
        safe_log("❌ Falta wallet.")
        return None

    if not private_key:
        safe_log("❌ Falta private key.")
        return None

    qty = float(qty)

    # Nonce único por orden
    nonce = int(time.time() * 1000)

    order = {
        "symbol": symbol,
        "side": side,    # buy or sell
        "qty": qty,
        "nonce": nonce,
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
        safe_log("❌ Sin respuesta del exchange.")
        return None

    if r.get("success") is True or r.get("status") == "ok":
        safe_log(f"🟢 ORDEN EJECUTADA → {side.upper()} {qty} {symbol}")
        return r

    safe_log("❌ Error ejecutando orden:", r)
    return None


# ============================================================
# WRAPPERS
# ============================================================

def open_long(user_id: int, symbol: str, qty: float):
    return place_market_order(user_id, symbol, "buy", qty)


def open_short(user_id: int, symbol: str, qty: float):
    return place_market_order(user_id, symbol, "sell", qty)
