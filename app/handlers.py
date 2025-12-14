from telegram import Update
from telegram.ext import CallbackContext
from app.keyboards import main_menu, capital_menu, referral_menu, trades_menu, bot_status_menu
from app.database import (
    create_user, save_user_wallet, save_user_capital, set_trading_status,
    get_user_capital, get_user_wallet, get_user_trades,
    get_user_referrer, get_referrer_total_fees
)
from app.config import MIN_CAPITAL
from app.trading_engine import process_user_trade_cycle


# ============================================================
# INICIO DEL BOT
# ============================================================

async def start(update: Update, context: CallbackContext):
    user = update.effective_user

    create_user(user.id, user.username)

    await update.message.reply_text(
        f"👋 Hola *{user.first_name}*\n"
        f"Bienvenido a *Trading X Hyper Pro* 🚀\n\n"
        f"Configura tu capital, tu wallet y activa el trading.\n",
        parse_mode="Markdown",
        reply_markup=main_menu()
    )


# ============================================================
# CALLBACK PRINCIPAL
# ============================================================

async def callbacks(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id

    # Menú principal
    if data == "back_main":
        await query.edit_message_text(
            "📍 *Menú Principal*\nSelecciona una opción:",
            parse_mode="Markdown",
            reply_markup=main_menu()
        )
        return

    # Activar trading
    if data == "activate_trading":
        capital = get_user_capital(user_id)
        wallet = get_user_wallet(user_id)

        if capital < MIN_CAPITAL:
            await query.edit_message_text(
                f"❌ Debes asignar al menos *{MIN_CAPITAL} USDC* de capital.\n"
                f"Configúralo en el menú.",
                parse_mode="Markdown",
                reply_markup=main_menu()
            )
            return

        if not wallet:
            await query.edit_message_text(
                f"❌ Debes configurar tu wallet primero.",
                reply_markup=main_menu()
            )
            return

        set_trading_status(user_id, "active")

        await query.edit_message_text(
            "🟢 *Trading Activado*\nEl bot comenzará a operar automáticamente.",
            parse_mode="Markdown",
            reply_markup=main_menu()
        )

        return

    # Desactivar trading
    if data == "stop_trading":
        set_trading_status(user_id, "inactive")

        await query.edit_message_text(
            "🔴 *Trading Desactivado*\nEl bot ha detenido todas las operaciones.",
            parse_mode="Markdown",
            reply_markup=main_menu()
        )
        return

    # Capital
    if data == "set_capital":
        await query.edit_message_text(
            "💰 *Configurar Capital*\nSelecciona una opción:",
            parse_mode="Markdown",
            reply_markup=capital_menu()
        )
        return

    if data == "capital_increase":
        await query.edit_message_text(
            "🔼 Escribe la cantidad en USDC que deseas *añadir* a tu capital."
        )
        context.user_data["awaiting_capital_increase"] = True
        return

    if data == "capital_decrease":
        await query.edit_message_text(
            "🔽 Escribe la cantidad en USDC que deseas *reducir* de tu capital."
        )
        context.user_data["awaiting_capital_decrease"] = True
        return

    # Wallet
    if data == "set_wallet":
        await query.edit_message_text(
            "🔗 *Configurar Wallet*\nEnvíame la dirección de tu wallet HyperLiquid."
        )
        context.user_data["awaiting_wallet"] = True
        return

    # Operaciones
    if data == "show_trades":
        trades = get_user_trades(user_id)

        if not trades:
            await query.edit_message_text(
                "📄 *Aún no tienes operaciones registradas.*",
                parse_mode="Markdown",
                reply_markup=trades_menu()
            )
            return

        msg = "📊 *Tus Operaciones:*\n\n"
        for t in trades[:10]:  # Solo muestra las últimas 10
            msg += (
                f"• {t['symbol']} | {t['side'].upper()}\n"
                f"  Entrada: {t['entry']}  →  Salida: {t['exit']}\n"
                f"  Ganancia: {t['profit']} USDC\n\n"
            )

        await query.edit_message_text(
            msg,
            parse_mode="Markdown",
            reply_markup=trades_menu()
        )
        return

    # Sistema de referidos
    if data == "ref_system":
        await query.edit_message_text(
            "👥 *Sistema de Referidos*\nSelecciona una opción:",
            parse_mode="Markdown",
            reply_markup=referral_menu()
        )
        return

    if data == "get_ref_link":
        ref_link = f"https://t.me/TradingXHyperProBot?start={user_id}"

        await query.edit_message_text(
            f"🔗 *Tu enlace de referido:*\n{ref_link}\n\n"
            f"Comparte este enlace para ganar el 5% del FEE de tus referidos.",
            parse_mode="Markdown",
            reply_markup=referral_menu()
        )
        return

    if data == "my_referrals":
        ref = get_user_referrer(user_id)

        await query.edit_message_text(
            f"👤 Usuario que te refirió:\n{ref if ref else 'Nadie'}",
            reply_markup=referral_menu()
        )
        return

    if data == "my_ref_earnings":
        total = get_referrer_total_fees(user_id)

        await query.edit_message_text(
            f"💵 *Tus ganancias por referidos:* {total} USDC",
            parse_mode="Markdown",
            reply_markup=referral_menu()
        )
        return

    # Estado del bot
    if data == "bot_status":
        await query.edit_message_text(
            "📈 Estado del bot en tiempo real.",
            reply_markup=bot_status_menu()
        )
        return


# ============================================================
# MENSAJES DE TEXTO (CAPITAL, WALLET, ETC.)
# ============================================================

async def text_handler(update: Update, context: CallbackContext):
    text = update.message.text
    user_id = update.effective_user.id

    # Guardar wallet
    if context.user_data.get("awaiting_wallet"):
        save_user_wallet(user_id, text)
        context.user_data["awaiting_wallet"] = False

        await update.message.reply_text(
            "🟢 Wallet guardada correctamente.",
            reply_markup=main_menu()
        )
        return

    # Aumentar capital
    if context.user_data.get("awaiting_capital_increase"):
        try:
            amount = float(text)
            current = get_user_capital(user_id)
            save_user_capital(user_id, current + amount)
            context.user_data["awaiting_capital_increase"] = False

            await update.message.reply_text(
                f"✔ Capital actualizado: {current + amount} USDC",
                reply_markup=main_menu()
            )
        except:
            await update.message.reply_text("❌ Debes enviar un número válido.")
        return

    # Reducir capital
    if context.user_data.get("awaiting_capital_decrease"):
        try:
            amount = float(text)
            current = get_user_capital(user_id)

            if amount > current:
                await update.message.reply_text("❌ No puedes reducir más de tu capital actual.")
                return

            save_user_capital(user_id, current - amount)
            context.user_data["awaiting_capital_decrease"] = False

            await update.message.reply_text(
                f"✔ Capital actualizado: {current - amount} USDC",
                reply_markup=main_menu()
            )
        except:
            await update.message.reply_text("❌ Debes enviar un número válido.")
        return
