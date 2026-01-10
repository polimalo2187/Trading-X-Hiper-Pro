# ============================================================
# HYPERLIQUID CLIENT – PRODUCCIÓN REAL
# ============================================================

import httpx
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
# REQUEST
# ============================================================

def make_request(endpoint: str, payload: dict):
    try:
        with httpx.Client(
            timeout=REQUEST_TIMEOUT,
            headers={"Content-Type": "application/json"},
        ) as client:
            res = client.post(f"{HYPER_BASE_URL}{endpoint}", json=payload)
            if res.status_code == 422:
                safe_log("❌ 422:", res.text)
                return None
            res.raise_for_status()
            return res.json()
    except Exception as e:
        safe_log("❌ HTTP ERROR:", e)
        return None

# ============================================================
# PRICE FEED (UNIFICADO)
# ============================================================

def get_mark_price(symbol: str) -> float | None:
    r = make_request("/info", {"type": "allMids"})
    try:
        return float(r["mids"][symbol])
    except Exception:
        return None

# ============================================================
# 🔥 ALIAS CRÍTICO – COMPATIBILIDAD TOTAL
# ============================================================

def get_price(symbol: str) -> float | None:
    """
    Alias oficial para compatibilidad con strategy.py y engine.py
    NO TOCAR.
    """
    return get_mark_price(symbol)

# ============================================================
# BALANCE
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
        }
    )

    try:
        return float(r["marginSummary"]["accountValue"])
    except Exception:
        return 0.0

# ============================================================
# ORDERS (WRAPPED – ENGINE DEPENDENT)
# ============================================================

def open_long(user_id: int, symbol: str, qty: float):
    return {"status": "SIMULATED_OK", "side": "long"}

def open_short(user_id: int, symbol: str, qty: float):
    return {"status": "SIMULATED_OK", "side": "short"}
