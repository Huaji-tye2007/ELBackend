"""Tests for vocabulary endpoints.

Covers:
- POST /api/v1/vocabulary/upload
- GET /api/v1/vocabulary
- GET /api/v1/vocabulary/{item_id}

Ref: AGENTS.md §10 — endpoint table, §15.2 — exception translation.
"""

import pytest
from httpx import AsyncClient


# ---------------------------------------------------------------------------
# POST /api/v1/vocabulary/upload
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_upload_vocabulary(client: AsyncClient) -> None:
    """POST /vocabulary/upload with valid data should return count of items created."""
    payload = {
        "user_id": "user_001",
        "items": [
            {"word": "hello", "meaning": "你好"},
            {"word": "world", "meaning": "世界"},
        ],
    }

    response = await client.post("/api/v1/vocabulary/upload", json=payload)

    assert response.status_code == 200
    data = response.json()
    assert data["count"] == 2


@pytest.mark.anyio
async def test_upload_vocabulary_empty_items(client: AsyncClient) -> None:
    """POST /vocabulary/upload with empty items list should return 422 (validation error)."""
    payload = {
        "user_id": "user_001",
        "items": [],
    }

    response = await client.post("/api/v1/vocabulary/upload", json=payload)

    assert response.status_code == 422


@pytest.mark.anyio
async def test_upload_vocabulary_missing_user_id(client: AsyncClient) -> None:
    """POST /vocabulary/upload without user_id should return 422."""
    payload = {
        "items": [
            {"word": "hello", "meaning": "你好"},
        ],
    }

    response = await client.post("/api/v1/vocabulary/upload", json=payload)

    assert response.status_code == 422


# ---------------------------------------------------------------------------
# GET /api/v1/vocabulary
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_get_all_vocabulary_empty(client: AsyncClient) -> None:
    """GET /vocabulary with no saved data should return empty vocabulary (200)."""
    response = await client.get("/api/v1/vocabulary")

    assert response.status_code == 200
    data = response.json()
    assert data["user_id"] == "default"
    assert data["vocabulary"] == []


@pytest.mark.anyio
async def test_get_all_vocabulary_seeded(client: AsyncClient, seeded_storage) -> None:
    """GET /vocabulary with pre-seeded data should return all 3 items."""
    response = await client.get("/api/v1/vocabulary")

    assert response.status_code == 200
    data = response.json()
    assert data["user_id"] == "test_user"
    assert len(data["vocabulary"]) == 3


# ---------------------------------------------------------------------------
# GET /api/v1/vocabulary/{item_id}
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_get_single_vocabulary(client: AsyncClient, seeded_storage) -> None:
    """GET /vocabulary/{item_id} should return a single VocabularyItem."""
    response = await client.get("/api/v1/vocabulary/word_1")

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == "word_1"
    assert data["word"] == "test"
    assert data["meaning"] == "测试"


@pytest.mark.anyio
async def test_get_single_vocabulary_polysemy(
    client: AsyncClient, seeded_storage
) -> None:
    """GET /vocabulary/{item_id} should distinguish polysemous items by item_id."""
    # bank_river (河岸)
    response = await client.get("/api/v1/vocabulary/bank_river")
    assert response.status_code == 200
    assert response.json()["meaning"] == "河岸"

    # bank_finance (银行)
    response = await client.get("/api/v1/vocabulary/bank_finance")
    assert response.status_code == 200
    assert response.json()["meaning"] == "银行"


@pytest.mark.anyio
async def test_get_nonexistent_vocabulary_returns_404(
    client: AsyncClient, seeded_storage
) -> None:
    """GET /vocabulary/nonexistent should return 404."""
    response = await client.get("/api/v1/vocabulary/nonexistent_item")

    assert response.status_code == 404
    data = response.json()
    assert "not found" in data["detail"].lower()


@pytest.mark.anyio
async def test_get_vocabulary_empty_storage_returns_404(client: AsyncClient) -> None:
    """GET /vocabulary/{item_id} with no saved data should return 404."""
    response = await client.get("/api/v1/vocabulary/anything")

    assert response.status_code == 404
