"""FastAPI dependency injection factories.

Provides singleton factories for all service classes, storage, LLM client,
and ECDICT database connection.  All factories are designed for use with
FastAPI ``Depends()`` and return instances with all dependencies injected
via ``__init__``.

Ref: AGENTS.md §9 (package layout), §11 (service class mapping), §15.3 (DI rules).
"""

from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable

from dotenv import load_dotenv

from app.core.exceptions import ECDictUnavailableError
from app.db.storage import JSONStorage
from app.llm.client import InstructorClient
from app.models.chapter import ChapterDB
from app.models.vocabulary import UserVocabulary
from app.models.word_sense import WordSenseDB

load_dotenv()


# ════════════════════════════════════════════════════════════════
# Settings
# ════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class Settings:
    """Application-wide settings loaded from environment variables.

    Mirrors the conventions in ``app/core/config.py`` (``get_llm_config()``)
    plus additional path configuration needed by the DI layer.
    """

    data_dir: Path = field(default_factory=lambda: Path("data"))
    """Root directory for runtime JSON data (UserVocabulary, ChapterDB, etc.)."""

    ecdict_db_path: Path = field(default_factory=lambda: Path("asset/ecdict_mobile.db"))
    """Path to the ECDICT SQLite database file."""

    openai_base_url: str = "http://localhost:11434/v1"
    """OpenAI-compatible API base URL."""

    openai_api_key: str = ""
    """API key for the LLM endpoint."""

    openai_model: str = "deepseek-v4-flash"
    """Model name for structured-output calls."""

    instructor_mode: str = "JSON"
    """Instructor structured-output mode. JSON avoids tool_choice for thinking models."""

    @classmethod
    def from_env(cls) -> Settings:
        """Construct Settings from environment variables with sensible defaults.

        Env vars: ``DATA_DIR``, ``ECDICT_DB_PATH``, ``LLM_BASE_URL``,
        ``LLM_API_KEY``, ``LLM_MODEL``, ``LLM_INSTRUCTOR_MODE``.
        """
        return cls(
            data_dir=Path(os.getenv("DATA_DIR", "data")),
            ecdict_db_path=Path(os.getenv("ECDICT_DB_PATH", "asset/ecdict_mobile.db")),
            openai_base_url=os.getenv("LLM_BASE_URL", "http://localhost:11434/v1"),
            openai_api_key=os.getenv("LLM_API_KEY", ""),
            openai_model=os.getenv("LLM_MODEL", "deepseek-v4-flash"),
            instructor_mode=os.getenv("LLM_INSTRUCTOR_MODE", "JSON"),
        )


# ════════════════════════════════════════════════════════════════
# Core infrastructure singletons
# ════════════════════════════════════════════════════════════════


@lru_cache
def get_settings() -> Settings:
    """Return a cached application Settings singleton.

    Reads from environment once; subsequent calls return the same instance.
    """
    return Settings.from_env()


@lru_cache
def get_llm_client() -> InstructorClient:
    """Return a cached InstructorClient singleton.

    Constructed once with settings from ``get_settings()``.
    """
    settings = get_settings()
    return InstructorClient(
        base_url=settings.openai_base_url,
        api_key=settings.openai_api_key,
        model=settings.openai_model,
        instructor_mode=settings.instructor_mode,
    )


@lru_cache
def get_ecdict_db() -> sqlite3.Connection:
    """Return a cached ECDICT SQLite database connection.

    Returns:
        An open ``sqlite3.Connection`` to the ECDICT database.

    Raises:
        ECDictUnavailableError: If the database file does not exist at
            ``settings.ecdict_db_path``.
    """
    settings = get_settings()
    path = settings.ecdict_db_path
    if not path.exists():
        raise ECDictUnavailableError(f"ECDICT database not found at {path}")
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    return conn


# ════════════════════════════════════════════════════════════════
# Storage factories
# ════════════════════════════════════════════════════════════════


@lru_cache
def get_user_vocab_storage() -> JSONStorage[UserVocabulary]:
    """Return a cached JSONStorage for ``data/UserVocabulary.json``."""
    settings = get_settings()
    return JSONStorage(settings.data_dir / "UserVocabulary.json", UserVocabulary)


@lru_cache
def get_chapter_db_storage() -> JSONStorage[ChapterDB]:
    """Return a cached JSONStorage for ``data/ChapterDB.json``."""
    settings = get_settings()
    return JSONStorage(settings.data_dir / "ChapterDB.json", ChapterDB)


@lru_cache
def get_word_sense_db() -> WordSenseDB:
    """Return a cached WordSenseDB singleton loaded from ``data/WordSenseDB.json``.

    Raises:
        FileNotFoundError: If ``data/WordSenseDB.json`` does not exist.
    """
    settings = get_settings()
    storage = JSONStorage(settings.data_dir / "WordSenseDB.json", WordSenseDB)
    return storage.load()


# ════════════════════════════════════════════════════════════════
# Service factories — implemented services
# ════════════════════════════════════════════════════════════════


