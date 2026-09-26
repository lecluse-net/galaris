import pytest

from app.file_share.service_references import (
    FileServiceReferenceError,
    normalize_destination_reference,
    normalize_source_reference,
    reference_filename,
)


def test_reference_filename_handles_paths_and_urls() -> None:
    assert reference_filename("Documents/report.pdf") == "report.pdf"
    assert reference_filename("https://cloud.example.test/files/Compte%20rendu.pdf?download=1") == (
        "Compte rendu.pdf"
    )


def test_affine_references_split_workspace_from_file() -> None:
    source = normalize_source_reference("affine", "company/blob-key")
    destination = normalize_destination_reference(
        "affine",
        "company/report.pdf",
        fallback_filename="source.pdf",
    )

    assert (source.target, source.remote) == ("company", "blob-key")
    assert (destination.target, destination.filename) == ("company", "report.pdf")
    assert normalize_destination_reference(
        "affine",
        "company",
        fallback_filename="source.pdf",
    ).filename == "source.pdf"


@pytest.mark.parametrize("reference", ["blob/key", "blobs/key"])
def test_affine_export_reference_requires_explicit_workspace(reference: str) -> None:
    with pytest.raises(FileServiceReferenceError, match="workspace/file-key"):
        normalize_source_reference("affine", reference)


def test_messenger_references_split_room_from_attachment() -> None:
    source = normalize_source_reference("messenger", "messenger:room-7/attachment-9")
    destination = normalize_destination_reference(
        "messenger",
        "room-8/report.pdf",
        fallback_filename="source.pdf",
    )

    assert (source.target, source.remote) == ("room-7", "attachment-9")
    assert (destination.target, destination.filename) == ("room-8", "report.pdf")


def test_grav_destination_splits_page_and_filename() -> None:
    explicit = normalize_destination_reference(
        "grav",
        "blog/2026/report.pdf",
        fallback_filename="source.pdf",
    )
    page_only = normalize_destination_reference(
        "grav",
        "blog/2026/",
        fallback_filename="source.pdf",
    )

    assert (explicit.target, explicit.filename) == ("blog/2026", "report.pdf")
    assert (page_only.target, page_only.filename) == ("blog/2026", "source.pdf")


def test_nextcloud_destination_preserves_directory_target() -> None:
    destination = normalize_destination_reference(
        "nextcloud",
        "Shared/reports/report.pdf",
        fallback_filename="source.pdf",
    )

    assert (destination.target, destination.filename) == ("Shared/reports", "report.pdf")


@pytest.mark.parametrize("service", ("affine", "messenger"))
def test_targeted_source_references_require_target_and_file(service: str) -> None:
    with pytest.raises(FileServiceReferenceError):
        normalize_source_reference(service, "missing-target")
