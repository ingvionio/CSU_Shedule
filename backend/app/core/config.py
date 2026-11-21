import base64
from functools import lru_cache

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL, make_url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore", hide_input_in_errors=True)

    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/csu_schedule"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    api_prefix: str = "/api/v1"

    # Вход администратора: один логин и пароль из окружения, выдаётся JWT.
    # Пустой пароль — вход в админку выключен.
    admin_login: str = "admin"
    admin_password: str = ""
    jwt_secret: str = "change-me"
    jwt_ttl_hours: int = 12

    # ЛК продукта (/statistic): свой логин и пароль, не как у методиста.
    # Пустой пароль — вход выключен.
    product_login: str = "product"
    product_password: str = ""
    # Событий статистики с одного устройства за час; лишние молча отбрасываются.
    product_events_limit_per_hour: int = 120

    # Почта для обращений (SMTP Яндекса). Пустой SMTP_USER — письма не
    # отправляются, а пишутся в лог; обращения при этом сохраняются.
    smtp_host: str = "smtp.yandex.ru"
    smtp_port: int = 465
    smtp_user: str = ""
    smtp_password: str = ""
    # Яндекс разрешает отправлять только от адреса ящика.
    smtp_from_name: str = "Расписание ИИТ"
    # Ссылка на приложение в письмах; пустая — без ссылки.
    public_app_url: str = ""

    # Лимиты обращений за час: с одного устройства и с одного IP. Лимит на IP
    # мягче — студенты в Wi-Fi вуза выходят в сеть с общего адреса.
    feedback_rate_limit_per_hour: int = 5
    feedback_ip_rate_limit_per_hour: int = 40

    # Сообщения группе/курсу/потоку за столько дней достаются и тем,
    # кто зарегистрировался или сменил группу после отправки.
    messages_late_join_days: int = 14
    # Не чаще одного напоминания по сообщению за столько часов.
    remind_cooldown_hours: int = 6

    # Web Push (VAPID). Ключи: python -m app.cli generate-vapid. Пустые — push
    # выключен, сообщения всё равно видны в приложении.
    vapid_public_key: str = ""
    vapid_private_key: str = ""
    # Контакт для push-сервисов: mailto:... или https://...
    vapid_subject: str = "mailto:admin@example.com"

    # Путь к JSON сервисного аккаунта Firebase; пусто — FCM выключен.
    fcm_credentials_file: str = ""

    # Worker: опрос пустой очереди, размер пачки и параллельность push.
    schedule_change_delay_seconds: int = Field(default=120, ge=0)
    worker_poll_seconds: float = Field(default=2, gt=0)
    push_batch_size: int = Field(default=100, gt=0)
    push_concurrency: int = Field(default=8, gt=0)
    push_max_attempts: int = Field(default=5, ge=1)

    # Интеграция с Moodle ИИТ ЧелГУ (eu.iit.csu.ru)
    moodle_base_url: str = "https://eu.iit.csu.ru"
    moodle_encryption_key: SecretStr
    moodle_mock: bool = False

    @field_validator("moodle_encryption_key")
    @classmethod
    def validate_moodle_key(cls, value: SecretStr) -> SecretStr:
        try:
            decoded = base64.b64decode(value.get_secret_value(), validate=True)
        except ValueError:
            raise ValueError("MOODLE_ENCRYPTION_KEY должен быть ключом из 32 случайных байт в base64") from None
        if len(decoded) != 32:
            raise ValueError("MOODLE_ENCRYPTION_KEY должен содержать ровно 32 байта")
        return value

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


def database_url() -> URL:
    url = make_url(get_settings().database_url)
    if url.drivername in {"sqlite", "sqlite+pysqlite"}:
        return url.set(drivername="sqlite+aiosqlite")
    if url.drivername == "postgresql":
        return url.set(drivername="postgresql+psycopg")
    return url
