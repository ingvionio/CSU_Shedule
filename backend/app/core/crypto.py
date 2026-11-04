"""Шифрование и дешифрование конфиденциальных данных (паролей Moodle).

Использует AES-256-GCM с уникальным nonce (12 байт) на каждую операцию.
Ключ шифрования берется из MOODLE_ENCRYPTION_KEY либо детерминированно
выводится из JWT_SECRET при отсутствии отдельного ключа.
"""

from __future__ import annotations

import base64
import hashlib
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import get_settings


def _get_encryption_key() -> bytes:
    settings = get_settings()
    custom_key = settings.moodle_encryption_key.strip()
    if custom_key:
        # Если передан base64, пробуем декодировать
        try:
            raw = base64.b64decode(custom_key)
            if len(raw) == 32:
                return raw
        except Exception:
            pass
        # Иначе хэшируем SHA-256 до 32 байт
        return hashlib.sha256(custom_key.encode("utf-8")).digest()

    # Деривация из jwt_secret с солью
    salt = b"csu_shedule_moodle_secret_salt_v1"
    return hashlib.sha256(settings.jwt_secret.encode("utf-8") + salt).digest()


def encrypt_secret(plain_text: str) -> str:
    """Шифрует строку с помощью AES-256-GCM и возвращает urlsafe base64."""
    if not plain_text:
        return ""
    key = _get_encryption_key()
    aesgcm = AESGCM(key)
    nonce = os.urandom(12)
    ciphertext = aesgcm.encrypt(nonce, plain_text.encode("utf-8"), None)
    payload = nonce + ciphertext
    return base64.urlsafe_b64encode(payload).decode("ascii")


def decrypt_secret(encrypted_text: str) -> str:
    """Расшифровывает строку, зашифрованную с помощью encrypt_secret."""
    if not encrypted_text:
        return ""
    try:
        payload = base64.urlsafe_b64decode(encrypted_text.encode("ascii"))
        if len(payload) < 28:  # 12 nonce + 16 auth tag
            raise ValueError("Слишком короткий шифротекст")
        nonce = payload[:12]
        ciphertext = payload[12:]
        key = _get_encryption_key()
        aesgcm = AESGCM(key)
        decrypted = aesgcm.decrypt(nonce, ciphertext, None)
        return decrypted.decode("utf-8")
    except Exception as exc:
        raise ValueError("Ошибка расшифровки данных Moodle") from exc
