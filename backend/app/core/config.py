from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/csu_schedule"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    api_prefix: str = "/api/v1"

    # Вход администратора: один логин и пароль из окружения, выдаётся JWT.
    # Пустой пароль — вход в админку выключен.
    admin_login: str = "admin"
    admin_password: str = ""
    jwt_secret: str = "change-me"
    jwt_ttl_hours: int = 12

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

    # Студенты: профиль ФИО + группа. Токен живёт долго; истёк — фронт
    # регистрируется заново тем же ключом устройства и получает того же пользователя.
    student_jwt_ttl_hours: int = 24 * 60
    # Новых профилей с одного IP за час (общий Wi-Fi вуза — лимит мягкий).
    student_register_ip_limit_per_hour: int = 60
    # Сообщения группе/курсу/потоку за столько дней достаются и тем,
    # кто зарегистрировался или сменил группу после отправки.
    messages_late_join_days: int = 14
    # Не чаще одного напоминания по сообщению за столько часов.
    remind_cooldown_hours: int = 6

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
