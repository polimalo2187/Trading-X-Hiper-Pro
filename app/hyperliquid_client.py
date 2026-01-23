# ============================================================
# HYPERLIQUID CLIENT – Trading X Hyper Pro
# PRODUCCIÓN REAL – BANK GRADE (LECTURA + ÓRDENES + SIGN)
# Hardening: 429 + 5xx + Circuit Breaker FAIL-FAST (sin sleeps largos)
# ============================================================

import time
import threading
import random
import httpx
from typing import Any, Dict, Optional
from decimal import Decimal, ROUND_DOWN, InvalidOperation

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

# ------------------------------------------------------------
# Logging
# ------------------------------------------------------------

def safe_log(*args):
    if VERBOSE_LOGS or not PRODUCTION_MODE:
        print(*args)

def err_log(*args):
    try:
        print(*args)
    except Exception:
        pass

# ------------------------------------------------------------
# HTTP Client reutilizable + límites
# ------------------------------------------------------------

_DEFAULT_HEADERS = {"Content-Type": "application/json"}

_client_lock = threading.Lock()
_http_client: Optional[httpx.Client] = None

def _get_http_client(timeout: Optional[float] = None) -> httpx.Client:
    global _http_client
    with _client_lock:
        if _http_client is None:
            limits = httpx.Limits(
                max_connections=8,
                max_keepalive_connections=4,
                keepalive_expiry=30.0,
            )
            _http_client = httpx.Client(
                timeout=timeout or REQUEST_TIMEOUT,
                headers=_DEFAULT_HEADERS,
                limits=limits,
            )
        else:
            try:
                _http_client.timeout = timeout or REQUEST_TIMEOUT
            except Exception:
                pass
        return _http_client

# ------------------------------------------------------------
# Circuit Breaker GLOBAL (FAIL-FAST)
# ------------------------------------------------------------

_cb_lock = threading.Lock()
_CB_UNTIL_TS = 0.0
_CB_LAST_REASON = ""

def _cb_remaining() -> float:
    with _cb_lock:
        return max(0.0, _CB_UNTIL_TS - time.time())

def _cb_reason() -> str:
    with _cb_lock:
        return _CB_LAST_REASON or ""

def _cb_trip(seconds: float, reason: str):
    global _CB_UNTIL_TS, _CB_LAST_REASON
    seconds = float(max(0.0, seconds))
    with _cb_lock:
        _CB_UNTIL_TS = max(_CB_UNTIL_TS, time.time() + seconds)
        _CB_LAST_REASON = reason

def _cb_allow_request() -> bool:
    """
    ✅ IMPORTANTE:
    Antes dormíamos aquí (sleep) y eso causaba TIMEOUT en trading_loop.
    Ahora: FAIL-FAST. Si CB activo, NO hacemos request y devolvemos {}.
    """
    rem = _cb_remaining()
    if rem > 0:
        err_log(f"⛔ CircuitBreaker activo ({_cb_reason()}) -> skip request (remain {rem:.2f}s)")
        return False
    return True

def _parse_retry_after(headers: httpx.Headers) -> Optional[float]:
    try:
        ra = headers.get("retry-after")
        if ra is None:
            return None
        ra = ra.strip()
        if not ra:
            return None
        return max(0.0, float(ra))
    except Exception:
        return None

def _sleep_short(base: float, cap: float = 2.0):
    """
    Sleep MUY corto para no romper el timeout de 45s del loop.
    """
    try:
        s = min(float(base), float(cap))
        s += random.uniform(0.05, 0.20)
        time.sleep(max(0.0, s))
    except Exception:
        pass

# ------------------------------------------------------------
# make_request (POST JSON) – HARDENED + FAIL-FAST
# ------------------------------------------------------------

