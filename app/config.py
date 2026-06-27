from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Concurrency
    MAX_WORKERS: int = 20
    MAX_RETRIES: int = 5
    BASE_BACKOFF: float = 1.0  # seconds; doubles each retry

    # Mock inference endpoint
    MOCK_RATE_LIMIT_PCT: float = 0.20
    MOCK_INFERENCE_URL: str = "http://localhost:8000/mock/infer"

    # Storage
    DB_PATH: str = "batches.db"

    # Logging
    LOG_LEVEL: str = "INFO"

    # Input limits
    MAX_PROMPTS: int = 1000
    MAX_FILE_SIZE_MB: int = 10

    # Rate limiting (applied to POST /batches per client IP)
    RATE_LIMIT: str = "10/minute"


settings = Settings()
