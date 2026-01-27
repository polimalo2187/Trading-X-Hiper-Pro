# ============================================================
# TRADING LOOP – Trading X Hyper Pro
# PRODUCCIÓN REAL 24/7 — BANK GRADE (BLINDADO)
# ============================================================

import asyncio
import logging
import random
import time
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

# ✅ FIX: evita que al hacer deploy “arranque tirando órdenes” inmediatamente
STARTUP_GRACE_SECONDS = 20        # espera inicial antes de escanear/operar

# ✅ FIX: reparte llamadas (evita picos, evita todos al mismo símbolo al mismo tiempo)
USER_JITTER_MAX_SECONDS = 2.0     # jitter aleatorio por usuario antes de ejecutar su ciclo

# ============================================================
# STATE
# ============================================================

user_locks: dict[int, asyncio.Lock] = {}
telegram_blacklist: set[int] = set()

# timestamp de arranque del loop
_loop_started_at = 0.0

# ============================================================
# LOG HARDENING (evita leaks de token en httpx logs)
# ============================================================

def _harden_logging():
    try:
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("httpcore").setLevel(logging.WARNING)
    except Exception:
        pass

# ============================================================
# LOG
# ============================================================

def log(msg: str, level: str = "INFO"):
    try:
        safe_msg = str(msg).encode("utf-8", errors="replace").decode("utf-8", errors="replace")
    except Exception:
        safe_msg = str(msg)

    print(f"[LOOP {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}] {level} {safe_msg}")

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
        try:
            await app.bot.send_message(chat_id=user_id, text=text, parse_mode="Markdown")
        except Exception as inner_e:
            log(f"Error Telegram retry usuario {user_id}: {inner_e}", "ERROR")

    except Exception as e:
        log(f"Error Telegram usuario {user_id}: {e}", "ERROR")

# ============================================================
# EJECUCIÓN SEGURA POR USUARIO
# ============================================================

async def execute_user_cycle(user_id: int, semaphore: asyncio.Semaphore):
    if user_id not in user_locks:
        user_locks[user_id] = asyncio.Lock()

    lock = user_locks[user_id]

    # evita reentradas por usuario
    if lock.locked():
        log(f"Usuario {user_id} ya en ejecución — skip")
        return None

    async with semaphore:
        async with lock:
            # ✅ jitter para repartir carga (por usuario)
            try:
                if USER_JITTER_MAX_SECONDS > 0:
                    await asyncio.sleep(random.uniform(0.0, float(USER_JITTER_MAX_SECONDS)))
            except Exception:
                pass

            try:
                loop = asyncio.get_running_loop()

                result = await asyncio.wait_for(
                    loop.run_in_executor(None, execute_trade_cycle, user_id),
                    timeout=TRADE_TIMEOUT_SECONDS
                )

                return result

            except asyncio.TimeoutError:
                log(f"Timeout ejecución usuario {user_id}", "WARN")
                return None

            except Exception as e:
                log(f"Error crítico usuario {user_id}: {e}", "ERROR")
                return None

# ============================================================
# LOOP PRINCIPAL
# ============================================================

async def trading_loop(app: Application):
    global _loop_started_at

    _harden_logging()
    _loop_started_at = time.time()

    log("Trading Loop iniciado — BANK GRADE 24/7")
    log(f"Startup grace: {STARTUP_GRACE_SECONDS}s (no escanea/operará durante este tiempo)")

    semaphore = asyncio.Semaphore(MAX_CONCURRENT_USERS)

    while True:
        try:
            # ✅ FIX: no arrancar “a operar” inmediatamente tras deploy/restart
            if STARTUP_GRACE_SECONDS > 0:
                elapsed = time.time() - float(_loop_started_at or time.time())
                if elapsed < float(STARTUP_GRACE_SECONDS):
                    await asyncio.sleep(1.0)
                    continue

            users = get_all_users() or []
            log(f"Usuarios activos: {len(users)}")

            tasks = []
            task_user_ids = []

            for user in users:
                user_id = user.get("user_id")
                if not user_id:
                    continue

                try:
                    if not user_is_ready(user_id):
                        continue
                except Exception as e:
                    log(f"Error verificando readiness usuario {user_id}: {e}", "ERROR")
                    continue

                tasks.append(execute_user_cycle(int(user_id), semaphore))
                task_user_ids.append(int(user_id))

            if not tasks:
                await asyncio.sleep(max(1, int(SCAN_INTERVAL or 1)))
                continue

            results = await asyncio.gather(*tasks, return_exceptions=True)

            for user_id, result in zip(task_user_ids, results):
                if isinstance(result, Exception):
                    log(f"Error ciclo usuario {user_id}: {result}", "ERROR")
                    continue

                if not isinstance(result, dict):
                    continue

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
            await asyncio.sleep(float(ERROR_BACKOFF_SECONDS or 3))

        await asyncio.sleep(max(1, int(SCAN_INTERVAL or 1)))
