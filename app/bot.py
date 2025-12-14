# ============================================================
# BOT PRINCIPAL – TRADING X HYPER PRO
# MENÚ AVANZADO – OPCIÓN A
# ============================================================

import logging
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

from app.config import TELEGRAM_BOT_TOKEN, BOT_NAME
from app.database import (
    create_user, save_user_wallet, save_user_capital,
    set_trading_status, get_user_wallet, get_user_capital,
    user_is_ready, get_user_trades, set_referrer,
    get_referrer_total_fees, get_owner_total_fees
)
from app.trading_engine import trading_loop
from app.strategy import analyze_symbol
from app.hyperliquid_client import get_balance


logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)


# ============================================================
# MENÚ PRINCIPAL (OPCIÓN A)
# ============================================================

def main_menu():
    keyboard = [
        [InlineKeyboardButton("📊 Dashboard", callback_data="dashboard")],
        [
            InlineKeyboardButton("⚙ Configurar Trading", callback_data="settings"),
            InlineKeyboardButton("📈 Operaciones", callback_data="operations"),
        ],
        [
            InlineKeyboardButton("👥 Referidos", callback_data="referrals"),
            InlineKeyboardButton("💰 Ganancias", callback_data="earnings"),
        ],
        [InlineKeyboardButton("ℹ️ Información", callback_data="info")],
    ]
    return InlineKeyboardMarkup(keyboard)


# ============================================================
# COMANDO /START
# ============================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    create_user(user.id, user.username)

    # Si tiene link de referido
    if context.args:
        ref = context.args[0]
        if ref.isdigit():
            set_referrer(user.id, int(ref))

    await update.message.reply_text(
        f"🤖 Bienvenido a *{BOT_NAME}*.\n"
        "Tu asistente profesional de trading 24/7.\n\n"
        "Selecciona una opción:",
        reply_markup=main_menu(),
        parse_mode="Markdown"
    )


# ============================================================
# DASHBOARD
# ============================================================

async def send_dashboard(update, context):
    query = update.callback_query
    user_id = query.from_user.id

    wallet = get_user_wallet(user_id)
    capital = get_user_capital(user_id)
    balance = get_balance(user_id)

    text = (
        "📊 *PANEL DE CONTROL*\n"
        "────────────────────────────\n"
        f"🪪 Usuario: `{user_id}`\n"
        f"👛 Wallet: `{wallet}`\n"
        f"💵 Capital asignado: `{capital} USDC`\n"
        f"🏦 Balance Exchange: `{balance} USDC`\n"
        "────────────────────────────\n"
        f"📌 Estado del trader: {'🟢 Activo' if user_is_ready(user_id) else '🔴 Inactivo'}"
    )

    await query.edit_message_text(text, reply_markup=main_menu(), parse_mode="Markdown")


# ============================================================
# CONFIGURACIÓN DE TRADING
# ============================================================

