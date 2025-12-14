# ============================================================
# SISTEMA DE NOTIFICACIONES – TRADING X HYPER PRO
# ============================================================

from telegram import InlineKeyboardMarkup, InlineKeyboardButton
from app.logger import log


# ============================================================
# ENVÍO BÁSICO DE MENSAJE
# ============================================================

async def safe_send_message(context, chat_id, text, reply_markup=None):
    """
    Envía mensajes sin que el bot se caiga si falla Telegram.
    """
    try:
        await context.bot.send_message(
            chat_id=chat_id,
            text=text,
            reply_markup=reply_markup
        )
    except Exception as e:
        log(f"❌ Error enviando mensaje a {chat_id}: {e}", "error")


# ============================================================
# NOTIFICACIONES DE TRADING
# ============================================================

async def notify_trade_open(context, user_id, symbol, side, qty, entry):
    msg = (
        f"🟢 *OPERACIÓN ABIERTA*\n"
        f"Par: {symbol}\n"
        f"Dirección: {side.upper()}\n"
        f"Cantidad: {qty}\n"
        f"Precio de entrada: {entry}\n\n"
        f"El bot está monitoreando esta operación…"
    )
    await safe_send_message(context, user_id, msg)


async def notify_trade_close(context, user_id, symbol, side, qty, entry, exit, profit):
    result_icon = "🟢" if profit >= 0 else "🔴"

    msg = (
        f"{result_icon} *OPERACIÓN CERRADA*\n"
        f"Par: {symbol}\n"
        f"Dirección: {side.upper()}\n"
        f"Entrada: {entry}\n"
        f"Salida: {exit}\n"
        f"Cantidad: {qty}\n\n"
        f"💰 *Resultado:* {profit} USDC"
    )

    await safe_send_message(context, user_id, msg)


# ============================================================
# NOTIFICACIONES DEL SISTEMA
# ============================================================

async def notify_status_change(context, user_id, status):
    icon = "🟢" if status == "active" else "⛔"
    msg = f"{icon} *El estado del bot cambió a:* {status.upper()}"
    await safe_send_message(context, user_id, msg)


async def notify_capital_change(context, user_id, capital):
    msg = f"💼 *Tu capital asignado ahora es:* {capital} USDC"
    await safe_send_message(context, user_id, msg)


async def notify_invalid_operation(context, user_id, reason):
    msg = f"⚠ *Operación no permitida:* {reason}"
    await safe_send_message(context, user_id, msg)


# ============================================================
# NOTIFICACIONES DE REFERIDOS
# ============================================================

async def notify_referral_reward(context, referrer_id, amount, user_id):
    msg = (
        f"🎉 *Nuevo beneficio de referido*\n"
        f"Usuario: {user_id}\n"
        f"Ganaste: {amount} USDC"
    )
    await safe_send_message(context, referrer_id, msg)


# ============================================================
# NOTIFICACIONES DE GANANCIAS PARA EL ADMIN
# ============================================================

async def notify_owner_fee(context, owner_id, amount, user_id):
    msg = (
        f"💰 *Nueva ganancia del bot*\n"
        f"Usuario: {user_id}\n"
        f"Tu FEE recibido: {amount} USDC"
    )
    await safe_send_message(context, owner_id, msg)
