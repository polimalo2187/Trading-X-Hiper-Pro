# ============================================================
# HYPERLIQUID CLIENT – Compacto y estable (COMPAT + PRICE RULE + MIN NOTIONAL FIX)
# Compatibilidad:
#   - market_scanner.py importa: make_request
#   - trading_engine.py usa: place_market_order, get_price, get_balance
#   - trading_engine.py importa: get_best_bid_ask
# FIX:
#   - Precio válido HL: MAX_DECIMALS=6, max_px_decimals=6-szDecimals, 5 sig figs
#   - Min notional >= 10 post-rounding (sube size con ROUND_UP si hace falta)
# ============================================================

import time
import threading
from typing import Any, Dict, Optional, Tuple
from decimal import Decimal, ROUND_DOWN, ROUND_UP, InvalidOperation

import httpx

from app.config import HYPER_BASE_URL, REQUEST_TIMEOUT, VERBOSE_LOGS, PRODUCTION_MODE
from app.database import get_user_wallet, get_user_private_key

# ---------------------------
# Logging mínimo
# ---------------------------
def _log(*args):
    if VERBOSE_LOGS or not PRODUCTION_MODE:
        print(*args)

def _must(*args):
    print(*args)

# ---------------------------
# HTTP (singleton)
# ---------------------------
_HEADERS = {"Content-Type": "application/json"}
_http_lock = threading.Lock()
_http: Optional[httpx.Client] = None

def _client(timeout: float) -> httpx.Client:
    global _http
    with _http_lock:
        if _http is None:
            _http = httpx.Client(
                timeout=timeout,
                headers=_HEADERS,
                limits=httpx.Limits(max_keepalive_connections=20, max_connections=50),
            )
        else:
            try:
                _http.timeout = httpx.Timeout(timeout)
            except Exception:
                pass
        return _http

def _post(endpoint: str, payload: dict, timeout: Optional[float] = None) -> Any:
    if timeout is None:
        timeout = REQUEST_TIMEOUT
    url = f"{HYPER_BASE_URL}{endpoint}"
    try:
        r = _client(timeout).post(url, json=payload)
        if r.status_code >= 400:
            return {"_http_error": True, "_http_status": r.status_code, "_http_body": r.text}
        return r.json()
    except Exception as e:
        return {"_http_error": True, "_http_status": 0, "_http_body": f"exception:{e}"}

# ============================================================
# ✅ COMPAT: market_scanner.py -> from app.hyperliquid_client import make_request
# ============================================================
def make_request(
    endpoint: str,
    payload: dict,
    retries: int = 3,
    backoff: float = 0.5,
    timeout: Optional[float] = None,
):
    last = None
    r = max(1, int(retries or 1))
    b = float(backoff or 0.0)
    for attempt in range(1, r + 1):
        last = _post(endpoint, payload, timeout=timeout)
        if isinstance(last, dict) and last.get("_http_error"):
            if attempt < r:
                time.sleep(b * attempt)
                continue
        return last
    return last

# ---------------------------
# Symbol utils
# ---------------------------
def norm_coin(symbol: str) -> str:
    if not isinstance(symbol, str):
        return ""
    s = symbol.strip().upper()
    s = s.replace("-PERP", "").replace("_PERP", "").replace("PERP", "")
    if "/" in s:
        s = s.split("/", 1)[0].strip()
    return s

# ---------------------------
# Meta cache: asset index + szDecimals
# ---------------------------
_META = {"coin_to_asset": {}, "asset_to_sz": {}, "ts": 0.0}
_meta_lock = threading.Lock()
META_TTL = 60.0

def _refresh_meta() -> None:
    now = time.time()
    with _meta_lock:
        if now - _META["ts"] < META_TTL:
            return

    r = make_request("/info", {"type": "meta"}, retries=2, backoff=0.2)
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

    with _meta_lock:
        _META["coin_to_asset"] = coin_to_asset
        _META["asset_to_sz"] = asset_to_sz
        _META["ts"] = now

