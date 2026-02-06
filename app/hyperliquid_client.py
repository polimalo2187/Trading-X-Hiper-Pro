# ============================================================
SL_TRIGGER_DEBUG = bool(int(os.getenv('SL_TRIGGER_DEBUG', '1')))
# ============================================================
# HYPERLIQUID CLIENT – Trading X Hyper Pro (PROD)
# FIX DEFINITIVO:
#  - Parse REAL de /exchange: status ok/err + response.data.statuses
#  - Diferencia NO_FILL (IocCancel) vs EXCHANGE_ERROR (MinTradeNtl, Tick, etc.)
#  - Log mínimo obligatorio en NO_FILL/ERROR aunque VERBOSE_LOGS=False
#  - Precio IOC desde L2 (best bid/ask) + slippage
#  - Min notional >= 10 USDC post-rounding
#  - + has_open_position(user_id): evitar múltiples posiciones abiertas
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

def must_log(*args):
    # Esto SIEMPRE loguea (solo para NO_FILL / EXCHANGE_ERROR)
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
                body = r.text if hasattr(r, "text") else "<no text>"
                safe_log(f"❌ HTTP {r.status_code} {endpoint} body={body}")
                return {"_http_error": True, "_http_status": r.status_code, "_http_body": body}

            data = r.json()
            if isinstance(data, (dict, list)):
                return data
            return {"_http_error": True, "_http_status": 0, "_http_body": f"bad_json:{type(data)}"}

        except Exception as e:
            safe_log(f"❌ HTTP exception {endpoint} attempt {attempt}/{retries}:", str(e))
            if attempt < retries:
                time.sleep(backoff * attempt)

    return {"_http_error": True, "_http_status": 0, "_http_body": "request_failed"}

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
# Cache meta + mids
# ------------------------------------------------------------

_META_CACHE: Dict[str, Any] = {"coin_to_asset": {}, "asset_to_sz": {}, "asset_to_tick": {}, "ts": 0.0}
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
    asset_to_tick: Dict[int, float] = {}

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
            asset_to_sz[i] = max(szd, 0)            # Tick size: el precio debe ser múltiplo del tick.
            # En meta de Hyperliquid suele venir como tickSz / tickSize (string o número).
            # ⚠️ Importante: NO confundir con tickDecimals (entero), que NO es tick size.
            tick_val = 0.0
            try:
                for k, v in item.items():
                    lk = str(k).lower()
                    if lk in ("ticksz", "ticksize"):
                        try:
                            tv = float(v)
                            if tv > 0:
                                tick_val = tv
                                break
                        except Exception:
                            continue
                asset_to_tick[i] = float(tick_val) if tick_val > 0 else 0.0
            except Exception:
                asset_to_tick[i] = 0.0

        with _cache_lock:
            _META_CACHE["coin_to_asset"] = coin_to_asset
            _META_CACHE["asset_to_sz"] = asset_to_sz
            _META_CACHE["asset_to_tick"] = asset_to_tick
            _META_CACHE["ts"] = now
    except Exception as e:
        safe_log("❌ Error meta:", str(e))

def get_asset_index(symbol: str) -> Optional[int]:
    _refresh_meta_cache()
    coin = norm_coin(symbol)
    with _cache_lock:
        return _META_CACHE["coin_to_asset"].get(coin)

def get_sz_decimals(asset_index: int) -> int:
    _refresh_meta_cache()
    with _cache_lock:
        return int(_META_CACHE["asset_to_sz"].get(asset_index, 0) or 0)

def get_tick_size(asset_index: int) -> float:
    """Tick size (paso de precio) del asset. Si no está disponible, devuelve 0.0."""
    _refresh_meta_cache()
    with _cache_lock:
        try:
            return float(_META_CACHE["asset_to_tick"].get(asset_index, 0.0) or 0.0)
        except Exception:
            return 0.0

