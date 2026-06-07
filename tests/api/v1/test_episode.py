"""Tests for app.api.v1.episode — episode retrieval and cache status.

Ref: AGENTS.md §16 (Testing Standards).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient


# ── Helpers ───────────────────────────────────────────────────────────────


def _make_episode_json(episode_id: int) -> str:
    """Build a minimal valid FormatSpec v3 episode as a JSON string."""
    return json.dumps(
        {
            "meta": {
                "ep": episode_id,
                "title": f"Episode {episode_id}",
                "kind": "main",
            },
            "messages": [
                {
                    "type": "narration",
                    "text": "Something happened.",
                    "marks": [
                        {
                            "word": "something",
                            "index": 0,
                            "definition": "某事",
                            "is_new": True,
                        }
                    ],
                },
                {
                    "type": "dialogue",
                    "side": "right",
                    "name": "Kazuhiko",
                    "text": "I understand.",
                    "marks": [],
                },
            ],
            "vocab": [{"word": "something", "definition": "某事", "is_new": True}],
        }
    )


# ── Tests: GET /cache/status ──────────────────────────────────────────────


class TestCacheStatus:
    """Tests for ``GET /api/v1/episode/cache/status``."""

    @pytest.mark.anyio
    async def test_cache_status_empty_dir(self, tmp_path: Path) -> None:
        """Returns zero counts for an empty cache directory."""
        from app.api.v1.episode import get_episode_cache_dir
        from app.main import app

        cache_dir = tmp_path / "EpisodeCache"
        cache_dir.mkdir()

        app.dependency_overrides[get_episode_cache_dir] = lambda: cache_dir

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/v1/episode/cache/status")
            assert resp.status_code == 200
            data = resp.json()
            assert data["cached_count"] == 0
            assert data["latest_episode_id"] is None

        app.dependency_overrides.clear()

    @pytest.mark.anyio
    async def test_cache_status_with_episodes(self, tmp_path: Path) -> None:
        """Returns correct counts when episodes exist."""
        from app.api.v1.episode import get_episode_cache_dir
        from app.main import app

        cache_dir = tmp_path / "EpisodeCache"
        cache_dir.mkdir()

        # Create episode files
        (cache_dir / "ep_0001.json").write_text(_make_episode_json(1))
        (cache_dir / "ep_0005.json").write_text(_make_episode_json(5))
        (cache_dir / "ep_0010.json").write_text(_make_episode_json(10))
        # Add a non-episode file that should be ignored
        (cache_dir / "index.json").write_text("{}")

        app.dependency_overrides[get_episode_cache_dir] = lambda: cache_dir

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/v1/episode/cache/status")
            assert resp.status_code == 200
            data = resp.json()
            assert data["cached_count"] == 3
            assert data["latest_episode_id"] == 10

        app.dependency_overrides.clear()

    @pytest.mark.anyio
    async def test_cache_status_missing_dir(self, tmp_path: Path) -> None:
        """Returns zero counts when cache directory does not exist."""
        from app.api.v1.episode import get_episode_cache_dir
        from app.main import app

        cache_dir = tmp_path / "nonexistent"

        app.dependency_overrides[get_episode_cache_dir] = lambda: cache_dir

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/v1/episode/cache/status")
            assert resp.status_code == 200
            data = resp.json()
            assert data["cached_count"] == 0
            assert data["latest_episode_id"] is None

        app.dependency_overrides.clear()


# ── Tests: GET /{episode_id} ──────────────────────────────────────────────


class TestGetEpisode:
    """Tests for ``GET /api/v1/episode/{episode_id}``."""

    @pytest.mark.anyio
    async def test_get_episode_success(self, tmp_path: Path) -> None:
        """Returns a valid FormatSpec v3 episode."""
        from app.api.v1.episode import get_episode_cache_dir
        from app.main import app

        cache_dir = tmp_path / "EpisodeCache"
        cache_dir.mkdir()
        (cache_dir / "ep_0003.json").write_text(_make_episode_json(3))

        app.dependency_overrides[get_episode_cache_dir] = lambda: cache_dir

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/v1/episode/3")
            assert resp.status_code == 200
            data = resp.json()

            # Verify FormatSpec v3 structure
            assert "meta" in data
            assert "messages" in data
            assert "vocab" in data
            assert data["meta"]["ep"] == 3
            assert data["meta"]["kind"] == "main"
            assert len(data["messages"]) == 2
            assert data["messages"][0]["type"] == "narration"
            assert data["messages"][1]["type"] == "dialogue"
            assert data["messages"][1]["side"] == "right"

        app.dependency_overrides.clear()

    @pytest.mark.anyio
    async def test_get_episode_not_found(self, tmp_path: Path) -> None:
        """Returns 404 when episode does not exist."""
        from app.api.v1.episode import get_episode_cache_dir
        from app.main import app

        cache_dir = tmp_path / "EpisodeCache"
        cache_dir.mkdir()

        app.dependency_overrides[get_episode_cache_dir] = lambda: cache_dir

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/v1/episode/999")
            assert resp.status_code == 404

        app.dependency_overrides.clear()

    @pytest.mark.anyio
    async def test_get_episode_missing_cache_dir(self, tmp_path: Path) -> None:
        """Returns 404 when cache directory does not exist."""
        from app.api.v1.episode import get_episode_cache_dir
        from app.main import app

        cache_dir = tmp_path / "nonexistent"

        app.dependency_overrides[get_episode_cache_dir] = lambda: cache_dir

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/v1/episode/1")
            assert resp.status_code == 404

        app.dependency_overrides.clear()

    @pytest.mark.anyio
    async def test_get_episode_marks_index_is_word_index(self, tmp_path: Path) -> None:
        """Verify that marks.index follows 0-based word index (split)."""
        from app.api.v1.episode import get_episode_cache_dir
        from app.main import app

        cache_dir = tmp_path / "EpisodeCache"
        cache_dir.mkdir()

        # Episode with mark that we can verify
        ep_json = json.dumps(
            {
                "meta": {"ep": 1, "title": "Test", "kind": "main"},
                "messages": [
                    {
                        "type": "narration",
                        "text": "The bank said the bank was closed.",
                        "marks": [
                            {
                                "word": "bank",
                                "index": 1,
                                "definition": "银行",
                                "is_new": True,
                            },
                            {
                                "word": "bank",
                                "index": 4,
                                "definition": "河岸",
                                "is_new": True,
                            },
                        ],
                    },
                ],
                "vocab": [
                    {"word": "bank", "definition": "银行", "is_new": True},
                    {"word": "bank", "definition": "河岸", "is_new": True},
                ],
            }
        )
        (cache_dir / "ep_0001.json").write_text(ep_json)

        app.dependency_overrides[get_episode_cache_dir] = lambda: cache_dir

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/v1/episode/1")
            assert resp.status_code == 200
            data = resp.json()

            marks = data["messages"][0]["marks"]
            text = data["messages"][0]["text"]
            # Verify split-index correspondence
            assert text.split(" ")[marks[0]["index"]] == marks[0]["word"]
            assert text.split(" ")[marks[1]["index"]] == marks[1]["word"]

        app.dependency_overrides.clear()
