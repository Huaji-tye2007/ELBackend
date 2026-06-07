"""Tests for app/utils/atomic_io.py — JSON atomic write/read utilities."""

import datetime
import json

import pytest
from pydantic import ValidationError

from app.models.fsrs import FsrsCard
from app.utils.atomic_io import atomic_read_json, atomic_write_json


def create_sample_fsrs_card() -> FsrsCard:
    """Create a valid FsrsCard for use in tests."""
    return FsrsCard(
        card_id=1,
        state=1,
        step=0,
        stability=2.5,
        difficulty=0.3,
        due=datetime.datetime(2026, 6, 8, tzinfo=datetime.timezone.utc),
        last_review=datetime.datetime(2026, 6, 7, tzinfo=datetime.timezone.utc),
    )


class TestAtomicWriteJson:
    """Tests for atomic_write_json."""

    def test_write_creates_file(self, tmp_path):
        """Writing a model should create a JSON file at the target path."""
        path = tmp_path / "data.json"
        card = create_sample_fsrs_card()
        atomic_write_json(path, card)
        assert path.exists()
        assert path.is_file()

    def test_write_produces_valid_json(self, tmp_path):
        """Written file should parse as valid JSON."""
        path = tmp_path / "data.json"
        card = create_sample_fsrs_card()
        atomic_write_json(path, card)
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
        assert data["card_id"] == 1
        assert data["state"] == 1

    def test_write_removes_tmp_file(self, tmp_path):
        """After successful write, .tmp file should not exist."""
        path = tmp_path / "data.json"
        card = create_sample_fsrs_card()
        atomic_write_json(path, card)
        tmp = path.with_suffix(".tmp")
        assert not tmp.exists(), ".tmp file should be cleaned up after atomic replace"


class TestAtomicReadJson:
    """Tests for atomic_read_json."""

    def test_read_returns_model_instance(self, tmp_path):
        """Reading should return a validated Pydantic model instance."""
        path = tmp_path / "data.json"
        card = create_sample_fsrs_card()
        atomic_write_json(path, card)
        result = atomic_read_json(path, FsrsCard)
        assert isinstance(result, FsrsCard)

    def test_roundtrip(self, tmp_path):
        """Write → read roundtrip should preserve all field values."""
        path = tmp_path / "data.json"
        card = create_sample_fsrs_card()
        atomic_write_json(path, card)
        result = atomic_read_json(path, FsrsCard)
        assert result == card

    def test_read_nonexistent_raises(self, tmp_path):
        """Reading a non-existent file should raise FileNotFoundError."""
        path = tmp_path / "nonexistent.json"
        with pytest.raises(FileNotFoundError):
            atomic_read_json(path, FsrsCard)

    def test_read_invalid_json_raises(self, tmp_path):
        """Reading a file with invalid JSON should raise an error."""
        path = tmp_path / "bad.json"
        path.write_text("not valid {json", encoding="utf-8")
        with pytest.raises((json.JSONDecodeError, ValidationError, ValueError)):
            atomic_read_json(path, FsrsCard)

    def test_read_valid_json_wrong_schema_raises(self, tmp_path):
        """Reading valid JSON that doesn't match the model should raise ValidationError."""
        path = tmp_path / "wrong.json"
        path.write_text('{"not_a_card_id": 999}', encoding="utf-8")
        with pytest.raises((ValidationError, ValueError)):
            atomic_read_json(path, FsrsCard)


class TestCrashSafety:
    """Tests for atomic write crash safety (os.replace guarantees)."""

    def test_corrupt_tmp_does_not_affect_original(self, tmp_path):
        """A corrupt .tmp file from a crashed write should not affect the valid original."""
        path = tmp_path / "data.json"
        card = create_sample_fsrs_card()

        # Write original valid data
        atomic_write_json(path, card)

        # Simulate crash: create corrupt .tmp file
        tmp_file = path.with_suffix(".tmp")
        tmp_file.write_text("corrupt{incomplete", encoding="utf-8")

        # Original should still be readable and valid
        result = atomic_read_json(path, FsrsCard)
        assert result == card
        assert tmp_file.exists(), ".tmp file still exists after crash"

    def test_overwrite_with_valid_data_replaces_original(self, tmp_path):
        """A successful write overwrites original with new data."""
        path = tmp_path / "data.json"
        card1 = create_sample_fsrs_card()
        atomic_write_json(path, card1)

        card2 = create_sample_fsrs_card()
        card2.state = 2
        atomic_write_json(path, card2)

        result = atomic_read_json(path, FsrsCard)
        assert result == card2
        assert result.state == 2

    def test_no_tmp_left_after_successful_write(self, tmp_path):
        """After a successful write, no .tmp file should remain."""
        path = tmp_path / "data.json"
        card = create_sample_fsrs_card()
        atomic_write_json(path, card)
        assert not path.with_suffix(".tmp").exists()