def _refresh_mids_cache():
    now = time.time()
    with _cache_lock:
        if now - _MIDS_CACHE["ts"] < MIDS_TTL:
            return

    r = make_request("/info", {"type": "allMids"})
    if not isinstance(r, dict):
        safe_log("❌ allMids inválido:", r)
        return

    mids: Dict[str, float] = {}
    for k, v in r.items():
        if not isinstance(k, str) or k.startswith("@"):
            continue
        try:
            mids[k.upper()] = float(v)
        except Exception:
            continue

    with _cache_lock:
        _MIDS_CACHE["mids"] = mids
        _MIDS_CACHE["ts"] = now

def get_price(symbol: str) -> float:
    coin = norm_coin(symbol)
    if not coin:
        return 0.0
    _refresh_mids_cache()
    with _cache_lock:
        px = _MIDS_CACHE["mids"].get(coin)
    return float(px) if px else 0.0

# ------------------------------------------------------------
# L2 Book -> best bid/ask
# ------------------------------------------------------------

def _get_l2_book(coin: str) -> Optional[dict]:
    coin = norm_coin(coin)
    if not coin:
        return None
    r = make_request("/info", {"type": "l2Book", "coin": coin})
    return r if isinstance(r, dict) else None

def _get_best_bid_ask(coin: str) -> Tuple[float, float]:
    try:
        book = _get_l2_book(coin)
        if not isinstance(book, dict):
            return (0.0, 0.0)
        levels = book.get("levels")
        if not isinstance(levels, list) or len(levels) < 2:
            return (0.0, 0.0)
        bids = levels[0] if isinstance(levels[0], list) else []
        asks = levels[1] if isinstance(levels[1], list) else []
        best_bid = float(bids[0].get("px", 0) or 0) if bids and isinstance(bids[0], dict) else 0.0
        best_ask = float(asks[0].get("px", 0) or 0) if asks and isinstance(asks[0], dict) else 0.0
        return (best_bid, best_ask)
    except Exception:
        return (0.0, 0.0)

# ✅ Export público (si algún módulo lo importa)
def get_best_bid_ask(symbol: str) -> Tuple[float, float]:
    return _get_best_bid_ask(symbol)

# ------------------------------------------------------------
# Formatting
# ------------------------------------------------------------

def _strip_trailing_zeros(num_str: str) -> str:
    if "." not in num_str:
        return num_str
    num_str = num_str.rstrip("0").rstrip(".")
    return num_str if num_str else "0"

def _to_decimal(x: float) -> Decimal:
    return Decimal(str(x))

def _quant(sz_decimals: int) -> Decimal:
    return Decimal("1") if sz_decimals <= 0 else Decimal("1").scaleb(-sz_decimals)

def _format_size_round(sz: float, sz_decimals: int, rounding) -> str:
    try:
        d = _to_decimal(sz)
        q = _quant(sz_decimals)
        out = d.quantize(q, rounding=rounding)
        return _strip_trailing_zeros(format(out, "f"))
    except (InvalidOperation, Exception):
        return "0"

def _format_size(sz: float, sz_decimals: int) -> str:
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
            q = Decimal("1") if allowed_decimals <= 0 else Decimal("1").scaleb(-allowed_decimals)
            out = d.quantize(q, rounding=rnd)
            return _strip_trailing_zeros(format(out, "f"))

        q = Decimal("1") if max_px_decimals <= 0 else Decimal("1").scaleb(-max_px_decimals)
        out = d.quantize(q, rounding=rnd)
        return _strip_trailing_zeros(format(out, "f"))

    except (InvalidOperation, Exception):
        return "0"