@lru_cache
def get_arc_planner():
    """Return a cached ArcPlanner singleton (no external dependencies).

    Uses lazy import to avoid circular dependency at module load time.
    """
    from app.services.arc_planner import ArcPlanner  # lazy import

    return ArcPlanner()


@lru_cache
def get_mastery_evaluator():
    """Return a cached MasteryEvaluator singleton (no external dependencies).

    Uses lazy import to avoid circular dependency at module load time.
    """
    from app.services.mastery_evaluator import MasteryEvaluator

    return MasteryEvaluator()


@lru_cache
def get_novel_preprocessor():
    """Return a cached NovelPreprocessor singleton with LLM client injected.

    Uses lazy import to avoid circular dependency at module load time.
    """
    from app.services.novel_preprocessor import NovelPreprocessor

    return NovelPreprocessor(llm_client=get_llm_client())


@lru_cache
def get_story_rewriter():
    """Return a cached StoryRewriter singleton with LLM client injected.

    Uses lazy import to avoid circular dependency at module load time.
    """
    from app.services.story_rewriter import StoryRewriter

    return StoryRewriter(llm_client=get_llm_client())


def get_vocabulary_annotator():
    """Return a fresh VocabularyAnnotator instance.

    Reloads UserVocabulary from storage on every call so that vocabulary
    uploads/updates are always reflected in Arc generation.

    Uses lazy import to avoid circular dependency at module load time.
    """
    from app.services.vocabulary_annotator import VocabularyAnnotator

    storage = get_user_vocab_storage()
    vocab = storage.load()
    ecdict_db = get_ecdict_db()
    return VocabularyAnnotator(user_vocab=vocab, ecdict_db=ecdict_db)


def get_vocabulary_scheduler() -> Callable[..., Any]:
    """Return the VocabularyScheduler ``schedule()`` function.

    The scheduler is a module-level async function, not a class instance.
    Callers must pass ``llm_client`` as a keyword argument when invoking.

    Returns:
        The ``schedule`` callable from
        ``app.services.vocabulary_scheduler.scheduler``.
    """
    from app.services.vocabulary_scheduler.scheduler import schedule

    return schedule


@lru_cache
def get_reading_tracker():
    """Return a cached ReadingTracker singleton.

    Uses lazy import to avoid circular dependency at module load time.
    """
    from app.services.reading_tracker import ReadingTracker

    settings = get_settings()
    return ReadingTracker(settings.data_dir)


@lru_cache
def get_arc_generation_manager():
    """Return a cached ArcGenerationManager singleton with all 5 services injected.

    Uses lazy import to avoid circular dependency at module load time.
    """
    from app.services.arc_generation_manager import ArcGenerationManager

    return ArcGenerationManager(
        arc_planner=get_arc_planner(),
        vocab_scheduler=get_vocabulary_scheduler(),
        story_rewriter=get_story_rewriter(),
        vocab_annotator=get_vocabulary_annotator(),
        episode_formatter=get_episode_formatter(),
    )


# ════════════════════════════════════════════════════════════════
# Service factories — stub placeholders (not yet implemented)
# ════════════════════════════════════════════════════════════════


@lru_cache
def get_vocabulary_preprocessor():
    """Return a cached VocabularyPreprocessor singleton with WordSenseDB injected.

    Uses lazy import to avoid circular dependency at module load time.
    """
    from app.services.vocabulary_preprocessor import VocabularyPreprocessor

    return VocabularyPreprocessor(word_sense_db=get_word_sense_db())


def get_user_vocab() -> UserVocabulary:
    """Load the current UserVocabulary from storage.

    Must be used as a FastAPI Depends (not cached with @lru_cache)
    because the vocabulary may change between requests.
    """
    storage = get_user_vocab_storage()
    return storage.load()


def get_progress():
    """Load the current ReadingProgress from the tracker.

    Returns a default progress state if no progress has been recorded yet.
    Must be used as a FastAPI Depends (not cached with @lru_cache)
    because progress advances over time.
    """

    tracker = get_reading_tracker()
    return tracker.get_progress()


@lru_cache
def get_episode_formatter():
    """Return a cached EpisodeFormatter singleton with cache_dir injected.

    Cache directory is ``<data_dir>/EpisodeCache``, created on first write.
    Uses lazy import to avoid circular dependency at module load time.
    """
    from app.services.episode_formatter import EpisodeFormatter

    settings = get_settings()
    cache_dir = settings.data_dir / "EpisodeCache"
    return EpisodeFormatter(cache_dir=cache_dir)


__all__ = [
    "Settings",
    "get_settings",
    "get_llm_client",
    "get_ecdict_db",
    "get_user_vocab_storage",
    "get_user_vocab",
    "get_progress",
    "get_chapter_db_storage",
    "get_word_sense_db",
    "get_arc_planner",
    "get_mastery_evaluator",
    "get_novel_preprocessor",
    "get_story_rewriter",
    "get_vocabulary_annotator",
    "get_vocabulary_scheduler",
    "get_vocabulary_preprocessor",
    "get_episode_formatter",
    "get_reading_tracker",
    "get_arc_generation_manager",
]
