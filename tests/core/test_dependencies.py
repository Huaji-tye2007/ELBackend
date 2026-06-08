"""Tests for app.core.dependencies — DI factories and singleton semantics.

Verification scope (AGENTS.md §16.2):
- Success: Settings, LLM client, storage, service factories return expected types.
- Failure: ECDICT missing raises ECDictUnavailableError; stub factories raise NotImplementedError.
- Edge: Singleton caching (lru_cache), environment variable overrides, lazy imports.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from unittest import mock

import pytest

from app.core.dependencies import (
    Settings,
    get_arc_generation_manager,
    get_arc_planner,
    get_chapter_db_storage,
    get_ecdict_db,
    get_llm_client,
    get_mastery_evaluator,
    get_novel_preprocessor,
    get_reading_tracker,
    get_settings,
    get_story_rewriter,
    get_user_vocab_storage,
    get_vocabulary_annotator,
    get_vocabulary_preprocessor,
    get_vocabulary_scheduler,
    get_word_sense_db,
)
from app.core.exceptions import ECDictUnavailableError
from app.db.storage import JSONStorage
from app.llm.client import InstructorClient
from app.models.chapter import ChapterDB
from app.models.vocabulary import UserVocabulary, VocabularyItem


# ── helpers ────────────────────────────────────────────────────────────


def _clear_all_caches() -> None:
    """Clear every lru_cache used by the dependencies module."""
    get_settings.cache_clear()
    get_llm_client.cache_clear()
    get_ecdict_db.cache_clear()
    get_user_vocab_storage.cache_clear()
    get_chapter_db_storage.cache_clear()
    get_arc_planner.cache_clear()
    get_mastery_evaluator.cache_clear()
    get_novel_preprocessor.cache_clear()
    get_story_rewriter.cache_clear()
    # vocabulary_annotator no longer cached (reloads vocab each call)
    get_reading_tracker.cache_clear()
    get_arc_generation_manager.cache_clear()


def _mock_vocab_storage():
    """Context manager that mocks UserVocabulary storage to avoid FileNotFoundError."""
    from app.models.fsrs import FsrsCard
    import datetime

    fake_vocab = UserVocabulary(
        user_id="test",
        vocabulary=[
            VocabularyItem(
                id="item_1",
                word="test",
                meaning="test",
                chapter_first_seen=1,
                history_window=[1, 1, 1, 1, 1],
                fsrs_card=FsrsCard(
                    card_id=1001,
                    state=1,
                    due=datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc),
                    last_review=None,
                ),
            )
        ],
    )
    mock_storage = mock.MagicMock(spec=JSONStorage)
    mock_storage.load.return_value = fake_vocab
    return mock.patch(
        "app.core.dependencies.get_user_vocab_storage",
        return_value=mock_storage,
    )


# ── Settings ───────────────────────────────────────────────────────────


class TestSettings:
    """Tests for the Settings dataclass and get_settings() factory."""

    def test_default_values(self) -> None:
        """Default Settings should match documented fallbacks."""
        _clear_all_caches()
        with mock.patch.dict(os.environ, {}, clear=True):
            s = get_settings()
            assert s.data_dir == Path("data")
            assert s.ecdict_db_path == Path("asset/ecdict_mobile.db")
            assert s.openai_base_url == "http://localhost:11434/v1"
            assert s.openai_api_key == ""
            assert s.openai_model == "deepseek-v4-flash"
            assert s.instructor_mode == "JSON"

    def test_custom_env_values(self) -> None:
        """Custom environment variables should override defaults."""
        _clear_all_caches()
        with mock.patch.dict(
            os.environ,
            {
                "DATA_DIR": "/tmp/my_data",
                "ECDICT_DB_PATH": "custom/ecdict.db",
                "LLM_BASE_URL": "https://api.example.com/v1",
                "LLM_API_KEY": "sk-test",
                "LLM_MODEL": "gpt-4",
                "LLM_INSTRUCTOR_MODE": "TOOLS",
            },
            clear=True,
        ):
            s = get_settings()
            assert s.data_dir == Path("/tmp/my_data")
            assert s.ecdict_db_path == Path("custom/ecdict.db")
            assert s.openai_base_url == "https://api.example.com/v1"
            assert s.openai_api_key == "sk-test"
            assert s.openai_model == "gpt-4"
            assert s.instructor_mode == "TOOLS"

    def test_frozen_dataclass(self) -> None:
        """Settings should be immutable (frozen)."""
        s = Settings()
        with pytest.raises(Exception):
            s.openai_api_key = "hacked"  # type: ignore[misc]

    def test_from_env_classmethod(self) -> None:
        """Settings.from_env() should return a Settings instance."""
        s = Settings.from_env()
        assert isinstance(s, Settings)


class TestGetSettings:
    """Tests for the get_settings() singleton factory."""

    def test_returns_settings_instance(self) -> None:
        """get_settings() should return a Settings dataclass instance."""
        _clear_all_caches()
        s = get_settings()
        assert isinstance(s, Settings)

    def test_singleton_returns_same_instance(self) -> None:
        """Multiple calls to get_settings() must return the same object."""
        _clear_all_caches()
        s1 = get_settings()
        s2 = get_settings()
        assert s1 is s2

    def test_has_required_attributes(self) -> None:
        """Settings must expose all five documented attributes."""
        _clear_all_caches()
        s = get_settings()
        for attr in (
            "data_dir",
            "ecdict_db_path",
            "openai_base_url",
            "openai_api_key",
            "openai_model",
            "instructor_mode",
        ):
            assert hasattr(s, attr), f"Missing attribute: {attr}"


# ── LLM Client ────────────────────────────────────────────────────────


class TestGetLLMClient:
    """Tests for get_llm_client() singleton factory."""

    def test_returns_instructor_client(self) -> None:
        """get_llm_client() should return an InstructorClient instance."""
        _clear_all_caches()
        with mock.patch.dict(os.environ, {"LLM_API_KEY": "sk-test"}, clear=True):
            client = get_llm_client()
            assert isinstance(client, InstructorClient)

    def test_singleton_returns_same_instance(self) -> None:
        """Multiple calls must return the same InstructorClient."""
        _clear_all_caches()
        with mock.patch.dict(os.environ, {"LLM_API_KEY": "sk-test"}, clear=True):
            c1 = get_llm_client()
            c2 = get_llm_client()
            assert c1 is c2

    def test_client_uses_configured_model(self) -> None:
        """The client's model should match LLM_MODEL env var."""
        _clear_all_caches()
        with mock.patch.dict(
            os.environ,
            {"LLM_MODEL": "custom-model", "LLM_API_KEY": "sk-test"},
            clear=True,
        ):
            client = get_llm_client()
            assert client.model == "custom-model"

    def test_client_uses_configured_instructor_mode(self) -> None:
        """The client's instructor mode should match LLM_INSTRUCTOR_MODE env var."""
        _clear_all_caches()
        with mock.patch.dict(
            os.environ,
            {"LLM_INSTRUCTOR_MODE": "TOOLS", "LLM_API_KEY": "sk-test"},
            clear=True,
        ):
            client = get_llm_client()
            assert client.mode.name == "TOOLS"


