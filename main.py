# ============================================================
# MAIN.PY – INICIO GENERAL DEL SISTEMA TRADING X HIPER PRO
# Sistema 24/7 – Bot Telegram + Trading Loop en paralelo
# ============================================================

import asyncio

from app.bot import run_bot
from app.trading_loop import trading_loop


async def main():
    # Ejecutamos bot y trading loop al mismo tiempo
    await asyncio.gather(
        run_bot(),
        trading_loop()
    )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        print("❌ ERROR CRÍTICO AL INICIAR EL SISTEMA:", e)
