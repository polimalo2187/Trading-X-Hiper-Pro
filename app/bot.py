# ============================================================
# BOT PRINCIPAL – TRADING X HYPER PRO
# Sistema completo de menú + registro + trading real
# ============================================================

import logging
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
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
    get_referrer_total_fees,
    get_owner_total_fees,
)
from app.hyperliquid_client import get_balance
from app.trading_engine import execute_trade


logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

# ============================================================
# MENÚ PRINCIPAL
# ============================================================

def main_menu():
    keyboard = [
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
        [InlineKeyboardButton("💰 Ganancias Admin", callback_data="earnings")],
        [InlineKeyboardButton("ℹ️ Información", callback_data="info")],
    ]
    return InlineKeyboardMarkup(keyboard)


# ============================================================
# /START
# ============================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    create_user(user.id, user.username)

    # Detectar link de referido
    if context.args:
        ref = context.args[0]
        if ref.isdigit():
            set_referrer(user.id, int(ref))

    await update.message.reply_text(
        f"🤖 Bienvenido a *{BOT_NAME}*.\n"
        f"Tu asistente profesional de trading 24/7.\n\n"
        f"Selecciona una opción:",
        reply_markup=main_menu(),
        parse_mode="Markdown"
    )


# ============================================================
# DASHBOARD
# ============================================================

async def dashboard(update, context):
    query = update.callback_query
    user_id = query.from_user.id

    wallet = get_user_wallet(user_id)
    private_key = get_user_private_key(user_id)
    capital = get_user_capital(user_id)
    balance = get_balance(user_id)

    text = (
        "📊 *PANEL PRINCIPAL*\n"
        "────────────────────────────\n"
        f"🪪 Usuario: `{user_id}`\n"
        f"👛 Wallet: `{wallet}`\n"
        f"🔐 Private Key: `{'✔ Guardada' if private_key else '❌ No configurada'}`\n"
        f"💵 Capital: `{capital} USDC`\n"
        f"🏦 Balance Exchange: `{balance} USDC`\n"
        "────────────────────────────\n"
        f"📌 Estado trader: {'🟢 ACTIVO' if user_is_ready(user_id) else '🔴 INACTIVO'}"
    )

    await query.edit_message_text(text, reply_markup=main_menu(), parse_mode="Markdown")


# ============================================================
# SUBMENÚ WALLET / PRIVATE KEY
# ============================================================

