# ============================================================
# security.py
# Sistema de seguridad para Trading X Hiper Pro
# Manejo de llaves, sanitización de datos y protección básica
# ============================================================

import hashlib
import hmac
import time
import re


# ------------------------------------------------------------
# HASH SEGURO PARA DATOS INTERNOS
# ------------------------------------------------------------
def secure_hash(value: str) -> str:
    """
    Genera un hash SHA256 seguro para contraseñas internas,
    validaciones o tokens temporales.
    """
    return hashlib.sha256(value.encode()).hexdigest()


# ------------------------------------------------------------
# SANITIZACIÓN DE DATOS ENTRANTES
# ------------------------------------------------------------
def clean_input(text: str) -> str:
    """
    Elimina caracteres peligrosos usados en ataques de inyección.
    """
    if not isinstance(text, str):
        return ""

    text = re.sub(r"[<>;{}\[\]\(\)]", "", text)  # elimina símbolos peligrosos
    return text.strip()


# ------------------------------------------------------------
# FIRMA HMAC PARA ENVÍOS A API PRIVADAS (si se usa futuro)
# ------------------------------------------------------------
def sign_payload(secret: str, message: str) -> str:
    """
    Firma un mensaje usando HMAC-SHA256 (útil para APIs privadas).
    """
    return hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()


# ------------------------------------------------------------
# TOKEN TEMPORAL PARA USOS INTERNOS DEL BOT
# ------------------------------------------------------------
def generate_temp_token(user_id: int) -> str:
    """
    Genera un token único basado en user_id y tiempo.
    Sirve para verificaciones internas del bot.
    """
    raw = f"{user_id}-{time.time()}"
    return secure_hash(raw)


# ------------------------------------------------------------
# LIMPIAR MONTO Y VALIDAR QUE NO TENGA CÓDIGO
# ------------------------------------------------------------
def sanitize_amount(value: str):
    """
    Limpia valores numéricos para evitar comandos ocultos.
    """
    value = clean_input(value)

    try:
        return float(value)
    except:
        return None


# ------------------------------------------------------------
# VALIDAR QUE UN TEXTO SEA SEGURO PARA GUARDAR EN BD
# ------------------------------------------------------------
def is_safe_text(text: str) -> bool:
    """
    Verifica que un texto no contenga inyecciones sospechosas.
    """
    if not text:
        return False

    prohibited = ["DROP", "DELETE", "UPDATE", "INSERT", "--", ";", "/*", "*/"]

    upper = text.upper()

    return not any(p in upper for p in prohibited)
