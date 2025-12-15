# ============================================================
# TRADING LOOP – TRADING X HYPER PRO
# Sistema de operaciones automáticas 24/7 usando el mejor par
# ============================================================

import asyncio
from telegram import Bot

from app.database import (
    user_is_ready,
    get_all_users
)

from app.market_scanner import get_best_symbol
from app.trading_engine import execute_trade
from app.config import SCAN_INTERVAL, TELEGRAM_BOT_TOKEN


# ============================================================
# CONFIGURAR BOT DE TELEGRAM
# ============================================================

bot = Bot(token=TELEGRAM_BOT_TOKEN)


# ============================================================
# LOOP PRINCIPAL DE TRADING
# ============================================================

async def trading_loop():
    """
    Cada SCAN_INTERVAL segundos:
    1. Escanea TODO el mercado.
    2. Obtiene el MEJOR PAR.
    3. Ejecuta una operación REAL para cada usuario listo.
    4. Envía resultados por Telegram.
    """

    print("🔄 Trading loop iniciado (24/7)...")

    while True:
        try:
            # ----------------------------------------------------
            # 1. Obtener el MEJOR PAR DEL MERCADO
            # ----------------------------------------------------
            best = get_best_symbol()

            if not best:
                print("⚠ No se encontró un par adecuado en el escáner.")
                await asyncio.sleep(SCAN_INTERVAL)
                continue

            symbol = best["symbol"]
            score = best["score"]

            print(f"🔥 Mejor par detectado: {symbol} | Score: {score}")

            # ----------------------------------------------------
            # 2. Procesar usuarios
            # ----------------------------------------------------
            users = get_all_users()

            for user in users:
                user_id = user["user_id"]

                if not user_is_ready(user_id):
                    continue

                # Ejecutar operación REAL para el usuario
                result = execute_trade(user_id, symbol)

                # ----------------------------------------------------
                # 3. Enviar mensaje al usuario
                # ----------------------------------------------------
                try:
                    await bot.send_message(
                        chat_id=user_id,
                        text=f"📈 *Par seleccionado:* `{symbol}`\n{result}",
                        parse_mode="Markdown"
                    )
                except Exception as e:
                    print(f"⚠ No pude enviar mensaje a {user_id} | Error: {e}")

        except Exception as e:
            print("❌ Error general en trading_loop:", e)

        # --------------------------------------------------------
        # 4. Esperar próximo ciclo
        # --------------------------------------------------------
        await asyncio.sleep(SCAN_INTERVAL)
