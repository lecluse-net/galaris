from unittest.mock import AsyncMock, Mock

import pytest

from core.params import params_service
from core.params.consts import Params
from core.params.dbadmin import _reload_runtime_params, datasets


@pytest.mark.asyncio
@pytest.mark.parametrize('legacy', [False, True])
async def test_vapid_identity_is_generated_once_ignoring_old_environment(db, monkeypatch, legacy):
    from sqlalchemy import delete, select
    from core.dbadmin import reconcile_dataset
    from core.params.models import Param
    from core.params.web_push import create_vapid_keys, deserialize_vapid_keys, web_push_keys
    from core.util import decrypt_value, encrypt_value
    from core import settings
    from py_vapid import Vapid

    master = settings.ENCRYPTION_MASTER_KEY
    canary = encrypt_value('existing-encrypted-data')
    old = create_vapid_keys()
    monkeypatch.setenv('WEB_PUSH_VAPID_PRIVATE_KEY', old.private_key if legacy else '')
    monkeypatch.setenv('WEB_PUSH_VAPID_PUBLIC_KEY', old.public_key if legacy else '')
    monkeypatch.setenv('WEB_PUSH_VAPID_SUBJECT', 'obsolete-invalid-contact')
    monkeypatch.setenv('WEB_PUSH_DELAY_SECONDS', '999')
    await db.execute(delete(Param).where(Param.name.in_([
        Params.WEB_PUSH_VAPID_KEYS, Params.WEB_PUSH_VAPID_SUBJECT, Params.WEB_PUSH_DELAY_SECONDS,
    ])))
    await reconcile_dataset(db, datasets()[0])
    first = web_push_keys()
    assert first is not None
    assert first != old
    assert await db.scalar(select(Param.value).where(Param.name == Params.WEB_PUSH_VAPID_SUBJECT)) == 'mailto:admin@localhost'
    assert float(await db.scalar(select(Param.value).where(Param.name == Params.WEB_PUSH_DELAY_SECONDS))) == 3.0
    # Exercise the actual sender library's key parser without calling a push provider.
    assert Vapid.from_string(first.private_key).private_key is not None
    encrypted = await db.scalar(select(Param.value).where(Param.name == Params.WEB_PUSH_VAPID_KEYS))
    assert first.private_key not in encrypted
    assert deserialize_vapid_keys(decrypt_value(encrypted)) == first
    monkeypatch.delenv('WEB_PUSH_VAPID_PRIVATE_KEY')
    monkeypatch.delenv('WEB_PUSH_VAPID_PUBLIC_KEY')
    result = await reconcile_dataset(db, datasets()[0])
    await params_service.refresh()
    assert result.inserted == result.updated == result.removed == 0
    assert web_push_keys() == first
    assert decrypt_value(canary) == 'existing-encrypted-data'
    assert settings.ENCRYPTION_MASTER_KEY == master


@pytest.mark.asyncio
@pytest.mark.parametrize('value', [None, 'corrupted-ciphertext', 'encrypted-invalid-pair'])
async def test_invalid_persisted_vapid_identity_never_rotates(db, value):
    from sqlalchemy import select
    from cryptography.fernet import InvalidToken
    from core.dbadmin import reconcile_dataset
    from core.params.models import Param
    from core.util import encrypt_value

    row = await db.scalar(select(Param).where(Param.name == Params.WEB_PUSH_VAPID_KEYS))
    row.value = encrypt_value('{"public_key":"bad","private_key":"bad"}') if value == 'encrypted-invalid-pair' else value
    before = row.value
    with pytest.raises((ValueError, InvalidToken)):
        await reconcile_dataset(db, datasets()[0])
    assert row.value == before


