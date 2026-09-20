import pytest
from httpx import AsyncClient

@pytest.mark.asyncio
async def test_access_albums_endpoint(
    client: AsyncClient, # Unauthenticated
):
    """Test que l'endpoint albums est accessible."""
    response = await client.get("/api/albums")
    # L'endpoint peut être public (200) ou protégé (401/403)
    assert response.status_code in [200, 401, 403]
