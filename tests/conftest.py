"""Top-level test fixtures for the ELBackend project.

Provides shared fixtures used across all test modules, including
JSON fixture loaders, sample data models, and mocks.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from unittest import mock

import pytest

from app.models.arc_plan import ArcPlan
from app.models.chapter import Chapter, ChapterDB
from app.models.progress import ReadingProgress
from app.models.vocabulary import UserVocabulary
from app.models.word_sense import WordSenseDB

FIXTURES_DIR = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def load_fixture_json(name: str) -> dict:
    """Load a JSON fixture file from tests/fixtures/ by name.

    Args:
        name: Fixture file name without the .json extension
              (e.g. "chapter_db" loads tests/fixtures/chapter_db.json).

    Returns:
        Parsed JSON as a dict.

    Raises:
        FileNotFoundError: If the fixture file does not exist.
    """
    path = FIXTURES_DIR / f"{name}.json"
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Pytest fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_data_dir(tmp_path: Path) -> Path:
    """Temporary directory for test data, backed by pytest's tmp_path."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    return data_dir


@pytest.fixture
def sample_chapters() -> list[Chapter]:
    """Load sample chapters from chapter_db.json.

    Returns the chapters as a list of Pydantic Chapter models.
    """
    db = load_fixture_json("chapter_db")
    return [Chapter.model_validate(ch) for ch in db["chapters"]]


@pytest.fixture
def sample_progress() -> ReadingProgress:
    """Minimal ReadingProgress at the start of chapter 1."""
    return ReadingProgress(
        current_chapter=1,
        current_episode=1,
        chapter_offset=0.0,
        total_episodes_read=0,
    )


@pytest.fixture
def sample_progress_mid() -> ReadingProgress:
    """ReadingProgress mid-chapter (offset 0.3)."""
    return ReadingProgress(
        current_chapter=1,
        current_episode=5,
        chapter_offset=0.3,
        total_episodes_read=25,
    )


@pytest.fixture
def sample_progress_end_chapter() -> ReadingProgress:
    """ReadingProgress near end of chapter (offset 0.95)."""
    return ReadingProgress(
        current_chapter=1,
        current_episode=9,
        chapter_offset=0.95,
        total_episodes_read=29,
    )


@pytest.fixture
def sample_arc_plan() -> ArcPlan:
    """Load the previous Arc plan (arc_id=2) from prev_arc_plan.json.

    The fixture JSON stores arc_id as int 2; we convert to str for Pydantic.
    """
    data = load_fixture_json("prev_arc_plan")
    data["arc_id"] = str(data["arc_id"])  # int → str for Pydantic str field
    return ArcPlan.model_validate(data)


class _CacheSpec:
    """Spec for mock.create_autospec — matches JSONStorage.load() interface."""

    def load(self, episode_id: int | None = None) -> dict: ...  # noqa: ARG002


@pytest.fixture
def mock_episode_cache():
    """Mock episode cache using create_autospec pattern (AGENTS.md §16.3)."""
    cache = mock.create_autospec(_CacheSpec, instance=True)

    def _load(episode_id: int | None = None) -> dict:  # noqa: ARG001
        return load_fixture_json("episode_cache_ep30")

    cache.load.side_effect = _load
    return cache


@pytest.fixture
def empty_chapter_db() -> ChapterDB:
    """An empty chapter database with no chapters."""
    return ChapterDB(chapters=[])


@pytest.fixture
def sample_user_vocabulary() -> UserVocabulary:
    """Load user vocabulary from user_vocabulary.json (24 items, including polysemy).

    Handles Python 3.10 Z-suffix incompatibility by replacing 'Z' with '+00:00'
    before parsing datetime fields via FsrsCard validators.
    """
    raw = (FIXTURES_DIR / "user_vocabulary.json").read_text(encoding="utf-8")
    # Python 3.10 compat: datetime.fromisoformat() rejects "Z" suffix
    raw = re.sub(r"(\d{2}:\d{2}:\d{2})Z", r"\1+00:00", raw)
    data = json.loads(raw)
    return UserVocabulary.model_validate(data)


@pytest.fixture
def sample_word_sense_db() -> WordSenseDB:
    """Load word sense database from word_sense_db.json (10 lemmas, 3 polysemous)."""
    data = load_fixture_json("word_sense_db")
    return WordSenseDB.model_validate(data)
