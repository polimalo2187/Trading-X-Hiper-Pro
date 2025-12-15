# ============================================================
# TRADING LOOP – Trading X Hyper Pro
# Archivo 7/9 – Ejecución automática 24/7
# ============================================================

import asyncio
from telegram import Bot

from app.database import (
    get_all_users,
    user_is_ready
)

from app.trading_engine import execute_trade
from app.config import SCAN_INTERVAL
from app.config import TELEGRAM_BOT_TOKEN


# ============================================================
# INICIALIZAR BOT DE TELEGRAM
# (El token se importa desde config)
# ============================================================

bot = Bot(token=TELEGRAM_BOT_TOKEN)


# ============================================================
# LOOP PRINCIPAL 24/7
# ============================================================

async def trading_loop():
    """
    Escanea todos los usuarios activos y ejecuta una operación real
    para cada uno. Se repite cada SCAN_INTERVAL segundos.
    """

    print("🔄 Trading Loop iniciado... Sistema REAL operando 24/7")

    while True:
        try:
            users = get_all_users()

            for user in users:
                user_id = user["user_id"]

                # Usuario debe:
                # - Tener wallet
                # - Tener private key
                # - Tener capital
                # - Tener trading activo
                if not user_is_ready(user_id):
                    continue

                # Ejecutar operación real
                result = execute_trade(user_id)

                # Enviar resultado al usuario por Telegram
                try:
                    await bot.send_message(chat_id=user_id, text=result)
                except Exception as e:
                    print(f"⚠ No se pudo enviar mensaje a {user_id}: {e}")

        except Exception as e:
            print(f"❌ Error en trading_loop: {e}")

        # Repetir según SCAN_INTERVAL
        await asyncio.sleep(SCAN_INTERVAL)