def _format_price_tick(px: float, tick_size: float, sz_decimals: int, is_buy: bool) -> str:
    """
    Formatea precio cumpliendo tickSize (múltiplo exacto).
    - BUY: redondea hacia arriba al tick (más agresivo para llenar IOC)
    - SELL: redondea hacia abajo al tick
    Si tick_size no está disponible, cae al formateador por decimales.
    """
    try:
        tick = float(tick_size or 0.0)
        if tick <= 0:
            return _format_price_side(px, sz_decimals, is_buy=is_buy)

        d_px = _to_decimal(px)
        if d_px <= 0:
            return "0"

        d_tick = _to_decimal(tick)

        # nº de ticks (entero)
        rnd = ROUND_UP if is_buy else ROUND_DOWN
        ticks = (d_px / d_tick).to_integral_value(rounding=rnd)
        out = ticks * d_tick

        # normalizar a precisión del tick (evita 0.10000000000002)
        q = d_tick
        out = out.quantize(q, rounding=rnd)

        return _strip_trailing_zeros(format(out, "f"))
    except (InvalidOperation, Exception):
        return _format_price_side(px, sz_decimals, is_buy=is_buy)

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
        return float(r.get("marginSummary", {}).get("accountValue", 0) or 0)
    except Exception:
        return 0.0

# ------------------------------------------------------------
# ✅ Detectar si ya hay posición abierta (1 trade a la vez)
# ------------------------------------------------------------


def get_position_entry_price(user_id: int, coin: str) -> float:
    """
    Devuelve el entryPx REAL de la posición abierta en el exchange para `coin`.
    Usa /info clearinghouseState (misma fuente que get_balance / has_open_position).

    Importante:
      - Retorna 0.0 si no hay posición o no se puede leer.
      - NO crea/cierras nada, solo lectura.
    """
    wallet = get_user_wallet(user_id)
    if not wallet:
        return 0.0

    coin = norm_coin(coin)
    if not coin:
        return 0.0

    r = make_request("/info", {"type": "clearinghouseState", "user": wallet})
    if not isinstance(r, dict):
        return 0.0

    aps = r.get("assetPositions") or []
    if not isinstance(aps, list):
        return 0.0

    for ap in aps:
        if not isinstance(ap, dict):
            continue
        pos = ap.get("position")
        if not isinstance(pos, dict):
            continue

        c = (pos.get("coin") or ap.get("coin") or "").strip().upper()
        if norm_coin(c) != coin:
            continue

        try:
            szi = float(pos.get("szi", 0) or 0)
        except Exception:
            szi = 0.0

        # Solo si hay size real
        if abs(szi) <= 0.0:
            continue

        for key in ("entryPx", "entry_px", "entryPrice", "avgPx", "averagePrice"):
            if key in pos:
                try:
                    v = float(pos.get(key) or 0)
                    if v > 0:
                        return v
                except Exception:
                    pass

    return 0.0

def get_open_position_size(user_id: int, coin: str) -> float:
    """Devuelve el SIZE REAL (abs(szi)) de la posición abierta para `coin`. 0.0 si no hay."""
    wallet = get_user_wallet(user_id)
    if not wallet:
        return 0.0

    coin = norm_coin(coin)
    if not coin:
        return 0.0

    r = make_request("/info", {"type": "clearinghouseState", "user": wallet})
    if not isinstance(r, dict):
        return 0.0

    aps = r.get("assetPositions") or []
    if not isinstance(aps, list):
        return 0.0

    for ap in aps:
        if not isinstance(ap, dict):
            continue
        pos = ap.get("position")
        if not isinstance(pos, dict):
            continue

        c = (pos.get("coin") or ap.get("coin") or "").strip().upper()
        if norm_coin(c) != coin:
            continue

        try:
            szi = float(pos.get("szi", 0) or 0)
        except Exception:
            szi = 0.0

        if abs(szi) <= 0.0:
            return 0.0

        return abs(float(szi))

    return 0.0

