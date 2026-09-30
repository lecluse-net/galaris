"""The Agent storage boundary keeps compact, correctly oriented avatars."""

import io
from uuid import uuid4

import pytest
from PIL import Image

from app.agent.avatars import normalize_avatar
from app.agent.models import Agent, Title
from core.database import get_db_session


def encode(image, format="PNG", **options):
    output = io.BytesIO()
    image.save(output, format=format, **options)
    return output.getvalue()


@pytest.mark.parametrize("format", ["PNG", "JPEG", "GIF", "WEBP"])
@pytest.mark.parametrize("size,expected", [((1200, 600), (512, 256)), ((300, 900), (171, 512)), ((80, 40), (80, 40))])
def test_avatar_storage_is_jpeg_bounded_and_preserves_proportions(format, size, expected):
    content = encode(Image.new("RGB", size, "blue"), format)
    with Image.open(io.BytesIO(normalize_avatar(content))) as result:
        assert result.format == "JPEG" and result.mode == "RGB"
        assert result.size == expected
        assert result.getpixel((result.width // 2, result.height // 2))[2] > 250


@pytest.mark.parametrize("mode,format", [("RGBA", "PNG"), ("P", "PNG"), ("P", "GIF")])
def test_transparency_becomes_white_and_metadata_is_removed(mode, format):
    image = Image.new("RGBA", (20, 30), (255, 0, 0, 0))
    if mode == "P":
        image = image.convert("P")
    options = {"transparency": image.getpixel((0, 0))} if format == "GIF" else {}
    content = encode(image, format, **options)
    with Image.open(io.BytesIO(normalize_avatar(content))) as result:
        assert result.size == (20, 30)
        assert result.getpixel((10, 15)) == (255, 255, 255)
        assert not result.getexif()


def test_exif_orientation_is_applied_before_resizing_and_private_metadata_is_stripped():
    image = Image.new("RGB", (1200, 600), "red")
    exif = Image.Exif()
    exif[274] = 6  # Rotate 90 degrees clockwise.
    exif[270] = "Synthetic camera metadata"
    content = encode(image, "JPEG", exif=exif)
    with Image.open(io.BytesIO(normalize_avatar(content))) as result:
        assert result.format == "JPEG" and result.size == (256, 512)
        assert not result.getexif()


def test_animated_image_is_stored_as_a_single_static_portrait():
    first = Image.new("RGB", (20, 30), "red")
    content = encode(first, "GIF", save_all=True, append_images=[Image.new("RGB", (20, 30), "blue")])
    with Image.open(io.BytesIO(normalize_avatar(content))) as result:
        assert result.format == "JPEG" and getattr(result, "n_frames", 1) == 1
        assert result.getpixel((10, 15))[0] > 250


@pytest.mark.asyncio
async def test_http_post_stores_a_compact_jpeg_and_rejects_invalid_replacement(client, monkeypatch):
    from core import settings

    monkeypatch.setattr(settings, "APP_HOST", "http://localhost")
    credentials = {"email": f"avatar-{uuid4().hex}@example.com", "password": "Synthetic-avatar-password-42!"}
    registered = await client.post("/api/auth/register", json=credentials)
    assert registered.status_code == 201, registered.text
    login = await client.post("/api/auth/login-json", json=credentials)
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    owner_id = (await client.get("/api/auth/me", headers=headers)).json()["id"]
    async with get_db_session() as db:
        title = Title(label="Synthetic portrait", gender="F")
        db.add(title)
        await db.flush()
        agent = Agent(user_id=owner_id, title_id=title.id, code=f"portrait-{uuid4().hex}", first_name="Synthetic", last_name="Portrait")
        db.add(agent)
        await db.flush()
        agent_id = agent.id

    # An uncompressed synthetic PNG reproduces a multi-megabyte avatar upload.
    source = encode(Image.new("RGB", (2048, 1536), "blue"), compress_level=0)
    assert len(source) > 8 * 1024 * 1024
    url = f"/api/agents/{agent_id}/avatar"
    assert (await client.post(url, files={"file": ("portrait.png", source, "image/png")})).status_code in {401, 403}
    uploaded = await client.post(url, headers=headers, files={"file": ("portrait.png", source, "image/png")})
    assert uploaded.status_code == 204, uploaded.text
    response = await client.get(url, headers=headers)
    assert response.status_code == 200 and response.headers["content-type"] == "image/jpeg"
    assert len(response.content) < len(source) // 100
    with Image.open(io.BytesIO(response.content)) as result:
        assert result.format == "JPEG" and result.size == (512, 384)
    metadata = (await client.get(f"/api/agents/{agent_id}", headers=headers)).json()
    revision = metadata["avatar_revision"]
    invalid = await client.post(url, headers=headers, files={"file": ("invalid.png", b"invalid image", "image/png")})
    assert invalid.status_code == 400
    assert (await client.get(url, headers=headers)).content == response.content
    assert (await client.get(f"/api/agents/{agent_id}", headers=headers)).json()["avatar_revision"] == revision
