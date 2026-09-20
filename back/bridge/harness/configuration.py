"""Administration and portable host setup for the generic manager."""

from ipaddress import ip_address
from pathlib import PurePosixPath

from pydantic import BaseModel, ConfigDict, Field, field_validator

from core.params import Params, RuntimeSettings, params_service, runtime_settings
from .distribution import update_url


class ManagerConfiguration(BaseModel):
    manager_url: str
    galaris_api_url: str
    secret_configured: bool


class ManagerConfigurationUpdate(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)
    manager_url: str
    galaris_api_url: str = ""
    # None preserves the existing key; empty explicitly clears it.
    secret: str | None = Field(default=None, repr=False)

    @field_validator("manager_url", "galaris_api_url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        return RuntimeSettings.validate_manager_url(value)

    @field_validator("secret")
    @classmethod
    def validate_secret(cls, value: str | None) -> str | None:
        return None if value is None else RuntimeSettings.validate_manager_secret(value)


def configuration() -> ManagerConfiguration:
    return ManagerConfiguration(
        manager_url=runtime_settings.HARNESS_MANAGER_URL,
        galaris_api_url=runtime_settings.HARNESS_MANAGER_GALARIS_API_URL,
        secret_configured=bool(runtime_settings.HARNESS_MANAGER_SECRET),
    )


async def save_configuration(data: ManagerConfigurationUpdate) -> ManagerConfiguration:
    values = {
        Params.HARNESS_MANAGER_URL: data.manager_url,
        Params.HARNESS_MANAGER_GALARIS_API_URL: data.galaris_api_url,
    }
    if data.secret is not None:
        values[Params.HARNESS_MANAGER_SECRET] = data.secret
    await params_service.set_runtime_values(values)
    return configuration()


class ManagerHostSetup(BaseModel):
    update_url: str = ""
    api_host: str = "0.0.0.0"
    api_port: int = Field(default=8485, ge=1, le=65535)
    allowed_ip: str = ""
    base_dir: str = "/opt/galaris-harnesses"
    ignore_dirs: str = ""
    # The API retains its historical MiB unit; generated limits are decimal MB.
    max_file_size_mb: float = Field(default=1_000_000 / 1_048_576, ge=1_000_000 / 1_048_576, le=1024, allow_inf_nan=False)
    max_raw_file_size_mb: float = Field(default=512_000_000 / 1_048_576, ge=1_000_000 / 1_048_576, le=10240, allow_inf_nan=False)

    @field_validator("update_url")
    @classmethod
    def validate_update_url(cls, value: str) -> str:
        return cls.validate_env_value(RuntimeSettings.validate_manager_url(value))

    @field_validator("api_host", "allowed_ip")
    @classmethod
    def validate_ip(cls, value: str) -> str:
        return str(ip_address(value.strip())) if value.strip() else ""

    @field_validator("base_dir", "ignore_dirs")
    @classmethod
    def validate_env_value(cls, value: str) -> str:
        # Also consumed by GNU Make. Reject expansion, quoting and line injection.
        if any(ord(char) < 32 or char in "$#\\\"'`;" for char in value):
            raise ValueError("Use a plain path without quotes, escapes or expansions")
        return value.strip()

    @field_validator("base_dir")
    @classmethod
    def validate_absolute_path(cls, value: str) -> str:
        if not PurePosixPath(value).is_absolute() or ".." in PurePosixPath(value).parts:
            raise ValueError("Use an absolute directory path")
        return value


def export_environment(setup: ManagerHostSetup) -> str:
    secret = runtime_settings.HARNESS_MANAGER_SECRET
    if not secret:
        raise ValueError("Save a manager secret before exporting")
    values: dict[str, str | int | float] = {
        "API_HOST": setup.api_host or "0.0.0.0",
        "API_PORT": setup.api_port,
        "ALLOWED_IP": setup.allowed_ip,
        "HARNESS_MANAGER_SECRET": secret,
        "BASE_DIR": setup.base_dir,
        "IGNORE_DIRS": setup.ignore_dirs,
        "MAX_FILE_SIZE_MB": setup.max_file_size_mb,
        "MAX_RAW_FILE_SIZE_MB": setup.max_raw_file_size_mb,
        "GALARIS_UPDATE_URL": ManagerHostSetup.validate_update_url(setup.update_url or update_url()),
    }
    return "# harness_manager/.env — contains a secret; keep private\n" + "".join(
        f"{name}={value}\n" for name, value in values.items()
    )
