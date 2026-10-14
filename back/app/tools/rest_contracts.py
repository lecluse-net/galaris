"""REST capability configuration and transport-independent invocation contracts."""

from typing import Literal
from urllib.parse import urlsplit
import re

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator


class RestAuth(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["none", "bearer", "header", "basic", "query"] = "none"
    param: str = "api_token"
    header_name: str = "X-API-Key"
    query_name: str = "api_key"
    login_param: str = "login"
    password_param: str = "password"


class RestConfig(BaseModel):
    """Credentials are parameter names, never literal tokens in a Tool definition."""

    model_config = ConfigDict(extra="forbid")
    base_url: str = Field(min_length=1, max_length=2048)
    auth: RestAuth = Field(default_factory=RestAuth)
    # HTTP header name -> connection parameter name (including encrypted parameters).
    header_params: dict[str, str] = Field(default_factory=dict)
    timeout: int = Field(default=60, ge=1, le=300)
    max_response_bytes: int = Field(default=2_097_152, ge=1, le=16_777_216)

    @model_validator(mode="after")
    def validate_configuration(self) -> "RestConfig":
        if not re.fullmatch(r"\$\{connection:[A-Za-z0-9_.-]+\}", self.base_url):
            validate_rest_base_url(self.base_url)
        for name in [*self.header_params, self.auth.header_name]:
            if not re.fullmatch(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+", name):
                raise ValueError("Invalid REST header name")
        transport_names = [*self.header_params]
        if self.auth.type == "header":
            transport_names.append(self.auth.header_name)
        if any(name.lower() in {"host", "content-length", "transfer-encoding", "connection"}
               for name in transport_names):
            raise ValueError("Transport headers cannot be configured")
        if self.auth.type == "query" and not re.fullmatch(r"[A-Za-z0-9_.-]+", self.auth.query_name):
            raise ValueError("Invalid REST authentication query name")
        return self


def validate_rest_base_url(value: str) -> None:
    try:
        url = urlsplit(value)
        valid = (url.scheme in {"http", "https"} and bool(url.hostname) and url.port != 0
                 and url.username is None and url.password is None and not url.query and not url.fragment
                 and not any(character.isspace() for character in value) and "\\" not in value)
    except ValueError:
        valid = False
    if not valid:
        raise ValueError("REST base URL requires HTTP(S), without credentials, query or fragment")


class RestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    method: Literal["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"] = "GET"
    path: str = Field(default="", max_length=8192)
    params: dict[str, str | int | float | bool | list[str]] = Field(default_factory=dict)
    headers: dict[str, str] = Field(default_factory=dict)
    json_body: JsonValue = None
    text_body: str | None = None

    @model_validator(mode="after")
    def validate_body(self) -> "RestRequest":
        if "json_body" in self.model_fields_set and self.text_body is not None:
            raise ValueError("Choose JSON or text for the REST request body")
        if any(not re.fullmatch(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+", name)
               or not value.isascii() or "\r" in value or "\n" in value
               for name, value in self.headers.items()):
            raise ValueError("Invalid REST request header")
        return self


class RestResponse(BaseModel):
    status_code: int
    headers: dict[str, str]
    body: JsonValue


class RestError(ValueError):
    """Safe failure message; remote URLs and credentials never appear in exceptions."""
