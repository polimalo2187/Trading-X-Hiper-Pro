# ============================================================
# BOT PRINCIPAL – TRADING X HYPER PRO
# Archivo 8/9 – Sistema de control vía Telegram (PRODUCCIÓN)
# ============================================================

import asyncio
import logging

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from app.config import TELEGRAM_BOT_TOKEN, BOT_NAME
from app.database import (
    create_user,
    save_user_wallet,
    save_user_private_key,
    save_user_capital,
    set_trading_status,
    get_user_wallet,
    get_user_private_key,
    get_user_capital,
    user_is_ready,
    get_user_trades,
    set_referrer,
    get_referrer_weekly,
    get_admin_daily_fees,
)
from app.hyperliquid_client import get_balance
from app.trading_loop import trading_loop


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)


# ============================================================
# MENÚ PRINCIPAL
# ============================================================

def main_menu():
    kb = [
        [InlineKeyboardButton("📊 Dashboard", callback_data="dashboard")],
        [
            InlineKeyboardButton("💳 Wallet / Private Key", callback_data="wallet_menu"),
            InlineKeyboardButton("💵 Capital", callback_data="capital_menu"),
        ],
        [
            InlineKeyboardButton("▶ Activar Trading", callback_data="activate"),
            InlineKeyboardButton("⏸ Pausar Trading", callback_data="deactivate"),
        ],
        [
            InlineKeyboardButton("📈 Operaciones", callback_data="operations"),
            InlineKeyboardButton("👥 Referidos", callback_data="referrals"),
        ],
        [InlineKeyboardButton("💰 Ganancias Admin", callback_data="earnings_admin")],
        [InlineKeyboardButton("ℹ️ Información", callback_data="info")],
    ]
    return InlineKeyboardMarkup(kb)


# ============================================================
# /START
# ============================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user = update.effective_user
    create_user(user.id, user.username)

    if context.args:
        ref = context.args[0]
        if ref.isdigit() and int(ref) != user.id:
            set_referrer(user.id, int(ref))

    await update.message.reply_text(
        f"🤖 Bienvenido a *{BOT_NAME}*.\n"
        f"Trading automático profesional 24/7.\n\n"
        f"Selecciona una opción:",
        reply_markup=main_menu(),
        parse_mode="Markdown"
    )


# ============================================================
# DASHBOARD
# ============================================================

async def dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    user_id = q.from_user.id

    msg = (
        "📊 *PANEL PRINCIPAL*\n"
        "───────────────────────────\n"
        f"🪪 Usuario: `{user_id}`\n"
        f"👛 Wallet: `{get_user_wallet(user_id)}`\n"
        f"🔐 Private Key: `{'✔ Configurada' if get_user_private_key(user_id) else '❌ No configurada'}`\n"
        f"💵 Capital: `{get_user_capital(user_id)} USDC`\n"
        f"🏦 Balance Exchange: `{get_balance(user_id)} USDC`\n"
        "───────────────────────────\n"
        f"📌 Estado Trading: {'🟢 ACTIVO' if user_is_ready(user_id) else '🔴 PAUSADO'}"
    )

    await q.edit_message_text(msg, reply_markup=main_menu(), parse_mode="Markdown")


# ============================================================
# ACTIVAR / DESACTIVAR TRADING
# ============================================================

async def activate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    set_trading_status(q.from_user.id, "active")

    await q.edit_message_text(
        "🟢 *Trading ACTIVADO*\n\n"
        "El bot está monitoreando el mercado.\n"
        "Recibirás notificaciones solo cuando haya operaciones reales.",
        reply_markup=main_menu(),
        parse_mode="Markdown"
    )


async def deactivate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    set_trading_status(q.from_user.id, "inactive")

    await q.edit_message_text(
        "🔴 *Trading PAUSADO*\n\n"
        "No se abrirán nuevas operaciones.",
        reply_markup=main_menu(),
        parse_mode="Markdown"
    )


# ============================================================
# OPERACIONES
# ============================================================

async def operations(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    trades = get_user_trades(q.from_user.id)

    if not trades:
        msg = "📈 *No tienes operaciones registradas.*"
    else:
        msg = "📈 *OPERACIONES RECIENTES:*\n\n"
        for t in trades[:10]:
            msg += (
                f"• {t['symbol']} | {t['side']}\n"
                f"  PnL: `{t['profit']} USDC`\n"
                "───────────────────────────\n"
            )

    await q.edit_message_text(msg, reply_markup=main_menu(), parse_mode="Markdown")


# ============================================================
# ROUTER + MAIN
# ============================================================

def run_bot():

    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(callback_router := lambda u, c: routes[u.callback_query.data](u, c)))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler := lambda u, c: None))

    app.job_queue.run_once(
        lambda ctx: asyncio.create_task(trading_loop(app)),
        when=3
    )

    print("🤖 Trading X Hyper Pro – Bot en PRODUCCIÓN")
    app.run_polling()


if __name__ == "__main__":
    run_bot()
