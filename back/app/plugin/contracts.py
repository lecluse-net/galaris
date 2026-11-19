"""Versioned declarative plugin bundle and inventory contracts."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

Version = Annotated[str, StringConstraints(pattern=r"^(0|[1-9][0-9]{0,8})\.(0|[1-9][0-9]{0,8})\.(0|[1-9][0-9]{0,8})$")]
PluginCode = Annotated[str, StringConstraints(
    max_length=100, pattern=r"^[a-z][a-z0-9-]*(\.[a-z][a-z0-9-]*)+$"
)]
Digest = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
Compatibility = Literal[
    "supported", "host_version", "untrusted_publisher", "unsupported_service",
    "native_publisher_required", "missing_dependency", "runtime_unconfigured",
]
Operation = Literal["installed", "activated", "deactivated", "removed", "activation_error"]


def version_parts(value: str) -> tuple[int, ...]:
    return tuple(int(part) for part in value.split("."))


class ManifestModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)


class LocalizedText(ManifestModel):
    en: str = Field(min_length=1, max_length=2000)
    fr: str = Field(min_length=1, max_length=2000)


class PresetContribution(ManifestModel):
    family: Literal["service_preset"]
    code: str = Field(max_length=100, pattern=r"^[a-z][a-z0-9-]*$")
    label: LocalizedText
    contract_version: Literal[1]
    sha256: Digest

    @property
    def path(self) -> str:
        return f"services/{self.code}.yaml"


class DocumentContribution(ManifestModel):
    family: Literal["document_format"]
    code: PluginCode
    label: LocalizedText
    contract_version: Literal[1]
    version: int = Field(ge=1, le=99999)
    sha256: Digest
    frontend_sha256: Digest

    @property
    def path(self) -> str:
        return f"backend/{self.code}.py"

    @property
    def frontend_path(self) -> str:
        return f"frontend/{self.code}.mjs"


class ProviderContribution(ManifestModel):
    family: Literal["llm_provider"]
    code: PluginCode
    label: LocalizedText
    contract_version: Literal[1]
    sha256: Digest

    @property
    def path(self) -> str:
        return f"backend/{self.code}.py"


class ConverterContribution(ManifestModel):
    family: Literal["preview_converter"]
    code: PluginCode
    label: LocalizedText
    contract_version: Literal[1]
    sha256: Digest

    @property
    def path(self) -> str:
        return f"backend/{self.code}.py"


class TemplateContribution(ManifestModel):
    family: Literal["data_template"]
    code: PluginCode
    label: LocalizedText
    contract_version: Literal[1]
    sha256: Digest

    @property
    def path(self) -> str:
        return f"data/{self.code}.json"


class FileShareProtocolContribution(ManifestModel):
    family: Literal["file_share_protocol"]
    code: PluginCode
    label: LocalizedText
    contract_version: Literal[1]
    sha256: Digest

    @property
    def path(self) -> str:
        return f"backend/{self.code}.py"


Contribution = Annotated[
    PresetContribution | DocumentContribution | ProviderContribution | ConverterContribution | TemplateContribution | FileShareProtocolContribution,
    Field(discriminator="family"),
]
PythonRequirement = Annotated[str, StringConstraints(max_length=128, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.-]*==[a-zA-Z0-9][a-zA-Z0-9_.+!-]*$")]


class RuntimeRequirement(ManifestModel):
    code: PluginCode
    image: str = Field(max_length=255, pattern=r"^[a-z0-9][a-z0-9.:/_-]*@sha256:[a-f0-9]{64}$")


@dataclass(frozen=True, slots=True)
class PluginRuntimeContext:
    endpoints: Mapping[str, str]


class Manifest(ManifestModel):
    format_version: Literal[1, 2]
    code: PluginCode
    label: LocalizedText
    description: LocalizedText
    version: Version
    minimum_galaris_version: Version
    maximum_galaris_version_exclusive: Version
    contributions: list[Contribution] = Field(min_length=1, max_length=16)
    python_requirements: list[PythonRequirement] = Field(default_factory=list, max_length=20)
    runtime_requirements: list[RuntimeRequirement] = Field(default_factory=lambda: list[RuntimeRequirement](), max_length=8)

    @property
    def publisher(self) -> str:
        return self.code.split(".", 1)[0]

    @property
    def executable(self) -> bool:
        return any(isinstance(item, (DocumentContribution, ProviderContribution, ConverterContribution, FileShareProtocolContribution))
                   for item in self.contributions)

    @model_validator(mode="after")
    def validate_release(self) -> Self:
        if version_parts(self.minimum_galaris_version) >= version_parts(self.maximum_galaris_version_exclusive):
            raise ValueError("Invalid host version range")
        if len({item.code for item in self.contributions}) != len(self.contributions):
            raise ValueError("Duplicate contribution code")
        if self.format_version != 2 and any(not isinstance(item, PresetContribution) for item in self.contributions):
            raise ValueError("This contribution requires manifest version 2")
        if (self.python_requirements or self.runtime_requirements) and not self.executable:
            raise ValueError("Runtime dependencies require an executable contribution")
        if len({item.code for item in self.runtime_requirements}) != len(self.runtime_requirements):
            raise ValueError("Duplicate runtime dependency code")
        for item in self.contributions:
            if not isinstance(item, PresetContribution) and item.code != self.code and not item.code.startswith(f"{self.code}."):
                raise ValueError("Contribution does not belong to the plugin namespace")
        return self


class Preview(BaseModel):
    manifest: Manifest
    digest: Digest
    signer: Digest
    compatibility: Compatibility
    host_version: str
    host_identity: Digest
    can_force: bool


class Release(Preview):
    installed: bool
    selected: bool
    active: bool
    forced: bool


class SampleContribution(ManifestModel):
    family: Literal["service_preset", "document_format"]
    code: str
    label: LocalizedText
    contract_version: int


class SampleManifest(ManifestModel):
    # A checkout sample describes its source, without claiming a signed release.
    model_config = ConfigDict(extra="ignore")
    code: PluginCode
    label: LocalizedText
    description: LocalizedText
    version: Version
    contributions: list[SampleContribution]


class SampleRelease(BaseModel):
    source: Literal["development_sample"] = "development_sample"
    manifest: SampleManifest
    active: bool = True
    target: Literal["documents", "rest", "mcp"]
    endpoint: str | None = None


InventoryEntry = Release | SampleRelease

class HostConfirmation(BaseModel):
    host_identity: Digest


class SampleConfirmation(BaseModel):
    source: Literal["development_sample"]


class PluginEventRead(BaseModel):
    version: Version
    operation: Operation
    occurred_at: datetime
    forced: bool


class PluginDetail(BaseModel):
    code: PluginCode
    releases: list[InventoryEntry]
    events: list[PluginEventRead]
