# ============================================================
# HYPERLIQUID CLIENT – Trading X Hyper Pro
# CLIENTE LIMPIO / ESTABLE / SIN RETRIES
# ============================================================

import time
import threading
import httpx
from typing import Any, Dict, Optional
from decimal import Decimal, ROUND_DOWN

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
# HTTP REQUEST SIMPLE
# ============================================================

_HEADERS = {"Content-Type": "application/json"}

def make_request(endpoint: str, payload: dict) -> Any:
    url = f"{HYPER_BASE_URL}{endpoint}"
    try:
        with httpx.Client(timeout=REQUEST_TIMEOUT, headers=_HEADERS) as client:
            r = client.post(url, json=payload)
            if r.status_code >= 400:
                safe_log("HTTP ERROR:", r.status_code, r.text)
                return None
            return r.json()
    except Exception as e:
        safe_log("HTTP EXCEPTION:", str(e))
        return None

# ============================================================
# NORMALIZADOR DE SÍMBOLO
# ============================================================

def norm_coin(symbol: str) -> str:
    if not symbol:
        return ""
    s = symbol.upper()
    s = s.replace("-PERP", "").replace("_PERP", "").replace("PERP", "")
    if "/" in s:
        s = s.split("/", 1)[0]
    return s.strip()

# ============================================================
# CACHE DE META Y PRICES
# ============================================================

_META = {"coin_to_asset": {}, "asset_to_sz": {}, "ts": 0.0}
_MIDS = {"data": {}, "ts": 0.0}

_META_TTL = 60
_MIDS_TTL = 2

_lock = threading.Lock()

def _refresh_meta():
    now = time.time()
    with _lock:
        if now - _META["ts"] < _META_TTL:
            return

    r = make_request("/info", {"type": "meta"})
    if not isinstance(r, dict):
        return

    universe = r.get("universe", [])
    coin_to_asset = {}
    asset_to_sz = {}

    for idx, item in enumerate(universe):
        name = item.get("name")
        if name:
            coin_to_asset[name.upper()] = idx
            asset_to_sz[idx] = int(item.get("szDecimals", 0))

    with _lock:
        _META["coin_to_asset"] = coin_to_asset
        _META["asset_to_sz"] = asset_to_sz
        _META["ts"] = now

def _refresh_mids():
    now = time.time()
    with _lock:
        if now - _MIDS["ts"] < _MIDS_TTL:
            return

    r = make_request("/info", {"type": "allMids"})
    if not isinstance(r, dict):
        return

    mids = {}
    for k, v in r.items():
        try:
            mids[k.upper()] = float(v)
        except Exception:
            pass

    with _lock:
        _MIDS["data"] = mids
        _MIDS["ts"] = now

def get_asset_index(symbol: str) -> Optional[int]:
    _refresh_meta()
    coin = norm_coin(symbol)
    return _META["coin_to_asset"].get(coin)

def get_sz_decimals(asset: int) -> int:
    _refresh_meta()
    return int(_META["asset_to_sz"].get(asset, 0))

def get_price(symbol: str) -> float:
    coin = norm_coin(symbol)
    if not coin:
        return 0.0
    _refresh_mids()
    return float(_MIDS["data"].get(coin, 0.0))

# ============================================================
# BALANCE (clearinghouseState)
# ============================================================

def get_balance(user_id: int) -> float:
    wallet = get_user_wallet(user_id)
    if not wallet:
        return 0.0

    r = make_request("/info", {"type": "clearinghouseState", "user": wallet})
    if not isinstance(r, dict):
        return 0.0

    try:
        return float(r.get("marginSummary", {}).get("accountValue", 0.0))
    except Exception:
        return 0.0

# ============================================================
# FIRMA (SDK OFICIAL)
# ============================================================

class HyperliquidSigner:
    def __init__(self, private_key: str):
        from hyperliquid.utils.signing import sign_l1_action
        from eth_account import Account
        self._account = Account.from_key(private_key)
        self._sign = sign_l1_action

    def sign(self, action: dict, nonce_ms: int):
        expires_after_ms = nonce_ms + 60_000
        is_mainnet = HYPER_BASE_URL.rstrip("/") == "https://api.hyperliquid.xyz"
        return self._sign(self._account, action, None, nonce_ms, expires_after_ms, is_mainnet)