async def settings_menu(update, context):
    query = update.callback_query
    user_id = query.from_user.id

    keyboard = [
        [InlineKeyboardButton("💳 Configurar Wallet", callback_data="set_wallet")],
        [InlineKeyboardButton("💵 Asignar Capital", callback_data="set_capital")],
        [InlineKeyboardButton("▶ Activar Trading", callback_data="activate_trading")],
        [InlineKeyboardButton("⏸ Desactivar Trading", callback_data="deactivate_trading")],
        [InlineKeyboardButton("⬅️ Volver", callback_data="back")]
    ]

    await query.edit_message_text(
        "⚙ *CONFIGURACIÓN DEL TRADING*\nElige una opción:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )


# ============================================================
# ASIGNAR WALLET
# ============================================================

async def set_wallet_handler(update, context):
    query = update.callback_query
    await query.edit_message_text(
        "🔗 Envía la *wallet de HyperLiquid* que vas a usar:",
        parse_mode="Markdown"
    )
    context.user_data["awaiting_wallet"] = True


async def text_message(update, context):
    user_id = update.effective_user.id
    text = update.message.text

    # GUARDAR WALLET
    if context.user_data.get("awaiting_wallet"):
        save_user_wallet(user_id, text)
        context.user_data["awaiting_wallet"] = False
        await update.message.reply_text("✅ Wallet configurada correctamente.", reply_markup=main_menu())
        return

    # CAPITAL
    if context.user_data.get("awaiting_capital"):
        try:
            cap = float(text)
            save_user_capital(user_id, cap)
            context.user_data["awaiting_capital"] = False
            await update.message.reply_text("💵 Capital guardado.", reply_markup=main_menu())
            return
        except:
            await update.message.reply_text("❌ Ingresa un número válido.")
            return


# ============================================================
# ASIGNAR CAPITAL
# ============================================================

async def assign_capital(update, context):
    query = update.callback_query
    context.user_data["awaiting_capital"] = True

    await query.edit_message_text(
        "💵 Ingresa el *capital en USDC* con el que deseas operar.\n\n"
        "Mínimo: 5 USDC",
        parse_mode="Markdown"
    )


# ============================================================
# ACTIVAR / DESACTIVAR TRADING
# ============================================================

async def activate_trading(update, context):
    query = update.callback_query
    set_trading_status(query.from_user.id, "active")

    await query.edit_message_text(
        "🟢 *Trading activado.*\nEl bot operará 24/7 automáticamente.",
        reply_markup=main_menu(),
        parse_mode="Markdown"
    )


async def deactivate_trading(update, context):
    query = update.callback_query
    set_trading_status(query.from_user.id, "inactive")

    await query.edit_message_text(
        "🔴 Trading desactivado.",
        reply_markup=main_menu(),
        parse_mode="Markdown"
    )


# ============================================================
# OPERACIONES DEL USUARIO
# ============================================================

async def user_operations(update, context):
    query = update.callback_query
    user_id = query.from_user.id

    trades = get_user_trades(user_id)

    if not trades:
        text = "📈 *No tienes operaciones registradas todavía.*"
    else:
        text = "📈 *OPERACIONES RECIENTES:*\n\n"
        for t in trades[:10]:
            text += (
                f"• {t['symbol']} | {t['side'].upper()}\n"
                f"  Ganancia: {t['profit']} USDC\n"
                f"  -------------------------\n"
            )

    await query.edit_message_text(
        text,
        reply_markup=main_menu(),
        parse_mode="Markdown"
    )


# ============================================================
# SISTEMA DE REFERIDOS
# ============================================================

async def referrals(update, context):
    query = update.callback_query
    user_id = query.from_user.id

    link = f"https://t.me/{BOT_NAME}?start={user_id}"
    earnings = get_referrer_total_fees(user_id)

    text = (
        "👥 *SISTEMA DE REFERIDOS*\n"
        "Invita y gana automáticamente.\n\n"
        f"🔗 Tu enlace:\n`{link}`\n\n"
        f"💰 Ganancia total por referidos: *{earnings} USDC*"
    )

    await query.edit_message_text(text, reply_markup=main_menu(), parse_mode="Markdown")


# ============================================================
# GANANCIAS DEL ADMIN (TÚ)
# ============================================================

async def earnings(update, context):
    query = update.callback_query
    total = get_owner_total_fees()

    await query.edit_message_text(
        f"💰 *GANANCIA DEL ADMINISTRADOR*\nTotal acumulado: `{total} USDC`",
        reply_markup=main_menu(),
        parse_mode="Markdown"
    )


# ============================================================
# INFORMACIÓN
# ============================================================

async def info(update, context):
    query = update.callback_query
    await query.edit_message_text(
        "ℹ️ *Trading X Hyper Pro*\nBot profesional de trading automático 24/7.",
        reply_markup=main_menu(),
        parse_mode="Markdown"
    )


# ============================================================
# CALLBACK HANDLER
# ============================================================

async def callback_router(update, context):
    data = update.callback_query.data

    routes = {
        "dashboard": send_dashboard,
        "settings": settings_menu,
        "operations": user_operations,
        "referrals": referrals,
        "earnings": earnings,
        "info": info,
        "set_wallet": set_wallet_handler,
        "set_capital": assign_capital,
        "activate_trading": activate_trading,
        "deactivate_trading": deactivate_trading,
        "back": start
    }

    if data in routes:
        await routes[data](update, context)


# ============================================================
# MAIN
# ============================================================

def run_bot():
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(callback_router))
    app.add_handler(CommandHandler("menu", start))
    app.add_handler(CommandHandler("panel", start))
    app.add_handler(CommandHandler("dashboard", start))
    app.add_handler(CommandHandler("config", start))
    app.add_handler(CommandHandler("help", info))
    app.add_handler(CommandHandler("me", start))

    # Mensajes de texto (wallet y capital)
    from telegram.ext import MessageHandler, filters
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_message))

    print("🤖 Bot ejecutándose...")
    app.run_polling()


if __name__ == "__main__":
    run_bot()
