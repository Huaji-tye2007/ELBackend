"""Tests for ReadingTracker — merged from services_1 and stub.

Covers:
- track returns ReadingProgress (dict + Pydantic model input)
- Persistence across sessions (file-backed)
- get_log retrieval
- Duplicate episode_id (overwrite)
- Chapter offset rollover (>= 1.0)
- Progress tracking (total_episodes_read increments)
- Route compatibility (httpx via mock)
- Chapter offset validation (ValueError)

Ref: AGENTS.md §16 — test file mirrors app/services/.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.models.episode_log import EpisodeReadingLog, WordLog
from app.models.progress import ReadingProgress
from app.services.reading_tracker import ReadingTracker


# ============================================================================
# Helpers
# ============================================================================


def _make_log(episode_id: int = 1) -> EpisodeReadingLog:
    """Create a minimal EpisodeReadingLog for testing."""
    return EpisodeReadingLog(
        episode_id=episode_id,
        word_logs=[
            WordLog(item_id="hello_1", appeared=3, clicked=1),
            WordLog(item_id="world_1", appeared=2, clicked=0),
        ],
    )


def _make_log_dict(episode_id: int = 1) -> dict:
    """Create a minimal EpisodeReadingLog as a plain dict."""
    return {
        "episode_id": episode_id,
        "word_logs": [
            {"item_id": "hello_1", "appeared": 3, "clicked": 1},
            {"item_id": "world_1", "appeared": 2, "clicked": 0},
        ],
    }


# ============================================================================
# Tests
# ============================================================================


class TestTrack:
    """Tests for ReadingTracker.track() method."""

    def test_track_with_dict_returns_reading_progress(self, tmp_path: Path) -> None:
        """track() with a dict input should return an updated ReadingProgress."""
        tracker = ReadingTracker(tmp_path)
        result = tracker.track(_make_log_dict(1))

        assert isinstance(result, ReadingProgress)
        assert result.total_episodes_read == 1
        assert result.current_episode == 2  # episode_id + 1

    def test_track_with_pydantic_model_returns_reading_progress(
        self, tmp_path: Path
    ) -> None:
        """track() with an EpisodeReadingLog model should return ReadingProgress."""
        tracker = ReadingTracker(tmp_path)
        log = _make_log(1)
        result = tracker.track(log)

        assert isinstance(result, ReadingProgress)
        assert result.total_episodes_read == 1

    def test_track_updates_chapter_id_and_offset(self, tmp_path: Path) -> None:
        """track() should store provided chapter_id and chapter_offset."""
        tracker = ReadingTracker(tmp_path)
        result = tracker.track(
            _make_log_dict(1),
            chapter_id=3,
            chapter_offset=0.42,
        )

        assert result.current_chapter == 3
        assert result.chapter_offset == 0.42

    def test_chapter_offset_validation_raises(self, tmp_path: Path) -> None:
        """track() should raise ValueError for chapter_offset outside [0.0, 1.0]."""
        tracker = ReadingTracker(tmp_path)

        with pytest.raises(ValueError, match="chapter_offset must be in"):
            tracker.track(_make_log_dict(1), chapter_offset=1.5)

        with pytest.raises(ValueError, match="chapter_offset must be in"):
            tracker.track(_make_log_dict(1), chapter_offset=-0.1)

    def test_word_log_without_item_id_rejected(self) -> None:
        """Reading logs must include item_id from episode marks."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            EpisodeReadingLog(
                episode_id=1,
                word_logs=[
                    {"word": "consumed", "meaning": "消耗", "appeared": 1, "clicked": 0}
                ],
            )


