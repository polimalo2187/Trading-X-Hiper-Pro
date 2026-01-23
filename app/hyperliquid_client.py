# ============================================================
# HYPERLIQUID CLIENT – Trading X Hyper Pro
# PRODUCCIÓN REAL – LISTO PARA PROD (LECTURA + ÓRDENES + SIGN)
# FIX PRO:
#  - /exchange NO traga 4xx/5xx: devuelve error con body
#  - BUY price ROUND_UP / SELL ROUND_DOWN
#  - NO_FILL retry responsable (1 vez)
#  - HTTP client reutilizable
#  - Auto-ajusta minSz / minNotional si existe en meta
# ============================================================

import time
import threading
import httpx
from typing import Any, Dict, Optional, Tuple
from decimal import Decimal, ROUND_DOWN, ROUND_UP, InvalidOperation

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

# ------------------------------------------------------------
# HTTP Client reutilizable
# ------------------------------------------------------------

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

def _read_text_safe(resp: httpx.Response) -> str:
    try:
        return resp.text
    except Exception:
        return "<no text>"

# ------------------------------------------------------------
# HTTP Request (POST JSON) – genérico (mantiene comportamiento)
#  - Para /exchange NO USAR este: usar make_exchange_request()
# ------------------------------------------------------------

def make_request(
    endpoint: str,
    payload: dict,
    retries: int = 4,
    backoff: float = 1.0,
    timeout: Optional[float] = None
):
    if timeout is None:
        timeout = REQUEST_TIMEOUT

    url = f"{HYPER_BASE_URL}{endpoint}"
    client = _get_http_client(timeout)

    for attempt in range(1, retries + 1):
        try:
            r = client.post(url, json=payload)

            if r.status_code == 429 or 500 <= r.status_code <= 599:
                safe_log(f"❌ HTTP {r.status_code} {endpoint} (attempt {attempt}/{retries}) body={_read_text_safe(r)}")
                if attempt < retries:
                    time.sleep(max(0.25, backoff) * (attempt * 1.5))
                    continue
                return {}

            if r.status_code >= 400:
                safe_log(f"❌ HTTP {r.status_code} {endpoint} (attempt {attempt}/{retries}) body={_read_text_safe(r)}")
                if attempt < retries:
                    time.sleep(backoff * attempt)
                    continue
                return {}

            data = r.json()
            if isinstance(data, (dict, list)):
                return data
            raise ValueError(f"Respuesta JSON inválida: {type(data)}")

        except (httpx.RequestError, ValueError) as e:
            safe_log(f"❌ HTTP error [{attempt}/{retries}] {endpoint}:", str(e))
        except Exception as e:
            safe_log(f"❌ Unknown error [{attempt}/{retries}] {endpoint}:", str(e))

        if attempt < retries:
            time.sleep(backoff * attempt)

    return {}

# ------------------------------------------------------------
# /exchange request – CRÍTICO: NO tragar 4xx/5xx
# ------------------------------------------------------------

