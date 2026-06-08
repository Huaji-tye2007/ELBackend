"""Tests for ArcGenerationManager — full 6-phase pipeline with retry and checkpoint.

All upstream services are mocked via ``unittest.mock.create_autospec``
per AGENTS.md §16.3.  No real LLM calls or file I/O to ``data/``.
"""

from __future__ import annotations

import asyncio
import datetime
import os
from pathlib import Path
from unittest import mock

import pytest

from app.core.exceptions import GenerationConflictError
from app.models.arc_generation import ArcGenerationState
from app.models.arc_plan import ArcPlan, EpisodeSlot, TargetWord
from app.models.chapter import Chapter
from app.models.episode import (
    DialogueMessage,
    Episode,
    Meta,
    NarrationMessage,
    VocabEntry,
)
from app.models.fsrs import FsrsCard
from app.models.progress import ReadingProgress
from app.models.vocabulary import UserVocabulary, VocabularyItem
from app.services.arc_generation_manager import ArcGenerationManager

# ════════════════════════════════════════════════════════════════
# Helpers
# ════════════════════════════════════════════════════════════════


def _make_fsrs_card() -> FsrsCard:
    """Create a minimal FSRS card for tests."""
    return FsrsCard(
        card_id=1001,
        state=1,
        stability=None,
        difficulty=None,
        due=datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc),
        last_review=None,
    )


def _make_vocab_item(item_id: str, word: str, meaning: str) -> VocabularyItem:
    """Create a minimal VocabularyItem."""
    return VocabularyItem(
        id=item_id,
        word=word,
        meaning=meaning,
        chapter_first_seen=1,
        history_window=[1, 1, 1, 1, 1],
        fsrs_card=_make_fsrs_card(),
    )


def _make_user_vocab() -> UserVocabulary:
    """Create a sample UserVocabulary with 3 items."""
    return UserVocabulary(
        user_id="test_user",
        vocabulary=[
            _make_vocab_item("item_1", "consume", "消费"),
            _make_vocab_item("item_2", "journey", "旅程"),
            _make_vocab_item("item_3", "discover", "发现"),
        ],
    )


def _make_progress() -> ReadingProgress:
    """Create a minimal ReadingProgress."""
    return ReadingProgress(
        current_chapter=1,
        current_episode=1,
        chapter_offset=0.0,
        total_episodes_read=0,
    )


def _make_chapter(
    chapter_id: int = 1,
    raw_text: str = "The journey begins at dawn.",
) -> Chapter:
    """Create a minimal Chapter."""
    return Chapter(
        chapter_id=chapter_id,
        title=f"Chapter {chapter_id}",
        raw_text=raw_text,
        summary="",
        characters=[],
        world_setting="",
        estimated_reading_time=0,
    )


def _make_target_word(
    item_id: str,
    word: str = "consume",
    meaning: str = "消费",
    is_new: bool = False,
) -> TargetWord:
    """Create a minimal TargetWord."""
    return TargetWord(
        item_id=item_id,
        word=word,
        meaning=meaning,
        is_new=is_new,
    )


def _make_episode_slot(
    episode_id: int = 1,
    episode_type: str = "main",
    source_text: str = "Sample source text.",
    target_words: list[TargetWord] | None = None,
) -> EpisodeSlot:
    """Create a minimal EpisodeSlot."""
    return EpisodeSlot(
        episode_id=episode_id,
        episode_type=episode_type,  # type: ignore[arg-type]
        source_text=source_text,
        target_words=target_words or [],
    )


def _make_arc_plan(
    arc_id: str = "arc_test",
    episodes: list[EpisodeSlot] | None = None,
) -> ArcPlan:
    """Create a minimal ArcPlan."""
    return ArcPlan(
        arc_id=arc_id,
        episodes=episodes
        or [
            _make_episode_slot(1, "main", "Text for episode 1."),
            _make_episode_slot(2, "main", "Text for episode 2."),
        ],
    )


