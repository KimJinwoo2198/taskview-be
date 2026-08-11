from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    taskview_ai_url: str = "http://127.0.0.1:8100"
    taskview_database_url: str = "postgresql://taskview:taskview@127.0.0.1:54329/taskview"
    taskview_be_fake_ai: bool = False

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
