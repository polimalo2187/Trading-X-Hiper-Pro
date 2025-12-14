import logging
from logging.handlers import RotatingFileHandler
import os

# ============================================================
# SISTEMA DE LOGS – TRADING X HYPER PRO
# ============================================================

LOG_DIR = "logs"

# Crear carpeta de logs si no existe
if not os.path.exists(LOG_DIR):
    os.makedirs(LOG_DIR)

# Ruta del archivo de log
LOG_FILE = os.path.join(LOG_DIR, "bot.log")

# Configuración del logger
logger = logging.getLogger("TradingX_HyperPro")
logger.setLevel(logging.INFO)

# Rotación de logs para evitar archivos enormes
handler = RotatingFileHandler(
    LOG_FILE,
    maxBytes=2_000_000,   # 2 MB por archivo
    backupCount=5         # Guarda 5 archivos rotados
)

# Formato profesional
formatter = logging.Formatter(
    "%(asctime)s - %(levelname)s - %(message)s"
)

handler.setFormatter(formatter)
logger.addHandler(handler)


# ============================================================
# FUNCIÓN DE ACCESO RÁPIDO
# ============================================================

def log(message: str, level: str = "info"):
    """
    Escribe logs en el archivo y consola.
    level = "info", "error", "warning"
    """

    if level == "info":
        logger.info(message)
    elif level == "warning":
        logger.warning(message)
    elif level == "error":
        logger.error(message)
    else:
        logger.info(message)

    print(message)
