# ============================================================
# HYPERLIQUID CLIENT – Trading X Hyper Pro
# PRODUCCIÓN REAL – LISTO PARA PROD (LECTURA + ÓRDENES + SIGN)
# ============================================================

import time
import threading
import httpx
from typing import Any, Dict, Optional
from decimal import Decimal, ROUND_DOWN, InvalidOperation

from app.config import (
    HYPER_BASE_URL,        # ej: "https://api.hyperliquid.xyz"
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

def make_request(endpoint: str, payload: dict, retries: int = 4, backoff: float = 1.0, timeout: Optional[float] = None):
    if timeout is None:
        timeout = REQUEST_TIMEOUT

    url = f"{HYPER_BASE_URL}{endpoint}"

    for attempt in range(1, retries + 1):
        try:
            with httpx.Client(timeout=timeout, headers=_DEFAULT_HEADERS) as client:
                r = client.post(url, json=payload)

                # Si falla, loguear body (clave para 422)
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
# Normalización de símbolo (perps: "BTC", "ETH"...)
# ------------------------------------------------------------

def norm_coin(symbol: str) -> str:
    if not isinstance(symbol, str):
        return ""
    s = symbol.strip().upper()
    # tolera inputs tipo BTC-PERP, BTC_PERP, BTC/USDC
    s = s.replace("-PERP", "").replace("_PERP", "").replace("PERP", "")
    if "/" in s:
        s = s.split("/", 1)[0].strip()
    return s

# ------------------------------------------------------------
# Cache: META (mapea coin -> asset index y szDecimals) y ALLMIDS (coin -> mid)
# ------------------------------------------------------------

_META_CACHE: Dict[str, Any] = {
    "coin_to_asset": {},     # coin -> index
    "asset_to_sz": {},       # index -> szDecimals
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

            # szDecimals es clave para size y también limita decimales de price
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
# Formateo estricto (evita 422 por tick/lot)
# ------------------------------------------------------------

def _strip_trailing_zeros(num_str: str) -> str:
    if "." not in num_str:
        return num_str
    num_str = num_str.rstrip("0").rstrip(".")
    return num_str if num_str else "0"

def _to_decimal(x: float) -> Decimal:
    # Convertir float->str primero para evitar artefactos binarios
    return Decimal(str(x))

def _format_size(sz: float, sz_decimals: int) -> str:
    try:
        d = _to_decimal(sz)
        if sz_decimals <= 0:
            out = d.quantize(Decimal("1"), rounding=ROUND_DOWN)
            return _strip_trailing_zeros(format(out, "f"))
        q = Decimal("1").scaleb(-sz_decimals)  # 10^-sz_decimals
        out = d.quantize(q, rounding=ROUND_DOWN)
        return _strip_trailing_zeros(format(out, "f"))
    except (InvalidOperation, Exception):
        return "0"

def _format_price(px: float, sz_decimals: int) -> str:
    """
    Perps: MAX_DECIMALS = 6. No más de (6 - szDecimals) decimales.
    Además, para precios >= 1, limitamos a ~5 cifras significativas de forma conservadora.
    (Evita 422 por px inválido)
    """
    MAX_DECIMALS = 6
    max_px_decimals = max(0, MAX_DECIMALS - int(sz_decimals or 0))

    try:
        d = _to_decimal(px)
        if d <= 0:
            return "0"

        # Caso precio grande: si tiene >=5 dígitos antes del punto, mandamos entero (válido).
        # Para 1..9999 aplicamos límite conservador de sig figs -> decimales permitidos.
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

        # Caso < 1: principalmente limitar decimales (6 y también 6-szDecimals)
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
# Firma: usar SDK oficial (sign_l1_action)
# ------------------------------------------------------------

class HyperliquidSigner:
    """
    Usa el signer del SDK oficial.
    Nota: algunas versiones requieren (expires_after, is_mainnet).
    """
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
            expires_after_ms = int(nonce_ms) + 60_000  # 60s

        if is_mainnet is None:
            is_mainnet = (str(HYPER_BASE_URL).rstrip("/") == "https://api.hyperliquid.xyz")

        # sign_l1_action(wallet, action, vault_address, timestamp, expires_after, is_mainnet)
        return self._sign_l1_action(self._account, action, vault_address, nonce_ms, expires_after_ms, is_mainnet)

# ------------------------------------------------------------
# Place market order (implementado como Limit IOC agresiva)
# ------------------------------------------------------------

def place_market_order(
    user_id: int,
    symbol: str,
    side: str,
    qty: float,
    slippage: float = 0.01,               # 1% por defecto
    vault_address: Optional[str] = None,  # si usas vault, aquí
):
    wallet = get_user_wallet(user_id)
    private_key = get_user_private_key(user_id)

    if not wallet or not private_key:
        safe_log("❌ Wallet / key missing")
        return None

    coin = norm_coin(symbol)
    asset = get_asset_index(coin)
    if asset is None:
        safe_log("❌ Asset no encontrado en meta.universe para:", coin)
        return None

    sz_decimals = get_sz_decimals(asset)

    mid = get_price(coin)
    if mid <= 0:
        safe_log("❌ No hay mid price para:", coin)
        return None

    is_buy = side.lower() == "buy"
    qty = max(0.000001, float(qty))

    raw_px = mid * (1 + slippage) if is_buy else mid * (1 - slippage)

    # ✅ Formateo estricto para evitar 422
    p_str = _format_price(raw_px, sz_decimals)
    s_str = _format_size(qty, sz_decimals)

    try:
        if float(s_str) <= 0 or float(p_str) <= 0:
            safe_log("❌ px/sz inválidos tras formateo:", coin, "px=", p_str, "sz=", s_str, "szDecimals=", sz_decimals)
            return None
    except Exception:
        safe_log("❌ px/sz inválidos tras formateo (parse fail):", coin, "px=", p_str, "sz=", s_str)
        return None

    # Nonce en milisegundos (recomendado)
    nonce = int(time.time() * 1000)

    action = {
        "type": "order",
        "orders": [{
            "a": asset,                       # asset index (int)
            "b": is_buy,                      # bool
            "p": p_str,                       # price string (estricto)
            "s": s_str,                       # size string (estricto)
            "r": False,                       # reduceOnly
            "t": {"limit": {"tif": "Ioc"}},   # IOC
        }],
        "grouping": "na",
    }

    # expiresAfter debe estar en payload y en firma coherente
    expires_after_ms = nonce + 60_000

    try:
        signer = HyperliquidSigner(private_key)
        signature = signer.sign(action, nonce, vault_address=vault_address, expires_after_ms=expires_after_ms)
    except Exception as e:
        safe_log("❌ Error firmando:", str(e))
        return None

    payload = {
        "action": action,
        "nonce": nonce,
        "signature": signature,
        "expiresAfter": expires_after_ms,
    }
    if vault_address:
        payload["vaultAddress"] = vault_address

    r = make_request("/exchange", payload)
    if not r:
        safe_log("❌ Order rejected:", coin, side, s_str, "px=", p_str)
        return None

    safe_log(f"🟢 MARKET(IOC) {side.upper()} {s_str} {coin} @~{p_str}")
    return r

# ------------------------------------------------------------
# Wrappers
# ------------------------------------------------------------

def open_long(user_id: int, symbol: str, qty: float):
    return place_market_order(user_id, symbol, "buy", qty)

def open_short(user_id: int, symbol: str, qty: float):
    return place_market_order(user_id, symbol, "sell", qty)
