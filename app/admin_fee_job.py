# ============================================================
# ADMIN FEE JOB – Trading X Hyper Pro
# Pago diario ADMIN (12:00 AM) – A2 Anti-Doble-Pago
# ============================================================

from datetime import datetime
import pytz

from app.database import (
    get_admin_daily_fees,
    reset_daily_fees,
    payment_exists,
    log_fee_payment,
)

from app.wallet_manager import pay_admin_fee


# ============================================================
# CONFIGURACIÓN HORARIA (CUBA)
# ============================================================

CUBA_TZ = pytz.timezone("America/Havana")


# ============================================================
# JOB PRINCIPAL
# ============================================================

def run_admin_fee_job():
    """
    Ejecuta el pago diario del ADMIN con protección A2.
    Se debe ejecutar EXACTAMENTE a las 12:00 AM (Cuba).
    """

    now_cuba = datetime.now(CUBA_TZ)
    period_id = f"ADMIN_{now_cuba.strftime('%Y-%m-%d')}"

    print(f"🕛 Ejecutando ADMIN FEE JOB – Periodo {period_id}")

    # ========================================================
    # A2 – ANTI DOBLE PAGO
    # ========================================================

    if payment_exists("ADMIN", period_id):
        print("⚠ Pago ADMIN ya ejecutado. Abortando.")
        return

    # ========================================================
    # OBTENER TOTAL ACUMULADO DEL DÍA
    # ========================================================

    total_fee = get_admin_daily_fees()

    if total_fee <= 0:
        print("ℹ No hay fee ADMIN para pagar hoy.")
        return

    # ========================================================
    # PAGO REAL ON-CHAIN
    # ========================================================

    tx_hash = pay_admin_fee(total_fee, currency="USDC")

    if not tx_hash:
        print("⚠ No se ejecutó pago (amount=0).")
        return

    # ========================================================
    # REGISTRO A2 (AUDITORÍA)
    # ========================================================

    log_fee_payment(
        payment_type="ADMIN",
        period_id=period_id,
        tx_hash=tx_hash,
        amount=total_fee
    )

    # ========================================================
    # RESET DIARIO
    # ========================================================

    reset_daily_fees()

    print(f"✅ ADMIN FEE PAGADO | {total_fee} USDC | TX {tx_hash}")