def has_open_position(user_id: int) -> bool:
    wallet = get_user_wallet(user_id)
    if not wallet:
        return False

    r = make_request("/info", {"type": "clearinghouseState", "user": wallet})
    if not isinstance(r, dict):
        return False

    positions = r.get("assetPositions")
    if not isinstance(positions, list):
        return False

    for ap in positions:
        if not isinstance(ap, dict):
            continue
        pos = ap.get("position")
        if not isinstance(pos, dict):
            continue

        szi = pos.get("szi")
        try:
            if szi is not None and float(szi) != 0.0:
                return True
        except Exception:
            pass

    return False

# ------------------------------------------------------------
# Signer (SDK)
# ------------------------------------------------------------

class HyperliquidSigner:
    def __init__(self, private_key: str):
        try:
            from hyperliquid.utils.signing import sign_l1_action
            from eth_account import Account
            self._account = Account.from_key(private_key)
            self._sign_l1_action = sign_l1_action
        except Exception as e:
            raise RuntimeError("Firma HL: instala hyperliquid-python-sdk") from e

    def sign(
        self,
        action: dict,
        nonce_ms: int,
        vault_address: Optional[str] = None,
        expires_after_ms: Optional[int] = None,
        is_mainnet: Optional[bool] = None
    ) -> Any:
        if expires_after_ms is None:
            expires_after_ms = int(nonce_ms) + 60_000
        if is_mainnet is None:
            is_mainnet = (str(HYPER_BASE_URL).rstrip("/") == "https://api.hyperliquid.xyz")
        return self._sign_l1_action(self._account, action, vault_address, nonce_ms, expires_after_ms, is_mainnet)

# ------------------------------------------------------------
# Parse REAL de /exchange: statuses
# ------------------------------------------------------------

def _unwrap_exchange(resp: Any) -> Tuple[str, Any]:
    if not isinstance(resp, dict):
        return ("unknown", resp)
    st = str(resp.get("status") or "").lower()
    if st in ("ok", "err") and "response" in resp:
        return (st, resp.get("response"))
    return ("unknown", resp)

def _extract_statuses(resp: Any) -> list:
    """
    Esperado en OK:
      {"status":"ok","response":{"type":"order","data":{"statuses":[ ... ]}}}
    """
    st, inner = _unwrap_exchange(resp)
    if st != "ok" or not isinstance(inner, dict):
        return []
    data = inner.get("data")
    if not isinstance(data, dict):
        return []
    statuses = data.get("statuses")
    return statuses if isinstance(statuses, list) else []

def _parse_status(status_obj: Any) -> Dict[str, Any]:
    """
    statuses[i] suele ser dict con UNA clave:
      {"filled": {...}} o {"error": "..."} o {"resting": {...}}
    """
    out = {"kind": "unknown", "error": "", "filled_sz": 0.0}
    if not isinstance(status_obj, dict) or not status_obj:
        return out

    if "error" in status_obj:
        out["kind"] = "error"
        out["error"] = str(status_obj.get("error") or "")
        return out

    if "filled" in status_obj and isinstance(status_obj.get("filled"), dict):
        out["kind"] = "filled"
        f = status_obj.get("filled")
        for k in ("totalSz", "filledSz", "sz"):
            if k in f:
                try:
                    out["filled_sz"] = float(f.get(k) or 0)
                    break
                except Exception:
                    pass
        return out

    if "resting" in status_obj:
        out["kind"] = "resting"
        return out

    out["kind"] = "unknown"
    return out

