"""FCM HTTP v1; OAuth-кэш общий для потоков worker'а."""

from __future__ import annotations

from functools import partial
from threading import Lock
from typing import TYPE_CHECKING

import requests

from app.core.config import get_settings
from app.services.push import SendResult, SubscriptionData

if TYPE_CHECKING:
    from google.oauth2.service_account import Credentials

SCOPE = "https://www.googleapis.com/auth/firebase.messaging"
# oauth2.googleapis.com из России отвечает медленно (~20 с); токен живёт час и кэшируется.
OAUTH_TIMEOUT = 45
_credentials: Credentials | None = None
_credentials_file: str | None = None
_lock = Lock()


def _load_credentials(filename: str) -> Credentials:
    from google.oauth2.service_account import Credentials

    return Credentials.from_service_account_file(filename, scopes=[SCOPE])


def _refresh_credentials(credentials: Credentials) -> None:
    from google.auth.transport.requests import Request

    credentials.refresh(partial(Request(), timeout=OAUTH_TIMEOUT))


def _access_token() -> tuple[str, str]:
    global _credentials, _credentials_file

    filename = get_settings().fcm_credentials_file
    with _lock:
        if _credentials is None or _credentials_file != filename:
            _credentials = _load_credentials(filename)
            _credentials_file = filename
        if not _credentials.project_id:
            raise ValueError("В ключе Firebase отсутствует project_id")
        if not _credentials.valid:
            _refresh_credentials(_credentials)
        if not _credentials.token:
            raise ValueError("Не удалось получить OAuth-токен Firebase")
        return _credentials.project_id, _credentials.token


def _invalidate_token(token: str) -> None:
    with _lock:
        # Параллельная отправка могла уже обновить токен после такого же 401.
        if _credentials is not None and _credentials.token == token:
            _credentials.token = None
            _credentials.expiry = None


def _error(response: requests.Response) -> tuple[str | None, str]:
    code = None
    message = "Ошибка доставки"
    try:
        error = response.json().get("error", {})
        message = error.get("message", message)
        for detail in error.get("details", []):
            if detail.get("@type") == "type.googleapis.com/google.firebase.fcm.v1.FcmError":
                code = detail.get("errorCode")
    except (ValueError, AttributeError, TypeError):
        pass
    return code, f"FCM HTTP {response.status_code} {code or ''}: {message}"[:500]


def send_one(subscription: SubscriptionData, data: dict) -> SendResult:
    body = {"message": {
        "token": subscription.endpoint,
        "notification": {"title": data["title"], "body": data["body"]},
        "data": {key: str(data[key]) for key in ("message_id", "url", "importance")},
        "android": {
            "priority": "HIGH", "ttl": "86400s",
            "notification": {"channel_id": "messages", "tag": f"message-{data['message_id']}"},
        },
    }}
    try:
        # После 401 один раз пробуем свежий OAuth-токен, затем действует backoff worker'а.
        for attempt in range(2):
            project_id, token = _access_token()
            response = requests.post(
                f"https://fcm.googleapis.com/v1/projects/{project_id}/messages:send",
                headers={"Authorization": f"Bearer {token}"}, json=body, timeout=10,
            )
            if response.status_code == 200:
                return SendResult("sent")
            code, error = _error(response)
            if response.status_code == 401:
                _invalidate_token(token)
                if attempt == 0:
                    continue
                return SendResult("retry", error)
            if response.status_code == 404 or code == "UNREGISTERED" or (
                response.status_code == 403 and code == "SENDER_ID_MISMATCH"
            ):
                return SendResult("gone", error)
            if response.status_code == 429 or response.status_code >= 500:
                return SendResult("retry", error)
            return SendResult("failed", error)
    except (OSError, requests.RequestException) as error:
        return SendResult("retry", str(error)[:500])
    except (ValueError, TypeError, ImportError) as error:
        return SendResult("failed", str(error)[:500])
    except Exception as error:
        # Ошибки OAuth, включая недоступность сервиса токенов, повторяет worker.
        return SendResult("retry", str(error)[:500])
    return SendResult("retry", "Не удалось отправить FCM")
