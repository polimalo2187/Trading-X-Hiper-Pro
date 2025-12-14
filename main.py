# ============================================================
# MAIN.PY – INICIO DEL BOT TRADING X HYPER PRO
# ============================================================

import asyncio
from telegram.ext import ApplicationBuilder
from app.config import TELEGRAM_BOT_TOKEN, BOT_NAME
from app.handlers import register_handlers
from app.scheduler import start_scheduler


# ============================================================
# INICIAR BOT
# ============================================================

async def main():
    print(f"🚀 Iniciando {BOT_NAME}...")

    app = (
        ApplicationBuilder()
        .token(TELEGRAM_BOT_TOKEN)
        .concurrent_updates(True)
        .build()
    )

    # Registrar todos los handlers
    register_handlers(app)

    # Iniciar scheduler en segundo plano
    asyncio.create_task(start_scheduler())

    print("🟢 BOT LISTO Y CORRIENDO...")
    await app.run_polling(close_loop=False)


# ============================================================
# EJECUCIÓN PRINCIPAL
# ============================================================

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        print("❌ ERROR INICIANDO EL BOT:", e)
