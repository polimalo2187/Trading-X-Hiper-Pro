# hyperliquid_client.py (limpio)
import time
import threading
from typing import Any, Dict, Optional, Tuple, List
from decimal import Decimal, ROUND_DOWN, InvalidOperation

import httpx
from app.config import HYPER_BASE_URL, REQUEST_TIMEOUT

_DEFAULT_HEADERS = {"Content-Type": "application/json"}
_http_lock = threading.Lock()
_http_client: Optional[httpx.Client] = None

def _get_http_client(timeout: float) -> httpx.Client:
    global _http_client
    with _http_lock:
        if _http_client is None:
            _http_client = httpx.Client(
                timeout=timeout,
                headers=_DEFAULT_HEADERS,
                limits=httpx.Limits(max_keepalive_connections=20, max_connections=50),
            )
        else:
            try:
                _http_client.timeout = httpx.Timeout(timeout)
            except Exception:
                pass
        return _http_client

def post(endpoint: str, payload: dict, timeout: Optional[float] = None) -> Any:
    if timeout is None:
        timeout = REQUEST_TIMEOUT
    url = f"{HYPER_BASE_URL}{endpoint}"
    r = _get_http_client(timeout).post(url, json=payload)
    if r.status_code >= 400:
        return {"_http_error": True, "_http_status": r.status_code, "_http_body": r.text}
    try:
        return r.json()
    except Exception:
        return {"_http_error": True, "_http_status": r.status_code, "_http_body": "bad_json"}

def norm_coin(symbol: str) -> str:
    if not isinstance(symbol, str):
        return ""
    s = symbol.strip().upper()
    s = s.replace("-PERP", "").replace("_PERP", "").replace("PERP", "")
    if "/" in s:
        s = s.split("/", 1)[0].strip()
    return s

# ---------- meta cache (solo para size decimals) ----------
_META_CACHE: Dict[str, Any] = {"coin_to_asset": {}, "asset_to_sz": {}, "ts": 0.0}
_cache_lock = threading.Lock()
META_TTL = 60.0

def refresh_meta_cache() -> None:
    now = time.time()
    with _cache_lock:
        if now - _META_CACHE["ts"] < META_TTL:
            return
    r = post("/info", {"type": "meta"})
    if not isinstance(r, dict) or "universe" not in r:
        return
    coin_to_asset: Dict[str, int] = {}
    asset_to_sz: Dict[int, int] = {}
    universe = r.get("universe") if isinstance(r.get("universe"), list) else []
    for i, item in enumerate(universe):
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        if name:
            coin_to_asset[str(name).upper()] = i
        try:
            szd = int(item.get("szDecimals", 0))
        except Exception:
            szd = 0
        asset_to_sz[i] = max(szd, 0)

    with _cache_lock:
        _META_CACHE["coin_to_asset"] = coin_to_asset
        _META_CACHE["asset_to_sz"] = asset_to_sz
        _META_CACHE["ts"] = now

def get_asset_index(symbol: str) -> Optional[int]:
    refresh_meta_cache()
    coin = norm_coin(symbol)
    with _cache_lock:
        return _META_CACHE["coin_to_asset"].get(coin)

def get_sz_decimals(asset_index: int) -> int:
    refresh_meta_cache()
    with _cache_lock:
        return int(_META_CACHE["asset_to_sz"].get(asset_index, 0) or 0)

# ---------- formatting: SOLO size ----------
def _to_decimal(x: float) -> Decimal:
    return Decimal(str(x))

def _quant(sz_decimals: int) -> Decimal:
    return Decimal("1") if sz_decimals <= 0 else Decimal("1").scaleb(-sz_decimals)

def format_size(sz: float, sz_decimals: int) -> str:
    try:
        d = _to_decimal(sz)
        q = _quant(sz_decimals)
        out = d.quantize(q, rounding=ROUND_DOWN)
        s = format(out, "f")
        if "." in s:
            s = s.rstrip("0").rstrip(".")
        return s if s else "0"
    except (InvalidOperation, Exception):
        return "0"

# ---------- info endpoints ----------
def get_l2_book(coin: str) -> Any:
    return post("/info", {"type": "l2Book", "coin": norm_coin(coin)})

def get_all_mids() -> Any:
    return post("/info", {"type": "allMids"})

def get_clearinghouse_state(user_wallet: str) -> Any:
    return post("/info", {"type": "clearinghouseState", "user": user_wallet})

# ---------- signing + exchange ----------
class HyperliquidSigner:
    def __init__(self, private_key: str):
        from hyperliquid.utils.signing import sign_l1_action
        from eth_account import Account
        self._account = Account.from_key(private_key)
        self._sign_l1_action = sign_l1_action

    def sign(self, action: dict, nonce_ms: int,
             vault_address: Optional[str] = None,
             expires_after_ms: Optional[int] = None,
             is_mainnet: Optional[bool] = None) -> Any:
        if expires_after_ms is None:
            expires_after_ms = nonce_ms + 60_000
        if is_mainnet is None:
            is_mainnet = (str(HYPER_BASE_URL).rstrip("/") == "https://api.hyperliquid.xyz")
        return self._sign_l1_action(self._account, action, vault_address, nonce_ms, expires_after_ms, is_mainnet)

def exchange(action: dict, private_key: str,
             vault_address: Optional[str] = None,
             expires_after_ms: Optional[int] = None) -> Any:
    nonce = int(time.time() * 1000)
    expires_after_ms = expires_after_ms or (nonce + 60_000)
    signer = HyperliquidSigner(private_key)
    signature = signer.sign(action, nonce, vault_address=vault_address, expires_after_ms=expires_after_ms)

    payload = {"action": action, "nonce": nonce, "signature": signature, "expiresAfter": expires_after_ms}
    if vault_address:
        payload["vaultAddress"] = vault_address
    return post("/exchange", payload)

# ---------- parse exchange response ----------
def unwrap_exchange(resp: Any) -> Tuple[str, Any]:
    if not isinstance(resp, dict):
        return ("unknown", resp)
    st = str(resp.get("status") or "").lower()
    if st in ("ok", "err") and "response" in resp:
        return (st, resp.get("response"))
    return ("unknown", resp)

def extract_statuses(resp: Any) -> List[Any]:
    st, inner = unwrap_exchange(resp)
    if st != "ok" or not isinstance(inner, dict):
        return []
    data = inner.get("data")
    if not isinstance(data, dict):
        return []
    statuses = data.get("statuses")
    return statuses if isinstance(statuses, list) else []

def parse_first_status(resp: Any) -> Dict[str, Any]:
    """
    Devuelve algo como:
      {"kind":"filled","filled_sz":1.23} / {"kind":"error","error":"MinTradeNtl"} / {"kind":"resting"}
    """
    out = {"kind": "unknown", "error": "", "filled_sz": 0.0}
    statuses = extract_statuses(resp)
    if not statuses or not isinstance(statuses[0], dict):
        return out
    s0 = statuses[0]
    if "error" in s0:
        out["kind"] = "error"
        out["error"] = str(s0.get("error") or "")
        return out
    if "filled" in s0 and isinstance(s0.get("filled"), dict):
        out["kind"] = "filled"
        f = s0["filled"]
        for k in ("totalSz", "filledSz", "sz"):
            if k in f:
                try:
                    out["filled_sz"] = float(f.get(k) or 0)
                    break
                except Exception:
                    pass
        return out
    if "resting" in s0:
        out["kind"] = "resting"
        return out
    return out
