# ============================================================
# STRATEGY – Trading X Hyper Pro
# Archivo 4/9 – Señales REALES nivel banco
# MODO GUERRA RENTABLE (4% → 18%)
# ============================================================

from collections import deque
from datetime import datetime, timedelta

from app.config import ENTRY_SIGNAL_THRESHOLD
from app.hyperliquid_client import get_price


# ============================================================
# BUFFER DE PRECIOS (SCALPING AGRESIVO CONTROLADO)
# ============================================================

PRICE_WINDOW = 3   # 🔥 Ultra rápido, ideal para compound diario

price_buffer = {}       # { symbol: deque([...]) }
last_update_time = {}   # { symbol: datetime }


def update_price(symbol: str, new_price: float):
    """
    Actualiza el buffer de precios por símbolo.
    Mantiene solo los últimos PRICE_WINDOW precios.
    """
    if symbol not in price_buffer:
        price_buffer[symbol] = deque(maxlen=PRICE_WINDOW)

    price_buffer[symbol].append(new_price)
    last_update_time[symbol] = datetime.utcnow()

    cleanup_stale_buffers()


def cleanup_stale_buffers():
    """
    Elimina símbolos que no se han actualizado
    en los últimos 10 minutos (limpieza de memoria).
    """
    now = datetime.utcnow()
    stale = [
        s for s, t in last_update_time.items()
        if now - t > timedelta(minutes=10)
    ]

    for s in stale:
        del price_buffer[s]
        del last_update_time[s]


# ============================================================
# SEÑAL DE ENTRADA – MODO GUERRA (PRODUCCIÓN)
# ============================================================

def get_entry_signal(symbol: str) -> dict:
    """
    Genera señal de entrada LONG o SHORT basada en:
        - Microtendencia real
        - Movimiento efectivo de precio
        - Filtro institucional (threshold dinámico)
    """

    price = get_price(symbol)
    if not price:
        return {"signal": False}

    update_price(symbol, price)

    prices = price_buffer.get(symbol)
    if not prices or len(prices) < PRICE_WINDOW:
        return {"signal": False}

    old_price = prices[0]
    last_price = prices[-1]

    if old_price <= 0:
        return {"signal": False}

    # ========================================================
    # FUERZA REAL DE MOVIMIENTO
    # ========================================================

    change = (last_price - old_price) / old_price
    raw_strength = abs(change * 100)  # % real

    # 🔥 AJUSTE CLAVE PARA PRODUCCIÓN
    # Permite entradas constantes sin overtrade
    strength = round(min(max(raw_strength, 0.0015), 7.5), 6)

    # ========================================================
    # THRESHOLD DINÁMICO (GUERRA)
    # ========================================================

    effective_threshold = max(
        ENTRY_SIGNAL_THRESHOLD * 0.65,
        0.0018   # piso absoluto para evitar bloqueo
    )

    if strength < effective_threshold:
        return {
            "signal": False,
            "strength": strength
        }

    direction = "long" if last_price > old_price else "short"

    return {
        "signal": True,
        "strength": strength,
        "direction": direction,
        "entry_price": price
    }


# ============================================================
# TP / SL – RENTABILIDAD COMPUESTA REAL
# ============================================================

def calculate_targets(
    entry_price: float,
    tp_percent: float,
    sl_percent: float,
    direction: str
) -> dict:
    """
    Calcula niveles finales de Take Profit y Stop Loss.
    Diseñado para:
        - Alta frecuencia
        - Pérdidas controladas
        - Ganancia compuesta diaria
    """

    # 🔒 CLAMPS DE SEGURIDAD (PRODUCCIÓN)
    tp_percent = min(max(tp_percent, 0.0015), 0.045)   # hasta 4.5%
    sl_percent = min(max(sl_percent, 0.0009), 0.020)  # hasta 2.0%

    if direction == "long":
        tp_price = entry_price * (1 + tp_percent)
        sl_price = entry_price * (1 - sl_percent)
    else:
        tp_price = entry_price * (1 - tp_percent)
        sl_price = entry_price * (1 + sl_percent)

    return {
        "tp": round(tp_price, 6),
        "sl": round(sl_price, 6)
      }
