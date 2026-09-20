"""Versioned, inert application blocks embedded in ordinary HTML documents."""

from html.parser import HTMLParser
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator


class DatasetBinding(BaseModel):
    model_config = ConfigDict(extra="forbid")
    uri: str = Field(pattern=r"^document://[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$")
    access: Literal["read", "write"] = "read"

    @property
    def document_id(self) -> UUID:
        return UUID(self.uri.removeprefix("document://"))


class DocumentApp(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,39}$")
    title: str = Field(min_length=1, max_length=120)
    html: str = Field(default="", max_length=2_000_000)
    css: str = Field(default="", max_length=50_000)
    javascript: str = Field(default="", max_length=100_000)
    datasets: dict[str, DatasetBinding] = Field(default_factory=dict, max_length=10)

    @model_validator(mode="after")
    def valid_aliases(self) -> "DocumentApp":
        import re
        if any(not re.fullmatch(r"[a-z][a-z0-9_-]{0,39}", alias) for alias in self.datasets):
            raise ValueError("Dataset aliases must be short lowercase identifiers.")
        return self


class AppDatasetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document_revision: int = Field(ge=1)
    operation: Literal["read", "replace", "append"] = "read"
    expected_revision: int | None = Field(default=None, ge=1)
    value: JsonValue = None

    @model_validator(mode="after")
    def mutation_requires_revision(self) -> "AppDatasetRequest":
        if self.operation != "read" and (self.expected_revision is None or "value" not in self.model_fields_set):
            raise ValueError("Dataset mutations require value and expected_revision.")
        return self


class AppDatasetResult(BaseModel):
    revision: int
    data: JsonValue


class AppGrantUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document_revision: int = Field(ge=1)
    access: Literal["read", "write"] | None


class AppGrantPublic(BaseModel):
    app_key: str
    app_title: str
    alias: str
    dataset_id: UUID
    dataset_title: str | None
    requested_access: Literal["read", "write"]
    access: Literal["read", "write"] | None


class AppPermissions(BaseModel):
    document_revision: int
    grants: list[AppGrantPublic]


class _AppParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[str] = []
        self.source: list[str] | None = None
        self.apps: list[DocumentApp] = []
        self.raw = False
        self.bindings: dict[str, DatasetBinding] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self.source is not None:
            raise ValueError("Application JSON must be escaped text inside its code block.")
        if tag == "code" and "language-galaris-app" in (dict(attrs).get("class") or "").split():
            if self.stack != ["pre"]:
                raise ValueError("Application blocks must be top-level pre/code blocks.")
            self.source = []
        attributes = dict(attrs)
        if tag in {"script", "style", "form", "canvas", "svg", "input", "button", "div", "section"} or any(key.startswith("on") for key in attributes):
            self.raw = True
        if uri := attributes.get("data-dataset"):
            alias = attributes.get("data-dataset-alias") or "entries"
            binding = DatasetBinding.model_validate({"uri": uri, "access": attributes.get("data-dataset-access") or ("write" if tag == "form" else "read")})
            if alias in self.bindings and self.bindings[alias] != binding:
                raise ValueError("Conflicting Dataset declarations.")
            self.bindings[alias] = binding
            self.raw = True
        if tag not in {"br", "hr", "img", "col", "input", "source", "wbr"}:
            self.stack.append(tag)

    def handle_endtag(self, tag: str) -> None:
        if tag == "code" and self.source is not None:
            self.apps.append(DocumentApp.model_validate_json("".join(self.source)))
            self.source = None
        if self.stack and self.stack[-1] == tag:
            self.stack.pop()

    def handle_data(self, data: str) -> None:
        if self.source is not None:
            self.source.append(data)


def document_apps(content: str) -> list[DocumentApp]:
    parser = _AppParser()
    parser.feed(content)
    parser.close()
    if parser.raw:
        parser.apps.append(DocumentApp(id="document-html", title="Document", html=content, datasets=parser.bindings))
    if len(parser.apps) > 10:
        raise ValueError("A document supports at most 10 application blocks.")
    if len({app.id for app in parser.apps}) != len(parser.apps):
        raise ValueError("Application identifiers must be unique within a document.")
    return parser.apps