# ── ECDICT Database ───────────────────────────────────────────────────


class TestGetEcdictDB:
    """Tests for get_ecdict_db() singleton factory."""

    def test_raises_when_file_missing(self) -> None:
        """Should raise ECDictUnavailableError when the DB file is absent."""
        _clear_all_caches()
        with mock.patch.dict(
            os.environ,
            {"ECDICT_DB_PATH": "nonexistent/path/ecdict.db"},
            clear=True,
        ):
            with pytest.raises(ECDictUnavailableError, match="not found"):
                get_ecdict_db()

    def test_connects_when_file_exists(self, tmp_path: Path) -> None:
        """Should return a sqlite3.Connection when the DB file exists."""
        _clear_all_caches()
        db_file = tmp_path / "test_ecdict.db"
        # Create an empty valid SQLite database
        db_file.write_bytes(b"")
        conn = sqlite3.connect(str(db_file))
        conn.execute("CREATE TABLE dict (word TEXT, exchange TEXT)")
        conn.commit()
        conn.close()

        with mock.patch.dict(
            os.environ,
            {"ECDICT_DB_PATH": str(db_file)},
            clear=True,
        ):
            db = get_ecdict_db()
            assert isinstance(db, sqlite3.Connection)
            # Verify the table exists by querying it
            db.execute("SELECT * FROM dict")

    def test_singleton_returns_same_connection(self, tmp_path: Path) -> None:
        """Multiple calls with same path must return the same connection."""
        _clear_all_caches()
        db_file = tmp_path / "singleton_ecdict.db"
        db_file.write_bytes(b"")
        conn = sqlite3.connect(str(db_file))
        conn.execute("CREATE TABLE dict (word TEXT, exchange TEXT)")
        conn.commit()
        conn.close()

        with mock.patch.dict(
            os.environ,
            {"ECDICT_DB_PATH": str(db_file)},
            clear=True,
        ):
            db1 = get_ecdict_db()
            db2 = get_ecdict_db()
            assert db1 is db2