def make_request(
    endpoint: str,
    payload: dict,
    retries: int = 4,          # ✅ menos intentos para no pasarnos de 45s
    backoff: float = 0.6,      # ✅ backoff más corto
    timeout: Optional[float] = None,
):
    if timeout is None:
        timeout = REQUEST_TIMEOUT

    # ✅ si CB activo => no bloqueamos (sin sleep), devolvemos {}
    if not _cb_allow_request():
        return {}

    url = f"{HYPER_BASE_URL}{endpoint}"

    for attempt in range(1, retries + 1):
        try:
            # re-check CB antes de cada intento
            if not _cb_allow_request():
                return {}

            client = _get_http_client(timeout=timeout)
            r = client.post(url, json=payload)

            # -----------------------
            # 429: Rate limit
            # -----------------------
            if r.status_code == 429:
                ra = _parse_retry_after(r.headers)
                base_sleep = ra if ra is not None else (backoff * (2 ** (attempt - 1)))
                base_sleep = min(base_sleep, 6.0)

                err_log(f"⏳ 429 {endpoint} (attempt {attempt}/{retries}) body={r.text if r.text else 'null'}")
                _cb_trip(seconds=max(2.0, base_sleep), reason="429 rate-limit")

                if attempt < retries:
                    _sleep_short(base_sleep, cap=2.0)
                    continue
                return {}

            # -----------------------
            # 5xx: Hyperliquid inestable
            # -----------------------
            if r.status_code in (500, 502, 503, 504):
                body = r.text if r.text else "null"
                err_log(f"❌ HTTP {r.status_code} {endpoint} (attempt {attempt}/{retries}) body={body}")

                # ✅ Trip CB pero sin sleep largo: el CB hará skip requests
                base_cb = min(4.0 + (1.2 * attempt), 18.0)
                _cb_trip(seconds=base_cb, reason=f"{r.status_code} upstream")

                if attempt < retries:
                    _sleep_short(0.4 + 0.2 * attempt, cap=2.0)
                    continue
                return {}

            # -----------------------
            # Otros errores
            # -----------------------
            if r.status_code >= 400:
                body = r.text if r.text else "null"
                err_log(f"❌ HTTP {r.status_code} {endpoint} (attempt {attempt}/{retries}) body={body}")
                return {}

            # -----------------------
            # OK: parse JSON
            # -----------------------
            try:
                data = r.json()
            except Exception as e:
                err_log(f"❌ JSON parse error {endpoint} (attempt {attempt}/{retries}): {e}")
                if attempt < retries:
                    _sleep_short(0.4 + 0.2 * attempt, cap=2.0)
                    continue
                return {}

            if isinstance(data, (dict, list)):
                return data

            err_log(f"❌ Respuesta JSON inválida {endpoint}: type={type(data)}")
            return {}

        except httpx.RequestError as e:
            err_log(f"❌ RequestError {endpoint} (attempt {attempt}/{retries}): {e}")
            _cb_trip(seconds=3.0, reason="network error")
        except Exception as e:
            err_log(f"❌ Unknown error {endpoint} (attempt {attempt}/{retries}): {e}")
            _cb_trip(seconds=3.0, reason="unknown error")

        if attempt < retries:
            _sleep_short(0.6 + 0.2 * attempt, cap=2.0)

    return {}

# ------------------------------------------------------------
# Normalización de símbolo
# ------------------------------------------------------------

def norm_coin(symbol: str) -> str:
    if not isinstance(symbol, str):
        return ""
    s = symbol.strip().upper()
    s = s.replace("-PERP", "").replace("_PERP", "").replace("PERP", "")
    if "/" in s:
        s = s.split("/", 1)[0].strip()
    return s

# ------------------------------------------------------------
# Cache meta/mids
# ------------------------------------------------------------

_META_CACHE: Dict[str, Any] = {"coin_to_asset": {}, "asset_to_sz": {}, "ts": 0.0}
_MIDS_CACHE: Dict[str, Any] = {"mids": {}, "ts": 0.0}

META_TTL = 120.0
MIDS_TTL = 3.0

_cache_lock = threading.Lock()

def _refresh_meta_cache():
    now = time.time()
    with _cache_lock:
        if now - _META_CACHE["ts"] < META_TTL:
            return

    r = make_request("/info", {"type": "meta"})
    if not isinstance(r, dict) or "universe" not in r:
        err_log("❌ meta inválida:", r)
        return

    coin_to_asset: Dict[str, int] = {}
    asset_to_sz: Dict[int, int] = {}

    try:
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

    except Exception as e:
        err_log("❌ Error procesando meta:", str(e))

def get_asset_index(symbol: str) -> Optional[int]:
    _refresh_meta_cache()
    coin = norm_coin(symbol)
    with _cache_lock:
        return _META_CACHE["coin_to_asset"].get(coin)

def get_sz_decimals(asset_index: int) -> int:
    _refresh_meta_cache()
    with _cache_lock:
        return int(_META_CACHE["asset_to_sz"].get(asset_index, 0) or 0)