def get_asset_index(symbol: str) -> Optional[int]:
    _refresh_meta()
    coin = norm_coin(symbol)
    with _meta_lock:
        return _META["coin_to_asset"].get(coin)

def get_sz_decimals(asset_index: int) -> int:
    _refresh_meta()
    with _meta_lock:
        return int(_META["asset_to_sz"].get(asset_index, 0) or 0)

# ---------------------------
# Mids cache (allMids) para get_price()
# ---------------------------
_MIDS = {"mids": {}, "ts": 0.0}
_mids_lock = threading.Lock()
MIDS_TTL = 2.0

def _refresh_mids() -> None:
    now = time.time()
    with _mids_lock:
        if now - _MIDS["ts"] < MIDS_TTL:
            return
    r = make_request("/info", {"type": "allMids"}, retries=2, backoff=0.2)
    if not isinstance(r, dict):
        return
    mids: Dict[str, float] = {}
    for k, v in r.items():
        if isinstance(k, str) and not k.startswith("@"):
            try:
                mids[k.upper()] = float(v)
            except Exception:
                pass
    with _mids_lock:
        _MIDS["mids"] = mids
        _MIDS["ts"] = now

def get_price(symbol: str) -> float:
    coin = norm_coin(symbol)
    if not coin:
        return 0.0
    _refresh_mids()
    with _mids_lock:
        px = _MIDS["mids"].get(coin)
    return float(px) if px else 0.0

# ---------------------------
# L2 best bid/ask
# ---------------------------
def _get_best_bid_ask(symbol: str) -> Tuple[float, float]:
    coin = norm_coin(symbol)
    if not coin:
        return (0.0, 0.0)

    book = make_request("/info", {"type": "l2Book", "coin": coin}, retries=2, backoff=0.2)
    if not isinstance(book, dict):
        return (0.0, 0.0)

    levels = book.get("levels")
    if not isinstance(levels, list) or len(levels) < 2:
        return (0.0, 0.0)

    bids = levels[0] if isinstance(levels[0], list) else []
    asks = levels[1] if isinstance(levels[1], list) else []

    try:
        best_bid = float(bids[0].get("px", 0) or 0) if bids and isinstance(bids[0], dict) else 0.0
        best_ask = float(asks[0].get("px", 0) or 0) if asks and isinstance(asks[0], dict) else 0.0
        return (best_bid, best_ask)
    except Exception:
        return (0.0, 0.0)

def get_best_bid_ask(symbol: str) -> Tuple[float, float]:
    return _get_best_bid_ask(symbol)

# ---------------------------
# Formatting helpers
# ---------------------------
def _strip0(s: str) -> str:
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s if s else "0"

def _to_dec(x: float) -> Decimal:
    return Decimal(str(x))

def _quant(decimals: int) -> Decimal:
    return Decimal("1") if decimals <= 0 else Decimal("1").scaleb(-decimals)

def _fmt_size_round(sz: float, sz_decimals: int, rounding) -> str:
    try:
        d = _to_dec(float(sz))
        q = _quant(sz_decimals)
        out = d.quantize(q, rounding=rounding)
        return _strip0(format(out, "f"))
    except (InvalidOperation, Exception):
        return "0"

def _fmt_size(sz: float, sz_decimals: int) -> str:
    return _fmt_size_round(sz, sz_decimals, ROUND_DOWN)

