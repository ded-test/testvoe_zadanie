from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://app:app@localhost:5433/app"
    webhook_secret: str = "dev-shared-secret"

    # сколько ждем колбек от провайдера потом сторож делает попытку неудачной
    provider_timeout_seconds: int = 60

    # таймаут самого POST /tasks.
    dispatch_timeout_seconds: float = 10.0

    watchdog_enabled: bool = True
    watchdog_interval_seconds: float = 2.0

    max_active_tasks: int = 3

    alpha_url: str = "http://localhost:8001"
    beta_url: str = "http://localhost:8002"
    webhook_base_url: str = "http://localhost:8000"
    # адрес самого сервиса для тестов: localhost на хосте, service внутри compose
    service_base_url: str = "http://localhost:8000"

    def provider_url(self, name: str) -> str:
        # имя ноги в каталоге должно совпадать с ключом
        mapping = {"alpha": self.alpha_url, "beta": self.beta_url}
        try:
            return mapping[name]
        except KeyError as exc:
            raise RuntimeError(f"неизвестный провайдер {name!r}") from exc


settings = Settings()