def _make_rewrite_result() -> mock.MagicMock:
    """Create a mocked RewriteResult with messages and target_words_used."""
    result = mock.MagicMock()
    result.messages = [
        NarrationMessage(type="narration", text="I began the journey.", marks=[]),
        DialogueMessage(
            type="dialogue", side="right", name="Hero", text="Let us go.", marks=[]
        ),
    ]
    result.target_words_used = [{"item_id": "item_1", "surface": "journey"}]
    result.model_dump.return_value = {
        "messages": [
            {"type": "narration", "text": "I began the journey.", "marks": []},
            {
                "type": "dialogue",
                "side": "right",
                "name": "Hero",
                "text": "Let us go.",
                "marks": [],
            },
        ],
        "target_words_used": [{"item_id": "item_1", "surface": "journey"}],
    }
    return result


def _make_annotated_messages() -> list:
    """Create annotated messages with marks."""
    from app.models.episode import Mark

    return [
        NarrationMessage(
            type="narration",
            text="I began the journey.",
            marks=[
                Mark(word="journey", index=2, definition="旅程", is_new=True),
            ],
        ),
        DialogueMessage(
            type="dialogue",
            side="right",
            name="Hero",
            text="Let us go.",
            marks=[],
        ),
    ]


def _make_episode_obj() -> Episode:
    """Create a minimal Episode for formatter output."""
    return Episode(
        meta=Meta(ep=1, title="Episode 1", kind="main"),
        messages=[
            NarrationMessage(type="narration", text="Hello.", marks=[]),
        ],
        vocab=[VocabEntry(word="hello", definition="你好", is_new=True)],
    )


# ════════════════════════════════════════════════════════════════
# Fixtures
# ════════════════════════════════════════════════════════════════


@pytest.fixture
def mock_arc_planner():
    """Mock ArcPlanner with plan_next_arc that returns ArcPlan."""
    planner = mock.MagicMock()
    # plan_next_arc is a sync method returning (ArcPlan, end_chapter_id, end_word_offset)
    planner.plan_next_arc.return_value = (_make_arc_plan(), 1, 0)
    return planner


@pytest.fixture
def mock_vocab_scheduler():
    """Mock schedule() function that returns populated arc_plan dict."""

    async def _schedule(arc_plan, user_vocab, now=None, **kwargs):
        episodes = arc_plan.get("episodes", [])
        for ep in episodes:
            ep["target_words"] = [
                {
                    "item_id": "item_1",
                    "word": "journey",
                    "meaning": "旅程",
                    "is_new": True,
                }
            ]
        return arc_plan

    return mock.AsyncMock(side_effect=_schedule)


@pytest.fixture
def mock_story_rewriter():
    """Mock StoryRewriter with rewrite_episode returning RewriteResult."""
    rewriter = mock.MagicMock()
    # Make rewrite_episode an AsyncMock since it's async
    rewriter.rewrite_episode = mock.AsyncMock(return_value=_make_rewrite_result())
    return rewriter


@pytest.fixture
def mock_vocab_annotator():
    """Mock VocabularyAnnotator with annotate returning annotated messages."""
    annotator = mock.MagicMock()
    annotator.annotate.return_value = _make_annotated_messages()
    return annotator


@pytest.fixture
def mock_episode_formatter(tmp_path: Path):
    """Mock EpisodeFormatter with format_episode and write_cache."""
    formatter = mock.MagicMock()
    formatter.format_episode.return_value = _make_episode_obj()
    formatter.write_cache.return_value = tmp_path / "EpisodeCache" / "ep_0001.json"
    return formatter


@pytest.fixture
def manager(
    mock_arc_planner,
    mock_vocab_scheduler,
    mock_story_rewriter,
    mock_vocab_annotator,
    mock_episode_formatter,
) -> ArcGenerationManager:
    """Create a fully-injected ArcGenerationManager with all mocks."""
    return ArcGenerationManager(
        arc_planner=mock_arc_planner,
        vocab_scheduler=mock_vocab_scheduler,
        story_rewriter=mock_story_rewriter,
        vocab_annotator=mock_vocab_annotator,
        episode_formatter=mock_episode_formatter,
    )


@pytest.fixture
def pipeline_data():
    """Return a dict of all data needed for _run_pipeline."""
    return {
        "arc_id": "arc_test_001",
        "user_id": "test_user",
        "progress": _make_progress(),
        "chapters": [_make_chapter()],
        "user_vocab": _make_user_vocab(),
        "prev_arc": None,
        "episode_cache": None,
    }