def _fmt_price_hl(px: float, sz_decimals: int, is_buy: bool) -> str:
    MAX_DECIMALS = 6
    rnd = ROUND_UP if is_buy else ROUND_DOWN

    try:
        d = _to_dec(float(px))
        if d <= 0:
            return "0"

        max_px_decimals = max(0, MAX_DECIMALS - int(sz_decimals or 0))

        if d >= 1:
            int_part = int(d)
            digits_before = len(str(abs(int_part))) if int_part != 0 else 1

            if digits_before >= 5:
                out = d.quantize(Decimal("1"), rounding=rnd)
                return _strip0(format(out, "f"))

            allowed_sig_decimals = max(0, 5 - digits_before)
            allowed_decimals = min(max_px_decimals, allowed_sig_decimals)
            q = _quant(allowed_decimals)
            out = d.quantize(q, rounding=rnd)
            return _strip0(format(out, "f"))

        q = _quant(max_px_decimals)
        out = d.quantize(q, rounding=rnd)
        return _strip0(format(out, "f"))

    except (InvalidOperation, Exception):
        return "0"

# ---------------------------
# Balance
# ---------------------------
def get_balance(user_id: int) -> float:
    wallet = get_user_wallet(user_id)
    if not wallet:
        return 0.0
    r = make_request("/info", {"type": "clearinghouseState", "user": wallet}, retries=2, backoff=0.2)
    if not isinstance(r, dict):
        return 0.0
    try:
        return float(r.get("marginSummary", {}).get("accountValue", 0) or 0)
    except Exception:
        return 0.0

# ---------------------------
# Signing + exchange
# ---------------------------
class HyperliquidSigner:
    def __init__(self, private_key: str):
        from hyperliquid.utils.signing import sign_l1_action
        from eth_account import Account
        self._acct = Account.from_key(private_key)
        self._sign = sign_l1_action

    def sign(
        self,
        action: dict,
        nonce_ms: int,
        vault_address: Optional[str] = None,
        expires_after_ms: Optional[int] = None,
        is_mainnet: Optional[bool] = None,
    ):
        if expires_after_ms is None:
            expires_after_ms = nonce_ms + 60_000
        if is_mainnet is None:
            is_mainnet = (str(HYPER_BASE_URL).rstrip("/") == "https://api.hyperliquid.xyz")
        return self._sign(self._acct, action, vault_address, nonce_ms, expires_after_ms, is_mainnet)

def _exchange(action: dict, private_key: str, vault_address: Optional[str] = None) -> Any:
    nonce = int(time.time() * 1000)
    expires_after = nonce + 60_000
    sig = HyperliquidSigner(private_key).sign(action, nonce, vault_address=vault_address, expires_after_ms=expires_after)
    payload = {"action": action, "nonce": nonce, "signature": sig, "expiresAfter": expires_after}
    if vault_address:
        payload["vaultAddress"] = vault_address
    return make_request("/exchange", payload, retries=2, backoff=0.2)

# ---------------------------
# Parse exchange (primer status)
# ---------------------------
def _unwrap(resp: Any) -> Tuple[str, Any]:
    if not isinstance(resp, dict):
        return ("unknown", resp)
    st = str(resp.get("status") or "").lower()
    if st in ("ok", "err") and "response" in resp:
        return (st, resp.get("response"))
    return ("unknown", resp)

def _first_status(resp: Any) -> Dict[str, Any]:
    out = {"kind": "unknown", "error": "", "filled_sz": 0.0}

    if isinstance(resp, dict) and resp.get("_http_error"):
        out["kind"] = "error"
        out["error"] = f"HTTP {resp.get('_http_status')} {resp.get('_http_body')}"
        return out

    st, inner = _unwrap(resp)
    if st == "err":
        out["kind"] = "error"
        out["error"] = str(inner)
        return out

    if st != "ok" or not isinstance(inner, dict):
        return out

    data = inner.get("data")
    if not isinstance(data, dict):
        return out

    statuses = data.get("statuses")
    if not isinstance(statuses, list) or not statuses or not isinstance(statuses[0], dict):
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

# ============================================================
# ✅ Min notional fix
# ============================================================
_MIN_TRADE_NOTIONAL = 10.0
_MIN_TRADE_BUFFER = 0.25  # para evitar caer debajo por rounding/validación

