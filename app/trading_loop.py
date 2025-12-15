# ============================================================
# TRADING LOOP – Trading X Hyper Pro
# Archivo 10/10 – Operaciones reales 24/7
# ============================================================

import asyncio
from telegram import Bot

from app.database import get_all_users, user_is_ready
from app.trading_engine import execute_trade
from app.config import SCAN_INTERVAL, TELEGRAM_BOT_TOKEN


# ============================================================
# INICIALIZAR BOT DE TELEGRAM
# ============================================================

bot = Bot(token=TELEGRAM_BOT_TOKEN)


# ============================================================
# LOOP PRINCIPAL – 24/7
# ============================================================

async def trading_loop():

    print("🔄 Trading Loop iniciado — Operando 24/7...")

    while True:

        try:
            users = get_all_users()

            for user in users:
                user_id = user["user_id"]

                if not user_is_ready(user_id):
                    continue

                # ----------------------------------------------------
                # El Trading Engine hace TODO:
                #  - Scanner real
                #  - Mejor par
                #  - Señal real
                #  - Entrada / salida real
                #  - Fees
                #  - Registro de trade
                # ----------------------------------------------------
                result = execute_trade(user_id)

                # Enviar resultado al usuario por Telegram
                try:
                    await bot.send_message(chat_id=user_id, text=result)
                except Exception as e:
                    print(f"⚠ No pude enviar mensaje al usuario {user_id}: {e}")

        except Exception as fatal:
            print("❌ Error grave en trading_loop:", fatal)

        # Esperar antes del próximo ciclo
        await asyncio.sleep(SCAN_INTERVAL)