def make_exchange_request(
    payload: dict,
    retries: int = 2,
    backoff: float = 0.6,
    timeout: Optional[float] = None
) -> Dict[str, Any]:
    if timeout is None:
        timeout = REQUEST_TIMEOUT

    endpoint = "/exchange"
    url = f"{HYPER_BASE_URL}{endpoint}"
    client = _get_http_client(timeout)

    last_err: Dict[str, Any] = {}

    for attempt in range(1, retries + 1):
        try:
            r = client.post(url, json=payload)

            # 429/5xx: backoff + retry
            if r.status_code == 429 or 500 <= r.status_code <= 599:
                body = _read_text_safe(r)
                last_err = {
                    "ok": False,
                    "reason": "EXCHANGE_HTTP",
                    "status_code": r.status_code,
                    "body": body[:800],
                }
                safe_log(f"❌ EXCHANGE HTTP {r.status_code} (attempt {attempt}/{retries}) body={body}")
                if attempt < retries:
                    time.sleep(max(0.25, backoff) * (attempt * 1.6))
                    continue
                return last_err

            # 4xx: NO reintentar mucho. Devuelve error con body.
            if r.status_code >= 400:
                body = _read_text_safe(r)
                err = {
                    "ok": False,
                    "reason": "EXCHANGE_HTTP",
                    "status_code": r.status_code,
                    "body": body[:800],
                }
                safe_log(f"❌ EXCHANGE HTTP {r.status_code} body={body}")
                return err

            # OK: parse JSON
            try:
                data = r.json()
            except Exception:
                body = _read_text_safe(r)
                return {"ok": False, "reason": "EXCHANGE_BAD_JSON", "status_code": r.status_code, "body": body[:800]}

            if isinstance(data, (dict, list)):
                return {"ok": True, "data": data}
            return {"ok": False, "reason": "EXCHANGE_BAD_JSON_TYPE", "type": str(type(data))}

        except httpx.RequestError as e:
            last_err = {"ok": False, "reason": "EXCHANGE_REQUEST_ERROR", "error": str(e)[:250]}
            safe_log(f"❌ EXCHANGE request error (attempt {attempt}/{retries}):", str(e))
        except Exception as e:
            last_err = {"ok": False, "reason": "EXCHANGE_UNKNOWN", "error": str(e)[:250]}
            safe_log(f"❌ EXCHANGE unknown error (attempt {attempt}/{retries}):", str(e))

        if attempt < retries:
            time.sleep(backoff * attempt)

    return last_err if last_err else {"ok": False, "reason": "EXCHANGE_FAIL"}

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
# Cache: META y ALLMIDS
#  + minSz / minNotional (si existen)
# ------------------------------------------------------------

_META_CACHE: Dict[str, Any] = {
    "coin_to_asset": {},
    "asset_to_sz": {},
    "asset_to_min_sz": {},
    "asset_to_min_ntl": {},
    "ts": 0.0
}
_MIDS_CACHE: Dict[str, Any] = {"mids": {}, "ts": 0.0}

META_TTL = 60.0
MIDS_TTL = 2.0

_cache_lock = threading.Lock()

def _parse_float(x: Any) -> float:
    try:
        return float(x)
    except Exception:
        return 0.0

def _refresh_meta_cache():
    now = time.time()
    with _cache_lock:
        if now - float(_META_CACHE.get("ts", 0.0) or 0.0) < META_TTL:
            return

    r = make_request("/info", {"type": "meta"})
    if not isinstance(r, dict) or "universe" not in r:
        safe_log("❌ meta inválida:", r)
        return

    coin_to_asset: Dict[str, int] = {}
    asset_to_sz: Dict[int, int] = {}
    asset_to_min_sz: Dict[int, float] = {}
    asset_to_min_ntl: Dict[int, float] = {}

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

            # Campos de mínimo (varían según versión API; lo hacemos defensivo)
            # Intentamos varios nombres típicos:
            min_sz = 0.0
            for k in ("minSz", "min_size", "minTradeSz", "minOrderSz"):
                if k in item:
                    min_sz = _parse_float(item.get(k))
                    break
            if min_sz > 0:
                asset_to_min_sz[i] = float(min_sz)

            min_ntl = 0.0
            for k in ("minNotional", "minNtl", "min_trade_notional", "minOrderNtl"):
                if k in item:
                    min_ntl = _parse_float(item.get(k))
                    break
            if min_ntl > 0:
                asset_to_min_ntl[i] = float(min_ntl)

        with _cache_lock:
            _META_CACHE["coin_to_asset"] = coin_to_asset
            _META_CACHE["asset_to_sz"] = asset_to_sz
            _META_CACHE["asset_to_min_sz"] = asset_to_min_sz
            _META_CACHE["asset_to_min_ntl"] = asset_to_min_ntl
            _META_CACHE["ts"] = now

    except Exception as e:
        safe_log("❌ Error procesando meta:", str(e))

