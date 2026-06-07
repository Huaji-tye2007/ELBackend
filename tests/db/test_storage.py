"""Tests for JSONStorage[T] generic persistence layer.

TDD RED phase: all tests must fail before JSONStorage is implemented.
"""

import json
from pathlib import Path

import pytest

from app.db.storage import JSONStorage
from app.models.fsrs import FsrsCard
from app.models.vocabulary import UserVocabulary, VocabularyItem


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_fsrs_card() -> dict:
    """Return a minimal valid FsrsCard dict for constructing VocabularyItem."""
    return {
        "card_id": 1,
        "state": 1,
        "step": 0,
        "stability": None,
        "difficulty": None,
        "due": "2026-06-01T00:00:00+00:00",
        "last_review": None,
    }


def _make_vocab_item(
    item_id: str, word: str, meaning: str, chapter: int = 1
) -> VocabularyItem:
    """Construct a minimal valid VocabularyItem."""
    fsrs = FsrsCard(**_make_fsrs_card())
    return VocabularyItem(
        id=item_id,
        word=word,
        meaning=meaning,
        chapter_first_seen=chapter,
        fsrs_card=fsrs,
    )


def _make_user_vocab() -> UserVocabulary:
    """Construct a minimal valid UserVocabulary."""
    return UserVocabulary(
        user_id="test_user",
        vocabulary=[
            _make_vocab_item("bank_river", "bank", "河岸"),
            _make_vocab_item("bank_finance", "bank", "银行", chapter=2),
        ],
    )


# ---------------------------------------------------------------------------
# 1. Init
# ---------------------------------------------------------------------------


class TestInit:
    def test_stores_path_and_model_type(self, tmp_path: Path):
        """JSONStorage.__init__ stores the path and model type."""
        p = tmp_path / "data.json"
        storage = JSONStorage(p, UserVocabulary)
        assert storage.path == p
        assert storage.model == UserVocabulary


# ---------------------------------------------------------------------------
# 2. Save
# ---------------------------------------------------------------------------


class TestSave:
    def test_save_creates_file(self, tmp_path: Path):
        """save() creates a file at the configured path."""
        p = tmp_path / "vocab.json"
        storage = JSONStorage(p, UserVocabulary)
        vocab = _make_user_vocab()
        storage.save(vocab)
        assert p.exists()
        assert p.is_file()

    def test_save_produces_valid_json(self, tmp_path: Path):
        """save() writes valid JSON that can be parsed back."""
        p = tmp_path / "vocab.json"
        storage = JSONStorage(p, UserVocabulary)
        vocab = _make_user_vocab()
        storage.save(vocab)
        raw = p.read_text(encoding="utf-8")
        data = json.loads(raw)
        assert data["user_id"] == "test_user"
        assert len(data["vocabulary"]) == 2

    def test_save_overwrites_existing_file(self, tmp_path: Path):
        """save() called twice replaces file content, not appends."""
        p = tmp_path / "vocab.json"
        storage = JSONStorage(p, UserVocabulary)

        vocab1 = _make_user_vocab()
        storage.save(vocab1)

        vocab2 = UserVocabulary(user_id="another_user", vocabulary=[])
        storage.save(vocab2)

        loaded = storage.load()
        assert loaded.user_id == "another_user"
        assert len(loaded.vocabulary) == 0

    def test_save_path_is_directory_raises(self, tmp_path: Path):
        """save() when path points to a directory should raise."""
        p = tmp_path  # tmp_path is a directory
        storage = JSONStorage(p, UserVocabulary)
        vocab = _make_user_vocab()
        with pytest.raises((IsADirectoryError, OSError, PermissionError)):
            storage.save(vocab)

    def test_save_parent_directory_missing_raises(self, tmp_path: Path):
        """save() when parent directory doesn't exist raises FileNotFoundError.

        data/ is .gitignored and may not exist on first run. Callers must
        ensure the parent directory exists before calling JSONStorage.save().
        See also: atomic_write_json — tmp_path.write_text() will fail if
        the parent directory is missing.
        """
        p = tmp_path / "nonexistent_dir" / "vocab.json"
        storage = JSONStorage(p, UserVocabulary)
        vocab = _make_user_vocab()
        with pytest.raises(FileNotFoundError):
            storage.save(vocab)


# ---------------------------------------------------------------------------
# 3. Load
# ---------------------------------------------------------------------------