# ============================================================
# API: place_market_order (engine)
# ============================================================
def place_market_order(
    user_id: int,
    symbol: str,
    side: str,
    qty: float,
    slippage: Optional[float] = None,
    vault_address: Optional[str] = None,
) -> dict:
    wallet = get_user_wallet(user_id)
    private_key = get_user_private_key(user_id)
    if not wallet or not private_key:
        return {"ok": False, "filled": False, "reason": "NO_WALLET_OR_KEY"}

    coin = norm_coin(symbol)
    asset = get_asset_index(coin)
    if asset is None:
        return {"ok": False, "filled": False, "reason": "NO_ASSET", "coin": coin}

    is_buy = str(side).lower() == "buy"
    sz_decimals = get_sz_decimals(asset)

    bid, ask = _get_best_bid_ask(coin)
    ref_px = ask if is_buy else bid
    if ref_px <= 0:
        ref_px = float(get_price(coin) or 0.0)
    if ref_px <= 0:
        return {"ok": False, "filled": False, "reason": "NO_PRICE", "coin": coin}

    slip = float(slippage) if slippage is not None else 0.02
    slip = max(0.0, min(slip, 0.08))

    raw_px = ref_px * (1 + slip) if is_buy else ref_px * (1 - slip)
    p_str = _fmt_price_hl(raw_px, sz_decimals, is_buy=is_buy)

    # size inicial
    qty = max(0.000001, float(qty))
    s_str = _fmt_size(qty, sz_decimals)

    # ✅ asegurar min notional DESPUÉS de redondear
    try:
        px_f = float(p_str)
        sz_f = float(s_str)
        notional = px_f * sz_f
    except Exception:
        return {"ok": False, "filled": False, "reason": "BAD_FORMATTED", "coin": coin, "px": p_str, "sz": s_str}

    if notional < (_MIN_TRADE_NOTIONAL + _MIN_TRADE_BUFFER):
        target_sz = (_MIN_TRADE_NOTIONAL + _MIN_TRADE_BUFFER) / max(px_f, 1e-12)
        s_up = _fmt_size_round(target_sz, sz_decimals, ROUND_UP)
        try:
            if float(s_up) > float(s_str):
                s_str = s_up
                sz_f = float(s_str)
                notional = px_f * sz_f
        except Exception:
            pass

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

    raw = _exchange(action, private_key, vault_address=vault_address)
    st = _first_status(raw)

    if st["kind"] == "error":
        err = st.get("error") or ""
        if "ioccancel" in err.lower() or "ioc cancel" in err.lower():
            _must(f"🟡 NO_FILL coin={coin} side={side} bid={bid} ask={ask} px={p_str} sz={s_str} ntl~{round(notional,4)} err={err}")
            return {"ok": True, "filled": False, "reason": "NO_FILL", "coin": coin, "error": err, "raw": raw}

        _must(f"❌ EXCHANGE_ERROR coin={coin} side={side} bid={bid} ask={ask} px={p_str} sz={s_str} ntl~{round(notional,4)} err={err}")
        return {"ok": False, "filled": False, "reason": "EXCHANGE_ERROR", "coin": coin, "error": err, "raw": raw}

    if st["kind"] == "filled" and float(st.get("filled_sz") or 0.0) > 0:
        _log(f"🟢 FILLED coin={coin} side={side} px={p_str} sz={s_str} ntl~{round(notional,4)} filled_sz={st.get('filled_sz')}")
        return {"ok": True, "filled": True, "reason": "FILLED", "coin": coin, "filled_sz": float(st["filled_sz"]), "raw": raw}

    _must(f"🟡 NO_FILL coin={coin} side={side} bid={bid} ask={ask} px={p_str} sz={s_str} ntl~{round(notional,4)} err=RESTING_OR_UNKNOWN")
    return {"ok": True, "filled": False, "reason": "NO_FILL", "coin": coin, "error": "RESTING_OR_UNKNOWN", "raw": raw}
