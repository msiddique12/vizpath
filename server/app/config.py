"""Application configuration loaded from environment variables."""

from typing import Optional

from pydantic import Field, field_validator, ValidationInfo
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment or .env file."""

    database_url: str = Field(..., alias="DATABASE_URL")
    db_pool_size: int = Field(default=5, alias="DB_POOL_SIZE")
    db_max_overflow: int = Field(default=10, alias="DB_MAX_OVERFLOW")
    auto_create_tables: bool = Field(default=True, alias="AUTO_CREATE_TABLES")

    redis_url: str = Field(default="redis://localhost:6379", alias="REDIS_URL")

    openai_api_key: Optional[str] = Field(default=None, alias="OPENAI_API_KEY")

    debug: bool = Field(default=False, alias="DEBUG")
    host: str = Field(default="0.0.0.0", alias="HOST")
    port: int = Field(default=8000, alias="PORT")
    environment: str = Field(default="development", alias="ENVIRONMENT")

    rate_limit_rpm: int = Field(default=120, alias="RATE_LIMIT_RPM")

    trace_retention_days: int = Field(default=7, alias="TRACE_RETENTION_DAYS")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @field_validator("database_url", mode="before")
    @classmethod
    def validate_database_url(cls, v: str, info: ValidationInfo) -> str:
        if not v:
            raise ValueError("DATABASE_URL is required")
        return v

    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"


settings = Settings()
