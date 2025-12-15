# ============================================================
# MARKET SCANNER – TRADING X HYPER PRO
# Escáner profesional de mercado para seleccionar el MEJOR PAR
# Compatible con hyperliquid_client.py
# ============================================================

import random
from app.hyperliquid_client import make_request, get_price

# ============================================================
# OBTENER LISTA DE PARES DISPONIBLES EN HYPERLIQUID
# ============================================================

def get_all_symbols():
    """
    Devuelve una lista de TODOS los símbolos PERPETUAL disponibles
    en HyperLiquid usando la API real.
    """

    payload = {"type": "allMids"}
    r = make_request("/info", payload)

    if not r or "mids" not in r:
        print("❌ No se pudo obtener la lista de pares.")
        return []

    # Los pares vienen con este formato:
    # { "BTC", "ETH", "SOL", ... }
    symbols = list(r["mids"].keys())
    return symbols


# ============================================================
# ANALIZAR UN PAR INDIVIDUAL
# ============================================================

def analyze_symbol(symbol):
    """
    Analiza un símbolo y devuelve un puntaje basado en:
    - Precio real
    - Momentum simulado
    - Volatilidad simulada
    - Volumen estimado
    """

    price = get_price(symbol)
    if not price or price <= 0:
        return None

    # Simulaciones controladas (hasta integrar datos reales)
    momentum = random.uniform(0.4, 1.0)
    volatility = random.uniform(0.3, 1.0)
    volume = random.uniform(0.5, 1.0)

    # Fórmula de scoring profesional
    score = (momentum * 0.5) + (volatility * 0.3) + (volume * 0.2)

    return {
        "symbol": symbol,
        "price": price,
        "momentum": round(momentum, 4),
        "volatility": round(volatility, 4),
        "volume": round(volume, 4),
        "score": round(score, 4),
    }


# ============================================================
# SELECCIONAR EL MEJOR PAR (TOP 1)
# ============================================================

def get_best_symbol():
    """
    Escanea TODOS los pares, los analiza uno por uno,
    y devuelve el MEJOR PAR para operar.
    """

    symbols = get_all_symbols()
    if not symbols:
        return None

    results = []

    for sym in symbols:
        analysis = analyze_symbol(sym)
        if analysis:
            results.append(analysis)

    if not results:
        return None

    # Ordenar por puntaje descendente
    results.sort(key=lambda x: x["score"], reverse=True)

    # Devolver el mejor par
    return results[0]


# ============================================================
# DEBUGGING LOCAL
# ============================================================

if __name__ == "__main__":
    best = get_best_symbol()
    print("MEJOR PAR DETECTADO:", best)
