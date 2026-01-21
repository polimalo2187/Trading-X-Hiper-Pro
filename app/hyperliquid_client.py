# ============================================================
# HYPERLIQUID CLIENT – Trading X Hyper Pro
# PRODUCCIÓN REAL – LISTO PARA PROD (LECTURA + ÓRDENES + SIGN)
# ============================================================

import time
import threading
import httpx
from typing import Any, Dict, Optional

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
# HTTP Client global (pool) + Request (POST JSON) con reintentos
# ------------------------------------------------------------

_DEFAULT_HEADERS = {"Content-Type": "application/json"}

_http_client_lock = threading.Lock()
_http_client: Optional[httpx.Client] = None

def _get_http_client(timeout: float) -> httpx.Client:
    global _http_client
    with _http_client_lock:
        if _http_client is None:
            _http_client = httpx.Client(
                timeout=timeout,
                headers=_DEFAULT_HEADERS,
                limits=httpx.Limits(max_connections=50, max_keepalive_connections=20),
            )
        return _http_client

def make_request(endpoint: str, payload: dict, retries: int = 4, backoff: float = 1.0, timeout: Optional[float] = None):
    if timeout is None:
        timeout = REQUEST_TIMEOUT

    url = f"{HYPER_BASE_URL}{endpoint}"
    client = _get_http_client(timeout)

    for attempt in range(1, retries + 1):
        try:
            r = client.post(url, json=payload)
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
    # tolera inputs tipo BTC-PERP, BTC_PERP, BTC/USDC (si te llegan así por tu capa Telegram)
    s = s.replace("-PERP", "").replace("_PERP", "").replace("PERP", "")
    # si llega BTC/USDC, nos quedamos con BTC para perps (tu bot opera perps)
    if "/" in s:
        s = s.split("/", 1)[0].strip()
    return s

# ------------------------------------------------------------
# Cache: META (mapea coin -> asset index) y ALLMIDS (coin -> mid)
# ------------------------------------------------------------

_META_CACHE: Dict[str, Any] = {"coin_to_asset": {}, "ts": 0.0}
_MIDS_CACHE: Dict[str, Any] = {"mids": {}, "ts": 0.0}

META_TTL = 60.0
MIDS_TTL = 2.0

_cache_lock = threading.Lock()

def _refresh_meta_cache():
    now = time.time()
    with _cache_lock:
        if now - _META_CACHE["ts"] < META_TTL and _META_CACHE.get("coin_to_asset"):
            return

    r = make_request("/info", {"type": "meta"})
    if not isinstance(r, dict) or "universe" not in r:
        safe_log("❌ meta inválida:", r)
        return

    coin_to_asset: Dict[str, int] = {}
    try:
        for i, item in enumerate(r["universe"]):
            # en meta.universe suele venir {"name":"BTC", ...}
            name = item.get("name") if isinstance(item, dict) else None
            if name:
                coin_to_asset[str(name).upper()] = i

        if coin_to_asset:
            with _cache_lock:
                _META_CACHE["coin_to_asset"] = coin_to_asset
                _META_CACHE["ts"] = now
    except Exception as e:
        safe_log("❌ Error procesando meta:", str(e))

def get_asset_index(symbol: str) -> Optional[int]:
    _refresh_meta_cache()
    coin = norm_coin(symbol)
    with _cache_lock:
        return _META_CACHE["coin_to_asset"].get(coin)

def _refresh_mids_cache():
    now = time.time()
    with _cache_lock:
        if now - _MIDS_CACHE["ts"] < MIDS_TTL and _MIDS_CACHE.get("mids"):
            return

    r = make_request("/info", {"type": "allMids"})
    if not isinstance(r, dict):
        safe_log("❌ allMids inválido (se esperaba dict):", type(r), r)
        return

    mids: Dict[str, float] = {}
    try:
        # allMids suele traer también keys spot tipo "@107". Para perps usamos keys "BTC", "ETH", etc.
        for k, v in r.items():
            if not isinstance(k, str):
                continue
            if k.startswith("@"):
                continue
            try:
                mids[k.upper()] = float(v)
            except Exception:
                continue

        if mids:
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
# Firma: usar SDK oficial para evitar rechazos en prod
# ------------------------------------------------------------

