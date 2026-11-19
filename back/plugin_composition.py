"""Bind trusted archive contributions to the host Document format registry."""

from collections.abc import Callable
from dataclasses import dataclass, replace
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import MappingProxyType

from app.document.formats import DocumentFormatDefinition, PluginDocumentEditor, prepare_plugin_document_formats
from app.file_share import FileShareBridge, prepare_plugin_file_share_bridges
from app.llm.provider_catalog import ProviderProfile, prepare_plugin_providers
from app.plugin.bundles import Bundle
from app.plugin.contracts import ConverterContribution, DocumentContribution, FileShareProtocolContribution, PluginRuntimeContext, ProviderContribution
from app.plugin.runtime import register_runtime, runtime_endpoint
from core.preview import PreviewConverter
from core.preview.conversion import prepare_plugin_converters

@dataclass(frozen=True, slots=True)
class _PreparedRelease:
    documents: tuple[DocumentFormatDefinition, ...]
    profiles: tuple[ProviderProfile, ...]
    converters: tuple[PreviewConverter, ...]
    file_share_bridges: tuple[FileShareBridge, ...]

_loaded: dict[str, _PreparedRelease] = {}


def _invoke(bundle: Bundle, contribution: DocumentContribution | ProviderContribution | ConverterContribution | FileShareProtocolContribution,
            entry: str) -> object:
    module_name = f"galaris_plugin_{bundle.digest}_{contribution.code.replace('.', '_').replace('-', '_')}"
    with TemporaryDirectory(prefix="galaris-plugin-") as folder:
        entry_point = Path(folder) / "plugin.py"
        entry_point.write_bytes(bundle.assets[contribution.path])
        spec = spec_from_file_location(module_name, entry_point)
        if spec is None or spec.loader is None:
            raise ValueError("Missing executable plugin entry point")
        module = module_from_spec(spec)
        sys.modules[module_name] = module
        try:
            spec.loader.exec_module(module)
            factory: object = getattr(module, entry, None)
            if not callable(factory):
                raise ValueError(f"Backend entry point must export {entry}")
            endpoints = {item.code: endpoint for item in bundle.manifest.runtime_requirements
                         if (endpoint := runtime_endpoint(item)) is not None}
            result: object = factory(PluginRuntimeContext(MappingProxyType(endpoints)))
            return result
        finally:
            sys.modules.pop(module_name, None)


def _load_format(bundle: Bundle, contribution: DocumentContribution) -> DocumentFormatDefinition:
    definition = _invoke(bundle, contribution, "plugin_format")
    if (not isinstance(definition, DocumentFormatDefinition) or definition.code != contribution.code
            or definition.provider != bundle.manifest.code or definition.version != contribution.version
            or definition.contract_version != contribution.contract_version or definition.storage_kind != "file"):
        raise ValueError("Document format does not match the signed declaration")
    return replace(definition, plugin_editor=PluginDocumentEditor(
        module_url=f"/api/plugins/assets/{bundle.digest}/{contribution.code}.mjs",
        label=contribution.label.model_dump(),
    ))


def _load_profile(bundle: Bundle, contribution: ProviderContribution) -> ProviderProfile:
    profile = _invoke(bundle, contribution, "plugin_provider")
    if not isinstance(profile, ProviderProfile) or profile.code != contribution.code:
        raise ValueError("Provider profile does not match the signed declaration")
    return profile


def _load_converter(bundle: Bundle, contribution: ConverterContribution) -> PreviewConverter:
    converter = _invoke(bundle, contribution, "plugin_converter")
    if not isinstance(converter, PreviewConverter) or converter.name != contribution.code:
        raise ValueError("Preview converter does not match the signed declaration")
    return converter


def _load_file_share_bridge(bundle: Bundle, contribution: FileShareProtocolContribution) -> FileShareBridge:
    bridge = _invoke(bundle, contribution, "plugin_file_share_protocol")
    if not isinstance(bridge, FileShareBridge) or bridge.service != contribution.code:
        raise ValueError("File-sharing protocol does not match the signed declaration")
    return bridge


def _prepare(bundles: tuple[Bundle, ...]) -> Callable[[], None]:
    candidate: dict[str, _PreparedRelease] = {}
    for bundle in bundles:
        prepared = _loaded.get(bundle.digest)
        if prepared is None:
            prepared = _PreparedRelease(
                tuple(_load_format(bundle, item) for item in bundle.manifest.contributions if isinstance(item, DocumentContribution)),
                tuple(_load_profile(bundle, item) for item in bundle.manifest.contributions if isinstance(item, ProviderContribution)),
                tuple(_load_converter(bundle, item) for item in bundle.manifest.contributions if isinstance(item, ConverterContribution)),
                tuple(_load_file_share_bridge(bundle, item) for item in bundle.manifest.contributions if isinstance(item, FileShareProtocolContribution)),
            )
        candidate[bundle.digest] = prepared
    promote_formats = prepare_plugin_document_formats(item for release in candidate.values() for item in release.documents)
    promote_providers = prepare_plugin_providers(item for release in candidate.values() for item in release.profiles)
    promote_converters = prepare_plugin_converters(item for release in candidate.values() for item in release.converters)
    promote_file_share = prepare_plugin_file_share_bridges(item for release in candidate.values() for item in release.file_share_bridges)

    def promote() -> None:
        global _loaded
        promote_formats()
        promote_providers()
        promote_converters()
        promote_file_share()
        _loaded = candidate

    return promote


def configure_plugin_runtime() -> None:
    register_runtime(_prepare)
