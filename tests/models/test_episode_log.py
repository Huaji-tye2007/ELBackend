"""Tests for app.models.episode_log — WordLog and EpisodeReadingLog."""

import pytest
from pydantic import ValidationError

from app.models.episode_log import EpisodeReadingLog, WordLog


class TestWordLog:
    """Tests for WordLog model."""

    def test_valid_minimal(self) -> None:
        """WordLog with required fields should validate."""
        wl = WordLog(item_id="awkward_1", appeared=3, clicked=0)
        assert wl.item_id == "awkward_1"
        assert wl.appeared == 3
        assert wl.clicked == 0

    def test_valid_full(self) -> None:
        """WordLog with all fields and clicked == appeared should validate."""
        wl = WordLog(item_id="meticulous_1", appeared=5, clicked=5)
        assert wl.item_id == "meticulous_1"
        assert wl.appeared == 5
        assert wl.clicked == 5

    def test_invalid_clicked_gt_appeared(self) -> None:
        """WordLog with clicked > appeared should raise ValidationError."""
        with pytest.raises(ValidationError):
            WordLog(item_id="bad_1", appeared=2, clicked=3)

    def test_invalid_appeared_negative(self) -> None:
        """WordLog with appeared < 0 should raise ValidationError."""
        with pytest.raises(ValidationError):
            WordLog(item_id="bad_2", appeared=-1, clicked=0)

    def test_invalid_clicked_negative(self) -> None:
        """WordLog with clicked < 0 should raise ValidationError."""
        with pytest.raises(ValidationError):
            WordLog(item_id="bad_3", appeared=1, clicked=-1)

    def test_roundtrip(self) -> None:
        """WordLog model_dump → model_validate should produce equal model."""
        wl = WordLog(item_id="awkward_1", appeared=3, clicked=1)
        data = wl.model_dump()
        reloaded = WordLog.model_validate(data)
        assert reloaded == wl


class TestEpisodeReadingLog:
    """Tests for EpisodeReadingLog model."""

    def test_valid_empty_logs(self) -> None:
        """EpisodeReadingLog with no word_logs should validate."""
        log = EpisodeReadingLog(episode_id=1, word_logs=[])
        assert log.episode_id == 1
        assert log.word_logs == []

    def test_valid_full(self) -> None:
        """EpisodeReadingLog with multiple WordLog entries should validate."""
        logs = [
            WordLog(item_id="awkward_1", appeared=3, clicked=0),
            WordLog(item_id="meticulous_1", appeared=5, clicked=2),
        ]
        log = EpisodeReadingLog(episode_id=18, word_logs=logs)
        assert log.episode_id == 18
        assert len(log.word_logs) == 2
        assert log.word_logs[0].item_id == "awkward_1"
        assert log.word_logs[1].clicked == 2

    def test_invalid_episode_id_zero(self) -> None:
        """EpisodeReadingLog with episode_id=0 should raise ValidationError."""
        with pytest.raises(ValidationError):
            EpisodeReadingLog(episode_id=0, word_logs=[])

    def test_invalid_episode_id_negative(self) -> None:
        """EpisodeReadingLog with episode_id < 0 should raise ValidationError."""
        with pytest.raises(ValidationError):
            EpisodeReadingLog(episode_id=-1, word_logs=[])

    def test_roundtrip(self) -> None:
        """EpisodeReadingLog model_dump → model_validate should produce equal model."""
        logs = [
            WordLog(item_id="awkward_1", appeared=3, clicked=1),
            WordLog(item_id="meticulous_1", appeared=5, clicked=0),
        ]
        log = EpisodeReadingLog(episode_id=18, word_logs=logs)
        data = log.model_dump()
        reloaded = EpisodeReadingLog.model_validate(data)
        assert reloaded == log
