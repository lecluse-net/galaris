"""REST capability configuration and transport-independent invocation contracts."""

from dataclasses import dataclass
from typing import Annotated, Literal
from urllib.parse import urlsplit
import re
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator


class RestAuth(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["none", "bearer", "header", "basic", "query"] = "none"
    param: str = "api_token"
    header_name: str = "X-API-Key"
    query_name: str = "api_key"
    login_param: str = "login"
    password_param: str = "password"

    def secret_parameter(self) -> str | None:
        if self.type == "basic":
            return self.password_param
        return self.param if self.type != "none" else None


class RestConfig(BaseModel):
    """Credentials are parameter names, never literal tokens in a Service definition."""

    model_config = ConfigDict(extra="forbid")
    base_url: str = Field(min_length=1, max_length=2048)
    auth: RestAuth = Field(default_factory=RestAuth)
    # HTTP header name -> connection parameter name (including encrypted parameters).
    header_params: dict[str, str] = Field(default_factory=dict)
    timeout: int = Field(default=60, ge=1, le=300)
    max_response_bytes: int = Field(default=2_097_152, ge=1, le=16_777_216)
    effect_receipt: Literal["n8n_data_table_insert"] | None = None

    def connection_parameters(self) -> set[str]:
        names = set(self.header_params.values())
        if self.base_url.startswith("${connection:"):
            names.add(self.base_url[len("${connection:"):-1])
        if (secret := self.auth.secret_parameter()) is not None:
            names.add(secret)
        if self.auth.type == "basic":
            names.add(self.auth.login_param)
        return names

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


UploadUri = Annotated[str, Field(min_length=1, max_length=8192)]
FormField = Annotated[str, Field(min_length=1, max_length=256, pattern=r"^[^\x00-\x1f\x7f]+$")]
UploadName = Annotated[str, Field(min_length=1, max_length=255, pattern=r"^[^/\\\x00-\x1f\x7f]+$")]


class RestFilePart(BaseModel):
    model_config = ConfigDict(extra="forbid")
    field: FormField
    uri: UploadUri
    filename: UploadName | None = None
    content_type: str | None = Field(default=None, max_length=255, pattern=r"^[A-Za-z0-9!#$&^_.+\-]+/[A-Za-z0-9!#$&^_.+\-]+$")


class RestToolRequest(RestRequest):
    """Agent uploads use the resource context of this MCP call."""
    file_uri: UploadUri | None = None
    form: dict[FormField, str | list[str]] | None = None
    files: list[RestFilePart] = Field(default_factory=list[RestFilePart], max_length=16)

    @model_validator(mode="after")
    def validate_upload(self) -> "RestToolRequest":
        modes = ("json_body" in self.model_fields_set, self.text_body is not None,
                 self.file_uri is not None, self.form is not None or bool(self.files))
        if sum(modes) > 1:
            raise ValueError("Select one REST body: JSON, text, file_uri, or form with optional files.")
        return self


@dataclass(frozen=True, slots=True, repr=False)
class RestUpload:
    field: str
    filename: str
    content_type: str
    content: bytes


class RestResponse(BaseModel):
    status_code: int
    headers: dict[str, str]
    body: JsonValue


class RestEffectIntent(BaseModel):
    reference: UUID
    binding: str


class RestError(ValueError):
    """Safe failure message; remote URLs and credentials never appear in exceptions."""


class RestRequestRejected(RestError):
    """Local validation rejected the request before sending it to the provider."""