async def wallet_menu(update, context):
    keyboard = [
        [InlineKeyboardButton("💼 Establecer Wallet", callback_data="set_wallet")],
        [InlineKeyboardButton("🔐 Establecer Private Key", callback_data="set_pk")],
        [InlineKeyboardButton("⬅ Volver", callback_data="back")],
    ]

    await update.callback_query.edit_message_text(
        "💳 *CONFIGURAR WALLET Y PRIVATE KEY*\nSelecciona una opción:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )


# ============================================================
# FLUJO PARA GUARDAR WALLET
# ============================================================

async def set_wallet(update, context):
    context.user_data["awaiting_wallet"] = True
    await update.callback_query.edit_message_text(
        "🔗 Envía ahora tu *wallet* vinculada a HyperLiquid.",
        parse_mode="Markdown"
    )


# ============================================================
# FLUJO PARA GUARDAR PRIVATE KEY
# ============================================================

async def set_pk(update, context):
    context.user_data["awaiting_pk"] = True
    await update.callback_query.edit_message_text(
        "🔐 Envía ahora tu *PRIVATE KEY* (sin confirmación adicional).",
        parse_mode="Markdown"
    )


# ============================================================
# MANEJO DE MENSAJES DE TEXTO (wallet, pk, capital)
# ============================================================

async def text_handler(update, context):
    user_id = update.effective_user.id
    txt = update.message.text

    # WALLET
    if context.user_data.get("awaiting_wallet"):
        save_user_wallet(user_id, txt)
        context.user_data["awaiting_wallet"] = False
        await update.message.reply_text("✅ Wallet guardada correctamente.", reply_markup=main_menu())
        return

    # PRIVATE KEY
    if context.user_data.get("awaiting_pk"):
        save_user_private_key(user_id, txt)
        context.user_data["awaiting_pk"] = False
        await update.message.reply_text("🔐 Private Key guardada correctamente.", reply_markup=main_menu())
        return

    # CAPITAL
    if context.user_data.get("awaiting_capital"):
        try:
            cap = float(txt)
            save_user_capital(user_id, cap)
            context.user_data["awaiting_capital"] = False
            await update.message.reply_text("💵 Capital guardado.", reply_markup=main_menu())
        except:
            await update.message.reply_text("❌ Número inválido.")
        return


# ============================================================
# ASIGNAR CAPITAL
# ============================================================

async def capital_menu(update, context):
    context.user_data["awaiting_capital"] = True
    await update.callback_query.edit_message_text(
        "💵 *Ingresa el capital en USDC* que deseas asignar.",
        parse_mode="Markdown"
    )


# ============================================================
# ACTIVAR / DESACTIVAR TRADING
# ============================================================

async def activate(update, context):
    set_trading_status(update.callback_query.from_user.id, "active")
    await update.callback_query.edit_message_text(
        "🟢 *Trading ACTIVADO.*",
        reply_markup=main_menu(),
        parse_mode="Markdown"
    )


async def deactivate(update, context):
    set_trading_status(update.callback_query.from_user.id, "inactive")
    await update.callback_query.edit_message_text(
        "🔴 *Trading PAUSADO.*",
        reply_markup=main_menu(),
        parse_mode="Markdown"
    )


# ============================================================
# OPERACIONES RECIENTES
# ============================================================

async def operations(update, context):
    query = update.callback_query
    user_id = query.from_user.id

    trades = get_user_trades(user_id)

    if not trades:
        msg = "📈 *No tienes operaciones registradas.*"
    else:
        msg = "📈 *OPERACIONES RECIENTES:*\n\n"
        for t in trades[:10]:
            msg += (
                f"• {t['symbol']} | {t['side']}\n"
                f"  Ganancia: `{t['profit']} USDC`\n"
                "───────────────────────\n"
            )

    await query.edit_message_text(msg, reply_markup=main_menu(), parse_mode="Markdown")


# ============================================================
# REFERIDOS
# ============================================================

async def referrals(update, context):
    user_id = update.callback_query.from_user.id
    link = f"https://t.me/{BOT_NAME}?start={user_id}"
    earnings = get_referrer_total_fees(user_id)

    msg = (
        "👥 *REFERIDOS*\n"
        "Invita y gana automáticamente.\n\n"
        f"🔗 Tu enlace:\n`{link}`\n\n"
        f"💰 Ganancia total: *{earnings} USDC*"
    )

    await update.callback_query.edit_message_text(msg, reply_markup=main_menu(), parse_mode="Markdown")


# ============================================================
# GANANCIA DEL ADMINISTRADOR
# ============================================================

async def earnings(update, context):
    total = get_owner_total_fees()
    msg = f"💰 *GANANCIA TOTAL DEL ADMIN:*\n`{total} USDC`"
    await update.callback_query.edit_message_text(msg, reply_markup=main_menu(), parse_mode="Markdown")


# ============================================================
# INFORMACIÓN DEL BOT
# ============================================================

async def info(update, context):
    await update.callback_query.edit_message_text(
        "ℹ️ *Trading X Hyper Pro*\nBot profesional de trading automático 24/7.",
        reply_markup=main_menu(),
        parse_mode="Markdown"
    )


# ============================================================
# ROUTER
# ============================================================

routes = {
    "dashboard": dashboard,
    "wallet_menu": wallet_menu,
    "set_wallet": set_wallet,
    "set_pk": set_pk,
    "capital_menu": capital_menu,
    "activate": activate,
    "deactivate": deactivate,
    "operations": operations,
    "referrals": referrals,
    "earnings": earnings,
    "info": info,
    "back": start,
}


async def callback_router(update, context):
    data = update.callback_query.data
    if data in routes:
        await routes[data](update, context)


# ============================================================
# RUN BOT
# ============================================================

def run_bot():
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    # Comandos
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", start))
    app.add_handler(CommandHandler("panel", start))

    # Callback del menú
    app.add_handler(CallbackQueryHandler(callback_router))

    # Mensajes de texto (wallet, pk, capital)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

    print("🤖 Bot ejecutándose...")
    app.run_polling()


if __name__ == "__main__":
    run_bot()
