"""Application configuration loaded from environment variables."""

import os
from collections.abc import Sequence
from urllib.parse import urlparse

from pydantic import Field, ValidationInfo, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment or .env file."""

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
    nvidia_llm_timeout_seconds: float = Field(
        default=20.0,
        alias="NVIDIA_LLM_TIMEOUT_SECONDS",
    )
    nvidia_llm_max_tokens: int = Field(
        default=2000,
        alias="NVIDIA_LLM_MAX_TOKENS",
    )
    nvidia_embedding_model: str = Field(
        default="nvidia/nv-embedqa-e5-v5",
        alias="NVIDIA_EMBEDDING_MODEL",
    )

    debug: bool = Field(default=False, alias="DEBUG")
    host: str = Field(default="0.0.0.0", alias="HOST")
    port: int = Field(default=8000, alias="PORT")
    environment: str = Field(default="development", alias="ENVIRONMENT")
    database_url: str | None = Field(default=None, alias="DATABASE_URL")
    cors_allowed_origins: list[str] = Field(
        default=["http://localhost:3000", "http://localhost:5173"],
        alias="CORS_ALLOWED_ORIGINS",
    )
    security_strict_mode: bool = Field(default=False, alias="SECURITY_STRICT_MODE")
    allow_unauthenticated_dev_fallback: bool = Field(
        default=False,
        alias="ALLOW_UNAUTHENTICATED_DEV_FALLBACK",
    )

    rate_limit_rpm: int = Field(default=120, alias="RATE_LIMIT_RPM")
    rate_limit_enabled: bool = Field(default=True, alias="RATE_LIMIT_ENABLED")
    rate_limit_ip_rpm: int = Field(default=240, alias="RATE_LIMIT_IP_RPM")
    rate_limit_user_rpm: int = Field(default=120, alias="RATE_LIMIT_USER_RPM")
    rate_limit_burst_multiplier: float = Field(
        default=1.0, alias="RATE_LIMIT_BURST_MULTIPLIER"
    )
    max_request_body_bytes: int = Field(default=1_048_576, alias="MAX_REQUEST_BODY_BYTES")

    trace_retention_days: int = Field(default=7, alias="TRACE_RETENTION_DAYS")
    alert_scheduler_enabled: bool = Field(default=False, alias="ALERT_SCHEDULER_ENABLED")
    alert_scheduler_interval_seconds: int = Field(
        default=300,
        alias="ALERT_SCHEDULER_INTERVAL_SECONDS",
    )
    alert_scheduler_notify: bool = Field(default=False, alias="ALERT_SCHEDULER_NOTIFY")
    alert_notification_async_enabled: bool = Field(
        default=True,
        alias="ALERT_NOTIFICATION_ASYNC_ENABLED",
    )
    alert_notification_queue_maxsize: int = Field(
        default=1000,
        alias="ALERT_NOTIFICATION_QUEUE_MAXSIZE",
    )
    alert_notification_max_retries: int = Field(
        default=3,
        alias="ALERT_NOTIFICATION_MAX_RETRIES",
    )
    alert_notification_retry_backoff_seconds: float = Field(
        default=0.5,
        alias="ALERT_NOTIFICATION_RETRY_BACKOFF_SECONDS",
    )
    alert_dead_letter_replay_max_attempts: int = Field(
        default=3,
        alias="ALERT_DEAD_LETTER_REPLAY_MAX_ATTEMPTS",
    )
    alert_dead_letter_replay_cooldown_seconds: int = Field(
        default=60,
        alias="ALERT_DEAD_LETTER_REPLAY_COOLDOWN_SECONDS",
    )
    enforce_migration_head: bool = Field(default=False, alias="ENFORCE_MIGRATION_HEAD")
    alert_webhook_allow_private_targets: bool = Field(
        default=False,
        alias="ALERT_WEBHOOK_ALLOW_PRIVATE_TARGETS",
    )
    alert_secret_encryption_key: str | None = Field(
        default=None,
        alias="ALERT_SECRET_ENCRYPTION_KEY",
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @field_validator("database_url", mode="before")
    @classmethod
    def validate_database_url(cls, v: str | None, info: ValidationInfo) -> str:
        environment = info.data.get("environment", "development").lower()
        if not v:
            if environment == "production" and not os.getenv("SKIP_DATABASE_URL_REQUIRED"):
                raise ValueError("DATABASE_URL is required in production")
            return "sqlite:///./vizpath.db"

        parsed = urlparse(v)
        if not parsed.scheme:
            raise ValueError("DATABASE_URL must include a URL scheme")
        return v

    @field_validator("cors_allowed_origins", mode="before")
    @classmethod
    def validate_cors_allowed_origins(cls, v: str | Sequence[str]) -> list[str]:
        if isinstance(v, str):
            return [origin.strip() for origin in v.split(",") if origin.strip()]
        if isinstance(v, Sequence):
            return [str(origin).strip() for origin in v if str(origin).strip()]
        raise ValueError("CORS_ALLOWED_ORIGINS must be a comma-separated string or list")

    @field_validator("port", mode="after")
    @classmethod
    def validate_port(cls, v: int) -> int:
        if not 1 <= v <= 65535:
            raise ValueError("PORT must be between 1 and 65535")
        return v

    @field_validator(
        "db_pool_size",
        "db_max_overflow",
        "rate_limit_rpm",
        "rate_limit_ip_rpm",
        "rate_limit_user_rpm",
        "max_request_body_bytes",
        "alert_scheduler_interval_seconds",
        "alert_notification_queue_maxsize",
        "alert_notification_max_retries",
        "alert_dead_letter_replay_cooldown_seconds",
    )
    @classmethod
    def validate_positive_ints(cls, v: int, info: ValidationInfo) -> int:
        if v < 0:
            raise ValueError(f"{info.field_name} must be 0 or greater")
        return v

    @field_validator("trace_retention_days")
    @classmethod
    def validate_trace_retention_days(cls, v: int) -> int:
        if v < 1:
            raise ValueError("TRACE_RETENTION_DAYS must be at least 1")
        return v

    @field_validator("rate_limit_burst_multiplier")
    @classmethod
    def validate_rate_limit_burst_multiplier(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("RATE_LIMIT_BURST_MULTIPLIER must be greater than 0")
        return v

    @field_validator("alert_notification_retry_backoff_seconds")
    @classmethod
    def validate_retry_backoff_seconds(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("ALERT_NOTIFICATION_RETRY_BACKOFF_SECONDS must be greater than 0")
        return v

    @field_validator("nvidia_llm_timeout_seconds")
    @classmethod
    def validate_nvidia_llm_timeout_seconds(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("NVIDIA_LLM_TIMEOUT_SECONDS must be greater than 0")
        return v

    @field_validator("nvidia_llm_max_tokens")
    @classmethod
    def validate_nvidia_llm_max_tokens(cls, v: int) -> int:
        if v < 128:
            raise ValueError("NVIDIA_LLM_MAX_TOKENS must be at least 128")
        if v > 4096:
            raise ValueError("NVIDIA_LLM_MAX_TOKENS must be 4096 or less")
        return v

    @field_validator("alert_dead_letter_replay_max_attempts")
    @classmethod
    def validate_replay_max_attempts(cls, v: int) -> int:
        if v < 1:
            raise ValueError("ALERT_DEAD_LETTER_REPLAY_MAX_ATTEMPTS must be at least 1")
        return v

    @field_validator("redis_url")
    @classmethod
    def validate_redis_url(cls, v: str) -> str:
        if not v:
            return v
        parsed = urlparse(v)
        if not parsed.scheme:
            raise ValueError("REDIS_URL must include a URL scheme")
        if parsed.scheme not in {"redis", "rediss"}:
            raise ValueError("REDIS_URL must use redis or rediss scheme")
        return v

    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"


settings = Settings()
