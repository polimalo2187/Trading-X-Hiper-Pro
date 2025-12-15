# ============================================================
# MARKET SCANNER – TRADING X HIPER PRO
# Escáner oficial del bot (selecciona el MEJOR PAR del mercado)
# ============================================================

import random
from app.hyperliquid_client import make_request, get_price


# ============================================================
# OBTENER TODOS LOS PARES DISPONIBLES (PERPETUALS REALES)
# ============================================================

def get_all_symbols():
    """
    Devuelve una lista de TODOS los símbolos disponibles en HyperLiquid.
    Estos pares son los que el bot puede operar en trading_engine.py.
    """

    payload = {"type": "allMids"}
    r = make_request("/info", payload)

    if not r or "mids" not in r:
        print("❌ No se pudo obtener la lista de pares desde HyperLiquid.")
        return []

    # Los pares vienen en formato dict: { "BTC": 12345.0, "ETH": ... }
    symbols = list(r["mids"].keys())
    return symbols


# ============================================================
# ANALIZAR UN PAR INDIVIDUAL
# ============================================================

def analyze_symbol(symbol):
    """
    Evalúa la calidad del par usando un score que combina:
    - Precio actual real
    - Momentum (simulado)
    - Volatilidad (simulada)
    - Profundidad / volumen (simulado)

    Todo esto se reemplazaría luego con datos reales si deseas.
    """

    price = get_price(symbol)

    if not price or price <= 0:
        return None

    # Simulaciones controladas para evaluar calidad del par
    momentum = random.uniform(0.4, 1.0)
    volatility = random.uniform(0.3, 1.0)
    liquidity = random.uniform(0.5, 1.0)

    # Score profesional para clasificación
    score = (
        (momentum * 0.50) +
        (volatility * 0.30) +
        (liquidity * 0.20)
    )

    return {
        "symbol": symbol,
        "price": price,
        "momentum": round(momentum, 4),
        "volatility": round(volatility, 4),
        "liquidity": round(liquidity, 4),
        "score": round(score, 4)
    }


# ============================================================
# SELECCIONAR EL MEJOR PAR DEL MERCADO
# ============================================================

def get_best_symbol():
    """
    Escanea TODOS los pares disponibles y selecciona el que tenga
    el score MÁS ALTO. Ese será el par oficial que el bot operará.
    """

    symbols = get_all_symbols()

    if not symbols:
        print("❌ No hay pares disponibles para analizar.")
        return None

    results = []

    for sym in symbols:
        analysis = analyze_symbol(sym)
        if analysis:
            results.append(analysis)

    if not results:
        print("❌ Ningún par devolvió análisis válido.")
        return None

    # Ordenar por score (descendente)
    results.sort(key=lambda x: x["score"], reverse=True)

    best = results[0]

    print(f"🔥 Mejor par detectado: {best['symbol']} (Score: {best['score']})")

    return best