def _detect_fill(resp: Any) -> Dict[str, Any]:
    out = {"filled": False, "filled_sz": 0.0, "status": "UNKNOWN", "error": ""}

    if not resp:
        out["status"] = "ERROR"
        out["error"] = "EMPTY_RESPONSE"
        return out

    if isinstance(resp, dict) and resp.get("_http_error"):
        out["status"] = "ERROR"
        out["error"] = f"HTTP {resp.get('_http_status')} {resp.get('_http_body')}"
        return out

    st, inner = _unwrap_exchange(resp)
    if st == "err":
        out["status"] = "ERROR"
        out["error"] = str(inner)
        return out

    statuses = _extract_statuses(resp)
    if statuses:
        first = _parse_status(statuses[0])

        if first["kind"] == "error":
            err = (first.get("error") or "").strip()
            out["error"] = err
            if "ioccancel" in err.lower() or "ioc cancel" in err.lower():
                out["status"] = "NO_FILL"
                return out
            out["status"] = "ERROR"
            return out

        if first["kind"] == "filled":
            out["filled_sz"] = float(first.get("filled_sz") or 0.0)
            out["filled"] = out["filled_sz"] > 0
            out["status"] = "FILLED" if out["filled"] else "NO_FILL"
            return out

        if first["kind"] == "resting":
            out["status"] = "NO_FILL"
            out["error"] = "RESTING_UNEXPECTED"
            return out

    out["status"] = "ERROR"
    out["error"] = "NO_STATUSES_IN_RESPONSE"
    return out

# ------------------------------------------------------------
# Slippage adaptativo
# ------------------------------------------------------------

def _default_slippage(ref_px: float) -> float:
    try:
        if ref_px < 1:
            return 0.03
        if ref_px < 10:
            return 0.02
        return 0.01
    except Exception:
        return 0.02

def _clamp_slippage(x: float) -> float:
    try:
        x = float(x)
    except Exception:
        x = 0.02
    return max(0.0, min(x, 0.08))

# ------------------------------------------------------------
# Place market order (IOC agresiva)
# ------------------------------------------------------------

_MIN_TRADE_NOTIONAL = 10.0
_MIN_TRADE_BUFFER = 0.20

# ------------------------------------------------------------
# Margin mode / leverage (FORZAR ISOLATED)
# ------------------------------------------------------------

FORCE_ISOLATED = True
FORCE_LEVERAGE = 3

