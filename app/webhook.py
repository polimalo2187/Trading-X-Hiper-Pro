# ============================================================
# WEBHOOK – SERVIDOR PARA TELEGRAM
# ============================================================

from flask import Flask, request
from telegram import Update
from telegram.ext import Application
from app.bot import build_bot
from app.logger import logger
import os

app = Flask(__name__)
application: Application = build_bot()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # URL pública que dará Railway

# ============================================================
# ENDPOINT DE TELEGRAM
# ============================================================

@app.post(f"/{BOT_TOKEN}")
def telegram_webhook():
    try:
        data = request.get_json(force=True)
        update = Update.de_json(data, application.bot)
        application.update_queue.put_nowait(update)
    except Exception as e:
        logger.error(f"❌ Error procesando webhook: {e}")

    return "OK", 200

# ============================================================
# CONFIGURAR WEBHOOK
# ============================================================

async def set_webhook():
    await application.bot.set_webhook(WEBHOOK_URL + f"/{BOT_TOKEN}")
    logger.info(f"🟢 Webhook configurado en: {WEBHOOK_URL}/{BOT_TOKEN}")

# ============================================================
# INICIO DEL SERVIDOR
# ============================================================

def run_webhook():
    from app.startup import startup
    startup()

    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
