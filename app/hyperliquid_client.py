# ============================================================
# HYPERLIQUID CLIENT – Trading X Hyper Pro
# PRODUCCIÓN REAL – LISTO PARA PROD (LECTURA + ÓRDENES + SIGN)
# FIX REAL (DOC-BASED):
#  - Usa L2 book (best bid/ask) para precio IOC (más fills reales)
#  - Detecta status="err" correctamente (NO confundir con NO_FILL)
#  - NO_FILL real = IocCancel / sin match inmediato
#  - Garantiza MinTradeNtl (>= 10) DESPUÉS del redondeo de size
#  - BUY price ROUND_UP, SELL price ROUND_DOWN
#  - HTTP client reutilizable + backoff suave
#  - /exchange incluye expiresAfter (compat estable)
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
# Logging controlado
# ------------------------------------------------------------

def safe_log(*args):
    if VERBOSE_LOGS or not PRODUCTION_MODE:
        print(*args)

# ------------------------------------------------------------
# HTTP Client reutilizable (reduce 429/500)
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

# ------------------------------------------------------------
# HTTP Request (POST JSON) con reintentos + backoff
# Nota: NO “tragues” el body en /exchange; lo devolvemos para debug
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
                body = r.text if hasattr(r, "text") else "<no text>"
                safe_log(f"❌ HTTP {r.status_code} {endpoint} (attempt {attempt}/{retries}) body={body}")
                if attempt < retries:
                    time.sleep(max(0.25, backoff) * (attempt * 1.5))
                    continue
                return {"_http_error": True, "_http_status": r.status_code, "_http_body": body}

            if r.status_code >= 400:
                err_text = r.text if hasattr(r, "text") else "<no text>"
                safe_log(f"❌ HTTP error [{attempt}/{retries}] {endpoint}: {r.status_code} body={err_text}")
                if attempt < retries:
                    time.sleep(backoff * attempt)
                    continue
                # En /exchange nos interesa el body para ver el motivo exacto
                return {"_http_error": True, "_http_status": r.status_code, "_http_body": err_text}

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

    return {"_http_error": True, "_http_status": 0, "_http_body": "request_failed"}

# ------------------------------------------------------------
# Normalización de símbolo (perps: "BTC", "ETH"...)
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
# Cache: META (coin -> asset index + szDecimals) y ALLMIDS (coin -> mid)
# ------------------------------------------------------------

_META_CACHE: Dict[str, Any] = {"coin_to_asset": {}, "asset_to_sz": {}, "ts": 0.0}
_MIDS_CACHE: Dict[str, Any] = {"mids": {}, "ts": 0.0}

META_TTL = 60.0
MIDS_TTL = 2.0

_cache_lock = threading.Lock()

def _refresh_meta_cache():
    now = time.time()
    with _cache_lock:
        if now - _META_CACHE["ts"] < META_TTL:
            return

    r = make_request("/info", {"type": "meta"})
    if not isinstance(r, dict) or "universe" not in r:
        safe_log("❌ meta inválida:", r)
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

def _refresh_mids_cache():
    now = time.time()
    with _cache_lock:
        if now - _MIDS_CACHE["ts"] < MIDS_TTL:
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
# L2 Book (para BBO real: mejor bid/ask) -> mejor IOC fill
# ------------------------------------------------------------

def _get_l2_book(coin: str) -> Optional[dict]:
    coin = norm_coin(coin)
    if not coin:
        return None
    r = make_request("/info", {"type": "l2Book", "coin": coin})
    if not isinstance(r, dict):
        return None
    return r

def _get_best_bid_ask(coin: str) -> Tuple[float, float]:
    """
    Devuelve (best_bid, best_ask). Si no hay book, (0,0).
    Estructura de l2Book: levels[0] bids, levels[1] asks.
    Cada level: {"px": "...", "sz": "...", "n": ...}
    """
    try:
        book = _get_l2_book(coin)
        if not isinstance(book, dict):
            return (0.0, 0.0)
        levels = book.get("levels")
        if not isinstance(levels, list) or len(levels) < 2:
            return (0.0, 0.0)

        bids = levels[0] if isinstance(levels[0], list) else []
        asks = levels[1] if isinstance(levels[1], list) else []

        best_bid = 0.0
        best_ask = 0.0

        if bids and isinstance(bids[0], dict):
            best_bid = float(bids[0].get("px", 0) or 0)
        if asks and isinstance(asks[0], dict):
            best_ask = float(asks[0].get("px", 0) or 0)

        return (best_bid, best_ask)
    except Exception:
        return (0.0, 0.0)

# ------------------------------------------------------------
# Formateo estricto (evita tick/lot errors)
# FIX: price rounding depende del lado
# ------------------------------------------------------------

def _strip_trailing_zeros(num_str: str) -> str:
    if "." not in num_str:
        return num_str
    num_str = num_str.rstrip("0").rstrip(".")
    return num_str if num_str else "0"

def _to_decimal(x: float) -> Decimal:
    return Decimal(str(x))