# ════════════════════════════════════════════════════════════════
# Tests
# ════════════════════════════════════════════════════════════════


class TestFullPipeline:
    """Test the complete IDLE → COMPLETE pipeline."""

    async def test_full_pipeline_idle_to_complete(
        self, manager, pipeline_data, tmp_path: Path
    ):
        """A full pipeline run transitions through all 6 phases and reaches COMPLETE."""
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        monkeypatch_checkpoint(manager, data_dir / "arc_generation_state.json")

        await manager._run_pipeline(**pipeline_data)

        status = await manager.get_status()
        assert status.phase == "COMPLETE"
        assert status.progress["current"] == 2  # 2 episodes generated
        assert status.progress["total"] == 2
        assert status.retry_count == 0
        assert status.last_error is None

    async def test_all_phases_called_in_order(
        self, manager, pipeline_data, tmp_path: Path
    ):
        """Each service is invoked exactly as expected during the pipeline."""
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        monkeypatch_checkpoint(manager, data_dir / "arc_generation_state.json")

        await manager._run_pipeline(**pipeline_data)

        # ArcPlanner was called
        manager._arc_planner.plan_next_arc.assert_called_once()

        # VocabularyScheduler was called
        manager._vocab_scheduler.assert_called_once()

        # StoryRewriter was called for each episode (2 episodes)
        assert manager._story_rewriter.rewrite_episode.call_count == 2

        # VocabularyAnnotator was called for each episode
        assert manager._vocab_annotator.annotate.call_count == 2

        # EpisodeFormatter was called for each episode
        assert manager._episode_formatter.format_episode.call_count == 2
        assert manager._episode_formatter.write_cache.call_count == 2

    async def test_checkpoint_written_after_each_phase(
        self, manager, pipeline_data, tmp_path: Path
    ):
        """Checkpoint is written after each phase transition."""
        checkpoint_path = tmp_path / "data" / "arc_generation_state.json"
        os.makedirs(checkpoint_path.parent, exist_ok=True)
        monkeypatch_checkpoint(manager, checkpoint_path)

        # Track checkpoint writes
        checkpoint_phases: list[str] = []
        original_checkpoint = manager._checkpoint

        async def _tracking_checkpoint():
            await original_checkpoint()
            if manager._state is not None:
                checkpoint_phases.append(manager._state.phase)

        manager._checkpoint = _tracking_checkpoint  # type: ignore[method-assign]

        await manager._run_pipeline(**pipeline_data)

        # Verify phases were checkpointed in order
        assert "PLANNING" in checkpoint_phases
        assert "SCHEDULING" in checkpoint_phases
        assert "GENERATING" in checkpoint_phases
        assert "ANNOTATING" in checkpoint_phases
        assert "FORMATTING" in checkpoint_phases
        assert checkpoint_phases[-1] == "COMPLETE"


class TestConcurrency:
    """Test concurrent generation prevention."""

    async def test_concurrent_start_raises_conflict(
        self, manager, pipeline_data, tmp_path: Path
    ):
        """Starting a second generation while one is running raises GenerationConflictError."""
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        monkeypatch_checkpoint(manager, data_dir / "arc_generation_state.json")

        # Block the pipeline at the planner stage so we can test concurrency
        pipeline_blocker = asyncio.Event()

        async def _slow_planner(*args, **kwargs):
            await pipeline_blocker.wait()
            return (_make_arc_plan(), 1, 0)

        manager._arc_planner.plan_next_arc.side_effect = _slow_planner

        # Start first generation
        await manager.start_generation(
            arc_id="arc_001",
            user_id="test_user",
            progress=pipeline_data["progress"],
            chapters=pipeline_data["chapters"],
            user_vocab=pipeline_data["user_vocab"],
        )

        # Give task time to start and hit the blocker
        await asyncio.sleep(0.01)

        # Attempt concurrent start — should fail because pipeline is running
        with pytest.raises(GenerationConflictError, match="already in progress"):
            await manager.start_generation(
                arc_id="arc_002",
                user_id="test_user",
                progress=pipeline_data["progress"],
                chapters=pipeline_data["chapters"],
                user_vocab=pipeline_data["user_vocab"],
            )

        # Release the blocker to let the first pipeline complete
        pipeline_blocker.set()
        await asyncio.sleep(0.01)

    async def test_start_after_complete_allowed(
        self, manager, pipeline_data, tmp_path: Path
    ):
        """After pipeline completes, a new generation can be started."""
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        monkeypatch_checkpoint(manager, data_dir / "arc_generation_state.json")

        # Run first pipeline to completion
        await manager._run_pipeline(**pipeline_data)

        # Should be able to start a new one
        result = await manager.start_generation(
            arc_id="arc_003",
            progress=pipeline_data["progress"],
            chapters=pipeline_data["chapters"],
            user_vocab=pipeline_data["user_vocab"],
        )
        assert result["status"] == "queued"

        # Wait for task to finish
        await asyncio.sleep(0.05)


