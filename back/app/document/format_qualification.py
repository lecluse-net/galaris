"""Reusable codec TCK. Workflow/browser suites remain separate evidence."""
from dataclasses import dataclass
from collections.abc import Mapping
from .formats import DocumentFormatDefinition


@dataclass(frozen=True, slots=True)
class FormatExample:
    name: str
    content: str | bytes
    expected_text: str
    expected_references: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class FormatCheck:
    name: str
    status: str
    detail: str = ""


def qualify_document_format(
    definition: DocumentFormatDefinition, examples: tuple[FormatExample, ...], *,
    invalid_contents: tuple[str | bytes, ...] = (), reference_mapping: Mapping[str, str] | None = None,
) -> tuple[FormatCheck, ...]:
    """Execute independent examples, reporting every failure without source payloads.

    A successful codec report does not certify persistence, ACLs or frontend code.
    Plugins reuse this function with synthetic, independently specified examples.
    """
    checks: list[FormatCheck] = []
    if not examples:
        return (FormatCheck("examples", "not_run", "No qualification examples supplied"),)
    for example in examples:
        try:
            raw = example.content.encode("utf-8") if isinstance(example.content, str) else example.content
            definition.validate_content(raw)
            if definition.extract_content(raw) != example.expected_text:
                raise ValueError("Unexpected extracted text")
            references = definition.references(example.content) if isinstance(example.content, str) else ()
            if set(references) != set(example.expected_references):
                raise ValueError("Unexpected resource references")
            mapping = reference_mapping or {}
            if isinstance(example.content, str):
                remapped = definition.remap_references(example.content, mapping)
                definition.validate(remapped)
                expected = {mapping.get(uri, uri) for uri in example.expected_references}
                if set(definition.references(remapped)) != expected:
                    raise ValueError("Resource remapping did not preserve the reference set")
                if not definition.static_snapshot(example.content).strip():
                    raise ValueError("Empty static snapshot")
        except Exception as exc:
            checks.append(FormatCheck(example.name, "failed", type(exc).__name__))
        else:
            checks.append(FormatCheck(example.name, "passed"))
    for index, content in enumerate(invalid_contents):
        try:
            definition.validate_content(content.encode("utf-8") if isinstance(content, str) else content)
        except (ValueError, UnicodeError):
            checks.append(FormatCheck(f"invalid:{index}", "passed"))
        except Exception as exc:
            checks.append(FormatCheck(f"invalid:{index}", "failed", type(exc).__name__))
        else:
            checks.append(FormatCheck(f"invalid:{index}", "failed", "Invalid content accepted"))
    return tuple(checks)


FORMAT_QUALIFICATION_SUITES = (
    "codec", "lifecycle", "permissions", "concurrency", "assets", "import", "preview",
    "embed", "thumbnail", "pdf", "native_export", "browser", "missing_plugin",
)


@dataclass(frozen=True, slots=True)
class FormatSuiteEvidence:
    format_code: str
    format_version: int
    provider: str
    implementation_digest: str
    suite: str
    checks: tuple[FormatCheck, ...]


def document_format_conformance(
    definition: DocumentFormatDefinition, implementation_digest: str, evidence: tuple[FormatSuiteEvidence, ...],
) -> tuple[FormatCheck, ...]:
    """Missing, stale, duplicate or partial evidence can never qualify a release."""
    if len(implementation_digest) != 64 or any(char not in "0123456789abcdef" for char in implementation_digest):
        raise ValueError("Qualification requires the exact implementation SHA-256")
    result: list[FormatCheck] = []
    for suite in FORMAT_QUALIFICATION_SUITES:
        matches = [entry for entry in evidence if entry.suite == suite and entry.format_code == definition.code
            and entry.format_version == definition.version and entry.provider == definition.provider
            and entry.implementation_digest == implementation_digest]
        if not matches:
            result.append(FormatCheck(suite, "not_run"))
        elif len(matches) != 1 or not matches[0].checks or any(check.status != "passed" for check in matches[0].checks):
            result.append(FormatCheck(suite, "failed"))
        else:
            result.append(FormatCheck(suite, "passed"))
    return tuple(result)
