# ============================================================
# EVENTS MODULE – Trading X Hiper Pro
# ============================================================

from datetime import datetime
from .logger import log_event
from .notifications import send_notification
from .trading_engine import open_trade, close_trade
from .database import db
from .utils import format_price


# --------------------------------------------
# Registrador interno de eventos del bot
# --------------------------------------------
def record_event(user_id: int, event_type: str, data: dict = None):
    """
    Registra cualquier evento importante del sistema.
    """
    timestamp = datetime.utcnow()

    db.events.insert_one({
        "user_id": user_id,
        "event_type": event_type,
        "data": data or {},
        "timestamp": timestamp
    })

    log_event(f"[EVENT] {event_type} – {data}")


# --------------------------------------------
# Evento de apertura de trade
# --------------------------------------------
def on_trade_open(user_id: int, symbol: str, qty: float, entry: float, leverage: int):
    """
    Se ejecuta cuando se abre una operación.
    """
    record_event(user_id, "TRADE_OPEN", {
        "symbol": symbol,
        "qty": qty,
        "entry_price": entry,
        "leverage": leverage
    })

    msg = (
        f"🚀 *Operación Abierta*\n\n"
        f"• Par: `{symbol}`\n"
        f"• Cantidad: `{qty}`\n"
        f"• Precio de Entrada: `{format_price(entry)}`\n"
        f"• Apalancamiento: `{leverage}x`\n"
    )

    send_notification(user_id, msg)


# --------------------------------------------
# Evento de cierre de trade
# --------------------------------------------
def on_trade_close(user_id: int, symbol: str, qty: float, pnl: float, exit_price: float):
    """
    Se ejecuta cuando un trade se cierra.
    """
    record_event(user_id, "TRADE_CLOSE", {
        "symbol": symbol,
        "qty": qty,
        "exit_price": exit_price,
        "pnl": pnl
    })

    status = "🟢 GANANCIA" if pnl >= 0 else "🔴 PÉRDIDA"

    msg = (
        f"📉 *Operación Cerrada*\n\n"
        f"• Par: `{symbol}`\n"
        f"• Cantidad: `{qty}`\n"
        f"• Precio de salida: `{format_price(exit_price)}`\n"
        f"• Resultado: *{status}*\n"
        f"• PnL: `{pnl}` USDC\n"
    )

    send_notification(user_id, msg)


# --------------------------------------------
# Evento de error crítico
# --------------------------------------------
def on_critical_error(error_message: str):
    """
    Reporta un fallo grave del sistema.
    """
    log_event(f"[CRITICAL ERROR] {error_message}")

    # Notificar al dueño del bot
    owner_id = 1  # <- Cambiar si usas otro ID
    send_notification(owner_id, f"⚠️ *Error Crítico Detectado*\n\n{error_message}")


# --------------------------------------------
# Evento de señal de estrategia
# --------------------------------------------
def on_signal_detected(symbol: str, score: float):
    """
    Se ejecuta cuando la estrategia detecta una señal fuerte.
    """
    record_event(None, "SIGNAL", {
        "symbol": symbol,
        "score": score
    })

    log_event(f"[SIGNAL] {symbol} – Score: {score}")


# --------------------------------------------
# Evento de heartbeat (vida del sistema)
# --------------------------------------------
def heartbeat():
    """
    Marca de vida del bot (se ejecuta cada X minutos).
    """
    log_event("BOT HEARTBEAT – OK")
