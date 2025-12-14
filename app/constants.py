# ============================================================
# CONSTANTES GLOBALES DEL BOT TRADING X HIPER PRO
# ============================================================

# Mensajes fijos
WELCOME_MESSAGE = (
    "🚀 *Bienvenido a Trading X Hiper Pro*\n\n"
    "Un sistema de trading automático 24/7 basado en HyperLiquid PERP.\n"
    "Configura tu API, activa tu capital y deja que el bot opere por ti."
)

API_INSTRUCTIONS = (
    "📌 *Para comenzar, necesitas ingresar tus claves API de HyperLiquid.*\n\n"
    "Asegúrate de que tu API tenga permisos de TRADING.\n"
    "Nunca compartas estas claves con terceros."
)

MENU_MAIN_TITLE = "📊 Panel Principal – Trading X Hiper Pro"

ERROR_GENERIC = "❌ Ha ocurrido un error inesperado. Inténtalo nuevamente."
ERROR_API = "⚠️ No se pudo conectar con HyperLiquid. Verifica tus claves API."
ERROR_DB = "⚠️ Error al conectar con la base de datos."

SUCCESS_API_SAVED = "✅ Tus claves API han sido guardadas correctamente."
SUCCESS_TRADE_EXECUTED = "📈 Operación ejecutada exitosamente."
SUCCESS_TRADING_ENABLED = "✅ Trading automático activado."
SUCCESS_TRADING_DISABLED = "⏸ Trading automático desactivado."

# Opciones del menú
BTN_START = "🚀 Iniciar"
BTN_MY_ACCOUNT = "👤 Mi Cuenta"
BTN_TRADING = "📈 Trading Automático"
BTN_SETTINGS = "⚙️ Configuración"
BTN_BACK = "⬅️ Volver"

# Estados internos
STATE_WAITING_API_KEY = "waiting_api_key"
STATE_WAITING_SECRET_KEY = "waiting_secret_key"
STATE_IDLE = "idle"
