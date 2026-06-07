"""Smoke tests verifying that all shared fixtures load correctly."""

from __future__ import annotations

from app.models.arc_plan import ArcPlan
from app.models.chapter import Chapter, ChapterDB
from app.models.progress import ReadingProgress


def test_fixtures_load(
    sample_chapters: list[Chapter],
    sample_progress: ReadingProgress,
    sample_arc_plan: ArcPlan,
) -> None:
    """Smoke test: basic assertions that critical fixtures load."""
    assert len(sample_chapters) >= 1
    assert sample_progress.current_chapter == 1
    assert len(sample_arc_plan.episodes) > 0


def test_progress_fixtures(
    sample_progress_mid: ReadingProgress,
    sample_progress_end_chapter: ReadingProgress,
) -> None:
    """Verify the mid-chapter and end-chapter progress fixtures."""
    assert sample_progress_mid.chapter_offset == 0.3
    assert sample_progress_end_chapter.chapter_offset == 0.95


def test_mock_episode_cache(mock_episode_cache) -> None:
    """Verify the mock episode cache has a load method."""
    assert hasattr(mock_episode_cache, "load")
    assert callable(mock_episode_cache.load)


def test_empty_chapter_db(empty_chapter_db: ChapterDB) -> None:
    """Verify empty chapter DB has no chapters."""
    assert empty_chapter_db.chapters == []