class TestLoad:
    def test_load_returns_model_instance(self, tmp_path: Path):
        """load() returns an instance of the configured model type."""
        p = tmp_path / "vocab.json"
        storage = JSONStorage(p, UserVocabulary)
        vocab = _make_user_vocab()
        storage.save(vocab)
        loaded = storage.load()
        assert isinstance(loaded, UserVocabulary)

    def test_load_nonexistent_raises(self, tmp_path: Path):
        """load() on nonexistent file raises FileNotFoundError."""
        p = tmp_path / "does_not_exist.json"
        storage = JSONStorage(p, UserVocabulary)
        with pytest.raises(FileNotFoundError):
            storage.load()

    def test_load_corrupt_json_raises(self, tmp_path: Path):
        """load() on corrupt JSON raises an error."""
        p = tmp_path / "corrupt.json"
        p.write_text("this is not json", encoding="utf-8")
        storage = JSONStorage(p, UserVocabulary)
        with pytest.raises((json.JSONDecodeError, ValueError)):
            storage.load()

    def test_load_wrong_schema_raises(self, tmp_path: Path):
        """load() on valid JSON with wrong schema raises ValidationError."""
        p = tmp_path / "wrong.json"
        p.write_text('{"not_a_user_id": 123}', encoding="utf-8")
        storage = JSONStorage(p, UserVocabulary)
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            storage.load()

    def test_load_path_is_directory_raises(self, tmp_path: Path):
        """load() when path points to a directory should raise."""
        p = tmp_path  # tmp_path is a directory
        storage = JSONStorage(p, UserVocabulary)
        with pytest.raises((IsADirectoryError, OSError, PermissionError)):
            storage.load()


# ---------------------------------------------------------------------------
# 4. Roundtrip
# ---------------------------------------------------------------------------


class TestRoundtrip:
    def test_save_load_preserves_data(self, tmp_path: Path):
        """save() then load() returns an object with identical fields."""
        p = tmp_path / "vocab.json"
        storage = JSONStorage(p, UserVocabulary)
        vocab = _make_user_vocab()
        storage.save(vocab)
        loaded = storage.load()
        # model_dump comparison (deep equality)
        assert vocab.model_dump() == loaded.model_dump()

    def test_save_modify_save_load_reflects_changes(self, tmp_path: Path):
        """After save→modify→save, load returns the modified object."""
        p = tmp_path / "vocab.json"
        storage = JSONStorage(p, UserVocabulary)

        vocab = _make_user_vocab()
        storage.save(vocab)

        # Add a new item
        new_item = _make_vocab_item("new_word", "test", "测试", chapter=3)
        vocab.vocabulary.append(new_item)
        storage.save(vocab)

        loaded = storage.load()
        assert len(loaded.vocabulary) == 3
        assert loaded.vocabulary[-1].id == "new_word"

    def test_roundtrip_preserves_datetime_precision(self, tmp_path: Path):
        """Roundtrip preserves datetime field precision (via FsrsCard)."""
        p = tmp_path / "vocab.json"
        storage = JSONStorage(p, UserVocabulary)
        vocab = _make_user_vocab()
        storage.save(vocab)
        loaded = storage.load()

        original_due = vocab.vocabulary[0].fsrs_card.due
        loaded_due = loaded.vocabulary[0].fsrs_card.due
        assert original_due == loaded_due

    def test_roundtrip_preserves_none_datetime(self, tmp_path: Path):
        """Roundtrip preserves None last_review in FsrsCard."""
        p = tmp_path / "vocab.json"
        storage = JSONStorage(p, UserVocabulary)
        vocab = _make_user_vocab()
        storage.save(vocab)
        loaded = storage.load()
        assert loaded.vocabulary[0].fsrs_card.last_review is None

    def test_roundtrip_empty_vocabulary(self, tmp_path: Path):
        """Roundtrip preserves an empty UserVocabulary (no items)."""
        p = tmp_path / "vocab.json"
        storage = JSONStorage(p, UserVocabulary)
        vocab = UserVocabulary(user_id="empty_user", vocabulary=[])
        storage.save(vocab)
        loaded = storage.load()
        assert loaded.user_id == "empty_user"
        assert len(loaded.vocabulary) == 0
        assert loaded.model_dump() == vocab.model_dump()


# ---------------------------------------------------------------------------
# 5. Generic Type
# ---------------------------------------------------------------------------


class TestGenericType:
    def test_works_with_fsrs_card_model(self, tmp_path: Path):
        """JSONStorage works with any Pydantic model, e.g., FsrsCard."""
        p = tmp_path / "card.json"
        storage = JSONStorage(p, FsrsCard)
        card = FsrsCard(**_make_fsrs_card())
        storage.save(card)
        loaded = storage.load()
        assert isinstance(loaded, FsrsCard)
        assert loaded.card_id == 1
        assert loaded.state == 1


# ---------------------------------------------------------------------------
# 6. Crash safety (via atomic_write dependency)
# ---------------------------------------------------------------------------


class TestCrashSafety:
    def test_no_tmp_file_left_after_save(self, tmp_path: Path):
        """After successful save, no .tmp file remains."""
        p = tmp_path / "vocab.json"
        storage = JSONStorage(p, UserVocabulary)
        storage.save(_make_user_vocab())
        tmp = p.with_suffix(".tmp")
        assert not tmp.exists()

    def test_corrupt_tmp_does_not_corrupt_existing(self, tmp_path: Path):
        """A corrupt .tmp file left from a crash does not affect the valid file."""
        p = tmp_path / "vocab.json"
        storage = JSONStorage(p, UserVocabulary)

        # Save valid data first
        original = _make_user_vocab()
        storage.save(original)

        # Simulate crash: leave a corrupt .tmp file
        p.with_suffix(".tmp").write_text("corrupt", encoding="utf-8")

        # Load should still get original data (reads from .json, not .tmp)
        loaded = storage.load()
        assert loaded.user_id == original.user_id
        assert len(loaded.vocabulary) == len(original.vocabulary)
