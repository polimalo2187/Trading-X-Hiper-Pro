# ============================================================
# TRADING LOOP – Trading X Hyper Pro
# Archivo 10/10 – Operaciones reales 24/7 (VERSIÓN FINAL OPTIMIZADA)
# ============================================================

import asyncio
from telegram import error as tg_error
from telegram.ext import Application

from app.database import get_all_users, user_is_ready
from app.trading_engine import execute_trade
from app.config import SCAN_INTERVAL, TELEGRAM_BOT_TOKEN


# ============================================================
# OBTENER INSTANCIA REAL DEL BOT DESDE APPLICATION
# ============================================================

async def send_message_safe(app: Application, user_id: int, text: str):
    """Envía mensajes de forma segura manejando FloodWait y errores."""
    try:
        await app.bot.send_message(chat_id=user_id, text=text)

    except tg_error.RetryAfter as e:
        wait_time = int(e.retry_after) + 1
        print(f"⏳ FloodWait detectado. Esperando {wait_time}s...")
        await asyncio.sleep(wait_time)
        await app.bot.send_message(chat_id=user_id, text=text)

    except Exception as e:
        print(f"⚠ No pude enviar mensaje a {user_id}: {e}")


# ============================================================
# LOOP PRINCIPAL – 24/7
# ============================================================

async def trading_loop():
    """
    Este loop corre 24/7 dentro del mismo event-loop del bot.
    No crea nuevos loops, no usa Bot() externo, no bloquea asyncio.
    """

    print("🔄 Trading Loop iniciado — Operando 24/7...")

    # Instancia única de la aplicación Telegram
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    await app.initialize()
    await app.start()

    loop = asyncio.get_running_loop()

    while True:
        try:
            users = get_all_users()

            for user in users:
                user_id = user.get("user_id")
                if not user_id:
                    continue

                if not user_is_ready(user_id):
                    continue

                # =====================================================
                # EJECUTAR TRADE REAL (NO BLOQUEA ASYNCIO)
                # =====================================================
                result = await loop.run_in_executor(
                    None,
                    execute_trade,
                    user_id
                )

                # =====================================================
                # ENVÍO DEL RESULTADO AL USUARIO (SEGURO)
                # =====================================================
                await send_message_safe(app, user_id, result)

                # Pausa mínima anti-flood
                await asyncio.sleep(0.6)

        except Exception as fatal:
            print("❌ Error grave en trading_loop:", fatal)
            print("🛡 Reiniciando ciclo automáticamente...")
            await asyncio.sleep(2)

        # Pausa entre ciclos principales
        await asyncio.sleep(SCAN_INTERVAL)
