# ============================================================
# BOT PRINCIPAL – TRADING X HYPER PRO
# Archivo 8/9 – Sistema de control vía Telegram (VERSIÓN FINAL)
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
        f"Tu bot profesional de trading automático 24/7.\n\n"
        f"Selecciona una opción:",
        reply_markup=main_menu(),
        parse_mode="Markdown"
    )


# ============================================================
# REFERIDOS
# ============================================================

async def referrals(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    user_id = q.from_user.id

    # 🔧 ÚNICA LÍNEA MODIFICADA (USERNAME REAL DEL BOT)
    link = f"https://t.me/TradingXHiperPro_bot?start={user_id}"

    earnings = get_referrer_weekly(user_id)

    msg = (
        "👥 *PROGRAMA DE REFERIDOS*\n"
        "Los referidos acumulan fee todos los días.\n"
        "Los pagos se procesan *cada domingo*.\n\n"
        f"🔗 Tu enlace:\n`{link}`\n\n"
        f"💰 Acumulado semanal: *{earnings} USDC*"
    )

    await q.edit_message_text(msg, reply_markup=main_menu(), parse_mode="Markdown")


# ============================================================
# MAIN
# ============================================================

def run_bot():

    app = (
        ApplicationBuilder()
        .token(TELEGRAM_BOT_TOKEN)
        .build()
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", start))
    app.add_handler(CommandHandler("panel", start))
    app.add_handler(CallbackQueryHandler(callback_router))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

    app.job_queue.run_once(
        lambda ctx: asyncio.create_task(trading_loop()),
        when=3
    )

    print("🤖 Trading X Hyper Pro – Bot ejecutándose...")
    app.run_polling()


if __name__ == "__main__":
    run_bot()
