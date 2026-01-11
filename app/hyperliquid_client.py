# ============================================================
# HYPERLIQUID CLIENT – Trading X Hyper Pro
# PRODUCCIÓN REAL – BANK GRADE (COMPATIBLE)
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
# LOG CONTROLADO
# ============================================================

def safe_log(*args):
    if VERBOSE_LOGS and not PRODUCTION_MODE:
        print(*args)


# ============================================================
# HTTP REQUEST
# ============================================================

def make_request(endpoint: str, payload: dict):
    try:
        with httpx.Client(
            timeout=REQUEST_TIMEOUT,
            headers={"Content-Type": "application/json"},
        ) as client:
            r = client.post(f"{HYPER_BASE_URL}{endpoint}", json=payload)
            r.raise_for_status()
            return r.json()
    except Exception as e:
        safe_log("❌ Hyperliquid HTTP error:", endpoint, e)
        return None


# ============================================================
# MARKET CACHE (allMids)
# ============================================================

_MARKET_CACHE = {"mids": {}, "ts": 0}
CACHE_TTL = 3


def _refresh_market_cache():
    now = time.time()
    if now - _MARKET_CACHE["ts"] < CACHE_TTL:
        return

    r = make_request("/info", {"type": "allMids"})
    if r and "mids" in r:
        _MARKET_CACHE["mids"] = r["mids"]
        _MARKET_CACHE["ts"] = now


# ============================================================
# PRECIO REAL
# ============================================================

def get_price(symbol: str):
    """
    symbol: BTC-PERP, ETH-PERP, etc
    """
    _refresh_market_cache()
    mids = _MARKET_CACHE["mids"]

    if symbol not in mids:
        safe_log("❌ Símbolo inexistente:", symbol)
        return None

    try:
        return float(mids[symbol])
    except Exception:
        return None


# ============================================================
# BALANCE REAL (🔥 RESTAURADO – FIX CRÍTICO)
# ============================================================

def get_balance(user_id: int) -> float:
    """
    Devuelve el accountValue real del usuario en Hyperliquid
    Mantiene compatibilidad TOTAL con bot.py y engine
    """
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
# EIP-712 SIGN (HYPERLIQUID REAL)
# ============================================================

def sign_action(private_key: str, action: dict):
    msg = encode_structured_data({
        "types": {
            "EIP712Domain": [{"name": "name", "type": "string"}],
            "Action": [
                {"name": "nonce", "type": "uint256"},
                {"name": "action", "type": "string"},
            ],
        },
        "primaryType": "Action",
        "domain": {"name": "Hyperliquid"},
        "message": {
            "nonce": action["nonce"],
            "action": action["action"],
        },
    })

    signed = Account.sign_message(msg, private_key)
    return signed.signature.hex()


# ============================================================
# MARKET ORDER REAL
# ============================================================

def place_market_order(user_id: int, symbol: str, side: str, qty: float):
    wallet = get_user_wallet(user_id)
    private_key = get_user_private_key(user_id)

    if not wallet or not private_key:
        safe_log("❌ Wallet / key missing")
        return None

    nonce = int(time.time() * 1e9)

    action = {
        "type": "order",
        "orders": [{
            "asset": symbol,
            "isBuy": side == "buy",
            "sz": str(round(float(qty), 6)),
            "orderType": {"market": {}},
            "reduceOnly": False,
        }],
    }

    signed_payload = {
        "nonce": nonce,
        "action": str(action),
    }

    signature = sign_action(private_key, signed_payload)

    payload = {
        "action": action,
        "nonce": nonce,
        "signature": signature,
        "wallet": wallet,
    }

    r = make_request("/exchange", payload)
    if not r:
        safe_log("❌ Order rejected")
        return None

    safe_log(f"🟢 MARKET ORDER {side.upper()} {qty} {symbol}")
    return r


# ============================================================
# WRAPPERS
# ============================================================

def open_long(user_id: int, symbol: str, qty: float):
    return place_market_order(user_id, symbol, "buy", qty)


def open_short(user_id: int, symbol: str, qty: float):
    return place_market_order(user_id, symbol, "sell", qty)
