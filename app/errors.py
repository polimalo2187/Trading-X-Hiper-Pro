# ============================================================
# SISTEMA CENTRAL DE ERRORES – TRADING X HYPER PRO
# ============================================================

from app.logger import log


class BotError(Exception):
    """Error general del bot."""
    pass


class ExchangeError(Exception):
    """Errores relacionados con HyperLiquid."""
    pass


class DatabaseError(Exception):
    """Errores de conexión o escritura en MongoDB."""
    pass


# ============================================================
# MANEJADOR GENERAL DE ERRORES
# ============================================================

def handle_error(e, context=""):
    """
    Maneja errores globales sin detener el bot.
    Guarda en logs y permite continuar.
    """

    message = f"❌ ERROR en {context}: {str(e)}"
    log(message, "error")

    return {
        "status": "error",
        "context": context,
        "message": str(e)
    }