# ── Storage factories ─────────────────────────────────────────────────


class TestGetUserVocabStorage:
    """Tests for get_user_vocab_storage()."""

    def test_returns_json_storage(self) -> None:
        """Should return a JSONStorage parameterized for UserVocabulary."""
        _clear_all_caches()
        storage = get_user_vocab_storage()
        assert isinstance(storage, JSONStorage)

    def test_storage_model_is_user_vocabulary(self) -> None:
        """The storage's model type must be UserVocabulary."""
        _clear_all_caches()
        storage = get_user_vocab_storage()
        assert storage.model is UserVocabulary

    def test_storage_path_in_data_dir(self) -> None:
        """The storage path should be under the configured data_dir."""
        _clear_all_caches()
        with mock.patch.dict(os.environ, {"DATA_DIR": "/custom/data"}, clear=True):
            storage = get_user_vocab_storage()
            assert storage.path == Path("/custom/data/UserVocabulary.json")


class TestGetChapterDBStorage:
    """Tests for get_chapter_db_storage()."""

    def test_returns_json_storage(self) -> None:
        """Should return a JSONStorage parameterized for ChapterDB."""
        _clear_all_caches()
        storage = get_chapter_db_storage()
        assert isinstance(storage, JSONStorage)

    def test_storage_model_is_chapter_db(self) -> None:
        """The storage's model type must be ChapterDB."""
        _clear_all_caches()
        storage = get_chapter_db_storage()
        assert storage.model is ChapterDB


# ── Service factories — implemented ───────────────────────────────────


class TestGetArcPlanner:
    """Tests for get_arc_planner()."""

    def test_returns_arc_planner(self) -> None:
        """Should return an ArcPlanner instance."""
        _clear_all_caches()
        from app.services.arc_planner import ArcPlanner

        planner = get_arc_planner()
        assert isinstance(planner, ArcPlanner)

    def test_singleton_returns_same_instance(self) -> None:
        """Multiple calls must return the same ArcPlanner."""
        _clear_all_caches()
        p1 = get_arc_planner()
        p2 = get_arc_planner()
        assert p1 is p2


class TestGetMasteryEvaluator:
    """Tests for get_mastery_evaluator()."""

    def test_returns_mastery_evaluator(self) -> None:
        """Should return a MasteryEvaluator instance."""
        _clear_all_caches()
        from app.services.mastery_evaluator import MasteryEvaluator

        evaluator = get_mastery_evaluator()
        assert isinstance(evaluator, MasteryEvaluator)

    def test_singleton_returns_same_instance(self) -> None:
        """Multiple calls must return the same MasteryEvaluator."""
        _clear_all_caches()
        m1 = get_mastery_evaluator()
        m2 = get_mastery_evaluator()
        assert m1 is m2


class TestGetNovelPreprocessor:
    """Tests for get_novel_preprocessor()."""

    def test_returns_novel_preprocessor(self) -> None:
        """Should return a NovelPreprocessor instance."""
        _clear_all_caches()
        from app.services.novel_preprocessor import NovelPreprocessor

        with mock.patch.dict(os.environ, {"LLM_API_KEY": "sk-test"}, clear=True):
            preprocessor = get_novel_preprocessor()
            assert isinstance(preprocessor, NovelPreprocessor)

    def test_singleton_returns_same_instance(self) -> None:
        """Multiple calls must return the same NovelPreprocessor."""
        _clear_all_caches()
        with mock.patch.dict(os.environ, {"LLM_API_KEY": "sk-test"}, clear=True):
            n1 = get_novel_preprocessor()
            n2 = get_novel_preprocessor()
            assert n1 is n2


