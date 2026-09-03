from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0


def get_settings() -> Settings:
    s = Settings()
    return s


settings = get_settings()
