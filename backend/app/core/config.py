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

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
