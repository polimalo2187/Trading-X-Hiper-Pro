# ============================================================
# BOT PRINCIPAL – TRADING X HYPER PRO
# Archivo 8/9 – Sistema de control vía Telegram (VERSIÓN FINAL)
# MOD: Capital manual eliminado. El bot opera usando el balance real del exchange.
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

# ============================================================
# ENV (Admin / Bot)
# ============================================================
BOT_USERNAME = os.getenv("BOT_USERNAME", "TradingXHiperPro_bot")
ADMIN_TELEGRAM_ID = int(os.getenv("ADMIN_TELEGRAM_ID", "0") or "0")
ADMIN_WHATSAPP_LINK = os.getenv("ADMIN_WHATSAPP_LINK", "").strip()

from app.database import (
    create_user,
    save_user_wallet,
    save_user_private_key,
    set_trading_status,
    get_user_wallet,
    get_user_private_key,
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
    get_last_operation,
    get_admin_trade_stats,
    reset_admin_trade_stats_epoch,
    reset_user_trade_stats_epoch,
    get_user_trade_stats,
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

def main_menu(user_id: int | None = None):
    is_admin = bool(user_id) and int(user_id) == int(ADMIN_TELEGRAM_ID)

    kb = [
        [InlineKeyboardButton("📊 Dashboard", callback_data="dashboard")],
        [
            InlineKeyboardButton("💳 Wallet / Private Key", callback_data="wallet_menu"),
            # ✅ Capital eliminado: el bot usa el saldo real del exchange
        ],
        [
            InlineKeyboardButton("▶ Activar Trading", callback_data="activate"),
            InlineKeyboardButton("⏸ Pausar Trading", callback_data="deactivate"),
        ],
        [
            InlineKeyboardButton("📈 Operaciones", callback_data="operations"),
            InlineKeyboardButton("👥 Referidos", callback_data="referrals"),
        ],
        [InlineKeyboardButton("ℹ️ Información", callback_data="info")],
    ]

    if is_admin:
        kb.append([InlineKeyboardButton("🛠 Panel Admin", callback_data="admin_panel")])

    return InlineKeyboardMarkup(kb)


# ============================================================
# /START
# ============================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user = update.effective_user
    user_id = user.id
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
        reply_markup=main_menu(user_id),
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
    balance = get_balance(user_id)

    msg = (
        "📊 *PANEL PRINCIPAL*\n"
        "───────────────────────────\n"
        f"🪪 Usuario: `{user_id}`\n"
        f"👛 Wallet: `{wallet}`\n"
        f"🔐 Private Key: `{'✔ Configurada' if pk else '❌ No configurada'}`\n"
        f"🏦 Balance Exchange (capital operativo): `{balance} USDC`\n"
        "───────────────────────────\n"
        f"📌 Estado: {'🟢 ACTIVO' if user_is_ready(user_id) else '🔴 INACTIVO'}"
    )

    await q.edit_message_text(msg, reply_markup=main_menu(user_id), parse_mode="Markdown")


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


    # ✅ Admin: estadísticas por usuario (solicitud de ID)
    if context.user_data.get("awaiting_user_stats_id"):
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
        # Guardar el usuario seleccionado para los botones 24h/7d/30d
        context.user_data["user_stats_target_id"] = int(target_id)

        await update.message.reply_text(
            f"👤 Usuario seleccionado: `{target_id}`\n\n"
            "Elige el período:",
            parse_mode="Markdown",
            reply_markup=_user_stats_kb(),
        )
        return

    if context.user_data.get("awaiting_wallet"):
        save_user_wallet(user_id, text)
        context.user_data.clear()
        await update.message.reply_text("✅ Wallet guardada.", reply_markup=main_menu(user_id))
        return

    if context.user_data.get("awaiting_pk"):
        save_user_private_key(user_id, text)
        context.user_data.clear()
        await update.message.reply_text("🔐 Private Key guardada.", reply_markup=main_menu(user_id))
        return

    # ✅ Capital eliminado: no se procesa input de capital.
    # Si el usuario envía un número, se ignora o queda como mensaje normal.


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

    user_id = q.from_user.id
    set_trading_status(user_id, "inactive")

    await q.edit_message_text(
        "🔴 *Trading PAUSADO*.",
        reply_markup=main_menu(user_id),
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

    await q.edit_message_text(msg, reply_markup=main_menu(user_id), parse_mode="Markdown")


# ============================================================
# REFERIDOS
# ============================================================

async def referrals(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    user_id = q.from_user.id
    link = f"https://t.me/{BOT_USERNAME}?start={user_id}"
    valid = get_referral_valid_count(user_id)

    msg = f"""👥 *REFERIDOS*
Comparte tu enlace. Un *referido válido* es quien compra una suscripción.

🔗 Tu enlace:
`{link}`

✅ Referidos válidos: *{valid}*"""

    await q.edit_message_text(msg, parse_mode="Markdown", reply_markup=main_menu(user_id))


async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if q.from_user.id != ADMIN_TELEGRAM_ID:
        await q.edit_message_text("⛔ Acceso no autorizado.", reply_markup=main_menu(q.from_user.id))
        return

    kb = [
        [InlineKeyboardButton("✅ Activar Plan Premium", callback_data="activate_plan")],
        [InlineKeyboardButton("📊 Información Visual", callback_data="admin_visual")],
        [InlineKeyboardButton("📈 Estadísticas Trading", callback_data="admin_stats")],
        [InlineKeyboardButton("👤 Estadísticas por Usuario", callback_data="admin_user_stats")],
        [InlineKeyboardButton("⬅ Volver", callback_data="back")],
    ]
    await q.edit_message_text(
        "🛠 *PANEL DE ADMINISTRACIÓN*\nSelecciona una opción:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kb),
    )


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
# ADMIN – ESTADÍSTICAS DE TRADING (24h / 7d / 30d)
# ============================================================

def _format_pf(pf):
    try:
        if pf == float("inf"):
            return "∞"
        return f"{float(pf):.2f}"
    except Exception:
        return "0.00"


async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if q.from_user.id != ADMIN_TELEGRAM_ID:
        await q.edit_message_text("⛔ Acceso no autorizado.", reply_markup=main_menu(q.from_user.id))
        return

    kb = [
        [InlineKeyboardButton("📅 Últimas 24h", callback_data="admin_stats_24h")],
        [InlineKeyboardButton("📆 Últimos 7 días", callback_data="admin_stats_7d")],
        [InlineKeyboardButton("🗓 Últimos 30 días", callback_data="admin_stats_30d")],
        [InlineKeyboardButton("♻️ Reset Stats", callback_data="admin_stats_reset_confirm")],
        [InlineKeyboardButton("⬅ Volver", callback_data="admin_panel")],
    ]
    await q.edit_message_text(
        "📈 *ESTADÍSTICAS DE TRADING (ADMIN)*\nSelecciona el período:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kb),
    )


async def _admin_stats_show(update: Update, context: ContextTypes.DEFAULT_TYPE, label: str, hours: int):
    q = update.callback_query
    await q.answer()

    if q.from_user.id != ADMIN_TELEGRAM_ID:
        await q.edit_message_text("⛔ Acceso no autorizado.", reply_markup=main_menu(q.from_user.id))
        return

    stats = get_admin_trade_stats(hours=hours) or {}

    total = int(stats.get("total", 0) or 0)
    wins = int(stats.get("wins", 0) or 0)
    losses = int(stats.get("losses", 0) or 0)
    win_rate = float(stats.get("win_rate", 0.0) or 0.0)
    pnl_total = float(stats.get("pnl_total", 0.0) or 0.0)
    gross_profit = float(stats.get("gross_profit", 0.0) or 0.0)
    gross_loss = float(stats.get("gross_loss", 0.0) or 0.0)
    pf = stats.get("profit_factor", 0.0)

    if total == 0:
        msg = (
            f"📈 *ESTADÍSTICAS ({label})*\n"
            "───────────────────────────\n"
            "Sin datos en este período.\n"
            "───────────────────────────"
        )
    else:
        msg = (
            f"📈 *ESTADÍSTICAS ({label})*\n"
            "───────────────────────────\n"
            f"🧾 Trades: `{total}`\n"
            f"✅ Wins: `{wins}`\n"
            f"❌ Losses: `{losses}`\n"
            f"🎯 WinRate: `{win_rate:.2f}%`\n"
            "───────────────────────────\n"
            f"💰 PnL Neto: `{pnl_total:.6f}` USDC\n"
            f"🟢 Ganancias: `{gross_profit:.6f}`\n"
            f"🔴 Pérdidas: `{gross_loss:.6f}`\n"
            f"📊 Profit Factor: `{_format_pf(pf)}`\n"
            "───────────────────────────"
        )

    kb = [
        [InlineKeyboardButton("📅 24h", callback_data="admin_stats_24h"),
         InlineKeyboardButton("📆 7d", callback_data="admin_stats_7d"),
         InlineKeyboardButton("🗓 30d", callback_data="admin_stats_30d")],
        [InlineKeyboardButton("♻️ Reset Stats", callback_data="admin_stats_reset_confirm")],
        [InlineKeyboardButton("⬅ Volver", callback_data="admin_stats")],
    ]

    await q.edit_message_text(msg, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))


async def admin_stats_24h(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await _admin_stats_show(update, context, "24h", 24)


async def admin_stats_7d(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await _admin_stats_show(update, context, "7 días", 24 * 7)


async def admin_stats_30d(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await _admin_stats_show(update, context, "30 días", 24 * 30)


async def admin_stats_reset_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if q.from_user.id != ADMIN_TELEGRAM_ID:
        await q.edit_message_text("⛔ Acceso no autorizado.", reply_markup=main_menu(q.from_user.id))
        return

    kb = [
        [
            InlineKeyboardButton("✅ Sí, resetear", callback_data="admin_stats_reset_do"),
            InlineKeyboardButton("❌ Cancelar", callback_data="admin_stats"),
        ]
    ]

    msg = (
        "♻️ *RESETEAR ESTADÍSTICAS*\n"
        "───────────────────────────\n"
        "Esto reinicia el conteo de estadísticas (24h/7d/30d)\n"
        "a partir de *ahora*.\n\n"
        "✅ El historial de operaciones NO se borra.\n"
        "Solo cambia el punto de inicio para el panel de estadísticas.\n"
        "───────────────────────────\n"
        "¿Confirmas el reset?"
    )

    await q.edit_message_text(msg, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))


async def admin_stats_reset_do(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if q.from_user.id != ADMIN_TELEGRAM_ID:
        await q.edit_message_text("⛔ Acceso no autorizado.", reply_markup=main_menu(q.from_user.id))
        return

    try:
        reset_admin_trade_stats_epoch()
        msg = (
            "✅ *Stats reseteadas*\n"
            "Desde este momento las estadísticas (24h/7d/30d)\n"
            "comienzan en *cero* para la nueva configuración."
        )
    except Exception as e:
        msg = f"⚠ No se pudo resetear stats: `{e}`"

    kb = [
        [InlineKeyboardButton("📈 Ver Estadísticas", callback_data="admin_stats")],
        [InlineKeyboardButton("⬅ Admin", callback_data="admin_panel")],
    ]
    await q.edit_message_text(msg, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))


# ============================================================
# ADMIN – ESTADÍSTICAS POR USUARIO (24h / 7d / 30d)
# ============================================================

async def admin_user_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if q.from_user.id != ADMIN_TELEGRAM_ID:
        await q.edit_message_text("⛔ Acceso no autorizado.", reply_markup=main_menu(q.from_user.id))
        return

    # Pedir ID por mensaje
    context.user_data.clear()
    context.user_data["awaiting_user_stats_id"] = True

    kb = [[InlineKeyboardButton("⬅ Volver", callback_data="admin_panel")]]
    await q.edit_message_text(
        "👤 *ESTADÍSTICAS POR USUARIO*\n\n"
        "Envía el *ID de Telegram* del usuario para ver sus estadísticas.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kb),
    )


def _user_stats_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📅 Últimas 24h", callback_data="admin_user_stats_24h")],
        [InlineKeyboardButton("📆 Últimos 7 días", callback_data="admin_user_stats_7d")],
        [InlineKeyboardButton("🗓 Últimos 30 días", callback_data="admin_user_stats_30d")],
        [InlineKeyboardButton("♻️ Reset Usuario", callback_data="admin_user_stats_reset_confirm")],
        [InlineKeyboardButton("🔁 Cambiar usuario", callback_data="admin_user_stats")],
        [InlineKeyboardButton("⬅ Admin", callback_data="admin_panel")],
    ])


async def _admin_user_stats_show(update: Update, context: ContextTypes.DEFAULT_TYPE, label: str, hours: int):
    q = update.callback_query
    await q.answer()

    if q.from_user.id != ADMIN_TELEGRAM_ID:
        await q.edit_message_text("⛔ Acceso no autorizado.", reply_markup=main_menu(q.from_user.id))
        return

    target_id = context.user_data.get("user_stats_target_id")
    try:
        target_id = int(target_id)
    except Exception:
        # Si no hay usuario seleccionado, volver a pedirlo
        context.user_data.clear()
        context.user_data["awaiting_user_stats_id"] = True
        await q.edit_message_text(
            "👤 *ESTADÍSTICAS POR USUARIO*\n\n"
            "Envía el *ID de Telegram* del usuario para ver sus estadísticas.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅ Admin", callback_data="admin_panel")]]),
        )
        return

    stats = get_user_trade_stats(user_id=target_id, hours=hours) or {}

    total = int(stats.get("total", 0) or 0)
    wins = int(stats.get("wins", 0) or 0)
    losses = int(stats.get("losses", 0) or 0)
    win_rate = float(stats.get("win_rate", 0.0) or 0.0)
    pnl_total = float(stats.get("pnl_total", 0.0) or 0.0)
    gross_profit = float(stats.get("gross_profit", 0.0) or 0.0)
    gross_loss = float(stats.get("gross_loss", 0.0) or 0.0)
    pf = stats.get("profit_factor", 0.0)

    if total == 0:
        msg = (
            f"👤 *ESTADÍSTICAS USUARIO* `{target_id}` ({label})\n"
            "───────────────────────────\n"
            "Sin datos en este período.\n"
            "───────────────────────────"
        )
    else:
        msg = (
            f"👤 *ESTADÍSTICAS USUARIO* `{target_id}` ({label})\n"
            "───────────────────────────\n"
            f"🧾 Trades: `{total}`\n"
            f"✅ Wins: `{wins}`\n"
            f"❌ Losses: `{losses}`\n"
            f"🎯 WinRate: `{win_rate:.2f}%`\n"
            "───────────────────────────\n"
            f"💰 PnL Neto: `{pnl_total:.6f}` USDC\n"
            f"🟢 Ganancias: `{gross_profit:.6f}`\n"
            f"🔴 Pérdidas: `{gross_loss:.6f}`\n"
            f"📊 Profit Factor: `{_format_pf(pf)}`\n"
            "───────────────────────────"
        )

    await q.edit_message_text(msg, parse_mode="Markdown", reply_markup=_user_stats_kb())


