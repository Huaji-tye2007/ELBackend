"""Tests for Arc generation endpoints.

Covers:
- POST /api/v1/arc/generate
- GET /api/v1/arc/status

Ref: AGENTS.md §10 — endpoint table, §14 — Async Task Architecture.
"""

import pytest
from httpx import AsyncClient

from tests.api.v1.conftest import _MockArcGenerationManager


# ---------------------------------------------------------------------------
# POST /api/v1/arc/generate
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_arc_generate(client: AsyncClient) -> None:
    """POST /arc/generate should return {job_id, status: "queued"}."""
    response = await client.post("/api/v1/arc/generate", json={})

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "queued"
    assert "job_id" in data
    assert len(data["job_id"]) > 0


@pytest.mark.anyio
async def test_arc_generate_passes_chapter_list(
    client: AsyncClient, mock_arc_manager: _MockArcGenerationManager
) -> None:
    """POST /arc/generate should pass list[Chapter], not ChapterDB, to the manager."""
    response = await client.post("/api/v1/arc/generate", json={})

    assert response.status_code == 200
    call = mock_arc_manager._generate_calls[-1]
    chapters = call["chapters"]
    assert isinstance(chapters, list)
    assert chapters
    assert hasattr(chapters[0], "chapter_id")


@pytest.mark.anyio
async def test_arc_generate_with_custom_id(client: AsyncClient) -> None:
    """POST /arc/generate with arc_id should queue successfully."""
    payload = {"arc_id": "my_custom_arc"}

    response = await client.post("/api/v1/arc/generate", json=payload)

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "queued"


@pytest.mark.anyio
async def test_arc_generate_conflict_409(
    client: AsyncClient, mock_arc_manager: _MockArcGenerationManager
) -> None:
    """POST /arc/generate when already generating should return 409."""
    # First call succeeds
    await client.post("/api/v1/arc/generate", json={})

    # Second call should conflict
    response = await client.post("/api/v1/arc/generate", json={})

    assert response.status_code == 409
    data = response.json()
    assert "already" in data["detail"].lower()


# ---------------------------------------------------------------------------
# GET /api/v1/arc/status
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_arc_status(client: AsyncClient) -> None:
    """GET /arc/status should return ArcGenerationState with 200."""
    response = await client.get("/api/v1/arc/status")

    assert response.status_code == 200
    data = response.json()
    assert "arc_id" in data
    assert "phase" in data
    assert "progress" in data
    assert "retry_count" in data
    assert "elapsed_seconds" in data
    assert "estimated_remaining_seconds" in data
