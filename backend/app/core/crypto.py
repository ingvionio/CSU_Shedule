"""AES-256-GCM для секретов Moodle с привязкой к пользователю и назначению."""

from __future__ import annotations

import base64
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import get_settings


def _get_encryption_key() -> bytes:
    return base64.b64decode(get_settings().moodle_encryption_key.get_secret_value(), validate=True)


def encrypt_secret(plain_text: str, context: str = "") -> str:
    nonce = os.urandom(12)
    ciphertext = AESGCM(_get_encryption_key()).encrypt(nonce, plain_text.encode("utf-8"), context.encode("utf-8"))
    return base64.b64encode(nonce + ciphertext).decode("ascii")


def decrypt_secret(encrypted_text: str, context: str = "") -> str:
    try:
        payload = base64.b64decode(encrypted_text, validate=True)
        if len(payload) < 28:
            raise ValueError("Слишком короткий шифротекст")
        plain = AESGCM(_get_encryption_key()).decrypt(payload[:12], payload[12:], context.encode("utf-8"))
        return plain.decode("utf-8")
    except Exception:
        raise ValueError("Ошибка расшифровки данных Moodle") from None
