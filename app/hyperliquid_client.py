# ============================================================
# HYPERLIQUID CLIENT – Trading X Hyper Pro
# PRODUCCIÓN REAL – LISTO PARA PROD (LECTURA + ÓRDENES + SIGN)
# FIX NO_FILL: usa L2Book (best bid/ask) + 1 retry responsable
# Retorna dict: {"ok":bool,"filled":bool,...} para compatibilidad engine.py
# ============================================================

import time
import threading
import httpx
from typing import Any, Dict, Optional, Tuple
from decimal import Decimal, ROUND_DOWN, InvalidOperation

from app.config import (
    HYPER_BASE_URL,        # "https://api.hyperliquid.xyz"
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
# HTTP Request (POST JSON) con reintentos
# ------------------------------------------------------------

_DEFAULT_HEADERS = {"Content-Type": "application/json"}

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

    for attempt in range(1, retries + 1):
        try:
            with httpx.Client(timeout=timeout, headers=_DEFAULT_HEADERS) as client:
                r = client.post(url, json=payload)

                if r.status_code >= 400:
                    try:
                        err_text = r.text
                    except Exception:
                        err_text = "<no text>"
                    safe_log(f"❌ HTTP error [{attempt}/{retries}] {endpoint}: {r.status_code} body={err_text}")
                    r.raise_for_status()

                data = r.json()
                if isinstance(data, (dict, list)):
                    return data
                raise ValueError(f"Respuesta JSON inválida: {type(data)}")

        except (httpx.RequestError, httpx.HTTPStatusError, ValueError) as e:
            safe_log(f"❌ HTTP error [{attempt}/{retries}] {endpoint}:", str(e))
        except Exception as e:
            safe_log(f"❌ Unknown error [{attempt}/{retries}] {endpoint}:", str(e))

        if attempt < retries:
            time.sleep(backoff * attempt)

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
# Cache: META (coin -> asset index y szDecimals) y ALLMIDS (coin -> mid)
# ------------------------------------------------------------

_META_CACHE: Dict[str, Any] = {
    "coin_to_asset": {},
    "asset_to_sz": {},
    "ts": 0.0,
}
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
        safe_log("❌ allMids inválido:", type(r), r)
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
# Formateo estricto (evita 422 por tick/lot)
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
        safe_log("❌ Error leyendo balance:", str(e), r)
        return 0.0

# ------------------------------------------------------------
# Firma: SDK oficial (sign_l1_action)
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
            expires_after_ms = int(nonce_ms) + 60_000  # 60s
        if is_mainnet is None:
            is_mainnet = (str(HYPER_BASE_URL).rstrip("/") == "https://api.hyperliquid.xyz")
        return self._sign_l1_action(self._account, action, vault_address, nonce_ms, expires_after_ms, is_mainnet)

# ------------------------------------------------------------
# L2Book: obtener best bid/ask para cruzar y evitar NO_FILL
# ------------------------------------------------------------

def _get_best_bid_ask(coin: str) -> Tuple[float, float]:
    """
    Devuelve (best_bid, best_ask). Si no hay datos, (0,0).
    """
    coin = norm_coin(coin)
    if not coin:
        return 0.0, 0.0

    r = make_request("/info", {"type": "l2Book", "coin": coin})
    if not isinstance(r, dict):
        return 0.0, 0.0

    levels = r.get("levels")
    if not isinstance(levels, list) or len(levels) < 2:
        return 0.0, 0.0

    bids = levels[0]  # list of [px, sz] o dicts según versión
    asks = levels[1]

    def _px(level) -> float:
        try:
            if isinstance(level, list) and len(level) >= 1:
                return float(level[0])
            if isinstance(level, dict):
                return float(level.get("px") or level.get("p") or 0)
        except Exception:
            return 0.0
        return 0.0

    best_bid = _px(bids[0]) if isinstance(bids, list) and bids else 0.0
    best_ask = _px(asks[0]) if isinstance(asks, list) and asks else 0.0
    return float(best_bid), float(best_ask)

def _detect_fill(resp: Any) -> Dict[str, Any]:
    """
    Retorna {"filled": bool, "filled_sz": float}
    """
    out = {"filled": False, "filled_sz": 0.0}

    try:
        if not resp:
            return out

        # wrapper nuevo (si algún día vuelve aquí)
        if isinstance(resp, dict) and "filled" in resp:
            out["filled"] = bool(resp.get("filled"))
            out["filled_sz"] = float(resp.get("filled_sz") or 0.0)
            return out

        # buscar campos comunes en dict/list recursivo
        keys = {"filledsz", "fillsz", "filledsize", "filled_size", "filled", "filledqty", "filled_qty"}

        def walk(o):
            if isinstance(o, dict):
                for k, v in o.items():
                    lk = str(k).lower()
                    if lk in keys:
                        try:
                            return float(v)
                        except Exception:
                            pass
                    got = walk(v)
                    if got is not None:
                        return got
            elif isinstance(o, list):
                for it in o:
                    got = walk(it)
                    if got is not None:
                        return got
            return None

        f = walk(resp)
        if f is not None and float(f) > 0:
            out["filled"] = True
            out["filled_sz"] = float(f)
        return out
    except Exception:
        return out

  # ------------------------------------------------------------
# Place "market" (Limit IOC agresiva) usando best bid/ask
# + 1 retry responsable si NO_FILL
# ------------------------------------------------------------

def place_market_order(
    user_id: int,
    symbol: str,
    side: str,
    qty: float,
    vault_address: Optional[str] = None,

    # Ajustes de ejecución (seguros para producción)
    max_slippage: float = 0.05,      # 5% cap duro vs mid (anti locura)
    taker_bps_1: float = 0.0010,     # 0.10% cruza sobre ask/bajo bid
    taker_bps_2: float = 0.0030,     # 0.30% retry (más agresivo)
    retry_delay_seconds: float = 0.35,
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
        return {"ok": False, "filled": False, "reason": "NO_ASSET"}

    sz_decimals = get_sz_decimals(asset)

    is_buy = str(side).lower() == "buy"
    qty = max(0.000001, float(qty))

    # size string
    s_str = _format_size(qty, sz_decimals)
    try:
        if float(s_str) <= 0:
            return {"ok": False, "filled": False, "reason": "BAD_SIZE", "sz": s_str}
    except Exception:
        return {"ok": False, "filled": False, "reason": "BAD_SIZE_PARSE", "sz": s_str}

    # mid para caps
    mid = float(get_price(coin) or 0.0)
    if mid <= 0:
        return {"ok": False, "filled": False, "reason": "NO_MID"}

    # intentos: 2 (normal + retry)
    for attempt, bps in enumerate((taker_bps_1, taker_bps_2), start=1):
        best_bid, best_ask = _get_best_bid_ask(coin)

        # si no hay book, fallback mid
        if best_bid <= 0 or best_ask <= 0:
            raw_px = mid * (1 + bps) if is_buy else mid * (1 - bps)
        else:
            # BUY: cruzar por arriba del ask
            # SELL: cruzar por debajo del bid
            raw_px = (best_ask * (1 + bps)) if is_buy else (best_bid * (1 - bps))

        # cap vs mid (anti slippage loco)
        try:
            max_slip = max(0.0, float(max_slippage))
        except Exception:
            max_slip = 0.05

        if is_buy:
            raw_px = min(raw_px, mid * (1 + max_slip))
        else:
            raw_px = max(raw_px, mid * (1 - max_slip))

        p_str = _format_price(raw_px, sz_decimals)
        try:
            if float(p_str) <= 0:
                return {"ok": False, "filled": False, "reason": "BAD_PRICE", "px": p_str}
        except Exception:
            return {"ok": False, "filled": False, "reason": "BAD_PRICE_PARSE", "px": p_str}

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
            safe_log("❌ Error firmando:", str(e))
            return {"ok": False, "filled": False, "reason": "SIGN_ERROR", "error": str(e)}

        payload = {
            "action": action,
            "nonce": nonce,
            "signature": signature,
        }
        if vault_address:
            payload["vaultAddress"] = vault_address

        r = make_request("/exchange", payload)

        if not r:
            safe_log("❌ Order rejected:", coin, side, s_str, "px=", p_str)
            return {
                "ok": False,
                "filled": False,
                "reason": "EXCHANGE_REJECTED",
                "coin": coin,
                "side": side,
                "sz": s_str,
                "px": p_str,
                "attempt": attempt,
            }

        fill = _detect_fill(r)
        if fill.get("filled"):
            safe_log(f"🟢 MARKET(IOC) {side.upper()} {s_str} {coin} @~{p_str} (attempt {attempt}/2)")
            return {
                "ok": True,
                "filled": True,
                "filled_sz": float(fill.get("filled_sz") or 0.0),
                "reason": "FILLED",
                "coin": coin,
                "side": side,
                "sz": s_str,
                "px": p_str,
                "attempt": attempt,
                "raw": r,
            }

        # NO_FILL
        if attempt == 1:
            safe_log(f"🟡 NO_FILL {side.upper()} {s_str} {coin} @~{p_str} (attempt 1/2) -> retry")
            try:
                time.sleep(max(0.0, float(retry_delay_seconds)))
            except Exception:
                pass
            continue

        safe_log(f"🟡 NO_FILL {side.upper()} {s_str} {coin} @~{p_str} (IOC cancelado, no se cuenta trade)")
        return {
            "ok": True,
            "filled": False,
            "filled_sz": float(fill.get("filled_sz") or 0.0),
            "reason": "NO_FILL",
            "coin": coin,
            "side": side,
            "sz": s_str,
            "px": p_str,
            "attempt": attempt,
            "raw": r,
        }

    # fallback (no debería llegar)
    return {"ok": True, "filled": False, "filled_sz": 0.0, "reason": "NO_FILL", "coin": coin, "side": side}

# ------------------------------------------------------------
# Wrappers
# ------------------------------------------------------------

def open_long(user_id: int, symbol: str, qty: float):
    return place_market_order(user_id, symbol, "buy", qty)

def open_short(user_id: int, symbol: str, qty: float):
    return place_market_order(user_id, symbol, "sell", qty)