def _quant(sz_decimals: int) -> Decimal:
    if sz_decimals <= 0:
        return Decimal("1")
    return Decimal("1").scaleb(-sz_decimals)

def _format_size_round(sz: float, sz_decimals: int, rounding) -> str:
    try:
        d = _to_decimal(sz)
        q = _quant(sz_decimals)
        out = d.quantize(q, rounding=rounding)
        return _strip_trailing_zeros(format(out, "f"))
    except (InvalidOperation, Exception):
        return "0"

def _format_size(sz: float, sz_decimals: int) -> str:
    # por defecto DOWN para no “pasarte”
    return _format_size_round(sz, sz_decimals, ROUND_DOWN)

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
        safe_log("❌ Error leyendo balance:", str(e), r)
        return 0.0

# ------------------------------------------------------------
# Firma: usar SDK oficial (sign_l1_action)
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
# Exchange response helpers (status ok/err) + fill detection
# ------------------------------------------------------------

def _unwrap_exchange(resp: Any) -> Tuple[str, Any]:
    """
    Respuestas de action típicas:
      {"status":"ok","response":{"type":"order","data":{"statuses":[...]}}}
      {"status":"err","response":"SomeErrorOrObject"}
    """
    if not isinstance(resp, dict):
        return ("unknown", resp)

    st = str(resp.get("status") or "").lower()
    if st in ("ok", "err") and "response" in resp:
        return (st, resp.get("response"))
    return ("unknown", resp)

def _extract_error_text(resp: Any) -> str:
    """
    Intenta sacar texto legible del error.
    """
    try:
        if isinstance(resp, dict) and resp.get("_http_error"):
            return f"HTTP {resp.get('_http_status')} {resp.get('_http_body')}"
        st, inner = _unwrap_exchange(resp)
        if st == "err":
            # inner puede ser string, list o dict
            if isinstance(inner, str):
                return inner
            return str(inner)
        # algunos errores vienen dentro de dict
        if isinstance(resp, dict):
            for k in ("error", "err", "message", "msg"):
                if k in resp:
                    return str(resp.get(k))
        return ""
    except Exception:
        return ""

def _detect_ioc_cancel(resp: Any) -> bool:
    """
    Para IOC, a veces viene un status tipo 'iocCancel' o parecido en status strings.
    Si no hay match inmediato, se considera NO_FILL real.
    """
    try:
        st, inner = _unwrap_exchange(resp)
        if st == "err":
            # IocCancel aparece como error en docs oficiales
            txt = str(inner).lower()
            return "ioccancel" in txt or "ioc_cancel" in txt or "ioc cancel" in txt

        # En ok, podría venir un status string en statuses
        if isinstance(inner, dict):
            data = inner.get("data") if isinstance(inner.get("data"), dict) else None
            statuses = data.get("statuses") if data and isinstance(data.get("statuses"), list) else []
            for s in statuses:
                if isinstance(s, dict):
                    # si hay un string status
                    for v in s.values():
                        if isinstance(v, str) and "ioc" in v.lower() and "cancel" in v.lower():
                            return True
        return False
    except Exception:
        return False

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
    out = {"filled": False, "filled_sz": 0.0, "status": "UNKNOWN", "err": ""}

    if not resp:
        out["status"] = "EMPTY"
        return out

    # HTTP error encapsulado
    if isinstance(resp, dict) and resp.get("_http_error"):
        out["status"] = "ERROR"
        out["err"] = _extract_error_text(resp)
        return out

    st, inner = _unwrap_exchange(resp)
    if st == "err":
        out["status"] = "ERROR"
        out["err"] = _extract_error_text(resp)
        return out

    filled = _find_filled_sz(resp)
    if filled is None:
        # Si es IOC cancel explícito, lo marcamos NO_FILL real
        if _detect_ioc_cancel(resp):
            out["status"] = "NO_FILL"
            return out
        out["status"] = "NO_FILL"
        return out

    out["filled_sz"] = float(filled)
    out["filled"] = float(filled) > 0
    out["status"] = "FILLED" if out["filled"] else "NO_FILL"
    return out

# ------------------------------------------------------------
# Slippage adaptativo + clamp
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
# Place market order (Limit IOC agresiva, DOC-BASED)
#  - precio desde L2 best bid/ask (cruza de verdad)
#  - asegura MinTradeNtl (>= 10) post-redondeo
# ------------------------------------------------------------