class TestGetStoryRewriter:
    """Tests for get_story_rewriter()."""

    def test_returns_story_rewriter(self) -> None:
        """Should return a StoryRewriter instance."""
        _clear_all_caches()
        from app.services.story_rewriter import StoryRewriter

        with mock.patch.dict(os.environ, {"LLM_API_KEY": "sk-test"}, clear=True):
            rewriter = get_story_rewriter()
            assert isinstance(rewriter, StoryRewriter)

    def test_singleton_returns_same_instance(self) -> None:
        """Multiple calls must return the same StoryRewriter."""
        _clear_all_caches()
        with mock.patch.dict(os.environ, {"LLM_API_KEY": "sk-test"}, clear=True):
            r1 = get_story_rewriter()
            r2 = get_story_rewriter()
            assert r1 is r2


class TestGetVocabularyAnnotator:
    """Tests for get_vocabulary_annotator()."""

    def test_returns_vocabulary_annotator(self, tmp_path: Path) -> None:
        """Should return a VocabularyAnnotator when UserVocabulary exists."""
        _clear_all_caches()
        # Create a minimal UserVocabulary file
        from app.models.fsrs import FsrsCard
        from app.models.vocabulary import UserVocabulary, VocabularyItem
        import datetime

        data_dir = tmp_path / "data"
        data_dir.mkdir()
        vocab_file = data_dir / "UserVocabulary.json"

        now = datetime.datetime.now(datetime.timezone.utc)
        vocab = UserVocabulary(
            user_id="test_user",
            vocabulary=[
                VocabularyItem(
                    id="hello_greeting",
                    word="hello",
                    meaning="你好",
                    chapter_first_seen=1,
                    fsrs_card=FsrsCard(
                        card_id=1,
                        state=1,
                        due=now,
                        last_review=None,
                    ),
                )
            ],
        )

        vocab_file.write_text(vocab.model_dump_json(), encoding="utf-8")

        with mock.patch.dict(os.environ, {"DATA_DIR": str(data_dir)}, clear=True):
            from app.services.vocabulary_annotator import VocabularyAnnotator

            annotator = get_vocabulary_annotator()
            assert isinstance(annotator, VocabularyAnnotator)


class TestGetVocabularyScheduler:
    """Tests for get_vocabulary_scheduler()."""

    def test_returns_callable(self) -> None:
        """Should return a callable (the schedule function)."""
        fn = get_vocabulary_scheduler()
        assert callable(fn)

    def test_returns_schedule_function(self) -> None:
        """The returned callable should be the scheduler's schedule function."""
        from app.services.vocabulary_scheduler.scheduler import schedule

        fn = get_vocabulary_scheduler()
        assert fn is schedule


# ── Service factories — stubs ─────────────────────────────────────────


class TestGetWordSenseDB:
    """Tests for get_word_sense_db()."""

    def test_returns_word_sense_db(self, tmp_path: Path) -> None:
        """Should return a WordSenseDB instance when WordSenseDB.json exists."""
        _clear_all_caches()
        from app.models.word_sense import WordSenseDB

        data_dir = tmp_path / "data"
        data_dir.mkdir()
        ws_file = data_dir / "WordSenseDB.json"
        ws_file.write_text(
            '{"test": {"is_polysemous": false, "senses": [{"id": "test_1", "meaning": "测试"}]}}',
            encoding="utf-8",
        )

        with mock.patch.dict(os.environ, {"DATA_DIR": str(data_dir)}, clear=True):
            db = get_word_sense_db()
            assert isinstance(db, WordSenseDB)
            assert db.lookup("test") is not None


class TestGetVocabularyPreprocessor:
    """Tests for get_vocabulary_preprocessor()."""

    def test_returns_vocabulary_preprocessor(self, tmp_path: Path) -> None:
        """Should return a VocabularyPreprocessor instance when WordSenseDB exists."""
        _clear_all_caches()
        from app.services.vocabulary_preprocessor import VocabularyPreprocessor

        data_dir = tmp_path / "data"
        data_dir.mkdir()
        ws_file = data_dir / "WordSenseDB.json"
        ws_file.write_text(
            '{"test": {"is_polysemous": false, "senses": [{"id": "test_1", "meaning": "测试"}]}}',
            encoding="utf-8",
        )

        with mock.patch.dict(os.environ, {"DATA_DIR": str(data_dir)}, clear=True):
            preprocessor = get_vocabulary_preprocessor()
            assert isinstance(preprocessor, VocabularyPreprocessor)

    def test_singleton_returns_same_instance(self, tmp_path: Path) -> None:
        """Multiple calls must return the same VocabularyPreprocessor."""
        _clear_all_caches()

        data_dir = tmp_path / "data"
        data_dir.mkdir()
        ws_file = data_dir / "WordSenseDB.json"
        ws_file.write_text(
            '{"test": {"is_polysemous": false, "senses": [{"id": "test_1", "meaning": "测试"}]}}',
            encoding="utf-8",
        )

        with mock.patch.dict(os.environ, {"DATA_DIR": str(data_dir)}, clear=True):
            p1 = get_vocabulary_preprocessor()
            p2 = get_vocabulary_preprocessor()
            assert p1 is p2


