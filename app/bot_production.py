# ============================================================
# BOT PRINCIPAL – TRADING X HYPER PRO
# Archivo 8/9 – Sistema de control vía Telegram (VERSIÓN FINAL)
# ============================================================

import asyncio
import logging
import os

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
    # Referidos (solo conteo)
    set_referrer,
    get_referral_valid_count,
    # Planes
    ensure_access_on_activate,
    is_user_registered,
    activate_premium_plan,
    # Admin visual
    get_admin_visual_stats,
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

    # Sistema de referidos (solo desde enlace /start)
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
# DASHBOARD
# ============================================================

async def dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    user_id = q.from_user.id

    wallet = get_user_wallet(user_id)
    pk = get_user_private_key(user_id)
    capital = get_user_capital(user_id)
    balance = get_balance(user_id)

    msg = (
        "📊 *PANEL PRINCIPAL*\n"
        "───────────────────────────\n"
        f"🪪 Usuario: `{user_id}`\n"
        f"👛 Wallet: `{wallet}`\n"
        f"🔐 Private Key: `{'✔ Configurada' if pk else '❌ No configurada'}`\n"
        f"💵 Capital: `{capital} USDC`\n"
        f"🏦 Balance Exchange: `{balance} USDC`\n"
        "───────────────────────────\n"
        f"📌 Estado: {'🟢 ACTIVO' if user_is_ready(user_id) else '🔴 INACTIVO'}"
    )

    await q.edit_message_text(msg, reply_markup=main_menu(), parse_mode="Markdown")


# ============================================================
# SUBMENÚ WALLET / PRIVATE KEY
# ============================================================

async def wallet_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    kb = [
        [InlineKeyboardButton("💼 Establecer Wallet", callback_data="set_wallet")],
        [InlineKeyboardButton("🔐 Establecer Private Key", callback_data="set_pk")],
        [InlineKeyboardButton("⬅ Volver", callback_data="back")],
    ]

    await q.edit_message_text(
        "💳 *Configurar Wallet y Private Key*",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode="Markdown"
    )


async def set_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    context.user_data.clear()
    context.user_data["awaiting_wallet"] = True

    await q.edit_message_text(
        "🔗 Envía ahora tu *WALLET* vinculada a HyperLiquid.",
        parse_mode="Markdown"
    )


