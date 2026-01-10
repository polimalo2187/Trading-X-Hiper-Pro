# ============================================================
# HYPERLIQUID CLIENT – PRODUCCIÓN REAL (CONTRATO ESTABLE)
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
# LOG SEGURO
# ============================================================

def safe_log(*args):
    if VERBOSE_LOGS and not PRODUCTION_MODE:
        print(*args)

# ============================================================
# REQUEST BASE
# ============================================================

def make_request(endpoint: str, payload: dict):
    try:
        with httpx.Client(
            timeout=REQUEST_TIMEOUT,
            headers={"Content-Type": "application/json"},
        ) as client:
            res = client.post(f"{HYPER_BASE_URL}{endpoint}", json=payload)

            if res.status_code == 422:
                safe_log("❌ 422 Hyperliquid:", res.text)
                return None

            res.raise_for_status()
            return res.json()

    except Exception as e:
        safe_log("❌ HTTP ERROR:", e)
        return None

# ============================================================
# PRICE FEED (CONTRATO OFICIAL)
# ============================================================

def get_price(symbol: str) -> float | None:
    r = make_request("/info", {"type": "allMids"})
    try:
        return float(r["mids"][symbol])
    except Exception:
        return None

# Alias defensivo (por compatibilidad futura)
get_mark_price = get_price

# ============================================================
# BALANCE
# ============================================================

def get_balance(user_id: int) -> float:
    wallet = get_user_wallet(user_id)
    if not wallet:
        return 0.0

    r = make_request("/info", {
        "type": "clearinghouseState",
        "user": wallet,
    })

    try:
        return float(r["marginSummary"]["accountValue"])
    except Exception:
        return 0.0

# ============================================================
# FIRMA EIP-712
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
# ORDEN MARKET REAL (CONTRATO ENGINE)
# ============================================================

def place_market_order(user_id: int, symbol: str, side: str, qty: float):
    wallet = get_user_wallet(user_id)
    private_key = get_user_private_key(user_id)

    if not wallet or not private_key:
        safe_log("❌ Usuario sin wallet o private key")
        return None

    nonce = time.time_ns()

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
        return None

    if r.get("success") or r.get("status") in ("ok", "accepted", "queued"):
        return r

    safe_log("❌ Orden rechazada:", r)
    return None

# ============================================================
# WRAPPERS (COMPATIBILIDAD)
# ============================================================

def open_long(user_id: int, symbol: str, qty: float):
    return place_market_order(user_id, symbol, "buy", qty)

def open_short(user_id: int, symbol: str, qty: float):
    return place_market_order(user_id, symbol, "sell", qty)