def _refresh_mids_cache():
    now = time.time()
    with _cache_lock:
        if now - _MIDS_CACHE["ts"] < MIDS_TTL:
            return

    r = make_request("/info", {"type": "allMids"})
    if not isinstance(r, dict):
        err_log("❌ allMids inválido:", type(r), r)
        return

    mids: Dict[str, float] = {}
    try:
        for k, v in r.items():
            if not isinstance(k, str):
                continue
            if k.startswith("@"):
                continue
            try:
                mids[k.upper()] = float(v)
            except Exception:
                continue

        with _cache_lock:
            _MIDS_CACHE["mids"] = mids
            _MIDS_CACHE["ts"] = now
    except Exception as e:
        err_log("❌ Error procesando allMids:", str(e))

def get_price(symbol: str) -> float:
    coin = norm_coin(symbol)
    if not coin:
        return 0.0

    _refresh_mids_cache()
    with _cache_lock:
        price = _MIDS_CACHE["mids"].get(coin)

    if price is None:
        err_log("❌ No hay mid para:", coin)
        return 0.0
    return float(price)

# ------------------------------------------------------------
# Formateo estricto
# ------------------------------------------------------------

def _strip_trailing_zeros(num_str: str) -> str:
    if "." not in num_str:
        return num_str
    num_str = num_str.rstrip("0").rstrip(".")
    return num_str if num_str else "0"

def _to_decimal(x: float) -> Decimal:
    return Decimal(str(x))

def _format_size(sz: float, sz_decimals: int) -> str:
    try:
        d = _to_decimal(sz)
        if sz_decimals <= 0:
            out = d.quantize(Decimal("1"), rounding=ROUND_DOWN)
            return _strip_trailing_zeros(format(out, "f"))
        q = Decimal("1").scaleb(-sz_decimals)
        out = d.quantize(q, rounding=ROUND_DOWN)
        return _strip_trailing_zeros(format(out, "f"))
    except (InvalidOperation, Exception):
        return "0"

def _format_price(px: float, sz_decimals: int) -> str:
    MAX_DECIMALS = 6
    max_px_decimals = max(0, MAX_DECIMALS - int(sz_decimals or 0))

    try:
        d = _to_decimal(px)
        if d <= 0:
            return "0"

        if d >= 1:
            int_part = int(d)
            digits_before = len(str(abs(int_part))) if int_part != 0 else 1

            if digits_before >= 5:
                out = d.quantize(Decimal("1"), rounding=ROUND_DOWN)
                return _strip_trailing_zeros(format(out, "f"))

            allowed_sig_decimals = max(0, 5 - digits_before)
            allowed_decimals = min(max_px_decimals, allowed_sig_decimals)

            if allowed_decimals <= 0:
                out = d.quantize(Decimal("1"), rounding=ROUND_DOWN)
                return _strip_trailing_zeros(format(out, "f"))

            q = Decimal("1").scaleb(-allowed_decimals)
            out = d.quantize(q, rounding=ROUND_DOWN)
            return _strip_trailing_zeros(format(out, "f"))

        if max_px_decimals <= 0:
            out = d.quantize(Decimal("1"), rounding=ROUND_DOWN)
            return _strip_trailing_zeros(format(out, "f"))

        q = Decimal("1").scaleb(-max_px_decimals)
        out = d.quantize(q, rounding=ROUND_DOWN)
        return _strip_trailing_zeros(format(out, "f"))

    except (InvalidOperation, Exception):
        return "0"
# ------------------------------------------------------------
# Balance (clearinghouseState)
# ------------------------------------------------------------

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
        err_log("❌ Error leyendo balance:", str(e), r)
        return 0.0

# ------------------------------------------------------------
# Firma (SDK)
# ------------------------------------------------------------

