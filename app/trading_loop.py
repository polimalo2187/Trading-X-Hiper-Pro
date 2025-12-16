# ============================================================
# TRADING LOOP – Trading X Hyper Pro
# Archivo 10/10 – Operaciones reales 24/7 (VERSIÓN FINAL)
# ============================================================

import asyncio
from telegram import Bot, error as tg_error

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

                # Validación del usuario
                if not user_is_ready(user_id):
                    continue

                # =====================================================
                # EJECUTAR TRADE REAL
                # =====================================================
                result = execute_trade(user_id)

                # =====================================================
                # ENVÍO DEL RESULTADO AL USUARIO
                # Manejo profesional de FloodWait y otros errores
                # =====================================================
                try:
                    await bot.send_message(chat_id=user_id, text=result)

                except tg_error.RetryAfter as e:
                    # Esperar el tiempo que Telegram exige
                    wait_time = int(e.retry_after) + 1
                    print(f"⏳ FloodWait detectado. Esperando {wait_time}s...")
                    await asyncio.sleep(wait_time)
                    await bot.send_message(chat_id=user_id, text=result)

                except Exception as e:
                    print(f"⚠ No pude enviar mensaje a {user_id}: {e}")

                # Pausa mínima para no saturar a Telegram
                await asyncio.sleep(0.6)

        except Exception as fatal:
            print("❌ Error grave en trading_loop:", fatal)
            print("🛡 Reiniciando ciclo automáticamente...")
            await asyncio.sleep(2)

        # Esperar antes del próximo ciclo
        await asyncio.sleep(SCAN_INTERVAL)
