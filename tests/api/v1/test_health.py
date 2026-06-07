"""Tests for GET /health endpoint.

Ref: AGENTS.md §10 — endpoint table, §16.8 — route testing.
"""

import pytest
from httpx import AsyncClient


@pytest.mark.anyio
async def test_health_returns_200(client: AsyncClient) -> None:
    """GET /health should return 200 with {"status": "ok"}.

    The health endpoint has no dependencies and should always succeed.
    """
    response = await client.get("/api/v1/health")

    assert response.status_code == 200
    data = response.json()
    assert data == {"status": "ok"}
