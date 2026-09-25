from pathlib import Path
from zipfile import ZipFile

import pytest

from app.skill import storage


@pytest.fixture
def skill_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(
        type(storage.settings), "GALARIS_SKILLS_ROOT", str(tmp_path / "skills")
    )
    return tmp_path / "skills"


@pytest.mark.asyncio
async def test_install_complete_zip_preserves_supporting_files(
    skill_root: Path, tmp_path: Path
) -> None:
    archive = tmp_path / "research.zip"
    with ZipFile(archive, "w") as output:
        output.writestr(
            "research/SKILL.md",
            "---\nname: research\ndescription: Research procedure.\n---\n# Research\n",
        )
        output.writestr("research/scripts/run.py", "print('ok')\n")
        output.writestr("research/assets/icon.bin", b"\x00\x01")

    installed = await storage.install_upload(
        archive.name, archive.read_bytes(), None, "Research", False
    )

    assert installed.code == "research"
    assert (skill_root / "research/scripts/run.py").read_text() == "print('ok')\n"
    assert (skill_root / "research/assets/icon.bin").read_bytes() == b"\x00\x01"
    assert storage.inspect("research").valid is True


@pytest.mark.asyncio
async def test_zip_path_traversal_is_rejected(skill_root: Path, tmp_path: Path) -> None:
    archive = tmp_path / "bad.zip"
    with ZipFile(archive, "w") as output:
        output.writestr("../SKILL.md", "bad")

    with pytest.raises(ValueError, match="chemin|Chemin"):
        await storage.install_upload(archive.name, archive.read_bytes(), None, None, False)

    assert not (skill_root.parent / "SKILL.md").exists()


def test_resolve_file_cannot_escape_skill(skill_root: Path) -> None:
    (skill_root / "safe").mkdir(parents=True)
    (skill_root / "safe/SKILL.md").write_text(
        "---\nname: safe\ndescription: Safe skill.\n---\n", encoding="utf-8"
    )

    with pytest.raises(ValueError):
        storage.resolve_file("safe", "../secret")


@pytest.mark.asyncio
async def test_system_skill_uses_bundled_read_only_storage(skill_root: Path) -> None:
    inspection = storage.inspect("galaris")

    assert inspection.available is True
    assert inspection.valid is True
    assert not (skill_root / "galaris").exists()
    assert storage.source_skill_dir("galaris") == storage.SYSTEM_SKILLS_ROOT / "galaris"
    assert storage.read_text("galaris", "SKILL.md").startswith("---\nname: galaris")

    with pytest.raises(ValueError, match="système"):
        await storage.install_markdown(
            "galaris",
            "Galaris",
            "---\nname: galaris\ndescription: Override.\n---\n",
        )


def test_system_skill_documents_every_native_mcp_tool(skill_root: Path) -> None:
    from app.tools.mcp_loader import load_mcp_tools

    # Native operations may live in a dedicated system guide linked by the general skill.
    markdown = storage.read_text("galaris", "SKILL.md") + storage.read_text("galaris-lab", "SKILL.md")
    missing = sorted(
        f"{definition.tool_code}:{definition.name}"
        for definition in load_mcp_tools()
        if f"`{definition.name}" not in markdown
    )

    assert missing == []


def test_system_skill_does_not_expose_private_workspace_scheme() -> None:
    markdown = storage.read_text("galaris", "SKILL.md")

    assert "workspace://" not in markdown


@pytest.mark.asyncio
async def test_skill_files_support_atomic_create_write_append_move_and_delete(
    skill_root: Path,
) -> None:
    await storage.install_markdown(
        "editable",
        "Editable",
        "---\nname: editable\ndescription: Editable skill.\n---\n# Editable\n",
    )

    created = await storage.write_file(
        "editable",
        "references/notes.md",
        b"first\n",
        overwrite=False,
    )
    appended = await storage.append_file(
        "editable",
        "references/notes.md",
        "second\n",
    )
    written = await storage.write_file(
        "editable",
        "references/notes.md",
        b"replacement\n",
        overwrite=True,
        expected_revision=appended.revision,
    )
    with pytest.raises(RuntimeError, match="revision conflict"):
        await storage.write_file(
            "editable",
            "references/notes.md",
            b"stale update\n",
            overwrite=True,
            expected_revision=created.revision,
        )
    moved = await storage.move_file(
        "editable",
        "references/notes.md",
        "references/archive.md",
        overwrite=False,
    )
    deleted = await storage.delete_file(
        "editable",
        "references/archive.md",
    )

    assert created.content == b"first\n"
    assert appended.content == b"first\nsecond\n"
    assert written.content == b"replacement\n"
    assert moved.path == "references/archive.md"
    assert deleted.content == b"replacement\n"
    assert not (skill_root / "editable/references").exists()


@pytest.mark.asyncio
async def test_skill_definition_mutations_preserve_frontmatter_and_system_files(
    skill_root: Path,
) -> None:
    await storage.install_markdown(
        "editable",
        "Editable",
        "---\nname: editable\ndescription: Editable skill.\n---\n",
    )

    with pytest.raises(ValueError, match="frontmatter|name"):
        await storage.write_file(
            "editable",
            "SKILL.md",
            b"# invalid\n",
            overwrite=True,
        )
    with pytest.raises(PermissionError, match="système"):
        await storage.write_file(
            "galaris",
            "SKILL.md",
            b"---\nname: galaris\ndescription: Changed.\n---\n",
            overwrite=True,
        )
    with pytest.raises(PermissionError, match="supprimé"):
        await storage.delete_file("editable", "SKILL.md")

    assert storage.inspect("editable").valid is True
