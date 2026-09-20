import asyncio
from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from core.preview import PreviewConverter, PreviewFile, prepare_preview, register_preview_converter
from core.preview import conversion


@pytest.fixture(autouse=True)
def isolated_registry(monkeypatch):
    monkeypatch.setattr(conversion, "_converters", {})


@asynccontextmanager
async def unused_converter(source):
    pytest.fail("An incompatible converter was called")
    yield source


@pytest.mark.asyncio
@pytest.mark.parametrize("register_incompatible", [False, True])
async def test_unmatched_source_is_returned_unchanged(register_incompatible):
    if register_incompatible:
        register_preview_converter(
            PreviewConverter("unmatched", "1", lambda mime, name: False, unused_converter)
        )
    source = PreviewFile(Path("original.png"), "original.png", "image/png")
    async with prepare_preview(source) as prepared:
        assert prepared is source


def test_duplicate_names_do_not_replace_registration():
    converter = PreviewConverter("unique", "1", lambda mime, name: True, unused_converter)
    register_preview_converter(converter)
    with pytest.raises(ValueError, match="Duplicate preview converter: unique"):
        register_preview_converter(replace(converter, version="2"))
    assert conversion._converters["unique"] is converter


@pytest.mark.asyncio
async def test_matching_priority_and_name_order_select_exactly_one_converter():
    called = []

    def accepts(mime, name):
        assert (mime, name) == ("application/x-example", "source.example")
        return True

    def converter(name, priority):
        @asynccontextmanager
        async def convert(source):
            called.append(name)
            yield replace(source, name="converted.pdf", media_type="application/pdf")

        return PreviewConverter(name, "1", accepts, convert, priority)

    register_preview_converter(converter("low", 0))
    register_preview_converter(converter("z-high", 10))
    register_preview_converter(converter("a-high", 10))
    register_preview_converter(
        PreviewConverter("incompatible", "1", lambda mime, name: False, unused_converter, 100)
    )
    source = PreviewFile(Path("source.example"), "source.example", "application/x-example")
    async with prepare_preview(source) as prepared:
        assert prepared.media_type == "application/pdf"
    assert called == ["a-high"]


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["success", "consumer_error", "conversion_error", "cancel"])
async def test_derivative_lifetime_and_source_preservation(tmp_path, outcome):
    original_path = tmp_path / "source.example"
    original_path.write_bytes(b"original")
    source = PreviewFile(original_path, original_path.name, "application/x-example")
    created = []
    entered = asyncio.Event()

    @asynccontextmanager
    async def convert(original):
        with TemporaryDirectory(dir=tmp_path) as directory:
            path = Path(directory) / "converted.pdf"
            path.write_bytes(b"converted")
            created.append(path)
            if outcome == "conversion_error":
                raise RuntimeError("conversion failed")
            yield PreviewFile(path, path.name, "application/pdf")

    register_preview_converter(PreviewConverter("example", "1", lambda mime, name: True, convert))

    async def consume():
        async with prepare_preview(source) as prepared:
            assert prepared.path.read_bytes() == b"converted"
            assert original_path.read_bytes() == b"original"
            entered.set()
            if outcome == "consumer_error":
                raise RuntimeError("consumer failed")
            if outcome == "cancel":
                await asyncio.Event().wait()

    if outcome == "cancel":
        task = asyncio.create_task(consume())
        await asyncio.wait_for(entered.wait(), timeout=1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    elif outcome.endswith("error"):
        with pytest.raises(RuntimeError, match="failed"):
            await consume()
    else:
        await consume()

    assert len(created) == 1
    assert not created[0].exists()
    assert not created[0].parent.exists()
    assert original_path.read_bytes() == b"original"
