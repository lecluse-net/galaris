from concurrent.futures import ThreadPoolExecutor
from io import BytesIO

from PIL import Image

from core.preview import thumbnails


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
    assert all(path.parent == tmp_path and len(path.name) == 68 for path in paths)


def test_concurrent_writes_publish_one_complete_image(tmp_path):
    path = tmp_path / "thumbnail.png"
    images = [thumbnails.encode(Image.new("RGB", (40, 20), color)) for color in ("red", "blue")]
    with ThreadPoolExecutor(max_workers=2) as executor:
        list(executor.map(lambda content: thumbnails.write(path, content), images))
    assert thumbnails.read(path) in images
    assert list(tmp_path.iterdir()) == [path]
    assert thumbnails.read(path, max_bytes=10) is None
    with Image.open(BytesIO(path.read_bytes())) as image:
        assert image.size == (40, 20)