def get_asset_index(symbol: str) -> Optional[int]:
    _refresh_meta_cache()
    coin = norm_coin(symbol)
    with _cache_lock:
        return _META_CACHE["coin_to_asset"].get(coin)

def get_sz_decimals(asset_index: int) -> int:
    _refresh_meta_cache()
    with _cache_lock:
        return int(_META_CACHE["asset_to_sz"].get(asset_index, 0) or 0)

def get_min_sz(asset_index: int) -> float:
    _refresh_meta_cache()
    with _cache_lock:
        return float(_META_CACHE["asset_to_min_sz"].get(asset_index, 0.0) or 0.0)

def get_min_notional(asset_index: int) -> float:
    _refresh_meta_cache()
    with _cache_lock:
        return float(_META_CACHE["asset_to_min_ntl"].get(asset_index, 0.0) or 0.0)

def _refresh_mids_cache():
    now = time.time()
    with _cache_lock:
        if now - float(_MIDS_CACHE.get("ts", 0.0) or 0.0) < MIDS_TTL:
            return

    r = make_request("/info", {"type": "allMids"})
    if not isinstance(r, dict):
        safe_log("❌ allMids inválido (se esperaba dict):", type(r), r)
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
        safe_log("❌ Error procesando allMids:", str(e))

def get_price(symbol: str) -> float:
    coin = norm_coin(symbol)
    if not coin:
        return 0.0

    _refresh_mids_cache()
    with _cache_lock:
        price = _MIDS_CACHE["mids"].get(coin)

    if price is None:
        safe_log("❌ No hay mid para:", coin)
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

def _format_size(sz: float, sz_decimals: int, round_up: bool = False) -> str:
    try:
        d = _to_decimal(sz)
        rnd = ROUND_UP if round_up else ROUND_DOWN

        if sz_decimals <= 0:
            out = d.quantize(Decimal("1"), rounding=rnd)
            return _strip_trailing_zeros(format(out, "f"))

        q = Decimal("1").scaleb(-sz_decimals)
        out = d.quantize(q, rounding=rnd)
        return _strip_trailing_zeros(format(out, "f"))
    except (InvalidOperation, Exception):
        return "0"

def _format_price_side(px: float, sz_decimals: int, is_buy: bool) -> str:
    MAX_DECIMALS = 6
    max_px_decimals = max(0, MAX_DECIMALS - int(sz_decimals or 0))
    rnd = ROUND_UP if is_buy else ROUND_DOWN

    try:
        d = _to_decimal(px)
        if d <= 0:
            return "0"

        if d >= 1:
            int_part = int(d)
            digits_before = len(str(abs(int_part))) if int_part != 0 else 1

            if digits_before >= 5:
                out = d.quantize(Decimal("1"), rounding=rnd)
                return _strip_trailing_zeros(format(out, "f"))

            allowed_sig_decimals = max(0, 5 - digits_before)
            allowed_decimals = min(max_px_decimals, allowed_sig_decimals)

            if allowed_decimals <= 0:
                out = d.quantize(Decimal("1"), rounding=rnd)
                return _strip_trailing_zeros(format(out, "f"))

            q = Decimal("1").scaleb(-allowed_decimals)
            out = d.quantize(q, rounding=rnd)
            return _strip_trailing_zeros(format(out, "f"))

        if max_px_decimals <= 0:
            out = d.quantize(Decimal("1"), rounding=rnd)
            return _strip_trailing_zeros(format(out, "f"))

        q = Decimal("1").scaleb(-max_px_decimals)
        out = d.quantize(q, rounding=rnd)
        return _strip_trailing_zeros(format(out, "f"))

    except (InvalidOperation, Exception):
        return "0"

# ------------------------------------------------------------
# Balance
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
        safe_log("❌ Error leyendo balance:", str(e), r)
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
# Fill detector
# ------------------------------------------------------------