# ============================================================
# UTILIDADES DE FORMATO (STRICT)
# ============================================================

def _to_decimal(x: float) -> Decimal:
    return Decimal(str(x))

def _fmt_size(sz: float, sz_decimals: int) -> str:
    d = _to_decimal(sz)
    if sz_decimals <= 0:
        return str(d.quantize(Decimal("1"), rounding=ROUND_DOWN))
    q = Decimal("1").scaleb(-sz_decimals)
    return str(d.quantize(q, rounding=ROUND_DOWN)).rstrip("0").rstrip(".")

def _fmt_price(px: float, sz_decimals: int) -> str:
    d = _to_decimal(px)
    if d <= 0:
        return "0"
    q = Decimal("1").scaleb(-max(0, 6 - sz_decimals))
    return str(d.quantize(q, rounding=ROUND_DOWN)).rstrip("0").rstrip(".")

# ============================================================
# PLACE MARKET ORDER (LIMIT IOC SIMPLE)
# - SIN RETRIES
# - SIN ESCALADOS
# - SI NO LLENA -> NO_FILL
# ============================================================

def place_market_order(
    user_id: int,
    symbol: str,
    side: str,
    qty_coin: float,
    slippage: float = 0.01,   # 1% simple y fijo
):
    wallet = get_user_wallet(user_id)
    private_key = get_user_private_key(user_id)

    if not wallet or not private_key:
        return {"ok": False, "filled": False, "reason": "NO_WALLET"}

    coin = norm_coin(symbol)
    asset = get_asset_index(coin)
    if asset is None:
        return {"ok": False, "filled": False, "reason": "NO_ASSET"}

    sz_decimals = get_sz_decimals(asset)
    mid = get_price(coin)
    if mid <= 0:
        return {"ok": False, "filled": False, "reason": "NO_PRICE"}

    is_buy = side.lower() == "buy"
    px = mid * (1 + slippage) if is_buy else mid * (1 - slippage)

    p_str = _fmt_price(px, sz_decimals)
    s_str = _fmt_size(qty_coin, sz_decimals)

    try:
        if float(p_str) <= 0 or float(s_str) <= 0:
            return {"ok": False, "filled": False, "reason": "BAD_PX_SZ"}
    except Exception:
        return {"ok": False, "filled": False, "reason": "BAD_PX_SZ"}

    nonce = int(time.time() * 1000)

    action = {
        "type": "order",
        "orders": [{
            "a": asset,
            "b": is_buy,
            "p": p_str,
            "s": s_str,
            "r": False,
            "t": {"limit": {"tif": "Ioc"}},
        }],
        "grouping": "na",
    }

    try:
        signer = HyperliquidSigner(private_key)
        signature = signer.sign(action, nonce)
    except Exception:
        return {"ok": False, "filled": False, "reason": "SIGN_FAIL"}

    payload = {
        "action": action,
        "nonce": nonce,
        "signature": signature,
    }

    r = make_request("/exchange", payload)
    if not isinstance(r, dict):
        return {"ok": False, "filled": False, "reason": "EXCHANGE_REJECT"}

    # DETECCIÓN SIMPLE DE FILL
    filled_sz = 0.0
    for k in ("filledSz", "filled", "filled_qty", "filledQty"):
        if k in r:
            try:
                filled_sz = float(r.get(k, 0))
            except Exception:
                pass

    if filled_sz > 0:
        return {
            "ok": True,
            "filled": True,
            "filled_sz": filled_sz,
            "coin": coin,
            "side": side,
            "price": p_str,
            "size": s_str,
        }

    return {
        "ok": True,
        "filled": False,
        "reason": "NO_FILL",
        "coin": coin,
        "side": side,
        "price": p_str,
        "size": s_str,
    }

# ============================================================
# WRAPPERS
# ============================================================

def open_long(user_id: int, symbol: str, qty_coin: float):
    return place_market_order(user_id, symbol, "buy", qty_coin)

def open_short(user_id: int, symbol: str, qty_coin: float):
    return place_market_order(user_id, symbol, "sell", qty_coin)
