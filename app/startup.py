# ============================================================
# STARTUP – INICIALIZACIÓN GLOBAL DEL SISTEMA
# ============================================================

import asyncio
from app.logger import logger
from app.database import client, db
from app.config import BOT_NAME
from app.security import run_integrity_check
from app.risk import validate_risk_parameters
from app.constants import VERSION

# ============================================================
# FUNCIÓN PRINCIPAL DE INICIO
# ============================================================

async def initialize_system():
    logger.info("🔄 Iniciando Trading X Hiper Pro...")
    logger.info(f"🤖 Bot: {BOT_NAME} – versión {VERSION}")

    # --------------------------------------------------------
    # Verificar conexión a MongoDB
    # --------------------------------------------------------
    try:
        db.list_collection_names()
        logger.info("🟢 MongoDB conectado correctamente.")
    except Exception as e:
        logger.error(f"❌ Error conectando a MongoDB: {e}")
        raise

    # --------------------------------------------------------
    # Seguridad: integridad de módulos
    # --------------------------------------------------------
    try:
        run_integrity_check()
        logger.info("🟢 Integridad del sistema verificada.")
    except Exception as e:
        logger.error(f"❌ Falla en chequeo de integridad: {e}")
        raise

    # --------------------------------------------------------
    # Validación de parámetros críticos de riesgo
    # --------------------------------------------------------
    try:
        validate_risk_parameters()
        logger.info("🟢 Parámetros de riesgo validados.")
    except Exception as e:
        logger.error(f"❌ Error en validación de riesgo: {e}")
        raise

    logger.info("🚀 Sistema inicializado completamente.")
    return True

# Wrapper síncrono
def startup():
    asyncio.run(initialize_system())
