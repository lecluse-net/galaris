from concurrent.futures import ThreadPoolExecutor
from io import BytesIO

from PIL import Image
import pytest

from core.preview import thumbnails


@pytest.mark.parametrize("content", [b"", b"not an image", b"\x89PNG\r\n\x1a\n"])
def test_invalid_images_have_no_thumbnail_and_preserve_the_source(tmp_path, content):
    source = tmp_path / "source.png"
    source.write_bytes(content)
    assert thumbnails.from_image(source) is None
    assert source.read_bytes() == content


def test_canonical_uris_have_distinct_bounded_keys(tmp_path, monkeypatch):
    monkeypatch.setattr(type(thumbnails.settings), "GALARIS_THUMBNAIL_ROOT", str(tmp_path))
    references = [
        "https://example.org/page?lang=fr",
        "https://example.org/page?lang=en",
        "https://example.org/page#section",
        "document://one/attachments/same",
        "document://two/attachments/same",
        "console://../../private/écran.html",
        "https://example.org/" + "long" * 2_000,
    ]
    paths = {thumbnails.cache_path(reference) for reference in references}
    assert len(paths) == len(references)
    assert all(path.is_relative_to(tmp_path) and len(path.name) == 69 for path in paths)
    assert all(len(path.relative_to(tmp_path).parts) == 3 for path in paths)


def test_flat_cache_moves_image_and_metadata_without_overwriting_newer_content(tmp_path, monkeypatch):
    monkeypatch.setattr(type(thumbnails.settings), "GALARIS_THUMBNAIL_ROOT", str(tmp_path))
    path = thumbnails.cache_path("https://example.org/legacy")
    legacy = tmp_path / path.with_suffix(".png").name
    Image.new("RGBA", (520, 320), (0, 0, 255, 0)).save(legacy)
    legacy.with_suffix(".json").write_bytes(b'{"title":"Synthetic page"}')
    content = thumbnails.read(path)
    with Image.open(BytesIO(content)) as image:
        assert image.format == "WEBP" and image.size == (320, 197)
        assert image.getpixel((0, 0))[3] == 0
    assert thumbnails.read(path.with_suffix(".json")) == b'{"title":"Synthetic page"}'
    assert path.exists() and not legacy.exists()
    assert not legacy.with_suffix(".json").exists()

    legacy.write_bytes(b"stale image")
    thumbnails.write(path, b"new image")
    assert thumbnails.read(path) == b"new image"
    thumbnails.delete("https://example.org/legacy")
    assert thumbnails.read(path) is None
    assert not legacy.exists()
    assert not path.with_suffix(".json").exists()


def test_concurrent_writes_publish_one_complete_image(tmp_path):
    path = tmp_path / "thumbnail.webp"
    images = [thumbnails.encode(Image.new("RGB", (40, 20), color)) for color in ("red", "blue")]
    with ThreadPoolExecutor(max_workers=2) as executor:
        list(executor.map(lambda content: thumbnails.write(path, content), images))
    assert thumbnails.read(path) in images
    assert list(tmp_path.iterdir()) == [path]
    assert thumbnails.read(path, max_bytes=10) is None
    with Image.open(BytesIO(path.read_bytes())) as image:
        assert image.size == (40, 20)


def test_legacy_migration_preserves_a_concurrent_refresh(tmp_path, monkeypatch):
    monkeypatch.setattr(type(thumbnails.settings), "GALARIS_THUMBNAIL_ROOT", str(tmp_path))
    path = thumbnails.cache_path("https://example.org/concurrent")
    legacy = tmp_path / path.with_suffix(".png").name
    Image.new("RGB", (520, 320), "blue").save(legacy)
    refreshed = thumbnails.encode(Image.new("RGB", (320, 197), "red"))
    link = thumbnails.os.link

    def refresh_before_publish(source, destination):
        thumbnails.write(path, refreshed)
        link(source, destination)

    monkeypatch.setattr(thumbnails.os, "link", refresh_before_publish)
    assert thumbnails.read(path) == refreshed
    assert path.read_bytes() == refreshed
    assert not legacy.exists()
    assert not list(tmp_path.rglob(".thumbnail-*"))


def test_failed_legacy_migration_serves_preview_and_preserves_source(tmp_path, monkeypatch):
    monkeypatch.setattr(type(thumbnails.settings), "GALARIS_THUMBNAIL_ROOT", str(tmp_path))
    path = thumbnails.cache_path("https://example.org/read-only")
    legacy = tmp_path / path.with_suffix(".png").name
    Image.new("RGB", (520, 320), "blue").save(legacy)
    original = legacy.read_bytes()

    def fail_publish(*args):
        raise OSError("Synthetic read-only cache")

    monkeypatch.setattr(thumbnails.os, "link", fail_publish)
    with Image.open(BytesIO(thumbnails.read(path))) as image:
        assert image.format == "WEBP" and image.size == (320, 197)
    assert legacy.read_bytes() == original
    assert not list(tmp_path.rglob(".thumbnail-*"))
