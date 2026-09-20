"""The retired generic webhook must not accept or dispatch requests."""

import pytest


@pytest.mark.asyncio
async def test_legacy_webhook_is_unavailable(client):
    for headers in ({}, {"Authorization": "Bearer obsolete-shared-token"}):
        response = await client.post('/api/webhook/anything', json={}, headers=headers)
        assert response.status_code == 404
    assert (await client.get('/api/webhook/health')).status_code == 404
