from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql://txn_user:txn_pass@db:5432/txn_db"
    REDIS_URL: str = "redis://redis:6379/0"
    GEMINI_API_KEY: str = ""
    UPLOAD_DIR: str = "/app/uploads"

    POSTGRES_USER: str = "txn_user"
    POSTGRES_PASSWORD: str = "txn_pass"
    POSTGRES_DB: str = "txn_db"

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
