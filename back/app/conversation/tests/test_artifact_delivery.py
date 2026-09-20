from unittest.mock import AsyncMock

import pytest

from app.agent.contracts import WorkingResource, WorkingSet
from app.conversation.artifact_delivery import (
    clean_artifact_references,
    presented_artifacts,
    resolve_presented_artifacts,
)
from app.file_share import ResourceContext, ResourceDescriptor


@pytest.mark.parametrize("connection,destination,uri,delivered,expected", [
    (7, "room", "chat://room/image", True, True),
    (8, "room", "chat://room/image", True, False),
    (7, "another-room", "chat://room/image", True, False),
    (7, "room", "chat://room/image-longer", True, False),
    (7, "room", "chat://room/image", False, False),
])
def test_delivery_receipt_matches_exact_resource_and_destination(connection, destination, uri, delivered, expected):
    from app.conversation.artifact_delivery import PresentedArtifact, was_delivered_to_room

    receipt = WorkingResource(resource_type="delivery_receipt", role="delivery_receipt:upload",
        reference=uri, metadata={"connection_id": connection, "destination": destination,
                                 "uri": uri, "delivered": delivered})
    assert was_delivered_to_room(WorkingSet(resources=[receipt]),
        PresentedArtifact(source_uri="chat://room/image", name="image.png"), 7, ("room",)) is expected


def _resource(reference: str, *, role: str = "file:output") -> WorkingResource:
    return WorkingResource(
        resource_type="artifact",
        role=role,
        reference=reference,
        label="index.html",
        metadata={"produced": True},
    )


def test_bare_filename_resolves_to_the_unique_verified_console_file() -> None:
    artifacts = presented_artifacts(
        WorkingSet(resources=[_resource("console://site/index.html")]),
        "Le fichier index.html est prêt.",
    )

    assert [(item.source_uri, item.name) for item in artifacts] == [
        ("console://site/index.html", "index.html")
    ]


def test_exact_provider_uri_selects_the_final_copy_without_duplicate_source() -> None:
    artifacts = presented_artifacts(
        WorkingSet(
            resources=[
                _resource("console://site/index.html"),
                _resource(
                    "nextcloud://room/attachment",
                    role="final_artifact",
                ),
            ]
        ),
        "Téléchargement : nextcloud://room/attachment",
    )

    assert [(item.source_uri, item.name) for item in artifacts] == [
        ("nextcloud://room/attachment", "index.html")
    ]


def test_unverified_filename_is_not_projected() -> None:
    assert presented_artifacts(WorkingSet(), "Téléchargez index.html") == ()


def test_cleaning_replaces_provider_and_sandbox_links_after_delivery() -> None:
    artifacts = presented_artifacts(
        WorkingSet(resources=[_resource("console://site/index.html")]),
        "[Voir](sandbox:/mnt/data/index.html) — console://site/index.html",
    )

    assert clean_artifact_references(
        "[Voir](sandbox:/mnt/data/index.html) — console://site/index.html",
        artifacts,
    ) == "Voir — index.html"


@pytest.mark.asyncio
async def test_existing_bare_filename_falls_back_to_console(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.conversation import artifact_delivery

    info = AsyncMock(
        return_value=ResourceDescriptor(
            uri="console://index.html",
            name="index.html",
            media_type="text/html",
            size=12,
        )
    )
    monkeypatch.setattr(artifact_delivery, "resource_info", info)

    artifacts = await resolve_presented_artifacts(
        ResourceContext(
            agent_id=7,
            runtime="internal",
            console_resource=object(),
        ),
        WorkingSet(),
        "Le fichier index.html est prêt.",
    )

    assert [(item.source_uri, item.name) for item in artifacts] == [
        ("console://index.html", "index.html")
    ]
    assert info.await_args.args[1] == "console://index.html"


@pytest.mark.asyncio
async def test_bare_filename_has_no_local_fallback_without_a_console(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.conversation import artifact_delivery

    info = AsyncMock()
    monkeypatch.setattr(artifact_delivery, "resource_info", info)

    artifacts = await resolve_presented_artifacts(
        ResourceContext(agent_id=7, runtime="internal"),
        WorkingSet(),
        "Le fichier index.html est prêt.",
    )

    assert artifacts == ()
    info.assert_not_awaited()


@pytest.mark.asyncio
async def test_exact_provider_uri_is_resolved_without_a_console(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.conversation import artifact_delivery

    uri = "nextcloud://Shared/index.html"
    info = AsyncMock(
        return_value=ResourceDescriptor(
            uri=uri,
            name="index.html",
            media_type="text/html",
            size=12,
        )
    )
    monkeypatch.setattr(artifact_delivery, "resource_info", info)

    artifacts = await resolve_presented_artifacts(
        ResourceContext(agent_id=7, runtime="internal"),
        WorkingSet(),
        f"Le fichier est prêt : {uri}",
    )

    assert [(item.source_uri, item.name) for item in artifacts] == [
        (uri, "index.html")
    ]
    info.assert_awaited_once()