class HyperliquidSigner:
    """
    Usa el signer del SDK oficial si está disponible.
    Esto evita errores sutiles de encoding (msgpack / action schema).
    """
    def __init__(self, private_key: str):
        self.private_key = private_key
        self._account = None
        self._sign_l1_action = None

        try:
            from eth_account import Account
            self._account = Account.from_key(private_key)

            # SDK: hyperliquid-python-sdk (paths varían por versión)
            try:
                from hyperliquid.utils.signing import sign_l1_action  # type: ignore
                self._sign_l1_action = sign_l1_action
            except Exception:
                from hyperliquid.utils.signing import sign_action as sign_l1_action  # type: ignore
                self._sign_l1_action = sign_l1_action

        except Exception as e:
            raise RuntimeError(
                "No se pudo importar hyperliquid-python-sdk para firma. "
                "Instala: pip install hyperliquid-python-sdk"
            ) from e

    @property
    def address(self) -> str:
        return self._account.address

    def sign(self, action: dict, nonce_ms: int, vault_address: Optional[str] = None) -> Any:
        return self._sign_l1_action(self._account, action, nonce_ms, vault_address)

# ------------------------------------------------------------
# Place market order (implementado como Limit IOC agresiva)
# ------------------------------------------------------------

def place_market_order(
    user_id: int,
    symbol: str,
    side: str,
    qty: float,
    slippage: float = 0.01,         # 1% por defecto
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

    mid = get_price(coin)
    if mid <= 0:
        safe_log("❌ No hay mid price para:", coin)
        return None

    is_buy = side.lower() == "buy"
    qty = max(0.000001, float(qty))

    # Precio agresivo para simular market: IOC (fill inmediato o cancel)
    px = mid * (1 + slippage) if is_buy else mid * (1 - slippage)

    # Nonce en milisegundos (crítico)
    nonce = int(time.time() * 1000)

    action = {
        "type": "order",
        "orders": [{
            "a": asset,              # asset index (int)
            "b": is_buy,             # bool
            "p": str(px),            # price string
            "s": str(qty),           # size string
            "r": False,              # reduceOnly
            "t": {"limit": {"tif": "Ioc"}},  # IOC
        }],
        "grouping": "na",
    }

    # Firma oficial (objeto con formato correcto)
    try:
        signer = HyperliquidSigner(private_key)
        signature = signer.sign(action, nonce, vault_address=vault_address)
    except Exception as e:
        safe_log("❌ Error firmando:", str(e))
        return None

    payload = {
        "action": action,
        "nonce": nonce,
        "signature": signature,
    }

    # Nota: el spec usa vaultAddress cuando aplica; NO uses "wallet" como campo.
    if vault_address:
        payload["vaultAddress"] = vault_address

    r = make_request("/exchange", payload)

    # Log útil si el exchange devuelve estructura de error
    if not r:
        safe_log("❌ Order rejected:", coin, side, qty)
        return None

    if isinstance(r, dict) and (r.get("status") in ("err", "error") or r.get("error")):
        safe_log("❌ Exchange error:", r)
        return None

    safe_log(f"🟢 MARKET(IOC) {side.upper()} {qty} {coin} @~{px}")
    return r

# ------------------------------------------------------------
# Wrappers
# ------------------------------------------------------------

def open_long(user_id: int, symbol: str, qty: float):
    return place_market_order(user_id, symbol, "buy", qty)

def open_short(user_id: int, symbol: str, qty: float):
    return place_market_order(user_id, symbol, "sell", qty)