def _set_isolated_leverage(
    private_key: str,
    asset: int,
    leverage: int,
    vault_address: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Fuerza isolated + leverage para el asset.
    Devuelve {"ok": bool, "reason": str, "raw": Any}
    """
    try:
        lev = int(leverage)
        if lev <= 0:
            lev = 1
    except Exception:
        lev = 1

    nonce = int(time.time() * 1000)
    expires_after_ms = nonce + 60_000

    action = {
        "type": "updateLeverage",
        "asset": asset,
        "isCross": False,
        "leverage": lev,
    }

    try:
        signer = HyperliquidSigner(private_key)
        signature = signer.sign(
            action,
            nonce,
            vault_address=vault_address,
            expires_after_ms=expires_after_ms,
        )
    except Exception as e:
        return {"ok": False, "reason": "SIGN_ERROR", "raw": str(e)}

    payload = {
        "action": action,
        "nonce": nonce,
        "signature": signature,
        "expiresAfter": expires_after_ms,
    }
    if vault_address:
        payload["vaultAddress"] = vault_address

    resp = make_request("/exchange", payload)
    st, inner = _unwrap_exchange(resp)
    if st == "ok":
        return {"ok": True, "reason": "OK", "raw": resp}

    return {"ok": False, "reason": str(inner), "raw": resp}

def place_market_order(
    user_id: int,
    symbol: str,
    side: str,
    qty: float,
    slippage: Optional[float] = None,
    vault_address: Optional[str] = None,
    max_no_fill_retries: int = 1,
    retry_delay_seconds: float = 0.35,
    slippage_step: float = 0.02,
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
    tick_size = get_tick_size(asset)
    is_buy = side.lower() == "buy"

    # ✅ FORZAR ISOLATED + LEVERAGE (antes de ordenar)
    if FORCE_ISOLATED:
        lev_resp = _set_isolated_leverage(
            private_key=private_key,
            asset=asset,
            leverage=FORCE_LEVERAGE,
            vault_address=vault_address,
        )
        if not lev_resp.get("ok"):
            must_log(
                f"❌ updateLeverage failed coin={coin} asset={asset} "
                f"lev={FORCE_LEVERAGE} reason={lev_resp.get('reason')}"
            )
            return {
                "ok": False,
                "filled": False,
                "reason": "LEVERAGE_MODE_SET_FAILED",
                "coin": coin,
                "error": lev_resp.get("reason"),
            }

    bid, ask = _get_best_bid_ask(coin)
    mid = float(get_price(coin) or 0.0)

    ref_px = (ask if is_buy else bid)
    if ref_px <= 0:
        ref_px = mid
    if ref_px <= 0:
        return {"ok": False, "filled": False, "reason": "NO_PRICE", "coin": coin}

    base_slip = _default_slippage(ref_px) if slippage is None else float(slippage)
    base_slip = _clamp_slippage(base_slip)

    total_attempts = 1 + max(0, int(max_no_fill_retries))

    for attempt in range(1, total_attempts + 1):
        bid, ask = _get_best_bid_ask(coin)
        mid = float(get_price(coin) or 0.0)
        ref_px = (ask if is_buy else bid)
        if ref_px <= 0:
            ref_px = mid
        if ref_px <= 0:
            return {"ok": False, "filled": False, "reason": "NO_PRICE", "coin": coin}

        slip = _clamp_slippage(base_slip + (attempt - 1) * float(slippage_step))
        raw_px = ref_px * (1 + slip) if is_buy else ref_px * (1 - slip)

        p_str = _format_price_tick(raw_px, tick_size, sz_decimals, is_buy=is_buy)

        qty = max(0.000001, float(qty))
        s_str = _format_size(qty, sz_decimals)

        try:
            px_f = float(p_str)
            sz_f = float(s_str)
        except Exception:
            return {
                "ok": False,
                "filled": False,
                "reason": "BAD_FORMATTED",
                "coin": coin,
                "px": p_str,
                "sz": s_str,
            }

        notional = px_f * sz_f

        if notional < (_MIN_TRADE_NOTIONAL + _MIN_TRADE_BUFFER):
            required_ntl = float(_MIN_TRADE_NOTIONAL + _MIN_TRADE_BUFFER)
            required_sz = required_ntl / max(px_f, 1e-12)

            # ✅ NO inyectamos size para "forzar" mínimos: respetamos el capital del usuario.
            # Si el exchange requiere un mínimo (notional), devolvemos razón explícita.
            must_log(
                f"🟠 MIN_NOTIONAL coin={coin} side={side} px={p_str} sz={s_str} "
                f"ntl~{round(notional,4)} required~{round(required_ntl,4)}"
            )
            return {
                "ok": False,
                "filled": False,
                "reason": "MIN_NOTIONAL",
                "coin": coin,
                "side": side,
                "px": p_str,
                "sz": s_str,
                "notional": float(notional),
                "min_notional": float(required_ntl),
                "required_sz": float(required_sz),
            }

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
            signature = signer.sign(
                action,
                nonce,
                vault_address=vault_address,
                expires_after_ms=expires_after_ms,
            )
        except Exception as e:
            return {"ok": False, "filled": False, "reason": "SIGN_ERROR", "coin": coin, "error": str(e)}

        payload = {"action": action, "nonce": nonce, "signature": signature, "expiresAfter": expires_after_ms}
        if vault_address:
            payload["vaultAddress"] = vault_address

        r = make_request("/exchange", payload)
        det = _detect_fill(r)

        # ---- ERROR real del exchange
        if det["status"] == "ERROR":
            must_log(
                f"❌ EXCHANGE_ERROR coin={coin} side={side} bid={bid} ask={ask} "
                f"px={p_str} sz={s_str} ntl~{round(notional,4)} err={det.get('error')}"
            )
            return {
                "ok": False,
                "filled": False,
                "reason": "EXCHANGE_ERROR",
                "coin": coin,
                "side": side,
                "bid": bid,
                "ask": ask,
                "px": p_str,
                "sz": s_str,
                "notional": float(notional),
                "error": det.get("error", ""),
                "raw": r,
            }

        # ---- FILLED
        if det["status"] == "FILLED":
            safe_log(
                f"🟢 FILLED coin={coin} side={side} px={p_str} sz={s_str} "
                f"ntl~{round(notional,4)} slip={round(slip*100,2)}%"
            )
            return {
                "ok": True,
                "filled": True,
                "reason": "FILLED",
                "coin": coin,
                "side": side,
                "bid": bid,
                "ask": ask,
                "px": p_str,
                "sz": s_str,
                "notional": float(notional),
                "slippage": slip,
                "attempt": attempt,
                "filled_sz": float(det.get("filled_sz") or 0.0),
                "raw": r,
            }

        # ---- NO_FILL (IOC cancel)
        must_log(
            f"🟡 NO_FILL coin={coin} side={side} bid={bid} ask={ask} "
            f"px={p_str} sz={s_str} ntl~{round(notional,4)} err={det.get('error')}"
        )
        if attempt < total_attempts:
            time.sleep(max(0.0, float(retry_delay_seconds)))
            continue

        return {
            "ok": True,
            "filled": False,
            "reason": "NO_FILL",
            "coin": coin,
            "side": side,
            "bid": bid,
            "ask": ask,
            "px": p_str,
            "sz": s_str,
            "notional": float(notional),
            "error": det.get("error", ""),
            "raw": r,
        }

    return {"ok": True, "filled": False, "reason": "NO_FILL", "coin": norm_coin(symbol)}

# ------------------------------------------------------------
# Wrappers
# ------------------------------------------------------------

def open_long(user_id: int, symbol: str, qty: float):
    return place_market_order(user_id, symbol, "buy", qty)

def open_short(user_id: int, symbol: str, qty: float):
    return place_market_order(user_id, symbol, "sell", qty)



# ============================================================
# ✅ SL REAL EN EXCHANGE (Trigger TP/SL) + Cancel por OID
# Permite proteger la posición aunque el bot / servidor caiga.
# Formato (docs):
# - Trigger orders: t.trigger {isMarket, triggerPx, tpsl:'sl'}
# - Cancel by oid: action.type='cancel' cancels[{a,o}]
# ============================================================

def _extract_first_oid(resp: Any) -> Optional[int]:
    """Intenta extraer el OID del primer status (resting/filled) en la respuesta ok del exchange."""
    try:
        statuses = _extract_statuses(resp)
        if not statuses:
            return None

        def _walk(x: Any) -> Optional[int]:
            if isinstance(x, dict):
                if "oid" in x:
                    try:
                        return int(x.get("oid"))
                    except Exception:
                        pass
                for v in x.values():
                    o = _walk(v)
                    if o is not None:
                        return o
            elif isinstance(x, list):
                for it in x:
                    o = _walk(it)
                    if o is not None:
                        return o
            return None

        return _walk(statuses[0])
    except Exception:
        return None


def _format_trigger_px(px: float, tick_size: float, reduce_side: str) -> str:
    """
    Formatea triggerPx cumpliendo tickSize.
    Para SL:
      - Si reduce_side='sell' (cerrando LONG): trigger ligeramente MÁS ALTO (más seguro) => ROUND_UP
      - Si reduce_side='buy'  (cerrando SHORT): trigger ligeramente MÁS BAJO (más seguro) => ROUND_DOWN
    """
    try:
        tick = float(tick_size or 0.0)
        if tick <= 0:
            return str(Decimal(str(px)).quantize(Decimal('0.00000001'), rounding=ROUND_DOWN)).rstrip('0').rstrip('.') or '0'

        d_px = _to_decimal(px)
        d_tick = _to_decimal(tick)

        if reduce_side.lower() == "sell":
            n = (d_px / d_tick).to_integral_value(rounding=ROUND_UP)
        else:
            n = (d_px / d_tick).to_integral_value(rounding=ROUND_DOWN)

        out = (n * d_tick).quantize(d_tick, rounding=ROUND_DOWN)
        return format(out, 'f')
    except Exception:
        return str(px)


def place_sl_trigger(
    user_id: int,
    symbol: str,
    side: str,
    qty: float,
    trigger_price: float,
    vault_address: Optional[str] = None,
) -> Optional[int]:
    """
    Crea un Stop Loss REAL en Hyperliquid (trigger order, market, reduce-only).
    Retorna oid (int) si la orden fue aceptada por el exchange.
    """
    wallet = get_user_wallet(user_id)
    private_key = get_user_private_key(user_id)
    if not wallet or not private_key:
        return None

    coin = norm_coin(symbol)
    asset = get_asset_index(coin)
    if asset is None:
        return None

    sz_decimals = get_sz_decimals(asset)
    tick_size = get_tick_size(asset)

    is_buy = side.lower() == "buy"

    try:
        s_str = _format_size(float(qty), sz_decimals)
    except Exception:
        return None

    trigger_px_str = _format_trigger_px(float(trigger_price), tick_size, reduce_side=side)

    nonce = int(time.time() * 1000)
    expires_after_ms = nonce + 60_000

    action = {
        "type": "order",
        "orders": [{
            "a": asset,
            "b": bool(is_buy),
            "p": "0",
            "s": s_str,
            "r": True,
            "t": {"trigger": {"isMarket": True, "triggerPx": str(trigger_px_str), "tpsl": "sl"}},
        }],
        "grouping": "na",
    }

    try:
        signer = HyperliquidSigner(private_key)
        signature = signer.sign(
            action,
            nonce,
            vault_address=vault_address,
            expires_after_ms=expires_after_ms,
        )
    except Exception:
        return None

    payload = {
        "action": action,
        "nonce": nonce,
        "signature": signature,
        "expiresAfter": expires_after_ms,
    }
    if vault_address:
        payload["vaultAddress"] = vault_address

    resp = make_request("/exchange", payload)
    st, _inner = _unwrap_exchange(resp)
    if st != "ok":
        must_log(f"❌ SL trigger rejected coin={coin} resp={resp}")
        return None

    oid = _extract_first_oid(resp)
    if oid is None:
        safe_log(f"⚠️ SL trigger OK pero sin oid parseable coin={coin} resp={resp}")
        return None

    return oid


def cancel_order_by_oid(
    user_id: int,
    symbol: str,
    oid: int,
    vault_address: Optional[str] = None,
) -> Dict[str, Any]:
    """Cancela una orden por OID (order id)."""
    wallet = get_user_wallet(user_id)
    private_key = get_user_private_key(user_id)
    if not wallet or not private_key:
        return {"ok": False, "reason": "NO_WALLET_OR_KEY"}

    coin = norm_coin(symbol)
    asset = get_asset_index(coin)
    if asset is None:
        return {"ok": False, "reason": "NO_ASSET", "coin": coin}

    try:
        oid_int = int(oid)
    except Exception:
        return {"ok": False, "reason": "BAD_OID"}

    nonce = int(time.time() * 1000)
    expires_after_ms = nonce + 60_000

    action = {"type": "cancel", "cancels": [{"a": asset, "o": oid_int}]}

    try:
        signer = HyperliquidSigner(private_key)
        signature = signer.sign(
            action,
            nonce,
            vault_address=vault_address,
            expires_after_ms=expires_after_ms,
        )
    except Exception as e:
        return {"ok": False, "reason": "SIGN_ERROR", "error": str(e)}

    payload = {"action": action, "nonce": nonce, "signature": signature, "expiresAfter": expires_after_ms}
    if vault_address:
        payload["vaultAddress"] = vault_address

    resp = make_request("/exchange", payload)
    st, inner = _unwrap_exchange(resp)
    if st == "ok":
        return {"ok": True, "reason": "OK", "raw": resp}
    return {"ok": False, "reason": str(inner), "raw": resp}
