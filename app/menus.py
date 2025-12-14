# ============================================================
# MENÚS – TRADING X HYPER PRO
# ============================================================

from telegram import InlineKeyboardMarkup, InlineKeyboardButton


# ============================================================
# MENÚ PRINCIPAL
# ============================================================

def main_menu():
    keyboard = [
        [InlineKeyboardButton("📊 Operaciones", callback_data="menu_operations")],
        [InlineKeyboardButton("💼 Capital", callback_data="menu_capital")],
        [InlineKeyboardButton("⚙ Estado Trading", callback_data="menu_status")],
        [InlineKeyboardButton("💰 Mis Ganancias", callback_data="menu_earnings")],
        [InlineKeyboardButton("👥 Referidos", callback_data="menu_referrals")],
        [InlineKeyboardButton("🔑 Configuración Wallet", callback_data="menu_wallet")]
    ]

    return InlineKeyboardMarkup(keyboard)


# ============================================================
# SUBMENÚ CAPITAL
# ============================================================

def capital_menu():
    keyboard = [
        [InlineKeyboardButton("➕ Aumentar Capital", callback_data="capital_add")],
        [InlineKeyboardButton("➖ Reducir Capital", callback_data="capital_reduce")],
        [InlineKeyboardButton("⬅ Volver", callback_data="main_menu")]
    ]
    return InlineKeyboardMarkup(keyboard)


# ============================================================
# SUBMENÚ ESTADO TRADING
# ============================================================

def status_menu():
    keyboard = [
        [InlineKeyboardButton("🟢 Activar", callback_data="status_active")],
        [InlineKeyboardButton("⛔ Desactivar", callback_data="status_inactive")],
        [InlineKeyboardButton("⬅ Volver", callback_data="main_menu")]
    ]
    return InlineKeyboardMarkup(keyboard)


# ============================================================
# SUBMENÚ WALLET
# ============================================================

def wallet_menu():
    keyboard = [
        [InlineKeyboardButton("🔧 Configurar Wallet", callback_data="wallet_set")],
        [InlineKeyboardButton("📌 Ver Wallet", callback_data="wallet_view")],
        [InlineKeyboardButton("⬅ Volver", callback_data="main_menu")]
    ]
    return InlineKeyboardMarkup(keyboard)


# ============================================================
# SUBMENÚ REFERIDOS
# ============================================================

def referrals_menu():
    keyboard = [
        [InlineKeyboardButton("📨 Mi enlace de referido", callback_data="ref_link")],
        [InlineKeyboardButton("💰 Mis ganancias por referidos", callback_data="ref_earnings")],
        [InlineKeyboardButton("⬅ Volver", callback_data="main_menu")]
    ]
    return InlineKeyboardMarkup(keyboard)


# ============================================================
# SUBMENÚ GANANCIAS
# ============================================================

def earnings_menu():
    keyboard = [
        [InlineKeyboardButton("📈 Ganancias Totales", callback_data="earn_total")],
        [InlineKeyboardButton("📅 Ganancias de Hoy", callback_data="earn_today")],
        [InlineKeyboardButton("⬅ Volver", callback_data="main_menu")]
    ]
    return InlineKeyboardMarkup(keyboard)


# ============================================================
# SUBMENÚ OPERACIONES
# ============================================================

def operations_menu():
    keyboard = [
        [InlineKeyboardButton("📄 Registro de operaciones", callback_data="ops_list")],
        [InlineKeyboardButton("🔴 Operaciones abiertas", callback_data="ops_open")],
        [InlineKeyboardButton("⬅ Volver", callback_data="main_menu")]
    ]
    return InlineKeyboardMarkup(keyboard)
