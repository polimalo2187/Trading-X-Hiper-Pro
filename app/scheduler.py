# ============================================================
# SCHEDULER – TRADING X HYPER PRO
# Ejecuta el motor de trading para cada usuario activo
# ============================================================

import threading
import time

from app.database import user_is_ready, users_col
from app.trading_engine import trading_loop
from app.config import SCAN_INTERVAL


# ============================================================
# CONTROL INTERNO DE HILOS POR USUARIO
# ============================================================

active_threads = {}  
# Esto evita que un usuario lance 2 operaciones simultáneas.


# ============================================================
# EJECUTA EL TRADING PARA UN USUARIO ESPECÍFICO
# ============================================================

def run_trading_for_user(user_id):
    try:
        if not user_is_ready(user_id):
            print(f"⚠️ Usuario {user_id} NO está listo. Saltando…")
            active_threads.pop(user_id, None)
            return

        print(f"🚀 Ejecutando ciclo de trading para usuario {user_id}")

        trading_loop(user_id)

    except Exception as e:
        print(f"❌ Error ejecutando trading para {user_id}: {e}")

    finally:
        # Libera el hilo para permitir futuros ciclos
        active_threads.pop(user_id, None)


# ============================================================
# OBTENER TODOS LOS USUARIOS ACTIVOS
# ============================================================

def get_active_users():
    """
    Devuelve todos los usuarios que tienen status = 'active'
    """
    users = users_col.find({"status": "active"})
    return [u["user_id"] for u in users]


# ============================================================
# SCHEDULER PRINCIPAL
# ============================================================

def scheduler_loop():
    """
    • Revisa cada X segundos (SCAN_INTERVAL desde config.py)
    • Identifica usuarios activos
    • Ejecuta trading para cada uno, sin hilos duplicados
    """

    print(f"⏱️ Scheduler iniciado. Intervalo: {SCAN_INTERVAL} segundos.")

    while True:
        try:
            active_users = get_active_users()

            if not active_users:
                print("⚪ No hay usuarios con trading activo.")

            else:
                print(f"🔎 Usuarios activos: {active_users}")

            # Para cada usuario activo lanzamos su ciclo
            for user_id in active_users:

                if user_id not in active_threads:
                    print(f"🟢 Lanzando hilo de trading para {user_id}")

                    th = threading.Thread(
                        target=run_trading_for_user,
                        args=(user_id,),
                        daemon=True
                    )

                    active_threads[user_id] = th
                    th.start()

        except Exception as e:
            print(f"❌ Error en scheduler: {e}")

        # Esperar el intervalo configurado
        time.sleep(SCAN_INTERVAL)


# ============================================================
# INICIAR SCHEDULER
# ============================================================

def start_scheduler():
    """
    Lanza el scheduler en segundo plano.
    Este archivo debe ser importado por bot.py ANTES de run_polling().
    """

    t = threading.Thread(target=scheduler_loop, daemon=True)
    t.start()
    print("✅ Scheduler iniciado correctamente en segundo plano.")
