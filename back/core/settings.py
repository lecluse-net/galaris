from pathlib import Path
from typing import ClassVar, Literal, Self

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL


def _read_app_version() -> str:
    """Read the Git reference baked into the backend image."""
    try:
        version = Path("/opt/galaris-version").read_text(encoding="utf-8").strip()
    except OSError:
        return "development"
    return version or "unknown"


class Settings(BaseSettings):
    """Typed bootstrap configuration loaded from the environment.

    Only values required before PostgreSQL is available, or tied to deployment
    infrastructure, belong here. Administrable runtime configuration lives in
    ``core.params.runtime_settings`` and is sourced exclusively from PostgreSQL.
    """

    GALARIS_SKILLS_ROOT: ClassVar[str] = "/data/skills"
    GALARIS_MEMORY_ROOT: ClassVar[str] = "/data/memory"
    GALARIS_INTERNAL_MESSENGER_ROOT: ClassVar[str] = "/data/chat"
    GALARIS_THUMBNAIL_ROOT: ClassVar[str] = "/data/thumbnails"

    # Isolated browser executor infrastructure. Operation preferences are sent
    # with each authenticated request by app.browser.
    BROWSER_EXECUTOR_URL: ClassVar[str] = "http://browser-executor:3000"

    # Browser-to-backend WebRTC crosses the container and client NAT boundaries.
    # TURN REST credentials are minted per authenticated user; the shared secret
    # never leaves the backend.
    WEBRTC_TURN_MODE: Literal["embedded", "external", "disabled"] = Field(
        default="embedded"
    )
    WEBRTC_ICE_URLS: str = Field(default="")
    WEBRTC_TURN_HOST: str = Field(default="auto")
    WEBRTC_TURN_PORT: int = Field(default=3_479, ge=1, le=65_535)
    WEBRTC_TURN_RELAY_IP: str = Field(default="auto")
    WEBRTC_TURN_RELAY_IP_RESOLVED: str = Field(default="")
    WEBRTC_TURN_SHARED_SECRET: SecretStr = Field(default=SecretStr(""))
    WEBRTC_TURN_TTL_SECONDS: int = Field(default=3_600, ge=60, le=86_400)

    # Common apps settings
    APP_NAME: str = Field(default="galaris")
    APP_VERSION: ClassVar[str] = _read_app_version()
    APP_HOST: str = Field(default="http://localhost:8484")
    # Preserve the deployment label; only the exact value "dev" relaxes behavior.
    APP_ENV: str = Field(default="prod")

    LOG_LEVEL: Literal[
        "TRACE", "DEBUG", "INFO", "SUCCESS", "WARNING", "ERROR", "CRITICAL"
    ] = "INFO"

    POSTGRES_USER: str = "galaris"
    POSTGRES_PASSWORD: str = Field(default="app_secret", min_length=1)
    POSTGRES_HOST: str = "postgres"
    POSTGRES_PORT: int = Field(default=5432, ge=1, le=65535)
    POSTGRES_DB: str = "galaris"

    # Keep the SQLAlchemy pool comfortably above scheduler concurrency because
    # active agent runs retain a connection alongside API/SSE/WebSocket traffic.
    # pre_ping and recycle handle stale remote-database connections.
    DB_POOL_SIZE: int = Field(default=20, ge=1)
    DB_MAX_OVERFLOW: int = Field(default=20, ge=0)
    DB_POOL_TIMEOUT: float = Field(default=30.0, ge=1.0)
    DB_POOL_RECYCLE: int = Field(default=1800, ge=-1)
    DB_POOL_PRE_PING: bool = Field(default=True)
    DB_STATEMENT_TIMEOUT_MS: int = Field(default=120_000, ge=1_000)
    DB_LOCK_TIMEOUT_MS: int = Field(default=10_000, ge=100)
    DBADMIN_COMMAND_TIMEOUT_SECONDS: float = Field(default=600, ge=1, le=86_400)

    ALGORITHM: ClassVar[Literal["HS256"]] = "HS256"
    AUTH_TOKEN_EXPIRE_MINUTES: ClassVar[int] = 30
    AUTH_REFRESH_TOKEN_EXPIRE_DAYS: ClassVar[int] = 30
    AUTH_REFRESH_TOKEN_REUSE_GRACE_SECONDS: ClassVar[int] = 10
    AUTH_REFRESH_COOKIE_NAME: ClassVar[str] = "galaris_refresh"
    AUTH_LOGIN_LOCKOUT_THRESHOLD: ClassVar[int] = 5
    AUTH_LOGIN_LOCKOUT_BASE_SECONDS: ClassVar[int] = 30
    AUTH_LOGIN_LOCKOUT_MAX_SECONDS: ClassVar[int] = 3_600
    ENCRYPTION_MASTER_KEY: str = ""
    BACK_ALLOWED_HOSTS: str = Field(default="")

    @model_validator(mode="after")
    def validate_production_secrets(self) -> Self:
        if not self.is_dev:
            for name in ("ENCRYPTION_MASTER_KEY",):
                if len(getattr(self, name).strip()) < 32:
                    raise ValueError(f"{name} must contain at least 32 characters in {self.APP_ENV}")
        return self

    @property
    def DATABASE_URL(self) -> str:
        """Build the database URL."""
        return URL.create(
            "postgresql+asyncpg", username=self.POSTGRES_USER,
            password=self.POSTGRES_PASSWORD, host=self.POSTGRES_HOST,
            port=self.POSTGRES_PORT, database=self.POSTGRES_DB,
        ).render_as_string(hide_password=False)

    @property
    def APP_API_URL(self) -> str:
        """Return the public API URL reachable by external runtimes."""
        app_host = self.APP_HOST.strip().rstrip("/")
        return f"{app_host}/api" if app_host else ""

    @property
    def ALLOWED_HOSTS(self) -> list[str]:
        """Derive trusted HTTP hosts from deployment addresses and optional aliases."""
        from urllib.parse import urlparse

        hosts = ["localhost", "127.0.0.1", "backend"]
        app_name = (self.APP_NAME or "").strip()
        if app_name:
            hosts.extend([f"{app_name}-back", f"{app_name}-front"])

        for address in (self.APP_HOST,):
            parsed = urlparse(address.strip())
            if parsed.hostname:
                hosts.append(parsed.hostname)

        # Add configured hosts.
        if self.BACK_ALLOWED_HOSTS:
            extra_hosts = [
                host.strip()
                for host in self.BACK_ALLOWED_HOSTS.split(",")
                if host.strip()
            ]
            hosts.extend(extra_hosts)

        # Development adds a wildcard; explicit operator overrides remain valid elsewhere.
        if self.is_dev:
            hosts.append("*")

        return list(dict.fromkeys(hosts))

    @property
    def is_dev(self) -> bool:
        return self.APP_ENV == "dev"

    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=True,
        extra="ignore",
    )


# Singleton created when the module loads.
# Usage: from core import settings
settings = Settings()