@pytest.mark.asyncio
@pytest.mark.parametrize('legacy', ['missing-private', 'mismatch', 'invalid-private'])
async def test_invalid_old_vapid_variables_do_not_block_initialization(db, monkeypatch, legacy):
    from sqlalchemy import delete, select
    from core.dbadmin import reconcile_dataset
    from core.params.models import Param
    from core.params.web_push import create_vapid_keys

    keys = create_vapid_keys()
    private = '' if legacy == 'missing-private' else ('invalid' if legacy == 'invalid-private' else create_vapid_keys().private_key)
    monkeypatch.setenv('WEB_PUSH_VAPID_PUBLIC_KEY', keys.public_key)
    monkeypatch.setenv('WEB_PUSH_VAPID_PRIVATE_KEY', private)
    await db.execute(delete(Param).where(Param.name == Params.WEB_PUSH_VAPID_KEYS))
    await reconcile_dataset(db, datasets()[0])
    assert await db.scalar(select(Param).where(Param.name == Params.WEB_PUSH_VAPID_KEYS)) is not None


@pytest.mark.asyncio
@pytest.mark.parametrize('valid', [True, False])
async def test_environment_cleanup_requires_valid_internal_keys_but_ignores_old_environment(db, monkeypatch, valid):
    from sqlalchemy import select
    from core.params.internal_secrets import verify_internal_secrets
    from core.params.models import Param
    for name in ('AUTH_SECRET_KEY', 'BROWSER_EXECUTOR_TOKEN', 'WEB_PUSH_VAPID_PRIVATE_KEY', 'WEB_PUSH_VAPID_PUBLIC_KEY'):
        monkeypatch.setenv(name, 'obsolete-and-invalid')
    if not valid:
        row = await db.scalar(select(Param).where(Param.name == Params.WEB_PUSH_VAPID_KEYS))
        row.value = None
    await db.commit()
    if valid:
        await verify_internal_secrets()
    else:
        with pytest.raises(ValueError, match='internal secret is missing'):
            await verify_internal_secrets()


@pytest.mark.asyncio
@pytest.mark.parametrize("legacy", ["", "existing-signing-key-preserved-0000001"])
async def test_internal_signing_key_is_generated_ignoring_environment_and_survives_restart(db, monkeypatch, legacy):
    from jose import jwt
    from sqlalchemy import delete, select
    from core import settings
    from core.dbadmin import reconcile_dataset
    from core.params.models import Param
    from core.secrets import auth_secret_key
    from core.util import decrypt_value, encrypt_value
    from core.user.mfa_service import _recovery_hash

    master = settings.ENCRYPTION_MASTER_KEY
    canary = encrypt_value('preexisting-encrypted-data')
    monkeypatch.setenv('AUTH_SECRET_KEY', legacy)
    await db.execute(delete(Param).where(Param.name == Params.AUTH_SECRET_KEY))
    await reconcile_dataset(db, datasets()[0])
    first = auth_secret_key()
    assert first != legacy
    assert len(first) >= 32
    stored = await db.scalar(select(Param.value).where(Param.name == Params.AUTH_SECRET_KEY))
    assert stored != first and decrypt_value(stored) == first
    token = jwt.encode({'sub': 'existing-session'}, first, algorithm=settings.ALGORITHM)
    recovery = _recovery_hash('recovery-code')
    monkeypatch.delenv('AUTH_SECRET_KEY')
    second = await reconcile_dataset(db, datasets()[0])
    await params_service.refresh()
    assert second.inserted == second.updated == second.removed == 0
    assert auth_secret_key() == first
    assert jwt.decode(token, auth_secret_key(), algorithms=[settings.ALGORITHM])['sub'] == 'existing-session'
    assert _recovery_hash('recovery-code') == recovery
    assert decrypt_value(canary) == 'preexisting-encrypted-data'
    assert settings.ENCRYPTION_MASTER_KEY == master


@pytest.mark.asyncio
@pytest.mark.parametrize('value', [None, 'corrupted-ciphertext'])
async def test_corrupt_internal_signing_key_stops_loading_without_rotating(db, value):
    from sqlalchemy import select
    from core.dbadmin import reconcile_dataset
    from core.params.models import Param
    from cryptography.fernet import InvalidToken

    row = await db.scalar(select(Param).where(Param.name == Params.AUTH_SECRET_KEY))
    row.value = value
    await db.flush()
    with pytest.raises((ValueError, InvalidToken)):
        await reconcile_dataset(db, datasets()[0])
    assert row.value == value


