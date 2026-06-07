"""Tests for app.api.v1.novel — novel upload, list, and retrieve endpoints.

Ref: AGENTS.md §16 (Testing Standards).
"""

from __future__ import annotations

from unittest import mock

import pytest
from httpx import ASGITransport, AsyncClient

from app.db.storage import JSONStorage
from app.models.chapter import Chapter, ChapterDB


# ── Helpers ───────────────────────────────────────────────────────────────


def _make_mock_storage() -> mock.MagicMock:
    """Create a MagicMock that looks like JSONStorage[ChapterDB]."""
    storage = mock.MagicMock(spec=JSONStorage)
    return storage


def _make_sample_chapter(chapter_id: int) -> Chapter:
    """Build a minimal Chapter for test assertions."""
    return Chapter(
        chapter_id=chapter_id,
        title=f"Chapter {chapter_id}",
        raw_text=f"Test content for chapter {chapter_id}.",
        summary=f"Summary of chapter {chapter_id}.",
        characters=["Alice", "Bob"],
        world_setting="Test World",
        estimated_reading_time=5,
    )


def _make_sample_chapter_db(count: int = 3) -> ChapterDB:
    """Build a ChapterDB with *count* sample chapters."""
    return ChapterDB(chapters=[_make_sample_chapter(i) for i in range(1, count + 1)])


# ── Tests: GET /chapters ──────────────────────────────────────────────────


class TestGetChapters:
    """Tests for ``GET /api/v1/novel/chapters``."""

    @pytest.mark.anyio
    async def test_get_chapters_empty(self) -> None:
        """Returns empty list when no novel has been uploaded."""
        from app.api.v1.novel import get_chapter_storage
        from app.main import app

        storage = _make_mock_storage()
        storage.load.side_effect = FileNotFoundError

        app.dependency_overrides[get_chapter_storage] = lambda: storage

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/v1/novel/chapters")
            assert resp.status_code == 200
            data = resp.json()
            assert data == []

        app.dependency_overrides.clear()

    @pytest.mark.anyio
    async def test_get_chapters_returns_list(self) -> None:
        """Returns list of chapter summaries (without raw_text)."""
        from app.api.v1.novel import get_chapter_storage
        from app.main import app

        db = _make_sample_chapter_db(3)
        storage = _make_mock_storage()
        storage.load.return_value = db

        app.dependency_overrides[get_chapter_storage] = lambda: storage

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/v1/novel/chapters")
            assert resp.status_code == 200
            data = resp.json()
            assert len(data) == 3
            # Each entry should NOT have raw_text
            for entry in data:
                assert "raw_text" not in entry
                assert "chapter_id" in entry
                assert "title" in entry
                assert "summary" in entry

        app.dependency_overrides.clear()


# ── Tests: GET /chapters/{chapter_id} ─────────────────────────────────────


class TestGetChapterById:
    """Tests for ``GET /api/v1/novel/chapters/{chapter_id}``."""

    @pytest.mark.anyio
    async def test_get_chapter_success(self) -> None:
        """Returns a single chapter including raw_text."""
        from app.api.v1.novel import get_chapter_storage
        from app.main import app

        db = _make_sample_chapter_db(3)
        storage = _make_mock_storage()
        storage.load.return_value = db

        app.dependency_overrides[get_chapter_storage] = lambda: storage

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/v1/novel/chapters/2")
            assert resp.status_code == 200
            data = resp.json()
            assert data["chapter_id"] == 2
            assert data["title"] == "Chapter 2"
            assert "raw_text" in data  # single chapter includes raw_text

        app.dependency_overrides.clear()

    @pytest.mark.anyio
    async def test_get_chapter_not_found(self) -> None:
        """Returns 404 when chapter_id does not exist."""
        from app.api.v1.novel import get_chapter_storage
        from app.main import app

        db = _make_sample_chapter_db(2)
        storage = _make_mock_storage()
        storage.load.return_value = db

        app.dependency_overrides[get_chapter_storage] = lambda: storage

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/v1/novel/chapters/999")
            assert resp.status_code == 404

        app.dependency_overrides.clear()

    @pytest.mark.anyio
    async def test_get_chapter_no_novel_uploaded(self) -> None:
        """Returns 404 when no novel DB exists."""
        from app.api.v1.novel import get_chapter_storage
        from app.main import app

        storage = _make_mock_storage()
        storage.load.side_effect = FileNotFoundError

        app.dependency_overrides[get_chapter_storage] = lambda: storage

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/v1/novel/chapters/1")
            assert resp.status_code == 404

        app.dependency_overrides.clear()


# ── Tests: POST /upload ───────────────────────────────────────────────────


class TestUploadNovel:
    """Tests for ``POST /api/v1/novel/upload``."""

    @pytest.mark.anyio
    async def test_upload_novel_success(self) -> None:
        """Upload succeeds and returns chapter_count."""
        from app.api.v1.novel import get_chapter_storage, get_novel_preprocessor
        from app.main import app

        chapters = [_make_sample_chapter(1), _make_sample_chapter(2)]

        # Mock preprocessor
        mock_preprocessor = mock.AsyncMock()
        mock_preprocessor.preprocess.return_value = chapters

        # Mock storage
        mock_storage = mock.MagicMock()

        app.dependency_overrides[get_novel_preprocessor] = lambda: mock_preprocessor
        app.dependency_overrides[get_chapter_storage] = lambda: mock_storage

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/novel/upload",
                json={
                    "title": "Test Novel",
                    "raw_text": "Chapter 1\nOnce upon a time...\n\nChapter 2\nThe end.",
                },
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data == {"chapter_count": 2}

        # Verify preprocessor was called
        mock_preprocessor.preprocess.assert_called_once_with(
            "Test Novel",
            "Chapter 1\nOnce upon a time...\n\nChapter 2\nThe end.",
        )
        # Verify storage.save was called with ChapterDB
        mock_storage.save.assert_called_once()
        saved_db = mock_storage.save.call_args[0][0]
        assert isinstance(saved_db, ChapterDB)
        assert len(saved_db.chapters) == 2

        app.dependency_overrides.clear()

    @pytest.mark.anyio
    async def test_upload_novel_empty_title(self) -> None:
        """Empty title should return 422 (validation error)."""
        from app.api.v1.novel import get_chapter_storage, get_novel_preprocessor
        from app.main import app

        mock_preprocessor = mock.AsyncMock()
        mock_storage = mock.MagicMock()

        app.dependency_overrides[get_novel_preprocessor] = lambda: mock_preprocessor
        app.dependency_overrides[get_chapter_storage] = lambda: mock_storage

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/novel/upload",
                json={"title": "", "raw_text": "Some text."},
            )
            assert resp.status_code == 422  # FastAPI validates Body(min_length=1)

        app.dependency_overrides.clear()

    @pytest.mark.anyio
    async def test_upload_novel_empty_raw_text(self) -> None:
        """Empty raw_text should return 422 (validation error)."""
        from app.api.v1.novel import get_chapter_storage, get_novel_preprocessor
        from app.main import app

        mock_preprocessor = mock.AsyncMock()
        mock_storage = mock.MagicMock()

        app.dependency_overrides[get_novel_preprocessor] = lambda: mock_preprocessor
        app.dependency_overrides[get_chapter_storage] = lambda: mock_storage

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/novel/upload",
                json={"title": "Test", "raw_text": ""},
            )
            assert resp.status_code == 422

        app.dependency_overrides.clear()
