# ============================================================
# TRADING LOOP – Trading X Hyper Pro
# PRODUCCION REAL 24/7
# ============================================================

import asyncio
from datetime import datetime
from telegram.ext import Application
from telegram import error as tg_error

from app.database import get_all_users, user_is_ready
from app.trading_engine import execute_trade_cycle
from app.config import SCAN_INTERVAL


# ============================================================
# LOG
# ============================================================

def log(msg: str, level: str = "INFO"):
    print(f"[LOOP {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}] {level} {msg}")


# ============================================================
# MENSAJERIA SEGURA
# ============================================================

async def send_message_safe(app: Application, user_id: int, text: str):
    try:
        await app.bot.send_message(chat_id=user_id, text=text, parse_mode="Markdown")
    except tg_error.RetryAfter as e:
        await asyncio.sleep(int(e.retry_after) + 1)
        await app.bot.send_message(chat_id=user_id, text=text, parse_mode="Markdown")
    except Exception as e:
        log(f"Error enviando mensaje a {user_id}: {e}", "ERROR")


# ============================================================
# LOOP PRINCIPAL
# ============================================================

async def trading_loop(app: Application):

    log("Trading Loop iniciado — PRODUCCION 24/7")

    loop = asyncio.get_running_loop()

    while True:
        try:
            log("Tick")

            users = get_all_users()
            log(f"Usuarios cargados: {len(users)}")

            for user in users:
                user_id = user.get("user_id")

                if not user_id:
                    continue

                if not user_is_ready(user_id):
                    log(f"Usuario {user_id} no listo")
                    continue

                log(f"Ejecutando ciclo usuario {user_id}")

                result = await loop.run_in_executor(
                    None,
                    execute_trade_cycle,
                    user_id
                )

                if not result:
                    log(f"Usuario {user_id}: sin evento")
                    continue

                if result.get("event") in ("OPEN", "BOTH"):
                    msg = result.get("open", {}).get("message")
                    if msg:
                        await send_message_safe(app, user_id, msg)

                if result.get("event") in ("CLOSE", "BOTH"):
                    msg = result.get("close", {}).get("message")
                    if msg:
                        await send_message_safe(app, user_id, msg)

                await asyncio.sleep(0.4)

        except Exception as e:
            log(f"Error grave en trading_loop: {e}", "ERROR")
            await asyncio.sleep(2)

        await asyncio.sleep(SCAN_INTERVAL)
