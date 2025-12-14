# ============================================================
# SESSION MANAGER – TRADING X HYPER PRO
# Mantiene las operaciones abiertas y estados temporales
# ============================================================

from app.config import MAX_CONCURRENT_TRADES

# Sesiones activas por usuario
# {
#   user_id: {
#       "open_trades": int,
#       "state": str
#   }
# }
_sessions = {}

# ============================================================
# CREAR / OBTENER SESIÓN
# ============================================================

def get_session(user_id):
    """
    Devuelve la sesión existente o crea una nueva.
    """
    if user_id not in _sessions:
        _sessions[user_id] = {
            "open_trades": 0,
            "state": "idle"  # idle / waiting / trading
        }
    return _sessions[user_id]


# ============================================================
# CONTROL DE OPERACIONES ABIERTAS
# ============================================================

def can_open_trade(user_id):
    """
    Verifica si el usuario puede abrir otra operación.
    """
    session = get_session(user_id)
    return session["open_trades"] < MAX_CONCURRENT_TRADES


def register_open_trade(user_id):
    """
    Suma una operación abierta.
    """
    session = get_session(user_id)
    session["open_trades"] += 1


def register_close_trade(user_id):
    """
    Resta una operación abierta.
    """
    session = get_session(user_id)
    if session["open_trades"] > 0:
        session["open_trades"] -= 1


# ============================================================
# MANEJO DEL ESTADO DEL USUARIO
# ============================================================

def set_state(user_id, state):
    """
    Cambia el estado temporal del usuario.
    """
    session = get_session(user_id)
    session["state"] = state


def get_state(user_id):
    """
    Obtiene el estado actual del usuario.
    """
    return get_session(user_id)["state"]


# ============================================================
# REINICIAR SESIÓN (OPCIONAL)
# ============================================================

def reset_session(user_id):
    """
    Reinicia completamente la sesión del usuario.
    """
    _sessions[user_id] = {
        "open_trades": 0,
        "state": "idle"
    }