async def admin_user_stats_24h(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await _admin_user_stats_show(update, context, "24h", 24)


async def admin_user_stats_7d(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await _admin_user_stats_show(update, context, "7 días", 24 * 7)


async def admin_user_stats_30d(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await _admin_user_stats_show(update, context, "30 días", 24 * 30)


async def admin_user_stats_reset_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if q.from_user.id != ADMIN_TELEGRAM_ID:
        await q.edit_message_text("⛔ Acceso no autorizado.", reply_markup=main_menu(q.from_user.id))
        return

    target_id = context.user_data.get("user_stats_target_id")
    try:
        target_id = int(target_id)
    except Exception:
        # No hay usuario seleccionado
        context.user_data.clear()
        context.user_data["awaiting_user_stats_id"] = True
        await q.edit_message_text(
            "👤 *ESTADÍSTICAS POR USUARIO*

"
            "Envía el *ID de Telegram* del usuario para ver sus estadísticas.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅ Admin", callback_data="admin_panel")]]),
        )
        return

    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Sí, resetear", callback_data="admin_user_stats_reset_do"),
            InlineKeyboardButton("❌ Cancelar", callback_data="admin_user_stats_24h"),
        ],
        [InlineKeyboardButton("⬅ Volver", callback_data="admin_user_stats_24h")],
    ])

    msg = (
        "♻️ *RESETEAR ESTADÍSTICAS (USUARIO)*\n"
        "───────────────────────────\n"
        f"Usuario: `{target_id}`\n\n"
        "Esto reinicia el conteo de estadísticas (24h/7d/30d)\n"
        "a partir de *ahora* para *este usuario*.\n\n"
        "✅ El historial de operaciones NO se borra.\n"
        "Solo cambia el punto de inicio del panel.\n"
        "───────────────────────────\n"
        "¿Confirmas el reset?"
    )

    await q.edit_message_text(msg, parse_mode="Markdown", reply_markup=kb)