class HyperliquidSigner:
    def __init__(self, private_key: str):
        self.private_key = private_key
        self._account = None
        self._sign_l1_action = None

        try:
            from hyperliquid.utils.signing import sign_l1_action
            from eth_account import Account
            self._account = Account.from_key(private_key)
            self._sign_l1_action = sign_l1_action
        except Exception as e:
            raise RuntimeError(
                "No se pudo importar hyperliquid-python-sdk para firma. "
                "Instala: pip install hyperliquid-python-sdk"
            ) from e

    @property
    def address(self) -> str:
        return self._account.address

    def sign(
        self,
        action: dict,
        nonce_ms: int,
        vault_address: Optional[str] = None,
        expires_after_ms: Optional[int] = None,
        is_mainnet: Optional[bool] = None,
    ) -> Any:
        if expires_after_ms is None:
            expires_after_ms = int(nonce_ms) + 60_000

        if is_mainnet is None:
            is_mainnet = (str(HYPER_BASE_URL).rstrip("/") == "https://api.hyperliquid.xyz")

        return self._sign_l1_action(self._account, action, vault_address, nonce_ms, expires_after_ms, is_mainnet)

# ------------------------------------------------------------
# Detectar FILL real (seguro)
# ------------------------------------------------------------

def _find_filled_sz(obj: Any) -> Optional[float]:
    try:
        if isinstance(obj, dict):
            for key in ("filledSz", "filled_size", "filled", "fillSz", "filled_qty", "filledQty"):
                if key in obj:
                    try:
                        return float(obj[key])
                    except Exception:
                        pass
            for v in obj.values():
                got = _find_filled_sz(v)
                if got is not None:
                    return got
        elif isinstance(obj, list):
            for it in obj:
                got = _find_filled_sz(it)
                if got is not None:
                    return got
        return None
    except Exception:
        return None

def _is_exchange_ok(resp: Any) -> bool:
    try:
        if not resp:
            return False
        if isinstance(resp, dict) and (resp.get("error") or resp.get("err")):
            return False
        filled = _find_filled_sz(resp)
        if filled is None:
            return False
        return filled > 0
    except Exception:
        return False

# ------------------------------------------------------------
# Órdenes: IOC agresiva (market-like)
# ------------------------------------------------------------

def place_market_order(
    user_id: int,
    symbol: str,
    side: str,
    qty: float,
    slippage: float = 0.01,
    vault_address: Optional[str] = None,
):
    wallet = get_user_wallet(user_id)
    private_key = get_user_private_key(user_id)

    if not wallet or not private_key:
        err_log("❌ Wallet / key missing")
        return None

    coin = norm_coin(symbol)
    asset = get_asset_index(coin)
    if asset is None:
        err_log("❌ Asset no encontrado en meta.universe para:", coin)
        return None

    sz_decimals = get_sz_decimals(asset)

    mid = get_price(coin)
    if mid <= 0:
        err_log("❌ No hay mid price para:", coin)
        return None

    is_buy = side.lower() == "buy"
    qty = max(0.000001, float(qty))

    raw_px = mid * (1 + float(slippage)) if is_buy else mid * (1 - float(slippage))

    p_str = _format_price(raw_px, sz_decimals)
    s_str = _format_size(qty, sz_decimals)

    try:
        if float(s_str) <= 0 or float(p_str) <= 0:
            err_log("❌ px/sz inválidos:", coin, "px=", p_str, "sz=", s_str, "szDecimals=", sz_decimals)
            return None
    except Exception:
        err_log("❌ px/sz inválidos (parse fail):", coin, "px=", p_str, "sz=", s_str)
        return None

    nonce = int(time.time() * 1000)
    expires_after_ms = nonce + 60_000

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
        signature = signer.sign(action, nonce, vault_address=vault_address, expires_after_ms=expires_after_ms)
    except Exception as e:
        err_log("❌ Error firmando:", str(e))
        return None

    payload = {"action": action, "nonce": nonce, "signature": signature}
    if vault_address:
        payload["vaultAddress"] = vault_address

    r = make_request("/exchange", payload)

    if not r:
        err_log(
            "❌ /exchange vacío (rechazo/no confirmación). "
            f"coin={coin} side={side} sz={s_str} px={p_str} slippage={slippage}"
        )
        return None

    if not _is_exchange_ok(r):
        err_log(f"🟡 NO_FILL {side.upper()} {s_str} {coin} @~{p_str} (IOC cancelado, no se cuenta trade)")
        return None

    safe_log(f"🟢 MARKET(IOC) {side.upper()} {s_str} {coin} @~{p_str}")
    return r

def open_long(user_id: int, symbol: str, qty: float):
    return place_market_order(user_id, symbol, "buy", qty)

def open_short(user_id: int, symbol: str, qty: float):
    return place_market_order(user_id, symbol, "sell", qty)
  