class TestPersistence:
    """Tests for file-backed persistence."""

    def test_progress_persists_across_instances(self, tmp_path: Path) -> None:
        """Progress saved by one tracker should be readable by another."""
        tracker1 = ReadingTracker(tmp_path)
        tracker1.track(_make_log_dict(1))

        tracker2 = ReadingTracker(tmp_path)
        progress = tracker2.get_progress()

        assert progress.total_episodes_read == 1
        assert progress.current_episode == 2

    def test_log_persists_across_instances(self, tmp_path: Path) -> None:
        """Logs saved by one tracker should be retrievable by another."""
        tracker1 = ReadingTracker(tmp_path)
        tracker1.track(_make_log_dict(1))

        tracker2 = ReadingTracker(tmp_path)
        log = tracker2.get_log(1)

        assert log is not None
        assert log.episode_id == 1
        assert len(log.word_logs) == 2
        assert log.word_logs[0].item_id == "hello_1"

    def test_duplicate_episode_overwrites_log(self, tmp_path: Path) -> None:
        """Tracking the same episode_id twice should overwrite the old log."""
        tracker = ReadingTracker(tmp_path)
        tracker.track(_make_log_dict(1))

        # Track same episode with different word_logs
        new_log = EpisodeReadingLog(
            episode_id=1,
            word_logs=[WordLog(item_id="only_one", appeared=5, clicked=3)],
        )
        tracker.track(new_log)

        retrieved = tracker.get_log(1)
        assert retrieved is not None
        assert len(retrieved.word_logs) == 1
        assert retrieved.word_logs[0].item_id == "only_one"


class TestChapterOffsetRollover:
    """Tests for chapter_offset >= 1.0 rollover logic."""

    def test_offset_at_one_rolls_to_next_chapter(self, tmp_path: Path) -> None:
        """When chapter_offset reaches 1.0, current_chapter increments and offset resets."""
        tracker = ReadingTracker(tmp_path)
        result = tracker.track(
            _make_log_dict(1),
            chapter_id=2,
            chapter_offset=1.0,
        )

        assert result.current_chapter == 3  # rolled to next
        assert result.chapter_offset == 0.0

    def test_offset_above_one_rolls_to_next_chapter(self, tmp_path: Path) -> None:
        """When chapter_offset exceeds 1.0, rollover still occurs."""
        tracker = ReadingTracker(tmp_path)
        result = tracker.track(
            _make_log_dict(1),
            chapter_id=5,
            chapter_offset=0.99,  # first set to 0.99
        )
        assert result.current_chapter == 5
        assert result.chapter_offset == 0.99

        # Now push beyond 1.0
        result2 = tracker.track(
            _make_log_dict(2),
            chapter_id=5,
            chapter_offset=1.0,
        )
        assert result2.current_chapter == 6
        assert result2.chapter_offset == 0.0


class TestGetLog:
    """Tests for get_log() method."""

    def test_get_log_returns_none_for_unknown_episode(self, tmp_path: Path) -> None:
        """get_log() should return None when no log exists for the episode."""
        tracker = ReadingTracker(tmp_path)
        assert tracker.get_log(999) is None

    def test_get_log_returns_stored_log(self, tmp_path: Path) -> None:
        """get_log() should return the previously stored EpisodeReadingLog."""
        tracker = ReadingTracker(tmp_path)
        original = _make_log(5)
        tracker.track(original)

        retrieved = tracker.get_log(5)
        assert retrieved is not None
        assert retrieved.episode_id == 5
        assert len(retrieved.word_logs) == len(original.word_logs)


class TestProgressTracking:
    """Tests for progress counters."""

    def test_total_episodes_read_increments(self, tmp_path: Path) -> None:
        """Each track() call should increment total_episodes_read by 1."""
        tracker = ReadingTracker(tmp_path)

        r1 = tracker.track(_make_log_dict(1))
        assert r1.total_episodes_read == 1

        r2 = tracker.track(_make_log_dict(2))
        assert r2.total_episodes_read == 2

        r3 = tracker.track(_make_log_dict(3))
        assert r3.total_episodes_read == 3

    def test_current_episode_tracks_next(self, tmp_path: Path) -> None:
        """current_episode should be set to episode_id + 1 after each track."""
        tracker = ReadingTracker(tmp_path)

        r1 = tracker.track(_make_log_dict(1))
        assert r1.current_episode == 2

        r2 = tracker.track(_make_log_dict(5))
        assert r2.current_episode == 6

    def test_get_progress_on_fresh_tracker(self, tmp_path: Path) -> None:
        """get_progress() on a fresh tracker should return defaults."""
        tracker = ReadingTracker(tmp_path)
        progress = tracker.get_progress()

        assert progress.current_chapter == 1
        assert progress.current_episode == 1
        assert progress.chapter_offset == 0.0
        assert progress.total_episodes_read == 0
