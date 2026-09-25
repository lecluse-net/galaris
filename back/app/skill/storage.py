"""Secure filesystem storage for complete skill directories."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import io
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import tempfile
from typing import Any, Iterator, TypedDict, cast
from uuid import uuid4
from zipfile import ZIP_DEFLATED, BadZipFile, ZipFile, ZipInfo

from loguru import logger
import yaml

from core import settings


CODE_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
MAX_UPLOAD_SIZE = 50 * 1024 * 1024
MAX_EXPANDED_SIZE = 200 * 1024 * 1024
MAX_FILE_COUNT = 2_000
MAX_TEXT_PREVIEW_SIZE = 2 * 1024 * 1024
MAX_COMPRESSION_RATIO = 250
_IGNORED_ARCHIVE_PARTS = {"__MACOSX"}
_IGNORED_ARCHIVE_FILES = {".DS_Store"}
SYSTEM_SKILLS_ROOT = Path(__file__).parent / "system_skills"
_TEXT_EXTENSIONS = {
    ".css", ".csv", ".env", ".html", ".ini", ".js", ".json", ".jsx",
    ".md", ".py", ".rst", ".sh", ".sql", ".toml", ".ts", ".tsx",
    ".txt", ".xml", ".yaml", ".yml",
}
_storage_lock = asyncio.Lock()


@dataclass(frozen=True)
class SkillInspection:
    available: bool
    valid: bool
    validation_error: str | None
    description: str | None
    file_count: int
    total_size: int


@dataclass(frozen=True)
class InstalledSkill:
    code: str
    label: str


@dataclass(frozen=True)
class SystemSkill:
    code: str
    label: str
    default_enabled: bool


SYSTEM_SKILLS = (
    SystemSkill(code="galaris", label="Galaris", default_enabled=True),
    SystemSkill(code="galaris-lab", label="Galaris Lab", default_enabled=False),
)


class StoredSkillFile(TypedDict):
    path: str
    name: str
    size: int
    text: bool


@dataclass(frozen=True)
class SkillFileData:
    path: str
    name: str
    content: bytes
    text: bool
    modified_at: datetime
    revision: int


def root() -> Path:
    """Return the configured canonical skill-library directory."""
    return Path(settings.GALARIS_SKILLS_ROOT).resolve()


def ensure_root() -> Path:
    skills_root = root()
    skills_root.mkdir(parents=True, exist_ok=True)
    (skills_root / ".staging").mkdir(exist_ok=True)
    (skills_root / ".trash").mkdir(exist_ok=True)
    return skills_root


def project_learned_markdown(agent_id: int, code: str, content: str) -> Path:
    """Materialize one DB-owned learned skill as a rebuildable runtime projection."""

    normalized = validate_code(code)
    metadata_from_markdown(content, expected_code=normalized)
    base = ensure_root() / ".learned" / str(agent_id) / normalized
    base.mkdir(parents=True, exist_ok=True)
    destination = base / "SKILL.md"
    temporary = base / f".SKILL.md.{uuid4().hex}.tmp"
    try:
        temporary.write_text(content.strip() + "\n", encoding="utf-8")
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination


def validate_code(code: str) -> str:
    normalized = str(code or "").strip()
    if not CODE_RE.fullmatch(normalized):
        raise ValueError("Le code doit être un slug en minuscules composé de lettres, chiffres et tirets")
    return normalized


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    return validate_code(slug)


def skill_dir(code: str) -> Path:
    return ensure_root() / validate_code(code)


def is_system_code(code: str) -> bool:
    normalized = validate_code(code)
    return any(skill.code == normalized for skill in SYSTEM_SKILLS)


def source_skill_dir(code: str) -> Path:
    normalized = validate_code(code)
    if is_system_code(normalized):
        return SYSTEM_SKILLS_ROOT / normalized
    return skill_dir(normalized)


def _parse_frontmatter(content: str) -> dict[str, Any]:
    normalized = content.lstrip("\ufeff")
    lines = normalized.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError("SKILL.md doit commencer par un frontmatter YAML délimité par ---")
    try:
        end = next(index for index in range(1, len(lines)) if lines[index].strip() == "---")
    except StopIteration as exc:
        raise ValueError("Le frontmatter YAML de SKILL.md n’est pas fermé") from exc
    try:
        raw = cast(object, yaml.safe_load("\n".join(lines[1:end])) or {})
    except yaml.YAMLError as exc:
        raise ValueError(f"Frontmatter YAML invalide : {exc}") from exc
    if not isinstance(raw, dict):
        raise ValueError("Le frontmatter de SKILL.md doit être un objet YAML")
    return cast(dict[str, Any], raw)


def metadata_from_markdown(content: str, expected_code: str | None = None) -> tuple[str, str]:
    metadata = _parse_frontmatter(content)
    name = str(metadata.get("name") or "").strip()
    description = str(metadata.get("description") or "").strip()
    if not name:
        raise ValueError("Le frontmatter de SKILL.md doit contenir name")
    if not description:
        raise ValueError("Le frontmatter de SKILL.md doit contenir description")
    normalized_name = slugify(name)
    if expected_code is not None and normalized_name != expected_code:
        raise ValueError(
            f"Le name du frontmatter ({name}) ne correspond pas au code de la compétence ({expected_code})"
        )
    return normalized_name, description


def default_markdown(code: str, label: str) -> str:
    return (
        "---\n"
        f"name: {code}\n"
        "description: Instructions réutilisables pour cette compétence.\n"
        "---\n\n"
        f"# {label}\n\n"
        "## Quand utiliser cette compétence\n\n"
        "Décrivez ici les situations dans lesquelles cette compétence doit être chargée.\n\n"
        "## Procédure\n\n"
        "1. Décrivez la première étape.\n"
    )


def _safe_relative(path: str) -> PurePosixPath:
    if not path or "\\" in path or "\x00" in path:
        raise ValueError("Chemin de fichier invalide")
    relative = PurePosixPath(path)
    if (
        relative.is_absolute()
        or not relative.parts
        or any(part in {"", ".", ".."} for part in relative.parts)
    ):
        raise ValueError("Le chemin doit rester dans le répertoire de la compétence")
    return relative


def resolve_file(code: str, relative_path: str) -> Path:
    base = source_skill_dir(code).resolve()
    relative = _safe_relative(relative_path)
    candidate = base.joinpath(*relative.parts)
    resolved = candidate.resolve()
    if not resolved.is_relative_to(base):
        raise ValueError("Le chemin sort du répertoire de la compétence")
    relative_candidate = candidate.relative_to(base)
    current = base
    for part in relative_candidate.parts:
        current /= part
        if current.is_symlink():
            raise ValueError("Les liens symboliques ne sont pas autorisés")
    if candidate.is_symlink():
        raise ValueError("Les liens symboliques ne sont pas autorisés")
    return resolved


def _is_text(path: Path) -> bool:
    if path.suffix.lower() in _TEXT_EXTENSIONS or path.name in {"Dockerfile", "Makefile"}:
        return True
    try:
        with path.open("rb") as stream:
            sample = stream.read(4096)
        sample.decode("utf-8")
        return b"\x00" not in sample
    except (OSError, UnicodeDecodeError):
        return False


def iter_skill_files(code: str) -> Iterator[tuple[str, Path]]:
    base = source_skill_dir(code)
    if not base.is_dir() or base.is_symlink():
        return
    for path in sorted(base.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"Lien symbolique interdit : {path.relative_to(base)}")
        if path.is_file():
            yield path.relative_to(base).as_posix(), path


def inspect(code: str) -> SkillInspection:
    base = source_skill_dir(code)
    if not base.is_dir() or base.is_symlink():
        return SkillInspection(False, False, "Répertoire absent", None, 0, 0)
    try:
        files = list(iter_skill_files(code))
        total_size = sum(path.stat().st_size for _, path in files)
        skill_md = base / "SKILL.md"
        if not skill_md.is_file() or skill_md.is_symlink():
            raise ValueError("Le répertoire ne contient pas de fichier SKILL.md")
        content = skill_md.read_text(encoding="utf-8")
        _, description = metadata_from_markdown(content, expected_code=code)
        return SkillInspection(True, True, None, description, len(files), total_size)
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        file_count = 0
        total_size = 0
        try:
            files = list(iter_skill_files(code))
            file_count = len(files)
            total_size = sum(path.stat().st_size for _, path in files)
        except (OSError, ValueError):
            pass
        return SkillInspection(True, False, str(exc), None, file_count, total_size)


def list_files(code: str) -> list[StoredSkillFile]:
    return [
        {
            "path": relative,
            "name": path.name,
            "size": path.stat().st_size,
            "text": _is_text(path),
        }
        for relative, path in iter_skill_files(code)
    ]


def read_text(code: str, relative_path: str) -> str:
    path = resolve_file(code, relative_path)
    if not path.is_file():
        raise FileNotFoundError(relative_path)
    if path.stat().st_size > MAX_TEXT_PREVIEW_SIZE:
        raise ValueError("Ce fichier est trop volumineux pour être affiché")
    if not _is_text(path):
        raise ValueError("Ce fichier est binaire et doit être téléchargé")
    return path.read_text(encoding="utf-8")


def read_file(code: str, relative_path: str) -> SkillFileData:
    """Read one bounded skill file after resolving it inside the skill directory."""

    path = resolve_file(code, relative_path)
    if not path.is_file():
        raise FileNotFoundError(relative_path)
    size = path.stat().st_size
    if size > MAX_UPLOAD_SIZE:
        raise ValueError("Ce fichier est trop volumineux")
    stat_result = path.stat()
    content = path.read_bytes()
    return SkillFileData(
        path=_safe_relative(relative_path).as_posix(),
        name=path.name,
        content=content,
        text=_is_text(path),
        modified_at=datetime.fromtimestamp(stat_result.st_mtime, timezone.utc),
        revision=_content_revision(content),
    )


def _content_revision(content: bytes) -> int:
    # Keep revisions below JavaScript's exact-integer limit because MCP serializes them as JSON.
    return max(1, int.from_bytes(hashlib.sha256(content).digest()[:6], "big"))


def _require_mutable_code(code: str) -> str:
    normalized = validate_code(code)
    if is_system_code(normalized):
        raise PermissionError(f"La compétence système {normalized} ne peut pas être modifiée")
    return normalized


def _validate_file_content(code: str, relative_path: PurePosixPath, content: bytes) -> None:
    if len(content) > MAX_UPLOAD_SIZE:
        raise ValueError("Le fichier dépasse la taille maximale de 50 Mio")
    if relative_path == PurePosixPath("SKILL.md"):
        try:
            markdown = content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("SKILL.md doit être encodé en UTF-8") from exc
        metadata_from_markdown(markdown, expected_code=code)


def _validate_library_limits(code: str, destination: Path, content_size: int) -> None:
    files = list(iter_skill_files(code))
    existing_size = destination.stat().st_size if destination.is_file() else 0
    file_count = len(files) + (0 if destination.is_file() else 1)
    total_size = sum(path.stat().st_size for _, path in files) - existing_size + content_size
    if file_count > MAX_FILE_COUNT:
        raise ValueError("La compétence contient trop de fichiers")
    if total_size > MAX_EXPANDED_SIZE:
        raise ValueError("La taille totale de la compétence est excessive")


async def write_file(
    code: str,
    relative_path: str,
    content: bytes,
    *,
    overwrite: bool,
    expected_revision: int | None = None,
) -> SkillFileData:
    """Create or atomically replace one file in a user-managed skill."""

    normalized = _require_mutable_code(code)
    relative = _safe_relative(relative_path)
    _validate_file_content(normalized, relative, content)
    async with _storage_lock:
        base = skill_dir(normalized)
        if not base.is_dir() or base.is_symlink():
            raise FileNotFoundError(normalized)
        destination = resolve_file(normalized, relative.as_posix())
        exists = destination.is_file()
        if destination.exists() and not exists:
            raise IsADirectoryError(relative.as_posix())
        if exists and not overwrite:
            raise FileExistsError(relative.as_posix())
        if not exists and overwrite:
            raise FileNotFoundError(relative.as_posix())
        if expected_revision is not None and exists:
            current_revision = _content_revision(destination.read_bytes())
            if current_revision != expected_revision:
                raise RuntimeError(
                    f"Skill file revision conflict: expected {expected_revision}, "
                    f"current revision is {current_revision}."
                )
        _validate_library_limits(normalized, destination, len(content))
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(f".{destination.name}.{uuid4().hex}.tmp")
        try:
            temporary.write_bytes(content)
            temporary.replace(destination)
        finally:
            temporary.unlink(missing_ok=True)
    return read_file(normalized, relative.as_posix())


async def append_file(code: str, relative_path: str, content: str) -> SkillFileData:
    """Append UTF-8 text while preserving SKILL.md validation and storage limits."""

    current = read_file(code, relative_path)
    if not current.text:
        raise ValueError("Ce fichier binaire ne peut pas recevoir de texte")
    try:
        updated = current.content.decode("utf-8") + content
    except UnicodeDecodeError as exc:
        raise ValueError("Ce fichier n’est pas encodé en UTF-8") from exc
    return await write_file(
        code,
        relative_path,
        updated.encode("utf-8"),
        overwrite=True,
        expected_revision=current.revision,
    )


async def delete_file(code: str, relative_path: str) -> SkillFileData:
    """Delete an auxiliary file without allowing the skill definition itself to disappear."""

    normalized = _require_mutable_code(code)
    relative = _safe_relative(relative_path)
    if relative == PurePosixPath("SKILL.md"):
        raise PermissionError("SKILL.md ne peut pas être supprimé ; supprimez la compétence")
    async with _storage_lock:
        current = read_file(normalized, relative.as_posix())
        path = resolve_file(normalized, relative.as_posix())
        path.unlink()
        base = skill_dir(normalized)
        parent = path.parent
        while parent != base and parent.is_relative_to(base):
            try:
                parent.rmdir()
            except OSError:
                break
            parent = parent.parent
    return current


async def move_file(
    code: str,
    source_path: str,
    destination_path: str,
    *,
    overwrite: bool,
) -> SkillFileData:
    """Rename one auxiliary file within the same user-managed skill."""

    normalized = _require_mutable_code(code)
    source_relative = _safe_relative(source_path)
    destination_relative = _safe_relative(destination_path)
    if PurePosixPath("SKILL.md") in {source_relative, destination_relative}:
        raise PermissionError("SKILL.md ne peut pas être déplacé ou renommé")
    async with _storage_lock:
        source = resolve_file(normalized, source_relative.as_posix())
        if not source.is_file():
            raise FileNotFoundError(source_relative.as_posix())
        destination = resolve_file(normalized, destination_relative.as_posix())
        if destination.exists() and not overwrite:
            raise FileExistsError(destination_relative.as_posix())
        if destination.exists() and not destination.is_file():
            raise IsADirectoryError(destination_relative.as_posix())
        destination.parent.mkdir(parents=True, exist_ok=True)
        source.replace(destination)
    return read_file(normalized, destination_relative.as_posix())


def write_markdown(code: str, content: str) -> None:
    code = validate_code(code)
    if is_system_code(code):
        raise ValueError(f"La compétence système {code} ne peut pas être modifiée")
    metadata_from_markdown(content, expected_code=code)
    if len(content.encode("utf-8")) > MAX_UPLOAD_SIZE:
        raise ValueError("Le fichier SKILL.md est trop volumineux")
    base = skill_dir(code)
    base.mkdir(parents=True, exist_ok=True)
    temp = base / ".SKILL.md.tmp"
    temp.write_text(content, encoding="utf-8")
    temp.replace(base / "SKILL.md")


def _validate_zip_info(info: ZipInfo) -> None:
    relative = _safe_relative(info.filename.rstrip("/"))
    if any(part in _IGNORED_ARCHIVE_PARTS for part in relative.parts):
        return
    mode = info.external_attr >> 16
    if stat.S_ISLNK(mode):
        raise ValueError(f"Lien symbolique interdit dans l’archive : {info.filename}")
    if info.file_size > MAX_EXPANDED_SIZE:
        raise ValueError(f"Fichier décompressé trop volumineux : {info.filename}")
    if info.compress_size > 0 and info.file_size / info.compress_size > MAX_COMPRESSION_RATIO:
        raise ValueError(f"Ratio de compression suspect : {info.filename}")


def _extract_zip(data: bytes, destination: Path) -> None:
    try:
        archive = ZipFile(io.BytesIO(data))
    except BadZipFile as exc:
        raise ValueError("Le fichier ZIP est invalide") from exc
    with archive:
        entries = [info for info in archive.infolist() if not info.is_dir()]
        if len(entries) > MAX_FILE_COUNT:
            raise ValueError("L’archive contient trop de fichiers")
        total_expanded = 0
        safe_entries: list[tuple[ZipInfo, PurePosixPath]] = []
        for info in entries:
            total_expanded += info.file_size
            if total_expanded > MAX_EXPANDED_SIZE:
                raise ValueError("La taille décompressée de l’archive est excessive")
            _validate_zip_info(info)
            relative = _safe_relative(info.filename)
            if (
                any(part in _IGNORED_ARCHIVE_PARTS for part in relative.parts)
                or relative.name in _IGNORED_ARCHIVE_FILES
            ):
                continue
            safe_entries.append((info, relative))
        paths = [relative for _, relative in safe_entries]
        direct = any(path == PurePosixPath("SKILL.md") for path in paths)
        wrapper: str | None = None
        if not direct:
            roots = {path.parts[0] for path in paths if path.parts}
            if len(roots) == 1:
                candidate = next(iter(roots))
                if any(path == PurePosixPath(candidate, "SKILL.md") for path in paths):
                    wrapper = candidate
            if wrapper is None:
                raise ValueError(
                    "Le ZIP doit contenir exactement une compétence avec un SKILL.md à sa racine"
                )
        for info, relative in safe_entries:
            effective = PurePosixPath(*relative.parts[1:]) if wrapper else relative
            if not effective.parts:
                continue
            target = destination.joinpath(*effective.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as source, target.open("wb") as output:
                shutil.copyfileobj(source, output)


def _replace_directory(staged: Path, code: str, overwrite: bool) -> None:
    if is_system_code(code):
        raise ValueError(f"Le code {code} est réservé à une compétence système")
    destination = skill_dir(code)
    if destination.exists() and not overwrite:
        raise FileExistsError(f"La compétence {code} existe déjà")
    backup: Path | None = None
    if destination.exists():
        backup = ensure_root() / ".staging" / f"backup-{code}-{uuid4().hex}"
        destination.replace(backup)
    try:
        staged.replace(destination)
    except Exception:
        if backup is not None and backup.exists() and not destination.exists():
            backup.replace(destination)
        raise
    if backup is not None:
        shutil.rmtree(backup, ignore_errors=True)


async def install_markdown(
    code: str, label: str, content: str, overwrite: bool = False
) -> InstalledSkill:
    code = validate_code(code)
    metadata_from_markdown(content, expected_code=code)
    async with _storage_lock:
        stage_parent = ensure_root() / ".staging" / uuid4().hex
        staged = stage_parent / "skill"
        staged.mkdir(parents=True)
        try:
            (staged / "SKILL.md").write_text(content, encoding="utf-8")
            _replace_directory(staged, code, overwrite)
        finally:
            shutil.rmtree(stage_parent, ignore_errors=True)
    return InstalledSkill(code, label.strip() or code)


async def install_upload(
    filename: str,
    data: bytes,
    requested_code: str | None,
    requested_label: str | None,
    overwrite: bool,
) -> InstalledSkill:
    if len(data) > MAX_UPLOAD_SIZE:
        raise ValueError("Le fichier téléversé dépasse la taille maximale de 50 Mio")
    lower_name = (filename or "").lower()
    async with _storage_lock:
        stage_parent = ensure_root() / ".staging" / uuid4().hex
        staged = stage_parent / "skill"
        staged.mkdir(parents=True)
        try:
            if lower_name.endswith(".zip"):
                _extract_zip(data, staged)
            elif lower_name.endswith(".md") or lower_name.endswith(".markdown"):
                try:
                    content = data.decode("utf-8")
                except UnicodeDecodeError as exc:
                    raise ValueError("Le fichier Markdown doit être encodé en UTF-8") from exc
                (staged / "SKILL.md").write_text(content, encoding="utf-8")
            else:
                raise ValueError("Seuls les fichiers ZIP et Markdown sont acceptés")

            markdown = (staged / "SKILL.md").read_text(encoding="utf-8")
            metadata_code, description = metadata_from_markdown(markdown)
            code = validate_code(requested_code) if requested_code else metadata_code
            metadata_from_markdown(markdown, expected_code=code)
            label = (requested_label or "").strip() or code
            _replace_directory(staged, code, overwrite)
            logger.info("Skill files installed: code={} description={}", code, description[:100])
            return InstalledSkill(code, label)
        finally:
            shutil.rmtree(stage_parent, ignore_errors=True)


def quarantine(code: str) -> Path | None:
    if is_system_code(code):
        raise ValueError(f"La compétence système {code} ne peut pas être supprimée")
    source = skill_dir(code)
    if not source.exists():
        return None
    destination = ensure_root() / ".trash" / (
        f"{code}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{uuid4().hex}"
    )
    source.replace(destination)
    return destination


def restore_quarantine(code: str, quarantined: Path | None) -> None:
    if quarantined is not None and quarantined.exists() and not skill_dir(code).exists():
        quarantined.replace(skill_dir(code))


def purge_quarantine(quarantined: Path | None) -> None:
    if quarantined is not None:
        shutil.rmtree(quarantined, ignore_errors=True)


def create_zip(code: str) -> Path:
    inspection = inspect(code)
    if not inspection.available:
        raise FileNotFoundError(code)
    descriptor, filename = tempfile.mkstemp(prefix=f"galaris-{code}-", suffix=".zip")
    os.close(descriptor)
    try:
        with ZipFile(filename, "w", ZIP_DEFLATED) as archive:
            for relative, path in iter_skill_files(code):
                archive.write(path, arcname=f"{code}/{relative}")
        return Path(filename)
    except Exception:
        Path(filename).unlink(missing_ok=True)
        raise


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(256 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
