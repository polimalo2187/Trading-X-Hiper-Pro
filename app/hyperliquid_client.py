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

                # Si falla, logueamos también el body para debug (clave en 422)
                try:
                    r.raise_for_status()
                except httpx.HTTPStatusError as e:
                    body_preview = ""
                    try:
                        body_preview = r.text
                    except Exception:
                        body_preview = ""
                    raise httpx.HTTPStatusError(
                        message=f"{str(e)} | body={body_preview}",
                        request=e.request,
                        response=e.response,
                    ) from e

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
        if now - _META_CACHE["ts"] < META_TTL:
            return

    r = make_request("/info", {"type": "meta"})
    if not isinstance(r, dict) or "universe" not in r:
        safe_log("❌ meta inválida:", r)
        return

    coin_to_asset: Dict[str, int] = {}
    try:
        for i, item in enumerate(r["universe"]):
            name = item.get("name")
            if name:
                coin_to_asset[str(name).upper()] = i

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

def _serialize_signature(sig: Any) -> Any:
    """
    Asegura que la firma sea JSON-serializable.
    El SDK suele devolver un dict listo; esto es blindaje extra.
    """
    try:
        if isinstance(sig, dict):
            return sig
        # Algunos objetos tienen .to_dict()
        to_dict = getattr(sig, "to_dict", None)
        if callable(to_dict):
            return to_dict()
        # Si es bytes/HexBytes
        if isinstance(sig, (bytes, bytearray)):
            return sig.hex()
        return sig
    except Exception:
        return sig

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
        # expires_after: timestamp ms después del cual se rechaza la acción (recomendado)
        if expires_after_ms is None:
            expires_after_ms = int(nonce_ms) + 60_000  # 60s

        # is_mainnet: el SDK lo usa para escoger dominios / config
        if is_mainnet is None:
            is_mainnet = (str(HYPER_BASE_URL).rstrip("/") == "https://api.hyperliquid.xyz")

        # IMPORTANTE:
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

    mid = get_price(coin)
    if mid <= 0:
        safe_log("❌ No hay mid price para:", coin)
        return None

    is_buy = side.lower() == "buy"
    qty = max(0.000001, float(qty))

    px = mid * (1 + slippage) if is_buy else mid * (1 - slippage)

    # Nonce en milisegundos (recomendado)
    nonce = int(time.time() * 1000)

    # ExpiresAfter (ms) – recomendado por docs para acciones soportadas como orders
    expires_after = nonce + 60_000  # 60s

    action = {
        "type": "order",
        "orders": [{
            "a": asset,                       # asset index (int)
            "b": is_buy,                      # bool
            "p": str(px),                     # price string
            "s": str(qty),                    # size string
            "r": False,                       # reduceOnly
            "t": {"limit": {"tif": "Ioc"}},   # IOC
        }],
        "grouping": "na",
    }

    try:
        signer = HyperliquidSigner(private_key)
        signature = signer.sign(action, nonce, vault_address=vault_address, expires_after_ms=expires_after)
        signature = _serialize_signature(signature)
    except Exception as e:
        safe_log("❌ Error firmando:", str(e))
        return None

    # IMPORTANTE (FIX 422):
    # expiresAfter debe ir en el payload del /exchange cuando se usa para firmar.
    payload = {
        "action": action,
        "nonce": nonce,
        "signature": signature,
        "expiresAfter": expires_after,
    }
    if vault_address:
        payload["vaultAddress"] = vault_address

    r = make_request("/exchange", payload)
    if not r:
        safe_log("❌ Order rejected:", coin, side, qty)
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
