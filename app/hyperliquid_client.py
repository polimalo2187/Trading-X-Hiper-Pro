# ============================================================
# HYPERLIQUID CLIENT – Trading X Hyper Pro
# PRODUCCIÓN REAL – BANK GRADE (VERSIÓN FINAL BLINDADA)
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
    if VERBOSE_LOGS or not PRODUCTION_MODE:
        print(*args)

# ============================================================
# HTTP REQUEST CON REINTENTOS Y TIMEOUT GLOBAL
# ============================================================

def make_request(endpoint: str, payload: dict, retries: int = 4, backoff: float = 1.0, timeout: float = None):
    """
    Request POST a Hyperliquid con blindaje total.
    retries: número de intentos
    backoff: tiempo incremental entre intentos
    timeout: timeout en segundos (fallback a REQUEST_TIMEOUT)
    """
    if timeout is None:
        timeout = REQUEST_TIMEOUT

    for attempt in range(1, retries + 1):
        try:
            with httpx.Client(timeout=timeout, headers={"Content-Type": "application/json"}) as client:
                r = client.post(f"{HYPER_BASE_URL}{endpoint}", json=payload)
                r.raise_for_status()
                data = r.json()

                if isinstance(data, (dict, list)):
                    return data

                raise ValueError("Respuesta JSON inválida")

        except (httpx.RequestError, httpx.HTTPStatusError, ValueError) as e:
            safe_log(f"❌ HTTP error [{attempt}/{retries}] {endpoint}:", e)
        except Exception as e:
            safe_log(f"❌ Unknown error [{attempt}/{retries}] {endpoint}:", e)

        if attempt < retries:
            time.sleep(backoff * attempt)

    return {}

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
    if not isinstance(r, list):
        return

    try:
        _MARKET_CACHE["mids"] = {str(symbol): float(price) for symbol, price in r}
        _MARKET_CACHE["ts"] = now
    except Exception as e:
        safe_log("❌ Error procesando market cache:", e)

# ============================================================
# PRECIO REAL
# ============================================================

def get_price(symbol: str):
    # --------------------------------------------------------
    # FIX CRÍTICO: NORMALIZAR A FORMATO PERPETUO
    # --------------------------------------------------------
    symbol = symbol if symbol.endswith("-PERP") else f"{symbol}-PERP"
    # --------------------------------------------------------

    _refresh_market_cache()
    mids = _MARKET_CACHE.get("mids", {})

    price = mids.get(symbol)
    if price is None:
        safe_log("❌ Símbolo inexistente o precio nulo:", symbol)
        return 0.0

    try:
        return float(price)
    except Exception as e:
        safe_log("❌ Error convirtiendo precio:", symbol, e)
        return 0.0

# ============================================================
# BALANCE REAL
# ============================================================

def get_balance(user_id: int) -> float:
    wallet = get_user_wallet(user_id)
    if not wallet:
        return 0.0

    r = make_request("/info", {"type": "clearinghouseState", "user": wallet})
    if not isinstance(r, dict):
        return 0.0

    try:
        account_value = r.get("marginSummary", {}).get("accountValue", 0)
        return float(account_value)
    except Exception as e:
        safe_log("❌ Error leyendo balance:", e, r)
        return 0.0

# ============================================================
# EIP-712 SIGN
# ============================================================

def sign_action(private_key: str, action: dict):
    if not isinstance(private_key, str) or not isinstance(action, dict):
        safe_log("❌ sign_action: invalid types")
        return None

    try:
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
    except Exception as e:
        safe_log("❌ Error firmando acción:", e)
        return None

# ============================================================
# MARKET ORDER REAL
# ============================================================

def place_market_order(user_id: int, symbol: str, side: str, qty: float):
    # --------------------------------------------------------
    # FIX CRÍTICO: NORMALIZAR A FORMATO PERPETUO
    # --------------------------------------------------------
    symbol = symbol if symbol.endswith("-PERP") else f"{symbol}-PERP"
    # --------------------------------------------------------

    wallet = get_user_wallet(user_id)
    private_key = get_user_private_key(user_id)

    if not wallet or not private_key:
        safe_log("❌ Wallet / key missing")
        return None

    nonce = int(time.time() * 1e9)
    qty = max(0.000001, float(qty))

    action = {
        "type": "order",
        "orders": [{
            "asset": symbol,
            "isBuy": side.lower() == "buy",
            "sz": str(round(qty, 6)),
            "orderType": {"market": {}},
            "reduceOnly": False,
        }],
    }

    signed_payload = {"nonce": nonce, "action": str(action)}
    signature = sign_action(private_key, signed_payload)
    if not signature:
        safe_log("❌ Firma inválida")
        return None

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