def _find_filled_sz(obj: Any) -> Optional[float]:
    try:
        if isinstance(obj, dict):
            for key in ("filledSz", "fillSz", "filled_size", "filled", "filled_qty", "filledQty"):
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

def _detect_fill(resp: Any) -> Dict[str, Any]:
    out = {"filled": False, "filled_sz": 0.0, "status": "UNKNOWN"}
    if not resp:
        out["status"] = "EMPTY"
        return out
    try:
        if isinstance(resp, dict) and (resp.get("error") or resp.get("err")):
            out["status"] = "ERROR"
            return out

        filled = _find_filled_sz(resp)
        if filled is None:
            out["status"] = "NO_FILL"
            return out

        out["filled_sz"] = float(filled)
        out["filled"] = float(filled) > 0
        out["status"] = "FILLED" if out["filled"] else "NO_FILL"
        return out
    except Exception:
        out["status"] = "EXCEPTION"
        return out

def _extract_exchange_error(data: Any) -> str:
    try:
        if isinstance(data, dict):
            for k in ("error", "err", "message", "msg"):
                if k in data and data.get(k):
                    return str(data.get(k))[:220]
        return ""
    except Exception:
        return ""

# ------------------------------------------------------------
# Slippage
# ------------------------------------------------------------

def _default_slippage(mid: float) -> float:
    try:
        if mid < 1:
            return 0.03
        if mid < 10:
            return 0.02
        return 0.01
    except Exception:
        return 0.02

def _clamp_slippage(x: float) -> float:
    try:
        x = float(x)
    except Exception:
        x = 0.02
    return max(0.0, min(x, 0.08))  # max 8%

# ------------------------------------------------------------
# Place market order (IOC agresiva) – PROD
# ------------------------------------------------------------

