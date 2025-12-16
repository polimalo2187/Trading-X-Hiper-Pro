# ============================================================
# MAIN.PY – INICIO DEL BOT TRADING X HYPER PRO
# ============================================================

from app.bot import run_bot

if __name__ == "__main__":
    try:
        run_bot()
    except Exception as e:
        print("❌ ERROR INICIANDO EL BOT:", e)
