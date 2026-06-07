"""Tests for dictionary endpoint.

Covers:
- GET /api/v1/dictionary/{word}

Ref: AGENTS.md §10 — endpoint table, §6 — ECDICT lookup.
"""

import pytest
from httpx import AsyncClient


# ---------------------------------------------------------------------------
# GET /api/v1/dictionary/{word}
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_dictionary_lookup_found(client: AsyncClient) -> None:
    """GET /dictionary/{word} with a known word should return 200 with meaning."""
    response = await client.get("/api/v1/dictionary/test")

    assert response.status_code == 200
    data = response.json()
    assert data["word"] == "test"
    assert data["meaning"] == "测试"


@pytest.mark.anyio
async def test_dictionary_lookup_another(client: AsyncClient) -> None:
    """GET /dictionary/{word} with 'bank' should return meaning."""
    response = await client.get("/api/v1/dictionary/bank")

    assert response.status_code == 200
    data = response.json()
    assert data["word"] == "bank"
    assert "银行" in data["meaning"] or "河岸" in data["meaning"]


@pytest.mark.anyio
async def test_dictionary_word_not_found(client: AsyncClient) -> None:
    """GET /dictionary/{word} with an unknown word should return 404."""
    response = await client.get("/api/v1/dictionary/nonexistent_word_xyz")

    assert response.status_code == 404
    data = response.json()
    assert "not found" in data["detail"].lower()