@pytest.mark.asyncio
@pytest.mark.parametrize("existing", ["absent", "custom", "reset"])
@pytest.mark.parametrize('name,legacy_value,custom_value', [
    (Params.BROWSER_VIEWPORT_WIDTH, '800', '1200'),
    (Params.BROWSER_SESSION_TTL_SECONDS, '180', '240'),
    (Params.BROWSER_MAX_SESSIONS, '48', '64'),
    (Params.MESSENGER_MAX_INLINE_MB, '8', '16'),
    (Params.PYDANTIC_AI_BINARY_INPUT_MAX_BYTES, '41943040', '83886080'),
])
async def test_operation_preferences_import_legacy_values_only_for_missing_rows(db, monkeypatch, existing, name, legacy_value, custom_value):
    from sqlalchemy import delete, select
    from core.dbadmin import reconcile_dataset
    from core.params.models import Param
    from core.params import runtime_settings

    monkeypatch.setattr(runtime_settings, name, getattr(runtime_settings, name))
    await db.execute(delete(Param).where(Param.name == name))
    expected = params_service.normalize(name, legacy_value) if existing == 'absent' else (custom_value if existing == 'custom' else None)
    if existing != 'absent':
        db.add(Param(name=name, value=expected))
    await db.flush()
    monkeypatch.setenv(name, legacy_value)
    await reconcile_dataset(db, datasets()[0])
    assert await db.scalar(select(Param.value).where(Param.name == name)) == expected
    # Even a later invalid legacy environment value cannot override a durable preference.
    monkeypatch.setenv(name, 'invalid')
    second = await reconcile_dataset(db, datasets()[0])
    assert second.inserted == second.updated == second.removed == 0
    assert await db.scalar(select(Param.value).where(Param.name == name)) == expected


@pytest.mark.asyncio
@pytest.mark.parametrize('name', [Params.HARNESS_MANAGER_SECRET, Params.LOGFIRE_TOKEN])
async def test_external_secret_is_imported_encrypted_once(db, monkeypatch, name):
    from cryptography.fernet import Fernet
    from sqlalchemy import delete, select
    from core.dbadmin import reconcile_dataset
    from core.params.models import Param
    from core.params import runtime_settings

    monkeypatch.setattr(runtime_settings, name, runtime_settings.HARNESS_MANAGER_SECRET)
    await db.execute(delete(Param).where(Param.name == name))
    secret = Fernet.generate_key().decode()
    monkeypatch.setenv(name, secret)
    await reconcile_dataset(db, datasets()[0])
    stored = await db.scalar(select(Param.value).where(Param.name == name))
    assert stored != secret
    assert params_service.reveal(name, stored) == secret
    monkeypatch.setenv(name, 'invalid')
    await reconcile_dataset(db, datasets()[0])
    assert await db.scalar(select(Param.value).where(Param.name == name)) == stored


@pytest.mark.asyncio
@pytest.mark.parametrize("existing", ["absent", "custom", "reset"])
async def test_compose_default_moves_once_without_overwriting_common_configuration(db, existing):
    from sqlalchemy import delete, select
    from core.dbadmin import reconcile_dataset
    from core.params.models import Param

    await db.execute(delete(Param).where(Param.name.in_(["hermes.default.compose", Params.HARNESS_DEFAULT_COMPOSE])))
    legacy = "services:\n  agent:\n    networks: [agents-net]\n"
    db.add(Param(name="hermes.default.compose", value=legacy))
    expected = legacy if existing == "absent" else ("{}" if existing == "custom" else None)
    if existing != "absent":
        db.add(Param(name=Params.HARNESS_DEFAULT_COMPOSE, value=expected))
    await db.flush()
    await reconcile_dataset(db, datasets()[0])
    assert await db.scalar(select(Param.value).where(Param.name == Params.HARNESS_DEFAULT_COMPOSE)) == expected
    assert await db.scalar(select(Param).where(Param.name == "hermes.default.compose")) is None
    second = await reconcile_dataset(db, datasets()[0])
    assert second.inserted == second.updated == second.removed == 0


