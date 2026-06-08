"""Tests for reading endpoints.

Covers:
- GET /api/v1/reading/progress
- POST /api/v1/reading/log
- POST /api/v1/reading/finish

Ref: AGENTS.md §10 — endpoint table, §16.8 — route testing.
"""

import pytest
from httpx import AsyncClient

from tests.api.v1.conftest import _MockReadingTracker


# ---------------------------------------------------------------------------
# GET /api/v1/reading/progress
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_get_progress(client: AsyncClient) -> None:
    """GET /progress should return the current ReadingProgress with 200."""
    response = await client.get("/api/v1/reading/progress")

    assert response.status_code == 200
    data = response.json()
    assert data["current_chapter"] == 1
    assert data["current_episode"] == 1
    assert data["chapter_offset"] == 0.0
    assert data["total_episodes_read"] == 0


@pytest.mark.anyio
async def test_get_progress_compat_route(client: AsyncClient) -> None:
    """GET /api/v1/progress should remain available for the documented contract."""
    response = await client.get("/api/v1/progress")

    assert response.status_code == 200
    data = response.json()
    assert data["current_chapter"] == 1
    assert data["current_episode"] == 1


# ---------------------------------------------------------------------------
# POST /api/v1/reading/log
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_log_reading(client: AsyncClient) -> None:
    """POST /reading/log should accept EpisodeReadingLog and return {updated: true}."""
    payload = {
        "episode_id": 1,
        "word_logs": [
            {"item_id": "hello_1", "appeared": 3, "clicked": 1},
            {"item_id": "world_1", "appeared": 2, "clicked": 0},
        ],
    }

    response = await client.post("/api/v1/reading/log", json=payload)

    assert response.status_code == 200
    data = response.json()
    assert data["updated"] is True


@pytest.mark.anyio
async def test_log_reading_invalid_clicked(
    client: AsyncClient, mock_reading_tracker: _MockReadingTracker
) -> None:
    """POST /reading/log with clicked > appeared should return 422 (Pydantic validation)."""
    payload = {
        "episode_id": 1,
        "word_logs": [
            {"item_id": "hello_1", "appeared": 1, "clicked": 5},
        ],
    }

    response = await client.post("/api/v1/reading/log", json=payload)

    assert response.status_code == 422


@pytest.mark.anyio
async def test_log_reading_missing_episode_id(client: AsyncClient) -> None:
    """POST /reading/log without episode_id should return 422."""
    payload = {
        "word_logs": [
            {"item_id": "hello_1", "appeared": 3, "clicked": 1},
        ],
    }

    response = await client.post("/api/v1/reading/log", json=payload)

    assert response.status_code == 422


# ---------------------------------------------------------------------------
# POST /api/v1/reading/finish
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_finish_episode(
    client: AsyncClient,
    mock_reading_tracker: _MockReadingTracker,
    seeded_storage_for_finish,
) -> None:
    """POST /reading/finish should trigger evaluation and return vocab_updated_count."""
    # First log a reading
    log_payload = {
        "episode_id": 1,
        "word_logs": [
            {"item_id": "hello_1", "appeared": 3, "clicked": 1},
        ],
    }
    await client.post("/api/v1/reading/log", json=log_payload)

    # Then finish
    finish_payload = {"episode_id": 1}
    response = await client.post("/api/v1/reading/finish", json=finish_payload)

    assert response.status_code == 200
    data = response.json()
    assert data["vocab_updated_count"] == 1


@pytest.mark.anyio
async def test_finish_episode_no_log(
    client: AsyncClient,
    mock_reading_tracker: _MockReadingTracker,
    seeded_storage_for_finish,
) -> None:
    """POST /reading/finish without a prior log should return 404."""
    finish_payload = {"episode_id": 999}

    response = await client.post("/api/v1/reading/finish", json=finish_payload)

    assert response.status_code == 404
    data = response.json()
    assert "no reading log found" in data["detail"].lower()


@pytest.mark.anyio
async def test_finish_episode_no_vocabulary(client: AsyncClient) -> None:
    """POST /reading/finish without vocabulary data should return 404."""
    # Log a reading first (storage is empty — cold start)
    log_payload = {
        "episode_id": 1,
        "word_logs": [
            {"item_id": "hello_1", "appeared": 3, "clicked": 1},
        ],
    }
    await client.post("/api/v1/reading/log", json=log_payload)

    finish_payload = {"episode_id": 1}
    response = await client.post("/api/v1/reading/finish", json=finish_payload)

    assert response.status_code == 404
    data = response.json()
    assert "no vocabulary data found" in data["detail"].lower()


@pytest.mark.anyio
async def test_finish_episode_invalid_id(client: AsyncClient) -> None:
    """POST /reading/finish with invalid episode_id should return 422."""
    finish_payload = {"episode_id": 0}

    response = await client.post("/api/v1/reading/finish", json=finish_payload)

    assert response.status_code == 422
