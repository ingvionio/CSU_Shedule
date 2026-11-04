"""Интеграция с платформой Moodle Института информационных технологий ЧелГУ (eu.iit.csu.ru).

Реализует:
1. Сессионную аутентификацию (обход CSRF logintoken, получение MoodleSession и sesskey).
2. Извлечение ФИО и числового moodle_id со страницы профиля.
3. Автоматическое определение академической группы студента по курсам через AJAX-шлюз.
4. Проверку валидности (core_session_touch) и прозрачное автопродление сессии по зашифрованному паролю.
5. Dev/Mock-режим при MOODLE_MOCK=True для локальной разработки и тестов без реального аккаунта.
6. Заготовки методов для Фазы 2 (календарь, дедлайны, оценки).
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import logging
import re
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup
import requests
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.crypto import decrypt_secret, encrypt_secret
from app.models import Group, User

logger = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)


class MoodleError(Exception):
    """Базовая ошибка взаимодействия с Moodle."""

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class MoodleAuthError(MoodleError):
    """Неверный логин или пароль, либо сессия завершена."""

    def __init__(self, message: str = "Неверный логин или пароль Moodle") -> None:
        super().__init__(message, status_code=401)


class MoodleGroupError(MoodleError):
    """Не удалось однозначно определить академическую группу."""

    def __init__(
        self,
        message: str = (
            "Не удалось определить академическую группу из профиля и курсов Moodle. "
            "Убедитесь, что вы зачислены на курсы текущего семестра, или обратитесь к методисту."
        ),
    ) -> None:
        super().__init__(message, status_code=422)


@dataclass
class MoodleSessionData:
    moodle_id: str
    moodle_username: str
    full_name: str
    group: Group
    cookies: dict[str, str]
    sesskey: str
    expires_at: datetime


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def normalize_group_key(name: str) -> str:
    """Удаляет пробелы, дефисы и приводит к нижнему регистру для гибкого сравнения."""
    return re.sub(r"[\s\-_—–]", "", name).lower()


class MoodleClient:
    """HTTP-клиент для работы с инсталляцией Moodle ЧелГУ."""

    def __init__(self, base_url: str | None = None, timeout: int = 12) -> None:
        self.base_url = (base_url or get_settings().moodle_base_url).rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": USER_AGENT,
                "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
            }
        )

    def fetch_logintoken(self) -> str:
        """Извлекает CSRF-токен logintoken со страницы входа /login/index.php."""
        url = f"{self.base_url}/login/index.php"
        try:
            resp = self.session.get(url, timeout=self.timeout)
            resp.raise_for_status()
        except requests.RequestException as exc:
            logger.error("Ошибка при запросе страницы входа Moodle: %s", exc)
            raise MoodleError("Не удалось связаться с сервером Moodle ЧелГУ", 502) from exc

        soup = BeautifulSoup(resp.text, "html.parser")
        token_input = soup.find("input", {"name": "logintoken"})
        if token_input and token_input.get("value"):
            return str(token_input["value"])

        match = re.search(r'name=["\']logintoken["\']\s+value=["\']([^"\']+)["\']', resp.text)
        if match:
            return match.group(1)

        raise MoodleError("Форма входа Moodle изменилась (logintoken не найден)", 502)

    def execute_login(self, username: str, password: str) -> tuple[str, str]:
        """Выполняет POST-запрос авторизации и возвращает (html_страницы, sesskey)."""
        logintoken = self.fetch_logintoken()
        login_url = f"{self.base_url}/login/index.php"
        payload = {
            "anchor": "",
            "logintoken": logintoken,
            "username": username,
            "password": password,
        }

        try:
            resp = self.session.post(login_url, data=payload, allow_redirects=True, timeout=self.timeout)
            resp.raise_for_status()
        except requests.RequestException as exc:
            logger.error("Ошибка при отправке учетных данных в Moodle: %s", exc)
            raise MoodleError("Сервер Moodle ЧелГУ временно недоступен", 502) from exc

        # Если нас перенаправило обратно на страницу входа — ошибка логина
        if "/login/index.php" in resp.url and "testsession" not in resp.url:
            soup = BeautifulSoup(resp.text, "html.parser")
            err_el = soup.find(class_=lambda c: c and ("alert-danger" in c or "loginerrors" in c))
            err_msg = err_el.get_text(strip=True) if err_el else "Неверный логин или пароль Moodle"
            raise MoodleAuthError(err_msg)

        sesskey = self._extract_sesskey(resp.text)
        return resp.text, sesskey

    def _extract_sesskey(self, html: str) -> str:
        match = re.search(r'"sesskey"\s*:\s*"([^"]+)"', html)
        if match:
            return match.group(1)
        logout_match = re.search(r'logout\.php\?sesskey=([a-zA-Z0-9]+)', html)
        if logout_match:
            return logout_match.group(1)
        return ""

    def get_profile_info(self) -> tuple[str, str, str]:
        """Запрашивает /user/profile.php и извлекает (full_name, moodle_id, sesskey)."""
        url = f"{self.base_url}/user/profile.php"
        try:
            resp = self.session.get(url, timeout=self.timeout)
            resp.raise_for_status()
        except requests.RequestException as exc:
            logger.error("Ошибка при получении профиля Moodle: %s", exc)
            raise MoodleError("Не удалось загрузить профиль Moodle", 502) from exc

        html = resp.text
        sesskey = self._extract_sesskey(html)
        soup = BeautifulSoup(html, "html.parser")

        # Извлечение moodle_id: из URL страницы после редиректа или из ссылок на странице
        moodle_id = ""
        id_match = re.search(r'[?&]id=(\d+)', resp.url)
        if id_match:
            moodle_id = id_match.group(1)
        else:
            profile_link = soup.find("a", href=re.compile(r'/user/profile\.php\?id=(\d+)'))
            if profile_link:
                m = re.search(r'[?&]id=(\d+)', profile_link["href"])
                if m:
                    moodle_id = m.group(1)

        # Извлечение ФИО: карточка Moove, аватар alt, тег title или .usertext
        full_name = ""
        card_h3 = soup.select_one(".card-profile h3")
        if card_h3:
            txt = _clean_text(card_h3.get_text())
            if txt and not any(w in txt.lower() for w in ["кабинет", "профиль", "dashboard"]):
                full_name = txt

        if not full_name:
            card_img = soup.select_one(".card-profile .userpicture img, .card-profile img.userpicture")
            if card_img and card_img.get("alt"):
                alt = _clean_text(card_img["alt"])
                if alt and not any(w in alt.lower() for w in ["картинка", "аватар", "user image", "picture"]):
                    full_name = alt

        if not full_name and soup.title and soup.title.string:
            title_text = _clean_text(soup.title.string)
            m = re.search(r'^([^|:]+?)\s*:\s*(?:публичный профиль|личный профиль|профиль|profile)', title_text, re.IGNORECASE)
            if m:
                full_name = m.group(1).strip()

        if not full_name:
            for sel in [".userbutton .usertext", ".usermenu .usertext", "#user-menu-toggle .usertext"]:
                el = soup.select_one(sel)
                if el:
                    txt = _clean_text(el.get_text())
                    if txt and txt.lower() not in ["вход", "войти", "выход", "выйти", "login", "logout"]:
                        full_name = txt
                        break

        if not full_name:
            raise MoodleError("Не удалось определить ФИО пользователя из профиля Moodle", 502)

        return full_name, moodle_id or "unknown", sesskey

    def call_ajax(self, sesskey: str, method_name: str, args: dict[str, Any]) -> Any:
        """Вызывает внутренний AJAX-метод Moodle (/lib/ajax/service.php)."""
        url = f"{self.base_url}/lib/ajax/service.php?sesskey={sesskey}&info={method_name}"
        payload = [{"index": 0, "methodname": method_name, "args": args}]
        try:
            resp = self.session.post(url, json=payload, timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, list) and len(data) > 0:
                item = data[0]
                if item.get("error") is True:
                    err = item.get("exception", {}).get("message", "Ошибка AJAX службы Moodle")
                    errcode = item.get("exception", {}).get("errorcode", "")
                    if errcode == "servicerequireslogin":
                        raise MoodleAuthError("Сеанс Moodle завершён или истёк")
                    raise MoodleError(f"Ошибка службы Moodle: {err}")
                return item.get("data")
            return None
        except (requests.RequestException, json.JSONDecodeError) as exc:
            logger.warning("Ошибка вызова AJAX метода %s: %s", method_name, exc)
            return None

    def get_enrolled_courses(self, sesskey: str) -> list[dict[str, Any]]:
        """Получает список зачисленных курсов пользователя через AJAX."""
        if not sesskey:
            return []
        data = self.call_ajax(
            sesskey,
            "core_course_get_enrolled_courses_by_timeline_classification",
            {"offset": 0, "limit": 50, "classification": "all", "sort": "fullname"},
        )
        if isinstance(data, dict) and "courses" in data:
            return data["courses"]
        return []

    def touch_session(self, sesskey: str) -> bool:
        """Проверяет активность сессии методом core_session_touch."""
        if not sesskey:
            return False
        try:
            url = f"{self.base_url}/lib/ajax/service.php?sesskey={sesskey}&info=core_session_touch"
            payload = [{"index": 0, "methodname": "core_session_touch", "args": {}}]
            resp = self.session.post(url, json=payload, timeout=6)
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, list) and len(data) > 0 and data[0].get("error") is False:
                    return True
        except Exception:
            pass
        return False


def match_student_group(
    courses: list[dict[str, Any]],
    profile_html: str,
    known_groups: list[Group],
) -> Group | None:
    """
    Автоматически сопоставляет студента с одной из академических групп из БД.
    Анализирует названия курсов и HTML профиля.
    """
    if not known_groups:
        return None

    # Собираем все текстовые фрагменты, где может упоминаться группа
    corpus_items: list[str] = []
    for c in courses:
        for key in ("fullname", "displayname", "shortname"):
            val = c.get(key)
            if val and isinstance(val, str):
                corpus_items.append(val)

    if profile_html:
        soup = BeautifulSoup(profile_html, "html.parser")
        # Очищаем от скриптов и стилей
        for s in soup(["script", "style"]):
            s.decompose()
        corpus_items.append(soup.get_text(" ", strip=True))

    full_text = " \n ".join(corpus_items)
    normalized_full_text = normalize_group_key(full_text)

    # Весовой подсчёт совпадений
    scores: Counter[int] = Counter()

    for group in known_groups:
        exact_name = group.name.strip()
        norm_group_name = normalize_group_key(exact_name)

        # 1. Прямое вхождение точного названия группы (например, "ИТ1-ПрИб-11" или "КБ-301")
        # Ищем совпадения с границами слов/символов
        pattern = re.compile(re.escape(exact_name), re.IGNORECASE)
        exact_matches = len(pattern.findall(full_text))
        if exact_matches > 0:
            scores[group.id] += exact_matches * 10

        # 2. Нормализованное вхождение без пробелов и дефисов
        if norm_group_name and norm_group_name in normalized_full_text:
            scores[group.id] += 5

        # 3. Совпадение по суффиксу/номеру направления (например, "ПрИб-11", "ПИб-21", "201")
        # Если в группе есть суффикс вроде "ПрИб-11"
        suffix_match = re.search(r"([А-ЯЁа-яё]+б?[-–—]?\d{2,3})$", exact_name)
        if suffix_match:
            suffix = suffix_match.group(1)
            norm_suffix = normalize_group_key(suffix)
            if norm_suffix in normalized_full_text:
                scores[group.id] += 3

    if not scores:
        return None

    best_group_id, best_score = scores.most_common(1)[0]
    if best_score > 0:
        return next((g for g in known_groups if g.id == best_group_id), None)

    return None


def authenticate_and_detect_student(
    db: Session,
    username: str,
    password: str,
) -> MoodleSessionData:
    """
    Проводит аутентификацию в Moodle ЧелГУ, получает профиль и автоматически
    определяет группу студента из базы.
    """
    settings = get_settings()
    now = datetime.now(timezone.utc)
    groups = list(db.scalars(select(Group)).all())

    # Dev / Mock режим для локальной разработки
    if settings.moodle_mock or username.startswith("mock_"):
        logger.info("Вход студента через Moodle MOCK режим: %s", username)
        if not groups:
            raise MoodleGroupError("В базе нет ни одной группы. Загрузите расписание перед входом.")
        # Берем первую доступную группу или ищем по имени в логине
        selected_group = groups[0]
        for g in groups:
            if normalize_group_key(g.name) in normalize_group_key(username):
                selected_group = g
                break

        return MoodleSessionData(
            moodle_id=f"mock_{hash(username) % 100000}",
            moodle_username=username,
            full_name=f"Студент {username.capitalize()}",
            group=selected_group,
            cookies={"MoodleSession": "mock_cookie_val"},
            sesskey="mock_sesskey_123",
            expires_at=now + timedelta(hours=settings.moodle_session_ttl_hours),
        )

    client = MoodleClient()
    profile_html, initial_sesskey = client.execute_login(username, password)
    full_name, moodle_id, profile_sesskey = client.get_profile_info()
    sesskey = profile_sesskey or initial_sesskey

    # Получаем курсы через AJAX для определения группы
    courses = client.get_enrolled_courses(sesskey)
    detected_group = match_student_group(courses, profile_html, groups)

    if detected_group is None:
        raise MoodleGroupError()

    expires_at = now + timedelta(hours=settings.moodle_session_ttl_hours)

    return MoodleSessionData(
        moodle_id=moodle_id,
        moodle_username=username,
        full_name=full_name,
        group=detected_group,
        cookies=client.session.cookies.get_dict(),
        sesskey=sesskey,
        expires_at=expires_at,
    )


def save_or_update_student(
    db: Session,
    moodle_data: MoodleSessionData,
    plain_password: str,
    device_key: str | None,
    ip: str | None,
) -> tuple[User, bool]:
    """
    Создает или обновляет запись пользователя User по данным Moodle.
    Шифрует пароль, сохраняет сессию и привязывает академическую группу.
    """
    now = datetime.now(timezone.utc)
    encrypted_pass = encrypt_secret(plain_password)
    cookie_str = json.dumps(moodle_data.cookies)

    # Ищем существующего пользователя по moodle_id или moodle_username
    user = db.scalar(
        select(User).where(
            (User.moodle_id == moodle_data.moodle_id)
            | (User.moodle_username == moodle_data.moodle_username)
        )
    )

    if user is None:
        # Также проверяем совпадение по ФИО, если пользователь был заведен до внедрения Moodle
        user = db.scalar(
            select(User).where(
                User.full_name == moodle_data.full_name,
                User.moodle_id.is_(None),
            )
        )

    group_changed = False

    if user is None:
        user = User(
            full_name=moodle_data.full_name,
            group_id=moodle_data.group.id,
            moodle_id=moodle_data.moodle_id,
            moodle_username=moodle_data.moodle_username,
            moodle_encrypted_password=encrypted_pass,
            moodle_session_cookie=cookie_str,
            moodle_sesskey=moodle_data.sesskey,
            moodle_session_expires_at=moodle_data.expires_at,
            moodle_auth_error=False,
            device_key_hash=device_key,
            created_at=now,
            last_seen_at=now,
        )
        db.add(user)
        group_changed = True
    else:
        group_changed = user.group_id != moodle_data.group.id
        user.full_name = moodle_data.full_name
        user.group_id = moodle_data.group.id
        user.moodle_id = moodle_data.moodle_id
        user.moodle_username = moodle_data.moodle_username
        user.moodle_encrypted_password = encrypted_pass
        user.moodle_session_cookie = cookie_str
        user.moodle_sesskey = moodle_data.sesskey
        user.moodle_session_expires_at = moodle_data.expires_at
        user.moodle_auth_error = False
        user.last_seen_at = now
        if device_key:
            user.device_key_hash = device_key

    db.flush()
    db.refresh(user, ["group"])

    if group_changed:
        from app.services.messages import attach_recent_messages

        attach_recent_messages(db, user, now)

    db.commit()
    return user, group_changed


def ensure_moodle_session(user: User, db: Session) -> requests.Session:
    """
    Возвращает авторизованную requests.Session для пользователя.
    Если кэшированная сессия истекла или недействительна, автоматически
    переавторизуется в Moodle с использованием зашифрованного пароля.
    """
    settings = get_settings()
    now = datetime.now(timezone.utc)

    # Проверяем кэшированную сессию
    if (
        user.moodle_session_expires_at
        and user.moodle_session_expires_at > now
        and user.moodle_session_cookie
        and user.moodle_sesskey
    ):
        try:
            cookies = json.loads(user.moodle_session_cookie)
            client = MoodleClient()
            client.session.cookies.update(cookies)
            if client.touch_session(user.moodle_sesskey):
                return client.session
        except Exception:
            pass

    # Сессия истекла — пробуем переавторизоваться
    if not user.moodle_username or not user.moodle_encrypted_password:
        user.moodle_auth_error = True
        db.commit()
        raise MoodleAuthError("Отсутствуют сохраненные учетные данные Moodle")

    try:
        plain_password = decrypt_secret(user.moodle_encrypted_password)
    except Exception as exc:
        user.moodle_auth_error = True
        db.commit()
        raise MoodleAuthError("Не удалось расшифровать пароль Moodle") from exc

    try:
        client = MoodleClient()
        _, sesskey = client.execute_login(user.moodle_username, plain_password)
        expires_at = now + timedelta(hours=settings.moodle_session_ttl_hours)

        user.moodle_session_cookie = json.dumps(client.session.cookies.get_dict())
        user.moodle_sesskey = sesskey
        user.moodle_session_expires_at = expires_at
        user.moodle_auth_error = False
        db.commit()
        return client.session
    except MoodleAuthError as exc:
        user.moodle_auth_error = True
        db.commit()
        raise exc
    except Exception as exc:
        logger.error("Ошибка автопродления сессии Moodle: %s", exc)
        raise MoodleError("Ошибка подключения к Moodle ЧелГУ", 502) from exc