@pytest.mark.asyncio
@pytest.mark.parametrize('state', ['missing', 'old-default', 'custom', 'reset'])
async def test_decimal_size_defaults_converge_without_overwriting_custom_limits(db, monkeypatch, state):
    from sqlalchemy import delete, select
    from core.dbadmin import reconcile_dataset
    from core.params.models import Param
    from core.params import runtime_settings

    limits = [
        (Params.MESSENGER_MAX_INLINE_MB, '4', '8', '3.814697265625', 1_048_576, 4_000_000),
        (Params.PYDANTIC_AI_BINARY_INPUT_MAX_BYTES, '20971520', '20971521', '20000000', 1, 20_000_000),
        (Params.MESSENGER_WHATSAPP_WEBHOOK_MAX_BYTES, '1048576', '1048577', '1000000', 1, 1_000_000),
        (Params.PROCESS_SANITIZE_MAX_BYTES, '65536', '65537', '64000', 1, 64_000),
    ]
    for name, old, custom, default, scale, byte_limit in limits:
        monkeypatch.delenv(name, raising=False)
        monkeypatch.setattr(runtime_settings, name, getattr(runtime_settings, name))
        await db.execute(delete(Param).where(Param.name == name))
        if state != 'missing':
            db.add(Param(name=name, value={'old-default': old, 'custom': custom, 'reset': None}[state]))
    await db.flush()
    for _ in range(2):
        await reconcile_dataset(db, datasets()[0])
        for name, old, custom, default, scale, byte_limit in limits:
            expected = custom if state == 'custom' else None if state == 'reset' else default
            assert await db.scalar(select(Param.value).where(Param.name == name)) == expected
            assert getattr(runtime_settings, name) * scale == (float(custom) * scale if state == 'custom' else byte_limit)


def test_shared_hermes_runtime_params_are_removed_by_authoritative_dataset() -> None:
    obsolete = {
        "BRIDGE_HERMES_MODE",
        "BRIDGE_HERMES_URL",
        "BRIDGE_HERMES_SECRET",
        "BRIDGE_HERMES_USERNAME",
        "BRIDGE_HERMES_DATA_ROOT",
        "BRIDGE_HERMES_RUNTIME_URL_TEMPLATE",
    }
    declared = {str(row["name"]) for row in params_service.declared_rows()}

    assert declared.isdisjoint(obsolete)
    assert datasets()[0].delete_missing is True


@pytest.mark.asyncio
async def test_prompt_default_reconciliation_advances_only_followers_and_new_baselines(
    monkeypatch,
) -> None:
    follower = Mock()
    follower.name = Params.AI_PLANNER_SYSTEM_PROMPT
    follower.value = None
    follower.default_digest = "old-default"
    customized = Mock()
    customized.name = Params.AI_TOPIC_CONTINUITY_SYSTEM_PROMPT
    customized.value = "Keep this"
    customized.default_digest = "old-default"
    legacy_customized = Mock()
    legacy_customized.name = Params.AI_TOPIC_RESOLUTION_SYSTEM_PROMPT
    legacy_customized.value = "Existing customization"
    legacy_customized.default_digest = None

    scalars = Mock()
    scalars.all.return_value = [follower, customized, legacy_customized]
    session = AsyncMock()
    session.scalars.return_value = scalars
    refresh = AsyncMock()
    monkeypatch.setattr(params_service, "refresh", refresh)

    await _reload_runtime_params(session, Mock())

    assert follower.default_digest == params_service.prompt_default_digest(follower.name)
    assert customized.default_digest == "old-default"
    assert legacy_customized.default_digest == params_service.prompt_default_digest(
        legacy_customized.name
    )
    session.flush.assert_awaited_once()
    refresh.assert_awaited_once()