_MIN_TRADE_NOTIONAL = 10.0
_MIN_TRADE_BUFFER = 0.15  # evita caer <10 tras rounding

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
        return {"ok": False, "filled": False, "reason": "NO_WALLET_OR_KEY"}

    coin = norm_coin(symbol)
    asset = get_asset_index(coin)
    if asset is None:
        return {"ok": False, "filled": False, "reason": "NO_ASSET", "coin": coin}

    sz_decimals = get_sz_decimals(asset)
    is_buy = side.lower() == "buy"

    mid0 = float(get_price(coin) or 0.0)
    if mid0 <= 0:
        return {"ok": False, "filled": False, "reason": "NO_MID", "coin": coin}

    base_slip = _default_slippage(mid0) if slippage is None else float(slippage)
    base_slip = _clamp_slippage(base_slip)

    total_attempts = 1 + max(0, int(max_no_fill_retries))
    last_resp = None

    for attempt in range(1, total_attempts + 1):
        # Precio real para cruzar: best ask/bid del libro
        bid, ask = _get_best_bid_ask(coin)
        mid = float(get_price(coin) or 0.0)

        ref_px = 0.0
        if is_buy:
            ref_px = ask if ask > 0 else (mid if mid > 0 else 0.0)
        else:
            ref_px = bid if bid > 0 else (mid if mid > 0 else 0.0)

        if ref_px <= 0:
            return {"ok": False, "filled": False, "reason": "NO_PRICE", "coin": coin}

        slip = _clamp_slippage(base_slip + (attempt - 1) * float(slippage_step))
        raw_px = ref_px * (1 + slip) if is_buy else ref_px * (1 - slip)

        p_str = _format_price_side(raw_px, sz_decimals, is_buy=is_buy)

        # Asegurar mínimo notional tras rounding:
        # - primero size DOWN (seguro), calculamos notional,
        # - si cae < 10, subimos size con ROUND_UP hasta >= 10+buffer
        qty = max(0.000001, float(qty))
        s_str = _format_size(qty, sz_decimals)

        try:
            px_f = float(p_str)
            sz_f = float(s_str)
        except Exception:
            return {"ok": False, "filled": False, "reason": "BAD_FORMATTED_PX_SZ_PARSE", "coin": coin, "px": p_str, "sz": s_str}

        if px_f <= 0 or sz_f <= 0:
            return {"ok": False, "filled": False, "reason": "BAD_FORMATTED_PX_SZ", "coin": coin, "px": p_str, "sz": s_str}

        notional = px_f * sz_f
        if notional < (_MIN_TRADE_NOTIONAL + _MIN_TRADE_BUFFER):
            target = (_MIN_TRADE_NOTIONAL + _MIN_TRADE_BUFFER) / max(px_f, 1e-12)
            s_str_up = _format_size_round(target, sz_decimals, ROUND_UP)
            try:
                if float(s_str_up) > 0:
                    s_str = s_str_up
                    sz_f = float(s_str)
                    notional = px_f * sz_f
            except Exception:
                pass

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
            return {"ok": False, "filled": False, "reason": "SIGN_ERROR", "coin": coin, "error": str(e)}

        payload = {
            "action": action,
            "nonce": nonce,
            "signature": signature,
            "expiresAfter": expires_after_ms,
        }
        if vault_address:
            payload["vaultAddress"] = vault_address

        r = make_request("/exchange", payload)
        last_resp = r

        fill = _detect_fill(r)

        # Si el exchange devolvió error, lo mostramos explícito
        if fill.get("status") == "ERROR":
            err_txt = fill.get("err") or _extract_error_text(r)
            safe_log("❌ EXCHANGE_ERROR:", coin, side, "px=", p_str, "sz=", s_str, "ntl~", round(notional, 4), "err=", err_txt)
            return {
                "ok": False,
                "filled": False,
                "reason": "EXCHANGE_ERROR",
                "coin": coin,
                "side": side,
                "sz": s_str,
                "px": p_str,
                "notional": float(notional),
                "error": err_txt,
                "raw": r,
            }

        if fill.get("filled"):
            safe_log(f"🟢 IOC {side.upper()} {s_str} {coin} px~{p_str} (ntl~{round(notional,4)}) attempt={attempt}")
            return {
                "ok": True,
                "filled": True,
                "reason": "FILLED",
                "coin": coin,
                "side": side,
                "sz": s_str,
                "px": p_str,
                "notional": float(notional),
                "slippage": slip,
                "attempt": attempt,
                "filled_sz": float(fill.get("filled_sz", 0.0) or 0.0),
                "raw": r,
            }

        # NO_FILL real (IOC cancel)
        if attempt < total_attempts:
            safe_log(f"🟡 NO_FILL {side.upper()} {s_str} {coin} px~{p_str} (ntl~{round(notional,4)}) -> retry")
            time.sleep(max(0.0, float(retry_delay_seconds)))
            continue

        safe_log(f"🟡 NO_FILL FINAL {side.upper()} {s_str} {coin} (IOC cancelado; no cuenta trade)")
        return {
            "ok": True,
            "filled": False,
            "reason": "NO_FILL",
            "coin": coin,
            "side": side,
            "sz": s_str,
            "px": p_str,
            "notional": float(notional),
            "slippage": slip,
            "attempt": attempt,
            "raw": r,
        }

    return {"ok": True, "filled": False, "reason": "NO_FILL", "coin": norm_coin(symbol), "raw": last_resp}

# ------------------------------------------------------------
# Wrappers
# ------------------------------------------------------------

def open_long(user_id: int, symbol: str, qty: float):
    return place_market_order(user_id, symbol, "buy", qty)

def open_short(user_id: int, symbol: str, qty: float):
    return place_market_order(user_id, symbol, "sell", qty)
