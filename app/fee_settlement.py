# ============================================================
# FEE SETTLEMENT – Trading X Hyper Pro
# Liquidación REAL del ADMIN (DIARIA – 12:00 AM HORA CUBA)
# ============================================================

import os
import time
import asyncio
from datetime import datetime, timezone

from app.database import (
    get_admin_daily_fees,
    reset_daily_fees,
    log_fee_payment,
)

# ============================================================
# VARIABLES DE ENTORNO (SEGURIDAD)
# ============================================================

ADMIN_WALLET_ADDRESS = os.getenv("ADMIN_WALLET_ADDRESS")
ADMIN_WALLET_PRIVATE_KEY = os.getenv("ADMIN_WALLET_PRIVATE_KEY")

if not ADMIN_WALLET_ADDRESS or not ADMIN_WALLET_PRIVATE_KEY:
    raise RuntimeError("❌ Variables de entorno del ADMIN no configuradas.")

# ============================================================
# UTILIDADES DE TIEMPO
# ============================================================

def now_utc():
    return datetime.now(timezone.utc)

def is_cuba_midnight(now: datetime) -> bool:
    """
    Retorna True si es exactamente 12:00 AM (00:00) hora Cuba.
    Cuba = UTC-4 (sin DST actualmente).
    """
    cuba_hour = (now.hour - 4) % 24
    return cuba_hour == 0 and now.minute == 0

# ============================================================
# TRANSFERENCIA ON-CHAIN REAL (HOOK)
# ============================================================

def send_onchain_payment(to_address: str, amount: float) -> str:
    """
    Ejecuta UNA transferencia real on-chain.
    Retorna tx_hash si es exitosa.
    """
    # TODO:
    # - Integrar cliente real del exchange / blockchain
    # - Firmar con ADMIN_WALLET_PRIVATE_KEY
    # - Confirmar transacción
    # - Retornar tx_hash real

    print(f"💸 Enviando {amount} USDC a {to_address}")
    time.sleep(0.5)  # latencia simulada
    return "0xADMIN_DAILY_TX_HASH"

# ============================================================
# LIQUIDACIÓN DIARIA DEL ADMIN
# ============================================================

async def settle_admin_daily():
    """
    Liquida TODA la fee diaria acumulada del admin
    en UNA sola transacción (12:00 AM Cuba).
    """
    total = get_admin_daily_fees()

    if total <= 0:
        print("ℹ️ No hay fee diaria del admin para liquidar.")
        return

    print(f"🏦 Liquidando fee diaria del ADMIN: {total} USDC")

    tx_hash = send_onchain_payment(
        ADMIN_WALLET_ADDRESS,
        total
    )

    log_fee_payment(
        payment_type="admin_daily",
        amount=total
    )

    reset_daily_fees()

    print(f"✅ Fee diaria del admin pagada. TX: {tx_hash}")

# ============================================================
# LOOP PRINCIPAL (INDEPENDIENTE DEL TRADING)
# ============================================================

async def run_settlement_loop():
    """
    Loop independiente.
    Revisa el reloj y liquida a las 12:00 AM Cuba.
    """
    print("🔁 Fee Settlement (ADMIN) iniciado – horario fijo 12:00 AM Cuba")

    last_run_date = None  # evita doble ejecución el mismo día

    while True:
        try:
            now = now_utc()

            if is_cuba_midnight(now):
                today_cuba = (now.hour - 4) % 24

                if last_run_date != now.date():
                    await settle_admin_daily()
                    last_run_date = now.date()

        except Exception as e:
            print("❌ Error en fee_settlement:", e)

        # revisa cada 60 segundos
        await asyncio.sleep(60)

# ============================================================
# ENTRYPOINT
# ============================================================

if __name__ == "__main__":
    asyncio.run(run_settlement_loop())