class TestRetry:
    """Test retry behavior with exponential backoff."""

    async def test_retry_succeeds_after_one_failure(
        self, manager, pipeline_data, tmp_path: Path
    ):
        """LLM fails once, retries, and succeeds."""
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        monkeypatch_checkpoint(manager, data_dir / "arc_generation_state.json")

        call_count = 0

        async def _fail_once(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("LLM timeout")
            return _make_rewrite_result()

        manager._story_rewriter.rewrite_episode.side_effect = _fail_once

        with mock.patch("asyncio.sleep", new_callable=mock.AsyncMock):
            await manager._run_pipeline(**pipeline_data)

        status = await manager.get_status()
        assert status.phase == "COMPLETE"
        assert status.retry_count == 0  # reset after success

    async def test_three_retries_exhausted_fails(
        self, manager, pipeline_data, tmp_path: Path
    ):
        """After 3 retries (4 total attempts), the pipeline transitions to FAILED."""
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        monkeypatch_checkpoint(manager, data_dir / "arc_generation_state.json")

        # StoryRewriter always fails
        manager._story_rewriter.rewrite_episode.side_effect = RuntimeError(
            "LLM persistent failure"
        )

        with mock.patch("asyncio.sleep", new_callable=mock.AsyncMock):
            await manager._run_pipeline(**pipeline_data)

        status = await manager.get_status()
        assert status.phase == "FAILED"
        assert status.last_error is not None
        assert "LLM persistent failure" in (status.last_error or "")
        assert status.retry_count == 3

    async def test_retry_backoff_intervals(
        self, manager, pipeline_data, tmp_path: Path
    ):
        """Retry waits 10s, 30s, 90s between attempts."""
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        monkeypatch_checkpoint(manager, data_dir / "arc_generation_state.json")

        # Make planner fail to trigger retries
        manager._arc_planner.plan_next_arc.side_effect = RuntimeError("fail")

        # Track sleep intervals
        sleep_intervals: list[float] = []

        async def _tracking_sleep(delay: float):
            sleep_intervals.append(delay)

        with mock.patch("asyncio.sleep", side_effect=_tracking_sleep):
            await manager._run_pipeline(**pipeline_data)

        # First retry at 10s, second at 30s, third at 90s
        retry_delays = [d for d in sleep_intervals if d > 0]
        assert len(retry_delays) == 3
        assert retry_delays[0] == 10.0
        assert retry_delays[1] == 30.0
        assert retry_delays[2] == 90.0


class TestResume:
    """Test resume from checkpoint."""

    async def test_resume_from_generating_midpoint(
        self, manager, pipeline_data, tmp_path: Path
    ):
        """Pipeline can resume from checkpoint at GENERATING(5/10)."""
        checkpoint_path = tmp_path / "data" / "arc_generation_state.json"
        os.makedirs(checkpoint_path.parent, exist_ok=True)
        monkeypatch_checkpoint(manager, checkpoint_path)

        # Create a checkpoint at GENERATING phase with progress 5/10
        state = ArcGenerationState(
            arc_id="arc_resume",
            phase="GENERATING",
            progress={"current": 5, "total": 10},
            started_at=datetime.datetime.now(datetime.timezone.utc),
            intermediate_data={
                "arc_plan": _make_arc_plan().model_dump(),
                "scheduled": {"episodes": []},  # Empty — will be rebuilt
            },
        )
        manager._state = state

        # Resume from this state
        # In MVP, resume re-runs the pipeline from scratch
        await manager._resume_pipeline(
            user_id=pipeline_data["user_id"],
            progress=pipeline_data["progress"],
            chapters=pipeline_data["chapters"],
            user_vocab=pipeline_data["user_vocab"],
        )

        status = await manager.get_status()
        assert status.phase == "COMPLETE"

    async def test_resume_skips_when_complete(
        self, manager, pipeline_data, tmp_path: Path
    ):
        """resume_pipeline is a no-op when phase is COMPLETE."""
        manager._state = ArcGenerationState(
            arc_id="arc_done",
            phase="COMPLETE",
            progress={"current": 10, "total": 10},
        )

        await manager._resume_pipeline(
            user_id=pipeline_data["user_id"],
            progress=pipeline_data["progress"],
            chapters=pipeline_data["chapters"],
            user_vocab=pipeline_data["user_vocab"],
        )

        # No services called
        manager._arc_planner.plan_next_arc.assert_not_called()


class TestProgress:
    """Test progress tracking during pipeline."""

    async def test_progress_updates_during_generating(
        self, manager, pipeline_data, tmp_path: Path
    ):
        """Progress current/total is updated after each episode generation."""
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        checkpoint_path = data_dir / "arc_generation_state.json"
        monkeypatch_checkpoint(manager, checkpoint_path)

        # Collect progress snapshots
        progress_snapshots: list[dict[str, int]] = []
        original_checkpoint = manager._checkpoint

        async def _tracking_checkpoint():
            await original_checkpoint()
            if manager._state is not None:
                progress_snapshots.append(dict(manager._state.progress))

        manager._checkpoint = _tracking_checkpoint  # type: ignore[method-assign]

        await manager._run_pipeline(**pipeline_data)

        # Should have progress entries showing incrementing current
        generating_progress = [p for p in progress_snapshots if p["total"] == 2]
        # At least one entry with current=1 and one with current=2
        currents = [p["current"] for p in generating_progress]
        assert 1 in currents
        assert 2 in currents


class TestEmptyTargetWords:
    """Test handling of episodes with no target words."""

    async def test_empty_target_words(self, manager, pipeline_data, tmp_path: Path):
        """Pipeline handles episodes with empty target_words gracefully."""
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        monkeypatch_checkpoint(manager, data_dir / "arc_generation_state.json")

        # Make scheduler return episodes with no target_words
        async def _schedule_empty(arc_plan, user_vocab, now=None, **kwargs):
            episodes = arc_plan.get("episodes", [])
            for ep in episodes:
                ep["target_words"] = []
            return arc_plan

        manager._vocab_scheduler.side_effect = _schedule_empty

        # Annotator should handle empty target_words
        manager._vocab_annotator.annotate.return_value = [
            NarrationMessage(type="narration", text="No marks.", marks=[]),
        ]

        await manager._run_pipeline(**pipeline_data)

        status = await manager.get_status()
        assert status.phase == "COMPLETE"
        # Annotator was still called (with empty target_words)
        assert manager._vocab_annotator.annotate.call_count >= 1

    async def test_missing_data_fails_gracefully(self, manager, tmp_path: Path):
        """Pipeline fails cleanly when required data is None."""
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        monkeypatch_checkpoint(manager, data_dir / "arc_generation_state.json")

        await manager._run_pipeline(
            arc_id="arc_no_data",
            user_id="test",
            progress=None,
            chapters=[],
            user_vocab=None,
        )

        status = await manager.get_status()
        assert status.phase == "FAILED"
        assert status.last_error is not None


# ════════════════════════════════════════════════════════════════
# Utility — monkeypatch checkpoint path
# ════════════════════════════════════════════════════════════════


def monkeypatch_checkpoint(manager: ArcGenerationManager, path: Path) -> None:
    """Redirect the manager's checkpoint writes to a test-specific path."""
    import app.services.arc_generation_manager as agm

    agm._CHECKPOINT_PATH = path
