"""Top-level test fixtures for the ELBackend project.

Provides shared fixtures used across all test modules, including
JSON fixture loaders, sample data dicts, and mocks.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

import pytest

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
def sample_chapters() -> list[dict]:
    """Load sample chapters from chapter_db.json.

    Returns the "chapters" list as a plain list of dicts.
    """
    db = load_fixture_json("chapter_db")
    return db["chapters"]


@pytest.fixture
def sample_progress() -> dict:
    """Minimal ReadingProgress dict at the start of chapter 1."""
    return {
        "current_chapter": 1,
        "current_episode": 0,
        "chapter_offset": 0.0,
        "total_episodes_read": 0,
    }


@pytest.fixture
def sample_progress_mid() -> dict:
    """ReadingProgress dict mid-chapter (offset 0.3)."""
    return {
        "current_chapter": 1,
        "current_episode": 5,
        "chapter_offset": 0.3,
        "total_episodes_read": 25,
    }


@pytest.fixture
def sample_progress_end_chapter() -> dict:
    """ReadingProgress dict near end of chapter (offset 0.95)."""
    return {
        "current_chapter": 1,
        "current_episode": 9,
        "chapter_offset": 0.95,
        "total_episodes_read": 29,
    }


@pytest.fixture
def sample_arc_plan() -> dict:
    """Load the previous Arc plan (arc_id=2) from prev_arc_plan.json.

    Note: arc_id is an int (2) in the fixture. Callers that need a
    string must convert it themselves.
    """
    return load_fixture_json("prev_arc_plan")


class _CacheSpec:
    """Spec for mock.create_autospec — matches JSONStorage.load() interface."""

    async def load(self, episode_id: int | None = None) -> dict: ...  # noqa: ARG002


@pytest.fixture
def mock_episode_cache():
    """Mock episode cache using create_autospec pattern (AGENTS.md §16.3)."""
    cache = mock.create_autospec(_CacheSpec, instance=True)

    async def _load(episode_id: int | None = None) -> dict:  # noqa: ARG001
        return load_fixture_json("episode_cache_ep30")

    cache.load.side_effect = _load
    return cache


@pytest.fixture
def empty_chapter_db() -> dict:
    """An empty chapter database dict with no chapters."""
    return {"chapters": []}