def place_market_order(
    user_id: int,
    symbol: str,
    side: str,
    qty: float,
    slippage: Optional[float] = None,
    vault_address: Optional[str] = None,
    max_no_fill_retries: int = 1,
    retry_delay_seconds: float = 0.35,
    slippage_step: float = 0.015,
):
    wallet = get_user_wallet(user_id)
    private_key = get_user_private_key(user_id)

    if not wallet or not private_key:
        safe_log("❌ Wallet / key missing")
        return {"ok": False, "filled": False, "reason": "NO_WALLET_OR_KEY"}

    coin = norm_coin(symbol)
    asset = get_asset_index(coin)
    if asset is None:
        safe_log("❌ Asset no encontrado en meta.universe para:", coin)
        return {"ok": False, "filled": False, "reason": "NO_ASSET", "coin": coin}

    sz_decimals = get_sz_decimals(asset)
    min_sz = float(get_min_sz(asset) or 0.0)
    min_ntl = float(get_min_notional(asset) or 0.0)

    mid0 = float(get_price(coin) or 0.0)
    if mid0 <= 0:
        return {"ok": False, "filled": False, "reason": "NO_MID", "coin": coin}

    is_buy = side.lower() == "buy"
    qty = max(0.000001, float(qty))

    # ✅ Auto-ajuste a mínimo si existe
    # - minSz: mínimo en coin
    # - minNotional: mínimo en USDC aprox
    try:
        if min_ntl > 0:
            need_qty = min_ntl / mid0
            if need_qty > qty:
                qty = need_qty
        if min_sz > 0 and qty < min_sz:
            qty = min_sz
    except Exception:
        pass

    # Redondeo size (si ajustamos mínimo, redondeamos ARRIBA para no quedar debajo)
    s_str = _format_size(qty, sz_decimals, round_up=True)
    try:
        if float(s_str) <= 0:
            return {"ok": False, "filled": False, "reason": "BAD_FORMATTED_SIZE", "coin": coin, "sz": s_str}
    except Exception:
        return {"ok": False, "filled": False, "reason": "BAD_FORMATTED_SIZE_PARSE", "coin": coin, "sz": s_str}

    base_slip = _default_slippage(mid0) if slippage is None else float(slippage)
    base_slip = _clamp_slippage(base_slip)

    total_attempts = 1 + max(0, int(max_no_fill_retries))

    for attempt in range(1, total_attempts + 1):
        mid = float(get_price(coin) or 0.0)
        if mid <= 0:
            return {"ok": False, "filled": False, "reason": "NO_MID", "coin": coin}

        slip = _clamp_slippage(base_slip + (attempt - 1) * float(slippage_step))
        raw_px = mid * (1 + slip) if is_buy else mid * (1 - slip)

        p_str = _format_price_side(raw_px, sz_decimals, is_buy=is_buy)

        try:
            if float(p_str) <= 0:
                return {"ok": False, "filled": False, "reason": "BAD_FORMATTED_PRICE", "coin": coin, "px": p_str}
        except Exception:
            return {"ok": False, "filled": False, "reason": "BAD_FORMATTED_PRICE_PARSE", "coin": coin, "px": p_str}

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
            return {"ok": False, "filled": False, "reason": "SIGN_ERROR", "coin": coin, "error": str(e)[:250]}

        payload = {
            "action": action,
            "nonce": nonce,
            "signature": signature,
            "expiresAfter": expires_after_ms,
        }
        if vault_address:
            payload["vaultAddress"] = vault_address

        ex = make_exchange_request(payload)
        if not ex.get("ok"):
            # ✅ AQUÍ YA VERÁS EL ERROR REAL EN LOGS
            return {
                "ok": False,
                "filled": False,
                "reason": "EXCHANGE_ERROR",
                "coin": coin,
                "detail": ex,
                "side": side,
                "sz": s_str,
                "px": p_str,
                "slippage": slip,
                "attempt": attempt,
            }

        data = ex.get("data")
        if not data:
            return {"ok": False, "filled": False, "reason": "EXCHANGE_EMPTY", "coin": coin, "raw": ex}

        # si viene error dentro del JSON
        err_msg = _extract_exchange_error(data)
        if err_msg:
            return {"ok": False, "filled": False, "reason": "EXCHANGE_ERROR", "coin": coin, "error": err_msg, "raw": data}

        fill = _detect_fill(data)
        if fill.get("filled"):
            safe_log(f"🟢 MARKET(IOC) {side.upper()} {s_str} {coin} @~{p_str} (slip={round(slip*100,2)}%)")
            return {
                "ok": True,
                "filled": True,
                "reason": "FILLED",
                "coin": coin,
                "side": side,
                "sz": s_str,
                "px": p_str,
                "slippage": slip,
                "attempt": attempt,
                "filled_sz": float(fill.get("filled_sz", 0.0) or 0.0),
                "raw": data,
            }

        # NO_FILL
        if attempt < total_attempts:
            safe_log(f"🟡 NO_FILL {side.upper()} {s_str} {coin} @~{p_str} (attempt {attempt}/{total_attempts}) -> retry")
            try:
                time.sleep(max(0.0, float(retry_delay_seconds)))
            except Exception:
                pass
            continue

        return {
            "ok": True,
            "filled": False,
            "reason": "NO_FILL",
            "coin": coin,
            "side": side,
            "sz": s_str,
            "px": p_str,
            "slippage": slip,
            "attempt": attempt,
            "filled_sz": float(fill.get("filled_sz", 0.0) or 0.0),
            "raw": data,
        }

    return {"ok": False, "filled": False, "reason": "EXCHANGE_FAIL", "coin": coin}

# ------------------------------------------------------------
# Wrappers
# ------------------------------------------------------------

def open_long(user_id: int, symbol: str, qty: float):
    return place_market_order(user_id, symbol, "buy", qty)

def open_short(user_id: int, symbol: str, qty: float):
    return place_market_order(user_id, symbol, "sell", qty)
