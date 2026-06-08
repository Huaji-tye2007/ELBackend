"""Test fixtures for API v1 route tests.

Provides a self-contained FastAPI test application with dependency
overrides so tests do not depend on app.main (T19) or
app.core.dependencies (T18) being ready.

Ref: AGENTS.md §16.8 — FastAPI route testing with httpx.AsyncClient.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.v1.router import router as v1_router
from app.core.dependencies import (
    get_arc_generation_manager,
    get_chapter_db_storage,
    get_ecdict_db,
    get_mastery_evaluator,
    get_progress,
    get_reading_tracker,
    get_user_vocab,
    get_user_vocab_storage,
    get_vocabulary_preprocessor,
)
from app.models.arc_generation import ArcGenerationState
from app.models.chapter import Chapter, ChapterDB
from app.models.episode_log import EpisodeReadingLog
from app.models.fsrs import FsrsCard
from app.models.progress import ReadingProgress
from app.models.vocabulary import UserVocabulary, VocabularyItem


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_item(
    item_id: str, word: str, meaning: str, chapter: int = 1
) -> VocabularyItem:
    """Create a minimal VocabularyItem for test data."""
    return VocabularyItem(
        id=item_id,
        word=word,
        meaning=meaning,
        chapter_first_seen=chapter,
        fsrs_card=FsrsCard(state=1, due=datetime.now(timezone.utc)),
    )


# ---------------------------------------------------------------------------
# In-memory mock storage
# ---------------------------------------------------------------------------


class _MockStorage:
    """In-memory mock for JSONStorage[UserVocabulary] used in API tests.

    Stores/loads a UserVocabulary instance in memory, allowing tests
    to verify the upload → save → load roundtrip without touching disk.
    """

    def __init__(self) -> None:
        self._data: UserVocabulary | None = None

    def load(self) -> UserVocabulary:
        """Load the in-memory UserVocabulary.

        Raises FileNotFoundError if nothing has been saved (simulates cold start).
        """
        if self._data is None:
            raise FileNotFoundError("No vocabulary data saved yet")
        return self._data

    def save(self, obj: UserVocabulary) -> None:
        """Save a UserVocabulary instance to memory."""
        self._data = obj


class _MockPreprocessor:
    """Mock VocabularyPreprocessor that converts raw items to VocabularyItems."""

    @staticmethod
    def preprocess(
        raw_items: list[dict[str, str]], user_id: str = "test"
    ) -> UserVocabulary:
        """Create a UserVocabulary from raw word-meaning pairs.

        Each word gets a VocabularyItem with a generated item_id and
        a default FSRS card (state=1, due=now).
        """
        items: list[VocabularyItem] = []
        for raw in raw_items:
            word = raw["word"]
            meaning = raw["meaning"]
            item_id = f"{word}_{len(items) + 1}"
            items.append(
                VocabularyItem(
                    id=item_id,
                    word=word,
                    meaning=meaning,
                    chapter_first_seen=1,
                    fsrs_card=FsrsCard(state=1, due=datetime.now(timezone.utc)),
                )
            )
        return UserVocabulary(user_id=user_id, vocabulary=items)


# ---------------------------------------------------------------------------
# Reading mocks
# ---------------------------------------------------------------------------


class _MockReadingTracker:
    """In-memory mock for ReadingTracker."""

    def __init__(self) -> None:
        self._progress = ReadingProgress(
            current_chapter=1,
            current_episode=1,
            chapter_offset=0.0,
            total_episodes_read=0,
        )
        self._logs: dict[int, EpisodeReadingLog] = {}
        self._track_calls: list[EpisodeReadingLog] = []

    def track(self, episode_log: EpisodeReadingLog) -> bool:
        self._track_calls.append(episode_log)
        self._logs[episode_log.episode_id] = episode_log
        self._progress = self._progress.model_copy(
            update={"total_episodes_read": self._progress.total_episodes_read + 1}
        )
        return True

    def get_progress(self) -> ReadingProgress:
        return self._progress

    def get_log(self, episode_id: int) -> EpisodeReadingLog | None:
        return self._logs.get(episode_id)


class _MockMasteryEvaluator:
    """Mock MasteryEvaluator that returns the input vocab unchanged but counts items."""

    def evaluate(
        self, episode_log: EpisodeReadingLog, user_vocab: UserVocabulary
    ) -> UserVocabulary:
        return user_vocab


# ---------------------------------------------------------------------------
# Dictionary mocks
# ---------------------------------------------------------------------------


class _MockEcdictDb(sqlite3.Connection):
    """In-memory SQLite mock for ECDICT dictionary lookups."""

    def __init__(self) -> None:
        super().__init__(":memory:")
        self.row_factory = sqlite3.Row
        self._setup_schema()

    def _setup_schema(self) -> None:
        self.execute(
            "CREATE TABLE dict (word TEXT PRIMARY KEY, translation TEXT, exchange TEXT)"
        )
        self.execute("INSERT INTO dict VALUES ('test', '测试', '')")
        self.execute("INSERT INTO dict VALUES ('bank', '银行;河岸', '')")
        self.commit()

    def execute(self, sql: str, parameters=()):  # type: ignore[override]
        return super().execute(sql, parameters)


# ---------------------------------------------------------------------------
# Arc mocks
# ---------------------------------------------------------------------------


class _MockArcGenerationManager:
    """Mock ArcGenerationManager with controllable state."""

    def __init__(self) -> None:
        self._state = ArcGenerationState(
            arc_id="test_arc",
            phase="IDLE",
            progress={"current": 0, "total": 10},
        )
        self._busy = False
        self._generate_calls: list[dict] = []

    async def start_generation(
        self, arc_id: str | None = None, user_id: str = "default", **kwargs: object
    ) -> dict:
        if self._busy:
            from app.core.exceptions import GenerationConflictError

            raise GenerationConflictError("Already generating")
        self._busy = True
        self._generate_calls.append({"arc_id": arc_id, "user_id": user_id, **kwargs})
        return {"job_id": "test_job_001", "status": "queued"}

    async def get_status(self) -> ArcGenerationState:
        return self._state

    async def resume_on_startup(self) -> None:
        pass


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_storage() -> _MockStorage:
    """In-memory storage mock for vocabulary endpoints."""
    return _MockStorage()


@pytest.fixture
def mock_preprocessor() -> _MockPreprocessor:
    """Vocabulary preprocessor mock."""
    return _MockPreprocessor()


@pytest.fixture
def mock_reading_tracker() -> _MockReadingTracker:
    """In-memory reading tracker mock."""
    return _MockReadingTracker()


@pytest.fixture
def mock_mastery_evaluator() -> _MockMasteryEvaluator:
    """Mastery evaluator mock."""
    return _MockMasteryEvaluator()


@pytest.fixture
def mock_ecdict_db() -> _MockEcdictDb:
    """In-memory ECDICT database mock."""
    return _MockEcdictDb()


@pytest.fixture
def mock_arc_manager() -> _MockArcGenerationManager:
    """Arc generation manager mock."""
    return _MockArcGenerationManager()


@pytest.fixture
def test_app(
    mock_storage: _MockStorage,
    mock_preprocessor: _MockPreprocessor,
    mock_reading_tracker: _MockReadingTracker,
    mock_mastery_evaluator: _MockMasteryEvaluator,
    mock_ecdict_db: _MockEcdictDb,
    mock_arc_manager: _MockArcGenerationManager,
) -> FastAPI:
    """FastAPI test application with the v1 router and overridden dependencies.

    Creates a standalone app that includes only the v1 router, with
    all dependencies replaced by in-memory mocks.

    Use with httpx.AsyncClient via ASGITransport for async route testing.
    """
    app = FastAPI()

    # Override vocabulary dependencies
    app.dependency_overrides[get_user_vocab_storage] = lambda: mock_storage
    app.dependency_overrides[get_vocabulary_preprocessor] = lambda: mock_preprocessor

    # Override reading dependencies
    app.dependency_overrides[get_reading_tracker] = lambda: mock_reading_tracker
    app.dependency_overrides[get_mastery_evaluator] = lambda: mock_mastery_evaluator

    # Override dictionary dependency
    app.dependency_overrides[get_ecdict_db] = lambda: mock_ecdict_db

    # Override arc dependency
    app.dependency_overrides[get_arc_generation_manager] = lambda: mock_arc_manager

    # Override progress and user_vocab used by arc generate route
    app.dependency_overrides[get_user_vocab] = lambda: UserVocabulary(
        user_id="test", vocabulary=[]
    )
    app.dependency_overrides[get_progress] = lambda: ReadingProgress(
        current_chapter=1,
        current_episode=1,
        chapter_offset=0.0,
        total_episodes_read=0,
    )

    # Override chapter DB used by arc generate route
    class _MockChapterStorage:
        def load(self):
            return ChapterDB(
                chapters=[
                    Chapter(
                        chapter_id=1,
                        title="Chapter 1",
                        raw_text="This is enough text for a mocked chapter.",
                        summary="A mocked chapter.",
                        characters=[],
                        world_setting="Test",
                        estimated_reading_time=1,
                    )
                ]
            )

        def save(self, _):
            pass

    app.dependency_overrides[get_chapter_db_storage] = lambda: _MockChapterStorage()

    app.include_router(v1_router, prefix="/api/v1")
    return app


@pytest.fixture
async def client(test_app: FastAPI) -> AsyncClient:
    """An httpx AsyncClient connected to the test FastAPI app.

    Uses ASGITransport for direct ASGI invocation (no network calls).
    """
    async with AsyncClient(
        transport=ASGITransport(app=test_app), base_url="http://test"
    ) as ac:
        yield ac


@pytest.fixture
def seeded_storage(mock_storage: _MockStorage) -> _MockStorage:
    """Storage pre-seeded with 3 vocabulary items for GET tests."""
    uv = UserVocabulary(
        user_id="test_user",
        vocabulary=[
            _make_item("word_1", "test", "测试"),
            _make_item("bank_river", "bank", "河岸"),
            _make_item("bank_finance", "bank", "银行"),
        ],
    )
    mock_storage.save(uv)
    return mock_storage


@pytest.fixture
def seeded_storage_for_finish(mock_storage: _MockStorage) -> _MockStorage:
    """Storage pre-seeded with vocabulary for finish-episode tests."""
    uv = UserVocabulary(
        user_id="test_user",
        vocabulary=[
            _make_item("hello_1", "hello", "你好"),
            _make_item("world_1", "world", "世界"),
        ],
    )
    mock_storage.save(uv)
    return mock_storage