# ── ReadingTracker ─────────────────────────────────────────────────────


class TestGetReadingTracker:
    """Tests for get_reading_tracker()."""

    def test_returns_reading_tracker(self) -> None:
        """Should return a ReadingTracker instance."""
        _clear_all_caches()
        from app.services.reading_tracker import ReadingTracker

        tracker = get_reading_tracker()
        assert isinstance(tracker, ReadingTracker)

    def test_singleton_returns_same_instance(self) -> None:
        """Multiple calls must return the same ReadingTracker."""
        _clear_all_caches()
        r1 = get_reading_tracker()
        r2 = get_reading_tracker()
        assert r1 is r2


# ── ArcGenerationManager ───────────────────────────────────────────────


class TestGetArcGenerationManager:
    """Tests for get_arc_generation_manager()."""

    def test_returns_arc_generation_manager(self) -> None:
        """Should return an ArcGenerationManager instance."""
        _clear_all_caches()
        from app.services.arc_generation_manager import ArcGenerationManager

        # Mock vocab storage to avoid FileNotFoundError on data/UserVocabulary.json
        with _mock_vocab_storage():
            manager = get_arc_generation_manager()
        assert isinstance(manager, ArcGenerationManager)

    def test_singleton_returns_same_instance(self) -> None:
        """Multiple calls must return the same ArcGenerationManager."""
        _clear_all_caches()
        with _mock_vocab_storage():
            a1 = get_arc_generation_manager()
            a2 = get_arc_generation_manager()
        assert a1 is a2


# ── Singleton caching ─────────────────────────────────────────────────


class TestSingletonCaching:
    """Cross-cutting tests verifying that lru_cache works for all stateful factories."""

    FACTORIES = [
        (get_settings, "get_settings"),
        (get_llm_client, "get_llm_client"),
        (get_arc_planner, "get_arc_planner"),
        (get_mastery_evaluator, "get_mastery_evaluator"),
        (get_novel_preprocessor, "get_novel_preprocessor"),
        (get_story_rewriter, "get_story_rewriter"),
        (get_reading_tracker, "get_reading_tracker"),
        (get_arc_generation_manager, "get_arc_generation_manager"),
    ]

    @pytest.mark.parametrize("factory, name", FACTORIES)
    def test_cached_instances_are_identical(self, factory, name) -> None:  # noqa: ARG002
        """All stateful factories must return the same object on repeat calls."""
        _clear_all_caches()
        with (
            mock.patch.dict(os.environ, {"LLM_API_KEY": "sk-test"}, clear=True),
            _mock_vocab_storage(),
        ):
            inst1 = factory()
            inst2 = factory()
            assert inst1 is inst2, (
                f"{name} did not return the same instance — lru_cache broken"
            )


# ── Edge cases ────────────────────────────────────────────────────────


class TestEdgeCases:
    """Edge case tests for the dependency injection layer."""

    def test_settings_partial_env_override(self) -> None:
        """Only some env vars set — others fall back to defaults."""
        _clear_all_caches()
        with mock.patch.dict(
            os.environ,
            {"LLM_API_KEY": "only-key-set", "DATA_DIR": "/only/data"},
            clear=True,
        ):
            s = get_settings()
            assert s.openai_api_key == "only-key-set"
            assert s.data_dir == Path("/only/data")
            # Unset ones use defaults
            assert s.openai_model == "deepseek-v4-flash"
            assert s.openai_base_url == "http://localhost:11434/v1"
            assert s.ecdict_db_path == Path("asset/ecdict_mobile.db")
            assert s.instructor_mode == "JSON"

    def test_storage_does_not_create_file(self, tmp_path: Path) -> None:
        """Storage factory should not create files — only storage.load() or .save() does."""
        _clear_all_caches()
        with mock.patch.dict(os.environ, {"DATA_DIR": str(tmp_path)}, clear=True):
            storage = get_user_vocab_storage()
            assert not storage.path.exists()
