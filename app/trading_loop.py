# ============================================================
# TRADING LOOP – TRADING X HYPER PRO
# Sistema de operaciones automáticas 24/7
# ============================================================

import asyncio
from app.database import user_is_ready
from app.trading_engine import execute_trade
from app.config import DEFAULT_PAIR, SCAN_INTERVAL
from app.database import get_all_users
from telegram import Bot


bot = Bot(token="")
# Nota: El token REAL se inserta dinámicamente desde bot.py


async def trading_loop():
    """
    Revisa todos los usuarios activos y ejecuta operaciones reales para cada uno.
    Corre cada SCAN_INTERVAL segundos.
    """
    print("🔄 Trading loop iniciado (24/7 REAL)...")

    while True:

        try:
            users = get_all_users()

            for user in users:
                user_id = user["user_id"]

                if not user_is_ready(user_id):
                    continue

                # Ejecutar trade real
                result = execute_trade(user_id, DEFAULT_PAIR)

                # Enviar resultado al usuario
                try:
                    await bot.send_message(
                        chat_id=user_id,
                        text=result
                    )
                except:
                    print(f"⚠ No pude enviar mensaje a {user_id}")

        except Exception as e:
            print("❌ Error en trading_loop:", e)

        await asyncio.sleep(SCAN_INTERVAL)
