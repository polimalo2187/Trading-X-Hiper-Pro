# ============================================================
# TRADING LOOP – Trading X Hyper Pro
# Archivo 10/10 – Operaciones reales 24/7 (FINAL)
# ============================================================

import asyncio
from telegram import error as tg_error
from telegram.ext import Application

from app.database import get_all_users, user_is_ready
from app.trading_engine import execute_trade
from app.config import SCAN_INTERVAL


# ============================================================
# ENVÍO SEGURO
# ============================================================

async def send_message_safe(app: Application, user_id: int, text: str):
    try:
        await app.bot.send_message(chat_id=user_id, text=text, parse_mode="Markdown")
    except tg_error.RetryAfter as e:
        await asyncio.sleep(int(e.retry_after) + 1)
        await app.bot.send_message(chat_id=user_id, text=text, parse_mode="Markdown")
    except Exception as e:
        print(f"⚠ Error enviando mensaje a {user_id}: {e}")


# ============================================================
# LOOP PRINCIPAL
# ============================================================

async def trading_loop(app: Application):

    print("🔄 Trading Loop iniciado — Operando 24/7...")
    loop = asyncio.get_running_loop()

    while True:
        try:
            users = get_all_users()

            for user in users:
                user_id = user.get("user_id")
                if not user_id or not user_is_ready(user_id):
                    continue

                result = await loop.run_in_executor(
                    None,
                    execute_trade,
                    user_id
                )

                if not result or not result.get("event"):
                    continue

                # 🔔 APERTURA
                if result.get("event") in ("OPEN", "BOTH"):
                    open_msg = result.get("open", {}).get("message")
                    if open_msg:
                        await send_message_safe(app, user_id, open_msg)

                # 🔔 CIERRE
                if result.get("event") in ("CLOSE", "BOTH"):
                    close_msg = result.get("close", {}).get("message")
                    if close_msg:
                        await send_message_safe(app, user_id, close_msg)

                await asyncio.sleep(0.5)

        except Exception as fatal:
            print("❌ Error grave en trading_loop:", fatal)
            await asyncio.sleep(2)

        await asyncio.sleep(SCAN_INTERVAL)