async def admin_user_stats_reset_do(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if q.from_user.id != ADMIN_TELEGRAM_ID:
        await q.edit_message_text("⛔ Acceso no autorizado.", reply_markup=main_menu(q.from_user.id))
        return

    target_id = context.user_data.get("user_stats_target_id")
    try:
        target_id = int(target_id)
    except Exception:
        context.user_data.clear()
        context.user_data["awaiting_user_stats_id"] = True
        await q.edit_message_text(
            "👤 *ESTADÍSTICAS POR USUARIO*\n\n"
            "Envía el *ID de Telegram* del usuario para ver sus estadísticas.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅ Admin", callback_data="admin_panel")]]),
        )
        return

    try:
        reset_user_trade_stats_epoch(target_id)
        msg = (
            "✅ *Stats del usuario reseteadas*\n"
            "───────────────────────────\n"
            f"Usuario: `{target_id}`\n\n"
            "Desde este momento las estadísticas (24h/7d/30d)\n"
            "comienzan en *cero* para este usuario."
        )
    except Exception as e:
        msg = f"⚠ No se pudo resetear stats del usuario: `{e}`"

    await q.edit_message_text(msg, parse_mode="Markdown", reply_markup=_user_stats_kb())


# ============================================================
# INFO
# ============================================================

async def info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    user_id = q.from_user.id
    data = get_last_operation(user_id) or {}
    last_open = data.get("last_open")
    last_close = data.get("last_close")

    lines = []
    lines.append("ℹ️ *INFORMACIÓN DE OPERACIONES*")
    lines.append("───────────────────────────")

    if last_open:
        lines.append("")
        lines.append("🟡 *Última operación ABIERTA*")
        lines.append(f"• Símbolo: `{last_open.get('symbol', '-')}`")
        lines.append(f"• Lado: `{last_open.get('side', '-')}`")
        lines.append(f"• Entrada: `{last_open.get('entry_price', '-')}`")
        lines.append(f"• Qty: `{last_open.get('qty', '-')}`")
        lines.append(f"• Apalancamiento: `{last_open.get('leverage', '-')}`")
    else:
        lines.append("")
        lines.append("🟡 *Última operación ABIERTA*")
        lines.append("_No hay datos aún._")

    if last_close:
        lines.append("")
        lines.append("✅ *Última operación CERRADA*")
        lines.append(f"• Símbolo: `{last_close.get('symbol', '-')}`")
        lines.append(f"• Lado: `{last_close.get('side', '-')}`")
        lines.append(f"• Entrada: `{last_close.get('entry_price', '-')}`")
        lines.append(f"• Salida: `{last_close.get('exit_price', '-')}`")
        lines.append(f"• Profit: `{last_close.get('profit', '-')}`")
    else:
        lines.append("")
        lines.append("✅ *Última operación CERRADA*")
        lines.append("_No hay datos aún._")

    msg = "\n".join(lines)
    await q.edit_message_text(msg, parse_mode="Markdown", reply_markup=main_menu(user_id))


