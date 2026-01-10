# ============================================================
# ARCHIVO: app/strategy.py
# ============================================================
# Estrategia de entrada por MOMENTUM ACUMULADO
# PRODUCCIÓN REAL – Hyperliquid
# ============================================================

from collections import deque
import time

# ============================================================
# CONFIGURACIÓN ESTRATEGIA (PRODUCCIÓN)
# ============================================================

PRICE_WINDOW = 6               # 🔥 Reducido para rotación real
ENTRY_SIGNAL_THRESHOLD = 0.10  # % movimiento mínimo
MAX_BUFFER_AGE = 120           # segundos (NO borrar tan agresivo)

# ============================================================
# BUFFER GLOBAL
# ============================================================

price_buffer: dict[str, deque] = {}
price_timestamp: dict[str, float] = {}

# ============================================================
# UTILIDADES
# ============================================================

def update_price(symbol: str, price: float):
    now = time.time()

    if symbol not in price_buffer:
        price_buffer[symbol] = deque(maxlen=PRICE_WINDOW)
        price_timestamp[symbol] = now

    # Solo limpiar si está REALMENTE muerto
    if now - price_timestamp[symbol] > MAX_BUFFER_AGE:
        price_buffer[symbol].clear()

    price_buffer[symbol].append(price)
    price_timestamp[symbol] = now


# ============================================================
# FUNCIÓN PRINCIPAL (ENGINE → STRATEGY)
# ============================================================

def get_entry_signal(symbol: str, price: float) -> dict:
    """
    Retorna SIEMPRE un dict explicativo
    """

    if price is None or price <= 0:
        return {
            "signal": False,
            "reason": "precio inválido"
        }

    update_price(symbol, price)

    prices = price_buffer.get(symbol)

    if not prices or len(prices) < PRICE_WINDOW:
        return {
            "signal": False,
            "reason": f"buffer incompleto ({len(prices)}/{PRICE_WINDOW})"
        }

    old_price = prices[0]
    last_price = prices[-1]

    if old_price <= 0:
        return {
            "signal": False,
            "reason": "precio histórico inválido"
        }

    change = (last_price - old_price) / old_price
    strength = abs(change) * 100

    if strength < ENTRY_SIGNAL_THRESHOLD:
        return {
            "signal": False,
            "strength": round(strength, 4),
            "reason": "momentum insuficiente"
        }

    direction = "long" if change > 0 else "short"

    return {
        "signal": True,
        "direction": direction,
        "strength": round(strength, 4),
        "entry_price": round(last_price, 6),
        "reason": "momentum confirmado"
      }
