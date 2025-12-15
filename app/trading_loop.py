# ============================================================
# TRADING LOOP – TRADING X HYPER PRO
# Escaneo + Selección del mejor par + Operación Real 24/7
# ============================================================

import asyncio
from telegram import Bot

from app.database import user_is_ready, get_all_users
from app.market_scanner import get_best_symbol     # ← archivo 9
from app.trading_engine import execute_trade       # ← archivo 10
from app.config import SCAN_INTERVAL, TELEGRAM_BOT_TOKEN


# ============================================================
# INICIALIZAR BOT DE TELEGRAM
# ============================================================

bot = Bot(token=TELEGRAM_BOT_TOKEN)


# ============================================================
# LOOP PRINCIPAL DE TRADING 24/7
# ============================================================

async def trading_loop():
    print("🔄 Trading Loop iniciado — Operando 24/7 con el mejor par del mercado...")

    while True:
        try:
            # Obtener usuarios registrados
            users = get_all_users()

            # Escanear el mercado solo UNA VEZ por ciclo
            best = get_best_symbol()

            if not best:
                print("⚠ No se pudo obtener el mejor par en este ciclo.")
                await asyncio.sleep(SCAN_INTERVAL)
                continue

            symbol = best["symbol"]
            print(f"📌 Mejor par detectado: {symbol} (score: {best['score']})")

            # Procesar cada usuario
            for user in users:
                user_id = user["user_id"]

                if not user_is_ready(user_id):
                    continue  # saltar usuarios sin wallet/pk/capital/apagados

                # Ejecutar operación REAL
                result = execute_trade(user_id, symbol)

                # Notificar al usuario
                try:
                    await bot.send_message(chat_id=user_id, text=result)
                except Exception as e:
                    print(f"⚠ No pude enviar mensaje al usuario {user_id}: {e}")

        except Exception as error:
            print("❌ Error grave en trading_loop:", error)

        # Esperar el intervalo antes del próximo ciclo
        await asyncio.sleep(SCAN_INTERVAL)