async def back_to_main(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    user_id = q.from_user.id

    wallet = get_user_wallet(user_id)
    pk = get_user_private_key(user_id)
    balance = get_balance(user_id)

    msg = (
        "📊 *PANEL PRINCIPAL*\n"
        "───────────────────────────\n"
        f"🪪 Usuario: `{user_id}`\n"
        f"👛 Wallet: `{wallet}`\n"
        f"🔐 Private Key: `{'✔ Configurada' if pk else '❌ No configurada'}`\n"
        f"🏦 Balance Exchange (capital operativo): `{balance} USDC`\n"
        "───────────────────────────\n"
        f"📌 Estado: {'🟢 ACTIVO' if user_is_ready(user_id) else '🔴 INACTIVO'}"
    )

    await q.edit_message_text(msg, reply_markup=main_menu(user_id), parse_mode="Markdown")


# ============================================================
# ROUTER
# ============================================================

routes = {
    "dashboard": dashboard,
    "wallet_menu": wallet_menu,
    "set_wallet": set_wallet,
    "set_pk": set_pk,
    "activate": activate,
    "deactivate": deactivate,
    "operations": operations,
    "referrals": referrals,
    "activate_plan": activate_plan,
    "admin_visual": admin_visual,
    "admin_stats": admin_stats,
    "admin_stats_24h": admin_stats_24h,
    "admin_stats_7d": admin_stats_7d,
    "admin_stats_30d": admin_stats_30d,
    "admin_stats_reset_confirm": admin_stats_reset_confirm,
    "admin_stats_reset_do": admin_stats_reset_do,
    "admin_user_stats": admin_user_stats,
    "admin_user_stats_24h": admin_user_stats_24h,
    "admin_user_stats_7d": admin_user_stats_7d,
    "admin_user_stats_30d": admin_user_stats_30d,
    "admin_user_stats_reset_confirm": admin_user_stats_reset_confirm,
    "admin_user_stats_reset_do": admin_user_stats_reset_do,
    "admin_panel": admin_panel,
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
