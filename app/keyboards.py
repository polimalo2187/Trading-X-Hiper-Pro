from telegram import InlineKeyboardMarkup, InlineKeyboardButton


# ============================================================
# MENÚ PRINCIPAL – TRADING X HYPER PRO
# ============================================================

def main_menu():
    keyboard = [
        [
            InlineKeyboardButton("🚀 Activar Trading", callback_data="activate_trading"),
            InlineKeyboardButton("🛑 Detener Trading", callback_data="stop_trading")
        ],
        [
            InlineKeyboardButton("💰 Establecer Capital", callback_data="set_capital"),
            InlineKeyboardButton("🔗 Configurar Wallet", callback_data="set_wallet")
        ],
        [
            InlineKeyboardButton("📊 Operaciones", callback_data="show_trades"),
            InlineKeyboardButton("📈 Estado del Bot", callback_data="bot_status")
        ],
        [
            InlineKeyboardButton("👥 Sistema de Referidos", callback_data="ref_system")
        ]
    ]

    return InlineKeyboardMarkup(keyboard)


# ============================================================
# SUBMENÚ PARA CAPITAL
# ============================================================

def capital_menu():
    keyboard = [
        [InlineKeyboardButton("➕ Aumentar Capital", callback_data="capital_increase")],
        [InlineKeyboardButton("➖ Reducir Capital", callback_data="capital_decrease")],
        [InlineKeyboardButton("⬅️ Volver", callback_data="back_main")]
    ]
    return InlineKeyboardMarkup(keyboard)


# ============================================================
# SUBMENÚ REFERIDOS
# ============================================================

def referral_menu():
    keyboard = [
        [InlineKeyboardButton("📨 Obtener mi enlace", callback_data="get_ref_link")],
        [InlineKeyboardButton("📊 Mis Referidos", callback_data="my_referrals")],
        [InlineKeyboardButton("💵 Mis Ganancias", callback_data="my_ref_earnings")],
        [InlineKeyboardButton("⬅️ Volver", callback_data="back_main")]
    ]
    return InlineKeyboardMarkup(keyboard)


# ============================================================
# SUBMENÚ OPERACIONES
# ============================================================

def trades_menu():
    keyboard = [
        [InlineKeyboardButton("📄 Ver Registro Completo", callback_data="view_trades_full")],
        [InlineKeyboardButton("🔄 Refrescar", callback_data="refresh_trades")],
        [InlineKeyboardButton("⬅️ Volver", callback_data="back_main")]
    ]
    return InlineKeyboardMarkup(keyboard)


# ============================================================
# BOT STATUS
# ============================================================

def bot_status_menu():
    keyboard = [
        [InlineKeyboardButton("🔄 Actualizar Estado", callback_data="refresh_status")],
        [InlineKeyboardButton("⬅️ Volver", callback_data="back_main")]
    ]
    return InlineKeyboardMarkup(keyboard)
