from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.messenger import native_resources as resource_attachments


@pytest.mark.asyncio
@pytest.mark.parametrize("allowed,managed", [(True, True), (False, True), (True, False)])
async def test_internal_attachment_requires_human_and_receiving_agent_access(monkeypatch, allowed, managed):
    uri = "file://00000000-0000-4000-8000-000000000001"
    info = AsyncMock(return_value=True)
    monkeypatch.setattr(resource_attachments, "resource_accessible", info)
    monkeypatch.setattr(resource_attachments, "check_privilege", AsyncMock(return_value=allowed))
    monkeypatch.setattr(resource_attachments, "get_db", Mock())
    monkeypatch.setattr(resource_attachments.user_service, "get_current_user", AsyncMock(return_value=Mock()))
    monkeypatch.setattr(resource_attachments, "current_management_scope", AsyncMock(return_value=SimpleNamespace(allows=lambda agent_id: managed and agent_id == 7)))
    if allowed and managed:
        assert await resource_attachments.prepare_resource_attachments([uri, uri], agent_id=7) == [uri]
        info.assert_awaited_once()
        assert info.await_args.args[0].agent_id == 7
        info.return_value = False
        with pytest.raises(PermissionError):
            await resource_attachments.prepare_resource_attachments([uri], agent_id=7)
    else:
        with pytest.raises(PermissionError):
            await resource_attachments.prepare_resource_attachments([uri], agent_id=7)
        info.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind,privilege", [("process", "PROCESS_READ"), ("code", "CODE_ACCESS"), ("agent", "AGENT_ACCESS")])
async def test_business_attachments_require_their_domain_privilege(monkeypatch, kind, privilege):
    uri = f"galaris://{kind}/" + ("7" if kind == "agent" else "00000000-0000-4000-8000-000000000001")
    async def check(_user, required, _db):
        return privilege in required
    monkeypatch.setattr(resource_attachments, "check_privilege", check)
    monkeypatch.setattr(resource_attachments, "get_db", Mock())
    monkeypatch.setattr(resource_attachments.user_service, "get_current_user", AsyncMock(return_value=Mock()))
    monkeypatch.setattr(resource_attachments, "resource_accessible", AsyncMock(return_value=True))
    assert await resource_attachments.prepare_resource_attachments([uri], agent_id=7) == [uri]
