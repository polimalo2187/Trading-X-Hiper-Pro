# ============================================================
# TRADING LOOP – Trading X Hyper Pro
# ============================================================

import asyncio
from telegram import error as tg_error
from telegram.ext import Application

from app.database import get_all_users, user_is_ready
from app.trading_engine import execute_trade_cycle
from app.config import SCAN_INTERVAL


async def send_message_safe(app: Application, user_id: int, text: str):
    try:
        await app.bot.send_message(chat_id=user_id, text=text, parse_mode="Markdown")
    except tg_error.RetryAfter as e:
        await asyncio.sleep(int(e.retry_after) + 1)
        await app.bot.send_message(chat_id=user_id, text=text, parse_mode="Markdown")
    except Exception as e:
        print(f"⚠ Error enviando mensaje a {user_id}: {e}")


async def trading_loop(app: Application):

    print("🔄 Trading Loop iniciado — PRODUCCIÓN")
    loop = asyncio.get_running_loop()

    while True:
        users = get_all_users()

        for user in users:
            user_id = user.get("user_id")
            if not user_id or not user_is_ready(user_id):
                continue

            result = await loop.run_in_executor(
                None,
                execute_trade_cycle,
                user_id
            )

            if not result:
                continue

            if result.get("open"):
                await send_message_safe(app, user_id, result["open"]["message"])

            if result.get("close"):
                await send_message_safe(app, user_id, result["close"]["message"])

            await asyncio.sleep(0.3)

        await asyncio.sleep(SCAN_INTERVAL)
