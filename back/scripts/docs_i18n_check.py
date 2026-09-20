"""Validate the two localized Galaris documentation trees."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
import re
from urllib.parse import unquote


LOCALES = ("fr", "en")
MARKDOWN_LINK = re.compile(
    r"(?<!!)\[[^\]]*\]\(([^)\s]+)(?:\s+['\"][^'\"]*['\"])?\)"
)
HEADING = re.compile(r"^(#{1,6})\s+", re.MULTILINE)
FENCE = re.compile(r"^```", re.MULTILINE)
LANGUAGE_SWITCH = re.compile(r'^<p align="right">.*href="([^"]+)".*</p>$')


def _files(root: Path, locale: str) -> dict[Path, Path]:
    locale_root = root / "docs" / locale
    if not locale_root.is_dir():
        return {}
    return {
        path.relative_to(locale_root): path
        for path in locale_root.rglob("*")
        if path.is_file()
    }


def _link_targets(content: str) -> Counter[str]:
    targets = Counter(
        target.replace("LICENSE-FR.md", "LICENSE.md")
        for target in MARKDOWN_LINK.findall(content)
    )
    first_line = content.splitlines()[0] if content else ""
    switch = LANGUAGE_SWITCH.fullmatch(first_line)
    if switch is not None:
        target = switch.group(1).replace("LICENSE-FR.md", "LICENSE.md")
        targets[target] -= 1
        if targets[target] <= 0:
            del targets[target]
    return targets


def _check_local_links(path: Path, root: Path) -> list[str]:
    if path.suffix != ".md":
        return []
    errors: list[str] = []
    content = path.read_text(encoding="utf-8")
    for raw_target in MARKDOWN_LINK.findall(content):
        target = unquote(raw_target).split("#", 1)[0]
        if (
            not target
            or target.startswith(("http://", "https://", "mailto:"))
            or "<" in target
            or ">" in target
        ):
            continue
        candidate = (path.parent / target).resolve()
        try:
            candidate.relative_to(root.resolve())
        except ValueError:
            errors.append(f"{path.relative_to(root)}: link escapes the repository: {raw_target}")
            continue
        if not candidate.exists():
            errors.append(f"{path.relative_to(root)}: broken local link: {raw_target}")
    return errors


def check_documentation_locales(root: Path) -> list[str]:
    """Return structural, parity, and local-link errors for ``docs/fr`` and ``docs/en``."""

    trees = {locale: _files(root, locale) for locale in LOCALES}
    errors: list[str] = []
    for locale in LOCALES:
        if not trees[locale]:
            errors.append(f"docs/{locale} is missing or empty")
    relative_files = set(trees["fr"]) | set(trees["en"])
    for relative in sorted(relative_files):
        missing = [locale for locale in LOCALES if relative not in trees[locale]]
        if missing:
            errors.append(
                f"documentation file {relative} is missing from: {', '.join(missing)}"
            )
            continue
        french_path = trees["fr"][relative]
        english_path = trees["en"][relative]
        if relative.suffix != ".md":
            if french_path.read_bytes() != english_path.read_bytes():
                errors.append(f"localized asset differs: {relative}")
            continue
        french = french_path.read_text(encoding="utf-8")
        english = english_path.read_text(encoding="utf-8")
        expected_switches = {
            "fr": f"en/{relative.as_posix()}",
            "en": f"fr/{relative.as_posix()}",
        }
        for locale, content in (("fr", french), ("en", english)):
            first_line = content.splitlines()[0] if content else ""
            switch = LANGUAGE_SWITCH.fullmatch(first_line)
            if switch is None or expected_switches[locale] not in switch.group(1):
                errors.append(f"docs/{locale}/{relative}: invalid language switch")
        if Counter(HEADING.findall(french)) != Counter(HEADING.findall(english)):
            errors.append(f"localized heading levels differ: {relative}")
        if len(FENCE.findall(french)) != len(FENCE.findall(english)):
            errors.append(f"localized fenced block counts differ: {relative}")
        if _link_targets(french) != _link_targets(english):
            errors.append(f"localized link targets differ: {relative}")

    selector = root / "docs" / "README.md"
    if not selector.is_file():
        errors.append("docs/README.md language selector is missing")
    for path in sorted((root / "docs").rglob("*.md")):
        errors.extend(_check_local_links(path, root))
    return errors


__all__ = ["check_documentation_locales"]
