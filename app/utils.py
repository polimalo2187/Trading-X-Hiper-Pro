# ============================================================
# utils.py – Funciones de apoyo internas
# Trading X Hyper Pro
# ============================================================

import time
import datetime
import math
from decimal import Decimal


# ============================================================
# FORMATEADORES
# ============================================================

def fmt_usd(value):
    """ Formatea un número como USD con 2-4 decimales. """
    try:
        v = float(value)
        if v >= 1:
            return f"{v:,.2f}"
        return f"{v:,.4f}"
    except:
        return "0.00"


def fmt_percent(value):
    """ Formatea porcentajes. """
    try:
        return f"{float(value) * 100:.2f}%"
    except:
        return "0%"


def timestamp_now():
    """ Devuelve timestamp actual UTC. """
    return datetime.datetime.utcnow()


# ============================================================
# VALIDACIONES Y SANITIZACIÓN
# ============================================================

def is_float(n):
    """ Verifica si un string o número puede convertirse a float. """
    try:
        float(n)
        return True
    except:
        return False


def clamp(value, min_v, max_v):
    """ Asegura que un valor esté dentro de un rango permitido. """
    return max(min_v, min(value, max_v))


# ============================================================
# SISTEMA AVANZADO DE LOGS (por usuario)
# ============================================================

def build_log_entry(user_id, title, data=None):
    """
    Devuelve un diccionario de log que se puede almacenar o enviar al usuario.
    """
    return {
        "user": user_id,
        "title": title,
        "data": data if data else {},
        "timestamp": timestamp_now()
    }


# ============================================================
# CÁLCULO DE FEES DEL BOT
# ============================================================

def calc_fees(profit, owner_fee_percent, ref_fee_percent):
    """
    Calcula los fees del bot y del referido.
    El bot cobra el fee **del profit generado**, no del capital.
    """

    profit = float(profit)

    owner_fee = profit * owner_fee_percent
    ref_fee = profit * ref_fee_percent

    # la ganancia final del dueño es owner_fee - ref_fee
    owner_real = owner_fee - ref_fee

    return {
        "owner_fee": round(owner_real, 6),
        "ref_fee": round(ref_fee, 6),
        "original_owner_fee": round(owner_fee, 6)
    }


# ============================================================
# RENDIMIENTO Y ESTADÍSTICAS
# ============================================================

def calculate_roi(entry_price, exit_price, leverage=1):
    """
    ROI real usando apalancamiento.
    """

    try:
        entry = float(entry_price)
        exitp = float(exit_price)

        if entry <= 0:
            return 0

        roi = ((exitp - entry) / entry) * leverage
        return round(roi, 6)

    except:
        return 0


def estimate_daily_profit(capital, avg_roi):
    return round(capital * avg_roi, 4)


def estimate_monthly_profit(capital, avg_roi):
    return round(capital * avg_roi * 30, 4)


# ============================================================
# FORMATEO AVANZADO DE OPERACIONES PARA TELEGRAM
# ============================================================

def format_trade_message(symbol, side, qty, entry, exit_price, profit):
    """
    Mensaje elegante para reportar una operación cerrada.
    """

    direction = "🟢 LONG" if side == "buy" else "🔴 SHORT"

    msg = (
        f"📊 *Operación Cerrada*\n"
        f"• Par: *{symbol}*\n"
        f"• Dirección: {direction}\n"
        f"• Cantidad: `{fmt_usd(qty)}`\n"
        f"• Entrada: `{fmt_usd(entry)}`\n"
        f"• Salida: `{fmt_usd(exit_price)}`\n"
        f"• Ganancia: *{fmt_usd(profit)} USDC*\n"
    )

    return msg


# ============================================================
# SISTEMA ANTI-SPAM / COOLDOWN DE COMANDOS
# ============================================================

_user_cooldowns = {}

def cooldown(user_id, seconds=3):
    """
    Impide que un usuario ejecute spam de comandos.
    """
    now = time.time()
    last = _user_cooldowns.get(user_id, 0)

    if now - last < seconds:
        return False  # debe esperar

    _user_cooldowns[user_id] = now
    return True


# ============================================================
# PARSERS Y CONVERSIONES
# ============================================================

def parse_symbol(sym):
    """ Asegura que el símbolo esté en formato estándar """
    return sym.upper().replace("/", "-")


def safe_float(n, default=0.0):
    """ Convierte un valor a float de manera segura """
    try:
        return float(n)
    except:
        return default
