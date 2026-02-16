"""Application configuration loaded from environment variables."""


from collections.abc import Sequence

from pydantic import Field, ValidationInfo, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment or .env file."""

    database_url: str = Field(..., alias="DATABASE_URL")
    db_pool_size: int = Field(default=5, alias="DB_POOL_SIZE")
    db_max_overflow: int = Field(default=10, alias="DB_MAX_OVERFLOW")
    auto_create_tables: bool = Field(default=True, alias="AUTO_CREATE_TABLES")

    redis_url: str = Field(default="redis://localhost:6379", alias="REDIS_URL")

    nvidia_api_key: str | None = Field(default=None, alias="NVIDIA_API_KEY")
    nvidia_base_url: str = Field(
        default="https://integrate.api.nvidia.com/v1",
        alias="NVIDIA_BASE_URL",
    )
    nvidia_llm_model: str = Field(
        default="nvidia/llama-3.3-nemotron-super-49b-v1.5",
        alias="NVIDIA_LLM_MODEL",
    )
    nvidia_embedding_model: str = Field(
        default="nvidia/nv-embedqa-e5-v5",
        alias="NVIDIA_EMBEDDING_MODEL",
    )

    debug: bool = Field(default=False, alias="DEBUG")
    host: str = Field(default="0.0.0.0", alias="HOST")
    port: int = Field(default=8000, alias="PORT")
    environment: str = Field(default="development", alias="ENVIRONMENT")
    cors_allowed_origins: list[str] = Field(
        default=["http://localhost:3000", "http://localhost:5173"],
        alias="CORS_ALLOWED_ORIGINS",
    )
    security_strict_mode: bool = Field(default=False, alias="SECURITY_STRICT_MODE")

    rate_limit_rpm: int = Field(default=120, alias="RATE_LIMIT_RPM")
    rate_limit_enabled: bool = Field(default=True, alias="RATE_LIMIT_ENABLED")
    rate_limit_ip_rpm: int = Field(default=240, alias="RATE_LIMIT_IP_RPM")
    rate_limit_user_rpm: int = Field(default=120, alias="RATE_LIMIT_USER_RPM")
    rate_limit_burst_multiplier: float = Field(
        default=1.0, alias="RATE_LIMIT_BURST_MULTIPLIER"
    )

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

    @field_validator("cors_allowed_origins", mode="before")
    @classmethod
    def validate_cors_allowed_origins(cls, v: str | Sequence[str]) -> list[str]:
        if isinstance(v, str):
            return [origin.strip() for origin in v.split(",") if origin.strip()]
        if isinstance(v, Sequence):
            return [str(origin).strip() for origin in v if str(origin).strip()]
        raise ValueError("CORS_ALLOWED_ORIGINS must be a comma-separated string or list")

    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"


settings = Settings()
