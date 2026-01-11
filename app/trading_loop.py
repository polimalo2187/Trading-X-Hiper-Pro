# ============================================================
# TRADING LOOP – Trading X Hyper Pro
# PRODUCCIÓN REAL 24/7 — BANK GRADE
# ============================================================

import asyncio
from datetime import datetime
from telegram.ext import Application
from telegram import error as tg_error

from app.database import get_all_users, user_is_ready
from app.trading_engine import execute_trade_cycle
from app.config import SCAN_INTERVAL


# ============================================================
# CONFIG BANK GRADE
# ============================================================

MAX_CONCURRENT_USERS = 5          # Control de carga
TRADE_TIMEOUT_SECONDS = 45        # Timeout duro por usuario
ERROR_BACKOFF_SECONDS = 3


# ============================================================
# STATE
# ============================================================

user_locks: dict[int, asyncio.Lock] = {}
telegram_blacklist: set[int] = set()


# ============================================================
# LOG
# ============================================================

def log(msg: str, level: str = "INFO"):
    print(f"[LOOP {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}] {level} {msg}")


# ============================================================
# MENSAJERÍA SEGURA (BANK GRADE)
# ============================================================

async def send_message_safe(app: Application, user_id: int, text: str):
    if user_id in telegram_blacklist:
        return

    try:
        await app.bot.send_message(
            chat_id=user_id,
            text=text,
            parse_mode="Markdown"
        )

    except tg_error.Forbidden:
        telegram_blacklist.add(user_id)
        log(f"Usuario {user_id} bloqueó el bot (blacklisted)", "WARN")

    except tg_error.RetryAfter as e:
        await asyncio.sleep(int(e.retry_after) + 1)
        await app.bot.send_message(chat_id=user_id, text=text, parse_mode="Markdown")

    except Exception as e:
        log(f"Error Telegram usuario {user_id}: {e}", "ERROR")


# ============================================================
# EJECUCIÓN SEGURA POR USUARIO
# ============================================================

async def execute_user_cycle(user_id: int, semaphore: asyncio.Semaphore):
    if user_id not in user_locks:
        user_locks[user_id] = asyncio.Lock()

    lock = user_locks[user_id]

    if lock.locked():
        log(f"Usuario {user_id} ya en ejecución — skip")
        return

    async with semaphore:
        async with lock:
            try:
                loop = asyncio.get_running_loop()

                result = await asyncio.wait_for(
                    loop.run_in_executor(None, execute_trade_cycle, user_id),
                    timeout=TRADE_TIMEOUT_SECONDS
                )

                return result

            except asyncio.TimeoutError:
                log(f"Timeout ejecución usuario {user_id}", "WARN")

            except Exception as e:
                log(f"Error crítico usuario {user_id}: {e}", "ERROR")


# ============================================================
# LOOP PRINCIPAL
# ============================================================

async def trading_loop(app: Application):

    log("Trading Loop iniciado — BANK GRADE 24/7")

    semaphore = asyncio.Semaphore(MAX_CONCURRENT_USERS)

    while True:
        try:
            users = get_all_users()
            log(f"Usuarios activos: {len(users)}")

            tasks = []

            for user in users:
                user_id = user.get("user_id")
                if not user_id:
                    continue

                if not user_is_ready(user_id):
                    continue

                tasks.append(execute_user_cycle(user_id, semaphore))

            results = await asyncio.gather(*tasks, return_exceptions=True)

            for user, result in zip(users, results):
                if not isinstance(result, dict):
                    continue

                user_id = user.get("user_id")

                if result.get("event") in ("OPEN", "BOTH"):
                    msg = result.get("open", {}).get("message")
                    if msg:
                        await send_message_safe(app, user_id, msg)

                if result.get("event") in ("CLOSE", "BOTH"):
                    msg = result.get("close", {}).get("message")
                    if msg:
                        await send_message_safe(app, user_id, msg)

        except Exception as e:
            log(f"FALLO SISTÉMICO trading_loop: {e}", "CRITICAL")
            await asyncio.sleep(ERROR_BACKOFF_SECONDS)

        await asyncio.sleep(SCAN_INTERVAL)
