# ============================================================
# HYPERLIQUID CLIENT – PRODUCCIÓN REAL
# ============================================================

import httpx
import time
from app.config import (
    HYPER_BASE_URL,
    REQUEST_TIMEOUT,
    VERBOSE_LOGS,
    PRODUCTION_MODE,
)

from app.database import get_user_wallet, get_user_private_key

# ============================================================
# LOG
# ============================================================

def safe_log(*args):
    if VERBOSE_LOGS and not PRODUCTION_MODE:
        print(*args)

# ============================================================
# CORE REQUEST
# ============================================================

def make_request(endpoint: str, payload: dict):
    try:
        with httpx.Client(
            timeout=REQUEST_TIMEOUT,
            headers={"Content-Type": "application/json"},
        ) as client:
            res = client.post(f"{HYPER_BASE_URL}{endpoint}", json=payload)
            res.raise_for_status()
            return res.json()
    except Exception as e:
        safe_log("❌ HTTP ERROR:", e)
        return None

# ============================================================
# PRICE FEED
# ============================================================

def get_price(symbol: str) -> float | None:
    r = make_request("/info", {"type": "allMids"})
    if not r or "mids" not in r:
        return None
    try:
        return float(r["mids"][symbol])
    except Exception:
        return None

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
# MARKET ORDER (REAL)
# ============================================================

def place_market_order(
    user_id: int,
    symbol: str,
    side: str,
    qty: float,
):
    wallet = get_user_wallet(user_id)
    priv_key = get_user_private_key(user_id)

    if not wallet or not priv_key:
        raise RuntimeError("Wallet o private key no disponible")

    payload = {
        "type": "order",
        "user": wallet,
        "order": {
            "coin": symbol,
            "isBuy": side == "BUY",
            "sz": qty,
            "limitPx": None,
            "orderType": "Market",
            "reduceOnly": False,
        },
        "nonce": int(time.time() * 1000),
        "signature": priv_key,  # asumimos signing upstream como ya lo tenías
    }

    r = make_request("/exchange", payload)
    if not r:
        raise RuntimeError("Order rejected by Hyperliquid")

    return r