async def set_pk(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    context.user_data.clear()
    context.user_data["awaiting_pk"] = True

    await q.edit_message_text(
        "🔐 Envía ahora tu *PRIVATE KEY*.",
        parse_mode="Markdown"
    )


# ============================================================
# INPUTS
# ============================================================

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text

    # ✅ Admin: activar plan premium por ID
    if context.user_data.get("awaiting_activate_plan_id"):
        if user_id != ADMIN_TELEGRAM_ID:
            context.user_data.clear()
            await update.message.reply_text("⛔ Acceso no autorizado.")
            return
        try:
            target_id = int(str(text).strip())
        except Exception:
            await update.message.reply_text("❌ ID inválido. Debe ser numérico.")
            return

        context.user_data.clear()
        if not is_user_registered(target_id):
            await update.message.reply_text("❌ Ese usuario no está registrado en la base de datos.", reply_markup=main_menu(user_id))
            return

        ok = activate_premium_plan(target_id)
        if not ok:
            await update.message.reply_text("❌ No se pudo activar el plan (error interno).", reply_markup=main_menu(user_id))
            return

        await update.message.reply_text(f"✅ Plan Premium activado para `{target_id}`.", parse_mode="Markdown", reply_markup=main_menu(user_id))
        return

    if context.user_data.get("awaiting_wallet"):
        save_user_wallet(user_id, text)
        context.user_data.clear()
        await update.message.reply_text("✅ Wallet guardada.", reply_markup=main_menu())
        return

    if context.user_data.get("awaiting_pk"):
        save_user_private_key(user_id, text)
        context.user_data.clear()
        await update.message.reply_text("🔐 Private Key guardada.", reply_markup=main_menu())
        return

    if context.user_data.get("awaiting_capital"):
        try:
            cap = float(text)
            save_user_capital(user_id, cap)
            context.user_data.clear()
            await update.message.reply_text("💵 Capital guardado.", reply_markup=main_menu())
        except:
            await update.message.reply_text("❌ Número inválido.")
        return


# ============================================================
# CAPITAL
# ============================================================

async def capital_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    context.user_data.clear()
    context.user_data["awaiting_capital"] = True

    await q.edit_message_text(
        "💵 Ingresa el *capital en USDC*: ",
        parse_mode="Markdown"
    )


# ============================================================
# ACTIVAR / DESACTIVAR TRADING
# ============================================================

async def activate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    user_id = q.from_user.id

    access = ensure_access_on_activate(user_id)
    if not access.get("allowed", False):
        msg = access.get("message") or "⛔ Tu acceso está bloqueado."
        if ADMIN_WHATSAPP_LINK:
            msg += f"\n\n📲 WhatsApp: {ADMIN_WHATSAPP_LINK}"
        await q.edit_message_text(msg, reply_markup=main_menu(user_id), parse_mode="Markdown")
        return

    # Si allowed, activamos trading como siempre
    set_trading_status(user_id, "active")

    plan_msg = access.get("plan_message") or "🟢 *Trading ACTIVADO*."
    await q.edit_message_text(plan_msg, reply_markup=main_menu(user_id), parse_mode="Markdown")


async def deactivate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    set_trading_status(q.from_user.id, "inactive")

    await q.edit_message_text(
        "🔴 *Trading PAUSADO*.",
        reply_markup=main_menu(),
        parse_mode="Markdown"
    )


# ============================================================
# OPERACIONES
# ============================================================

async def operations(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    user_id = q.from_user.id
    trades = get_user_trades(user_id)

    if not trades:
        msg = "📈 *No tienes operaciones registradas.*"
    else:
        msg = "📈 *OPERACIONES RECIENTES:*\n\n"
        for t in trades[:10]:
            msg += (
                f"• {t['symbol']} | {t['side']}\n"
                f"  Ganancia: `{t['profit']} USDC`\n"
                "───────────────────────────\n"
            )

    await q.edit_message_text(msg, reply_markup=main_menu(), parse_mode="Markdown")


# ============================================================
# REFERIDOS
# ============================================================

async def referrals(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    user_id = q.from_user.id
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
# ADMIN – ACTIVAR PLAN (PREMIUM)
# ============================================================

async def activate_plan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if q.from_user.id != ADMIN_TELEGRAM_ID:
        await q.edit_message_text("⛔ Acceso no autorizado.", reply_markup=main_menu(q.from_user.id))
        return

    context.user_data.clear()
    context.user_data["awaiting_activate_plan_id"] = True
    await q.edit_message_text(
        "✅ *Activar Plan Premium*\n\nIngresa el *ID de Telegram* del usuario:",
        parse_mode="Markdown"
    )


# ============================================================
# ADMIN – INFORMACIÓN VISUAL
# ============================================================

async def admin_visual(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if q.from_user.id != ADMIN_TELEGRAM_ID:
        await q.edit_message_text("⛔ Acceso no autorizado.", reply_markup=main_menu(q.from_user.id))
        return

    stats = get_admin_visual_stats() or {}
    msg = (
        "📊 *INFORMACIÓN VISUAL (ADMIN)*\n"
        "───────────────────────────\n"
        f"👤 Total registrados: `{stats.get('total_users', 0)}`\n"
        f"🆓 Free antiguos: `{stats.get('free_old', 0)}`\n"
        f"💎 Premium activos: `{stats.get('premium_active', 0)}`\n"
        f"⌛ Premium vencidos: `{stats.get('premium_expired', 0)}`\n"
        "───────────────────────────"
    )

    await q.edit_message_text(msg, reply_markup=main_menu(q.from_user.id), parse_mode="Markdown")


# ============================================================
# INFO
# ============================================================

async def info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    user_id = q.from_user.id

    trades = get_user_trades(user_id)
    last = trades[0] if trades else None

    msg = (
        '📌 *INFORMACIÓN DE OPERACIÓN*\n'
        '───────────────────────────\n'
    )

    msg += '🟡 Operación abierta: _No disponible aún_\n'

    if last:
        msg += (
            '\n✅ Última operación cerrada:\n'
            f"• Símbolo: `{last.get('symbol')}`\n"
            f"• Lado: `{last.get('side')}`\n"
            f"• Entrada: `{last.get('entry_price')}`\n"
            f"• Salida: `{last.get('exit_price')}`\n"
            f"• Qty: `{last.get('qty')}`\n"
            f"• Profit: `{last.get('profit')} USDC`\n"
        )
    else:
        msg += '\nℹ️ Aún no hay operaciones cerradas registradas.\n'

    msg += '───────────────────────────'

    await q.edit_message_text(
        msg,
        reply_markup=main_menu(user_id),
        parse_mode='Markdown'
    )


async def back_to_main(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    user_id = q.from_user.id

    wallet = get_user_wallet(user_id)
    pk = get_user_private_key(user_id)
    capital = get_user_capital(user_id)
    balance = get_balance(user_id)

    msg = (
        "📊 *PANEL PRINCIPAL*\n"
        "───────────────────────────\n"
        f"🪪 Usuario: `{user_id}`\n"
        f"👛 Wallet: `{wallet}`\n"
        f"🔐 Private Key: `{'✔ Configurada' if pk else '❌ No configurada'}`\n"
        f"💵 Capital: `{capital} USDC`\n"
        f"🏦 Balance Exchange: `{balance} USDC`\n"
        "───────────────────────────\n"
        f"📌 Estado: {'🟢 ACTIVO' if user_is_ready(user_id) else '🔴 INACTIVO'}"
    )

    await q.edit_message_text(msg, reply_markup=main_menu(), parse_mode="Markdown")


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
    "activate_plan": activate_plan,
    "admin_visual": admin_visual,
        "info": info,
    "back": back_to_main,
}


async def callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = update.callback_query.data
    handler = routes.get(data)
    if handler:
        await handler(update, context)


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

    # ✅ CORRECCIÓN CRÍTICA:
    # Se pasa la MISMA Application al trading loop
    app.job_queue.run_once(
        lambda ctx: asyncio.create_task(trading_loop(app)),
        when=3
    )

    print("🤖 Trading X Hyper Pro – Bot ejecutándose...")
    app.run_polling()


# ============================================================
# ENTRYPOINT
# ============================================================

if __name__ == "__main__":
    run_bot()