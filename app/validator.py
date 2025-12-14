# ============================================================
# validator.py
# Sistema central de validación para Trading X Hiper Pro
# ============================================================

import re

# ------------------------------------------------------------
# Validar símbolo PERP (ej: BTC-USD-PERP)
# ------------------------------------------------------------
def validate_symbol(symbol: str) -> bool:
    """
    Verifica que el símbolo siga el formato correcto PERP.
    Ejemplo válido: BTC-USD-PERP
    """
    pattern = r"^[A-Z0-9]+-USD-PERP$"
    return re.match(pattern, symbol) is not None


# ------------------------------------------------------------
# Validar número flotante
# ------------------------------------------------------------
def validate_float(value) -> bool:
    """
    Verifica si es un número válido (int o float).
    """
    try:
        float(value)
        return True
    except:
        return False


# ------------------------------------------------------------
# Validar un monto mínimo para operar
# ------------------------------------------------------------
def validate_min_amount(amount, minimum=1):
    """
    Verifica si el monto es mayor al mínimo permitido.
    """
    try:
        return float(amount) >= minimum
    except:
        return False


# ------------------------------------------------------------
# Validar API KEY o WALLET del usuario
# ------------------------------------------------------------
def validate_api_key(key: str) -> bool:
    """
    Validación básica para claves.
    Deben tener caracteres alfanuméricos y mínimo 20 dígitos.
    """
    if not key:
        return False

    if len(key) < 20:
        return False

    return bool(re.match(r"^[A-Za-z0-9]+$", key))


# ------------------------------------------------------------
# Validar SIDE: "buy" o "sell"
# ------------------------------------------------------------
def validate_side(side: str) -> bool:
    return side.lower() in ["buy", "sell"]


# ------------------------------------------------------------
# Validar parámetros de estrategia
# ------------------------------------------------------------
def validate_strategy_params(tp_min, tp_max, sl_min, sl_max):
    """
    Verifica parámetros lógicos para Take Profit / Stop Loss.
    """
    try:
        tp_min = float(tp_min)
        tp_max = float(tp_max)
        sl_min = float(sl_min)
        sl_max = float(sl_max)

        if tp_min <= 0 or tp_max <= 0:
            return False

        if sl_min <= 0 or sl_max <= 0:
            return False

        if tp_min >= tp_max:
            return False

        if sl_min >= sl_max:
            return False

        return True
    except:
        return False
