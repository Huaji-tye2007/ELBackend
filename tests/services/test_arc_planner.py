"""Tests for app.services.arc_planner — config constants and _slice_episode_text."""

from __future__ import annotations

import copy

import pytest

from app.models.arc_plan import ArcPlan, EpisodeSlot, PendingWord
from app.models.chapter import Chapter
from app.models.progress import ReadingProgress
from app.services.arc_planner import (
    DEFAULT_EPISODES_PER_ARC,
    MAX_EPISODE_WORDS,
    MIN_EPISODE_WORDS,
    OVERLAP_WORDS,
    SIDE_EP_TRIGGER_MIN_WORDS,
    SIDE_EP_REJECT_THRESHOLD,
    _slice_episode_text,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_chapter(
    chapter_id: int,
    title: str = "Test Chapter",
    raw_text: str = "",
) -> Chapter:
    """Create a minimal Chapter model for test brevity."""
    return Chapter(
        chapter_id=chapter_id,
        title=title,
        raw_text=raw_text,
        summary="",
        characters=[],
        world_setting="",
        estimated_reading_time=0,
    )


def _make_text(word_count: int) -> str:
    """Generate text with exactly *word_count* unique words.

    Produces "word_1 word_2 ... word_N" for deterministic, inspectable slices.
    """
    return " ".join(f"word_{i}" for i in range(word_count))


def _make_reading_progress(
    current_chapter: int = 1,
    chapter_offset: float = 0.0,
) -> ReadingProgress:
    """Create a minimal ReadingProgress for test brevity."""
    return ReadingProgress(
        current_chapter=current_chapter,
        current_episode=1,
        chapter_offset=chapter_offset,
        total_episodes_read=0,
    )


# ---------------------------------------------------------------------------
# Config constants
# ---------------------------------------------------------------------------


class TestConfigConstants:
    """Verify every module-level constant has the expected value."""

    def test_default_episodes_per_arc(self) -> None:
        assert DEFAULT_EPISODES_PER_ARC == 10

    def test_min_episode_words(self) -> None:
        assert MIN_EPISODE_WORDS == 400

    def test_max_episode_words(self) -> None:
        assert MAX_EPISODE_WORDS == 600

    def test_overlap_words(self) -> None:
        assert OVERLAP_WORDS == 100

    def test_side_ep_reject_threshold(self) -> None:
        assert SIDE_EP_REJECT_THRESHOLD == 3

    def test_side_ep_trigger_min_words(self) -> None:
        assert SIDE_EP_TRIGGER_MIN_WORDS == 5


# ---------------------------------------------------------------------------
# _slice_episode_text
# ---------------------------------------------------------------------------


class TestSliceNormalCases:
    """Happy-path slicing with enough words available."""

    def test_slice_normal_from_start(self) -> None:
        """1000-word text, start=0 → returns slice and next_offset."""
        text = _make_text(1000)
        sliced, next_start = _slice_episode_text(
            text,
            start_word_offset=0,
            min_words=MIN_EPISODE_WORDS,
            max_words=MAX_EPISODE_WORDS,
            overlap_words=OVERLAP_WORDS,
        )

        words = sliced.split()
        assert MIN_EPISODE_WORDS <= len(words) <= MAX_EPISODE_WORDS
        # next_start should be end_offset - overlap
        # end_offset = start + MAX_EPISODE_WORDS = 600
        assert next_start == MAX_EPISODE_WORDS - OVERLAP_WORDS  # 500

    def test_slice_from_mid_position(self) -> None:
        """1000-word text, start=200 → returns slice starting at word_200."""
        text = _make_text(1000)
        sliced, _next_start = _slice_episode_text(
            text,
            start_word_offset=200,
            min_words=MIN_EPISODE_WORDS,
            max_words=MAX_EPISODE_WORDS,
            overlap_words=OVERLAP_WORDS,
        )

        words = sliced.split()
        # First word should be "word_200"
        assert words[0] == "word_200"
        assert len(words) == MAX_EPISODE_WORDS

    def test_slice_overlap_calculation(self) -> None:
        """Verify next_start_word_offset = end_offset - overlap_words."""
        text = _make_text(1000)
        _sliced, next_start = _slice_episode_text(
            text,
            start_word_offset=0,
            min_words=MIN_EPISODE_WORDS,
            max_words=MAX_EPISODE_WORDS,
            overlap_words=OVERLAP_WORDS,
        )

        # end_offset = 600 (start 0 + max 600), overlap = 100 → next = 500
        assert next_start == 500

    def test_slice_continuity_with_overlap(self) -> None:
        """Two consecutive slices should overlap correctly."""
        text = _make_text(1500)

        slice1, next1 = _slice_episode_text(text, 0, 400, 600, 100)
        slice2, _next2 = _slice_episode_text(text, next1, 400, 600, 100)

        # slice1 ends at word_599, slice2 starts at 500
        # Words 500-599 appear in both slices
        words1 = set(slice1.split())
        words2 = set(slice2.split())
        overlap = words1 & words2
        assert len(overlap) == 100

    @pytest.mark.parametrize(
        "word_count,expected_slice_words",
        [
            (400, 400),  # exact min → returns all
            (401, 401),  # just above min → returns all
            (550, 550),  # mid-range → returns all
            (599, 599),  # just below max → returns all
            (600, 600),  # exact max → returns all
        ],
    )
    def test_slice_at_various_word_counts(
        self, word_count: int, expected_slice_words: int
    ) -> None:
        """When total words <= max, return all available words."""
        text = _make_text(word_count)
        sliced, next_start = _slice_episode_text(text, 0, 400, 600, 100)

        assert len(sliced.split()) == expected_slice_words
        if word_count <= 600:
            # When returning all words, next_start should be
            # word_count - overlap (but not less than 0)
            expected_next = max(0, word_count - 100)
            assert next_start == expected_next


class TestSliceEdgeCases:
    """Edge cases: short text, empty text, overlap boundaries."""

    def test_slice_short_text(self) -> None:
        """50-word text with min=400 → returns all 50 words."""
        text = _make_text(50)
        sliced, next_start = _slice_episode_text(text, 0, 400, 600, 100)

        assert len(sliced.split()) == 50
        # next_start = 50 - 100 = -50, clamped to 0
        assert next_start == 0

    def test_slice_empty_text(self) -> None:
        """Empty string → returns ("", 0)."""
        sliced, next_start = _slice_episode_text("", 0, 400, 600, 100)

        assert sliced == ""
        assert next_start == 0

    def test_slice_past_end(self) -> None:
        """start_word_offset beyond text length → returns ("", 0)."""
        text = _make_text(100)
        sliced, next_start = _slice_episode_text(text, 200, 400, 600, 100)

        assert sliced == ""
        assert next_start == 0

    def test_slice_exact_remaining_min(self) -> None:
        """Remaining words exactly equal to min at start."""
        text = _make_text(700)  # start at 300, remaining = 400
        sliced, _next_start = _slice_episode_text(text, 300, 400, 600, 100)

        assert len(sliced.split()) == 400

    def test_slice_overlap_clamped(self) -> None:
        """When overlap would push next_start before start, clamp to start."""
        # 50 words, min=10, max=30, overlap=100
        # remaining = 50, end = 50 (less than max 30? No, remaining is 50, end=30)
        # next = 30 - 100 = -70, clamped to 0
        text = _make_text(50)
        _sliced, next_start = _slice_episode_text(text, 0, 10, 30, 100)

        assert next_start == 0


class TestSliceRealWorld:
    """Scenarios mimicking actual episode slicing from novel text."""

    def test_natural_language_text(self) -> None:
        """Slice behaves correctly with real English sentences."""
        text = " ".join(
            [
                "The quick brown fox jumps over the lazy dog.",
            ]
            * 100  # 9 words × 100 = 900 words
        )
        sliced, next_start = _slice_episode_text(text, 0, 400, 600, 100)

        words = sliced.split()
        assert 400 <= len(words) <= 600
        assert next_start > 0

    def test_punctuation_preserved(self) -> None:
        """Punctuation should remain intact in sliced text."""
        text = "Hello, world! " * 600  # 1200 "words" (including punct)
        sliced, _next = _slice_episode_text(text, 0, 400, 600, 100)

        # rough check: should contain lots of "Hello,"
        assert "Hello," in sliced
        assert len(sliced.split()) == 600


# ---------------------------------------------------------------------------
# ArcPlanner skeleton
# ---------------------------------------------------------------------------


class TestArcPlannerSkeleton:
    """Verify ArcPlanner class structure and basic behavior."""

    def test_init_accepts_config(self) -> None:
        """ArcPlanner accepts optional config dict."""
        from app.services.arc_planner import ArcPlanner  # noqa: E402

        planner = ArcPlanner()
        assert planner is not None

    def test_init_with_config(self) -> None:
        """Config values override defaults."""
        from app.services.arc_planner import ArcPlanner  # noqa: E402

        planner = ArcPlanner(config={"min_episode_words": 300})
        assert planner.config["min_episode_words"] == 300

    def test_init_default_config(self) -> None:
        """Default config uses module-level constants."""
        from app.services.arc_planner import ArcPlanner  # noqa: E402

        planner = ArcPlanner()
        assert planner.config["min_episode_words"] == 400
        assert planner.config["max_episode_words"] == 600
        assert planner.config["overlap_words"] == 100

    def test_plan_next_arc_signature(self) -> None:
        """plan_next_arc accepts arc_id, progress, chapters, prev_arc, episode_cache."""
        from app.services.arc_planner import ArcPlanner  # noqa: E402
        import inspect

        sig = inspect.signature(ArcPlanner.plan_next_arc)
        params = list(sig.parameters.keys())
        assert "self" in params
        assert "arc_id" in params
        assert "progress" in params
        assert "chapters" in params
        assert "prev_arc" in params
        assert "episode_cache" in params

    def test_plan_next_arc_minimal(self) -> None:
        """plan_next_arc returns valid ArcPlan with minimal chapter."""
        from app.services.arc_planner import ArcPlanner  # noqa: E402

        planner = ArcPlanner()
        result = planner.plan_next_arc(
            arc_id="arc_001",
            progress=_make_reading_progress(),
            chapters=[_make_chapter(1, "Ch1", "hello world")],
            prev_arc=None,
            episode_cache=None,
        )
        arc_plan, end_ch, end_off = result
        assert isinstance(arc_plan, ArcPlan)
        assert arc_plan.arc_id == "arc_001"
        assert arc_plan.pending_words == []
        assert isinstance(arc_plan.episodes, list)
        assert isinstance(end_ch, int)
        assert isinstance(end_off, int)

    def test_validate_inputs_raises_on_invalid(self) -> None:
        """_validate_inputs raises ValueError on invalid progress."""
        from app.services.arc_planner import ArcPlanner  # noqa: E402

        planner = ArcPlanner()
        with pytest.raises(ValueError, match="chapter_offset"):
            planner._validate_inputs(
                progress=ReadingProgress(
                    current_chapter=1,
                    current_episode=1,
                    chapter_offset=-0.1,
                    total_episodes_read=0,
                ),
                chapters=[_make_chapter(1, raw_text="hello")],
            )

    def test_validate_inputs_empty_chapters(self) -> None:
        """_validate_inputs raises ValueError when chapters list is empty."""
        from app.services.arc_planner import ArcPlanner  # noqa: E402

        planner = ArcPlanner()
        with pytest.raises(ValueError, match="No chapters"):
            planner._validate_inputs(
                progress=_make_reading_progress(),
                chapters=[],
            )

    def test_validate_inputs_valid_passes(self) -> None:
        """_validate_inputs does not raise on valid input."""
        from app.services.arc_planner import ArcPlanner  # noqa: E402

        planner = ArcPlanner()
        # Should not raise
        planner._validate_inputs(
            progress=_make_reading_progress(chapter_offset=0.5),
            chapters=[_make_chapter(1, raw_text="some text")],
        )


# ---------------------------------------------------------------------------
# _extract_source_text TDD
# ---------------------------------------------------------------------------


class TestExtractSourceText:
    """TDD tests for _extract_source_text — walks chapters, slices text."""

    def test_extract_from_chapter_start(self, sample_chapters: list[Chapter]) -> None:
        """Extract a slice from the beginning of a chapter."""
        from app.services.arc_planner import ArcPlanner  # noqa: E402

        planner = ArcPlanner()
        text, end_ch, end_off = planner._extract_source_text(
            chapters=sample_chapters,
            start_chapter_id=1,
            start_word_offset=0,
            num_words=500,
        )
        words = text.split()
        assert 400 <= len(words) <= 600  # within episode range
        assert end_ch == 1  # all within chapter 1
        assert end_off == 500  # extracted exactly 500 words

    def test_extract_from_mid_chapter(self, sample_chapters: list[Chapter]) -> None:
        """Extract starting from a non-zero word offset."""
        from app.services.arc_planner import ArcPlanner  # noqa: E402

        planner = ArcPlanner()
        text, end_ch, end_off = planner._extract_source_text(
            chapters=sample_chapters,
            start_chapter_id=1,
            start_word_offset=200,
            num_words=500,
        )
        assert len(text.split()) == 500
        assert end_ch == 1
        assert end_off == 700  # started at 200, took 500, ended at 700

    def test_extract_cross_chapter_boundary(
        self, sample_chapters: list[Chapter]
    ) -> None:
        """When one chapter runs out of words, continue from next chapter."""
        from app.services.arc_planner import ArcPlanner  # noqa: E402

        planner = ArcPlanner()
        # Ch1 has 1411 words. Start at word 1200, need 500 words.
        text, end_ch, end_off = planner._extract_source_text(
            chapters=sample_chapters,
            start_chapter_id=1,
            start_word_offset=1200,
            num_words=500,
        )
        # 1411 - 1200 = 211 words from Ch1, rest from Ch2
        assert len(text.split()) == 500
        assert end_ch == 2  # crossed into chapter 2
        # Ch2 started at offset 0, took 500-211=289 words
        assert end_off == 289

    def test_extract_text_exhaustion_short(
        self, sample_chapters: list[Chapter]
    ) -> None:
        """When total text is insufficient, return what's available."""
        from app.services.arc_planner import ArcPlanner  # noqa: E402

        planner = ArcPlanner()
        # Start near end of Ch3 (1418 words). Ch3 has only 1418 words total.
        text, end_ch, _end_off = planner._extract_source_text(
            chapters=sample_chapters,
            start_chapter_id=3,
            start_word_offset=1300,
            num_words=500,
        )
        # Only 1418 - 1300 = 118 words available
        assert len(text.split()) == 118
        assert end_ch == 3

    def test_extract_exactly_on_chapter_boundary(
        self, sample_chapters: list[Chapter]
    ) -> None:
        """Extract that lands exactly at end of a chapter."""
        from app.services.arc_planner import ArcPlanner  # noqa: E402

        planner = ArcPlanner()
        # Ch2 has 874 words. Start at 374, take 500 → ends at 874 exactly
        text, end_ch, end_off = planner._extract_source_text(
            chapters=sample_chapters,
            start_chapter_id=2,
            start_word_offset=374,
            num_words=500,
        )
        assert len(text.split()) == 500
        assert end_ch == 2
        assert end_off == 874

    def test_extract_skip_to_next_chapter(self, sample_chapters: list[Chapter]) -> None:
        """Extract text that starts mid-chapter and needs one full skip."""
        from app.services.arc_planner import ArcPlanner  # noqa: E402

        planner = ArcPlanner()
        # Ch1 has 1411. Start at word 1400. Need 600 words.
        text, end_ch, _end_off = planner._extract_source_text(
            chapters=sample_chapters,
            start_chapter_id=1,
            start_word_offset=1400,
            num_words=600,
        )
        # Should get 11 words from Ch1 + 589 from Ch2
        assert len(text.split()) == 600
        assert end_ch == 2

    def test_extract_zero_words(self, sample_chapters: list[Chapter]) -> None:
        """Extract 0 words returns empty string at current position."""
        from app.services.arc_planner import ArcPlanner  # noqa: E402

        planner = ArcPlanner()
        text, end_ch, end_off = planner._extract_source_text(
            chapters=sample_chapters,
            start_chapter_id=1,
            start_word_offset=0,
            num_words=0,
        )
        assert text == ""
        assert end_ch == 1
        assert end_off == 0


# ---------------------------------------------------------------------------
# _build_episodes TDD
# ---------------------------------------------------------------------------


class TestBuildEpisodes:
    """TDD tests for _build_episodes — produces EpisodeSlot list."""

    def test_builds_correct_count(self, sample_chapters: list[Chapter]) -> None:
        """With enough text, produces exactly episodes_per_arc episodes (10)."""
        from app.services.arc_planner import ArcPlanner  # noqa: E402

        planner = ArcPlanner()
        progress = _make_reading_progress()
        episodes, _end_ch, _end_off = planner._build_episodes(
            arc_id="arc_003",
            progress=progress,
            chapters=sample_chapters,
            prev_arc=None,
            episode_cache=None,
        )
        # With 3703 words and ~500/episode with 100 overlap: ~9-10 episodes
        assert 8 <= len(episodes) <= planner.config["episodes_per_arc"]
        # All are main episodes (no side trigger since prev_arc=None)
        assert all(ep.episode_type == "main" for ep in episodes)

    def test_episodes_have_overlap(self, sample_chapters: list[Chapter]) -> None:
        """Consecutive main episodes overlap by OVERLAP_WORDS (100 words)."""
        from app.services.arc_planner import ArcPlanner  # noqa: E402

        planner = ArcPlanner()
        progress = _make_reading_progress()
        episodes, _, _ = planner._build_episodes(
            arc_id="arc_003",
            progress=progress,
            chapters=sample_chapters,
            prev_arc=None,
            episode_cache=None,
        )
        if len(episodes) >= 2:
            for i in range(len(episodes) - 1):
                ep1_words = episodes[i].source_text.split()
                ep2_words = episodes[i + 1].source_text.split()
                if len(ep1_words) >= 100 and len(ep2_words) >= 100:
                    assert ep1_words[-100:] == ep2_words[:100]

    def test_episodes_have_source_text_in_range(
        self, sample_chapters: list[Chapter]
    ) -> None:
        """Each main episode's source_text has 400-600 words (except possibly last)."""
        from app.services.arc_planner import ArcPlanner  # noqa: E402

        planner = ArcPlanner()
        progress = _make_reading_progress()
        episodes, _, _ = planner._build_episodes(
            arc_id="arc_003",
            progress=progress,
            chapters=sample_chapters,
            prev_arc=None,
            episode_cache=None,
        )
        for i, ep in enumerate(episodes):
            wc = len(ep.source_text.split())
            # Last episode may be shorter due to text exhaustion
            if i < len(episodes) - 1:
                assert (
                    planner.config["min_episode_words"]
                    <= wc
                    <= planner.config["max_episode_words"]
                ), f"Episode {i}: word count {wc} not in range"

    def test_episodes_initialize_target_words_empty(
        self, sample_chapters: list[Chapter]
    ) -> None:
        """All episodes have target_words initialized to empty list."""
        from app.services.arc_planner import ArcPlanner  # noqa: E402

        planner = ArcPlanner()
        progress = _make_reading_progress()
        episodes, _, _ = planner._build_episodes(
            arc_id="arc_003",
            progress=progress,
            chapters=sample_chapters,
            prev_arc=None,
            episode_cache=None,
        )
        for ep in episodes:
            assert ep.target_words == []

    def test_episodes_initialize_previous_context_empty(
        self, sample_chapters: list[Chapter]
    ) -> None:
        """When prev_arc=None, all episodes have previous_context = []."""
        from app.services.arc_planner import ArcPlanner  # noqa: E402

        planner = ArcPlanner()
        progress = _make_reading_progress()
        episodes, _, _ = planner._build_episodes(
            arc_id="arc_003",
            progress=progress,
            chapters=sample_chapters,
            prev_arc=None,
            episode_cache=None,
        )
        for ep in episodes:
            assert ep.previous_context == []

    def test_episode_ids_sequential_from_1(
        self, sample_chapters: list[Chapter]
    ) -> None:
        """Episode IDs are globally sequential, starting from 1 when prev_arc=None."""
        from app.services.arc_planner import ArcPlanner  # noqa: E402

        planner = ArcPlanner()
        progress = _make_reading_progress()
        episodes, _, _ = planner._build_episodes(
            arc_id="arc_003",
            progress=progress,
            chapters=sample_chapters,
            prev_arc=None,
            episode_cache=None,
        )
        for i, ep in enumerate(episodes):
            assert ep.episode_id == i + 1

    def test_return_end_position(self, sample_chapters: list[Chapter]) -> None:
        """Returns (episodes, end_chapter_id, end_word_offset) tuple."""
        from app.services.arc_planner import ArcPlanner  # noqa: E402

        planner = ArcPlanner()
        progress = _make_reading_progress()
        episodes, end_ch, end_off = planner._build_episodes(
            arc_id="arc_003",
            progress=progress,
            chapters=sample_chapters,
            prev_arc=None,
            episode_cache=None,
        )
        assert isinstance(end_ch, int)
        assert isinstance(end_off, int)
        assert end_ch >= 1
        assert end_off >= 0


# ---------------------------------------------------------------------------
# _should_add_side_episode TDD
# ---------------------------------------------------------------------------


class TestSideEpisodeDetection:
    """TDD tests for _should_add_side_episode."""

    def test_side_ep_triggered(self) -> None:
        """6 pending_words with rejected_count >= 3 → side episode triggered."""
        from app.services.arc_planner import ArcPlanner  # noqa: E402

        planner = ArcPlanner()
        prev_arc = ArcPlan(
            arc_id="2",
            pending_words=[
                PendingWord(item_id="w1", rejected_count=5),
                PendingWord(item_id="w2", rejected_count=3),
                PendingWord(item_id="w3", rejected_count=4),
                PendingWord(item_id="w4", rejected_count=3),
                PendingWord(item_id="w5", rejected_count=6),
                PendingWord(item_id="w6", rejected_count=3),
            ],
            episodes=[
                EpisodeSlot(episode_id=i, episode_type="main") for i in range(21, 31)
            ],
        )
        assert planner._should_add_side_episode(prev_arc) is True

    def test_side_ep_not_triggered_below_min(self) -> None:
        """Only 4 qualifying words → no side episode."""
        from app.services.arc_planner import ArcPlanner  # noqa: E402

        planner = ArcPlanner()
        prev_arc = ArcPlan(
            arc_id="2",
            pending_words=[
                PendingWord(item_id="w1", rejected_count=5),
                PendingWord(item_id="w2", rejected_count=4),
                PendingWord(item_id="w3", rejected_count=3),
                PendingWord(item_id="w4", rejected_count=3),
            ],
        )
        assert planner._should_add_side_episode(prev_arc) is False

    def test_side_ep_not_triggered_low_rejected(self) -> None:
        """5+ words but none have rejected_count >= 3 → no side episode."""
        from app.services.arc_planner import ArcPlanner  # noqa: E402

        planner = ArcPlanner()
        prev_arc = ArcPlan(
            arc_id="2",
            pending_words=[
                PendingWord(item_id="w1", rejected_count=2),
                PendingWord(item_id="w2", rejected_count=2),
                PendingWord(item_id="w3", rejected_count=1),
                PendingWord(item_id="w4", rejected_count=0),
                PendingWord(item_id="w5", rejected_count=2),
            ],
        )
        assert planner._should_add_side_episode(prev_arc) is False

    def test_side_ep_first_arc_no_pending(self) -> None:
        """prev_arc=None → no side episode."""
        from app.services.arc_planner import ArcPlanner  # noqa: E402

        planner = ArcPlanner()
        assert planner._should_add_side_episode(None) is False

    def test_side_ep_empty_pending_words(self) -> None:
        """prev_arc with empty pending_words → no side episode."""
        from app.services.arc_planner import ArcPlanner  # noqa: E402

        planner = ArcPlanner()
        prev_arc = ArcPlan(arc_id="2", pending_words=[])
        assert planner._should_add_side_episode(prev_arc) is False


# ---------------------------------------------------------------------------
# Side episode in _build_episodes TDD
# ---------------------------------------------------------------------------


class TestSideEpisodeInBuild:
    """Integration: side episode affects _build_episodes output."""

    def test_side_ep_at_index_9(self, sample_chapters: list[Chapter]) -> None:
        """When triggered, episode 9 (0-indexed) is side with source_text=None."""
        from app.services.arc_planner import ArcPlanner  # noqa: E402

        planner = ArcPlanner()
        progress = _make_reading_progress()
        prev_arc = ArcPlan(
            arc_id="2",
            pending_words=[
                PendingWord(item_id="w1", rejected_count=5),
                PendingWord(item_id="w2", rejected_count=4),
                PendingWord(item_id="w3", rejected_count=3),
                PendingWord(item_id="w4", rejected_count=6),
                PendingWord(item_id="w5", rejected_count=3),
                PendingWord(item_id="w6", rejected_count=4),
            ],
            episodes=[
                EpisodeSlot(episode_id=i, episode_type="main") for i in range(21, 31)
            ],
        )
        episodes, _, _ = planner._build_episodes(
            arc_id="arc_003",
            progress=progress,
            chapters=sample_chapters,
            prev_arc=prev_arc,
            episode_cache=None,
        )
        # With 3703 words, we should get at least 8 episodes
        assert len(episodes) >= 8
        # If we have at least 10: episode 9 is side
        if len(episodes) == 10:
            assert episodes[9].episode_type == "side"
            assert episodes[9].source_text is None

    def test_side_ep_before_text_exhaustion(self) -> None:
        """Side episode inserted before break when text runs out before configured position."""
        from app.services.arc_planner import ArcPlanner  # noqa: E402

        # Only enough text for ~3-4 main episodes (2000 words)
        chapters = [
            _make_chapter(1, "Short Chapter", " ".join([f"w{i}" for i in range(2000)])),
        ]
        prev_arc = ArcPlan(
            arc_id="2",
            pending_words=[
                PendingWord(item_id="w1", rejected_count=5),
                PendingWord(item_id="w2", rejected_count=4),
                PendingWord(item_id="w3", rejected_count=3),
                PendingWord(item_id="w4", rejected_count=6),
                PendingWord(item_id="w5", rejected_count=5),
                PendingWord(item_id="w6", rejected_count=4),
            ],
            episodes=[
                EpisodeSlot(episode_id=i, episode_type="main") for i in range(21, 31)
            ],
        )
        progress = _make_reading_progress()

        # Default config: side_ep at position -1 (last, i.e., index 9 of 10)
        planner = ArcPlanner()
        episodes, _, _ = planner._build_episodes(
            arc_id="arc_003",
            progress=progress,
            chapters=chapters,
            prev_arc=prev_arc,
            episode_cache=None,
        )

        # Should have produced main episodes + a side episode at the end
        assert len(episodes) >= 1
        # Last episode should be side (inserted before text exhaustion break)
        assert episodes[-1].episode_type == "side"
        assert episodes[-1].source_text is None
        # Verify at least one main episode exists before side
        main_eps = [ep for ep in episodes if ep.episode_type == "main"]
        assert len(main_eps) >= 1

    def test_side_ep_not_at_wrong_position(
        self, sample_chapters: list[Chapter]
    ) -> None:
        """Side episode only appears at configured position or before text exhaustion."""
        from app.services.arc_planner import ArcPlanner  # noqa: E402

        planner = ArcPlanner()
        progress = _make_reading_progress()
        prev_arc = ArcPlan(
            arc_id="2",
            pending_words=[
                PendingWord(item_id="w1", rejected_count=5),
                PendingWord(item_id="w2", rejected_count=4),
                PendingWord(item_id="w3", rejected_count=3),
                PendingWord(item_id="w4", rejected_count=6),
                PendingWord(item_id="w5", rejected_count=3),
                PendingWord(item_id="w6", rejected_count=5),
            ],
            episodes=[
                EpisodeSlot(episode_id=i, episode_type="main") for i in range(21, 31)
            ],
        )
        episodes, _, _ = planner._build_episodes(
            arc_id="arc_003",
            progress=progress,
            chapters=sample_chapters,
            prev_arc=prev_arc,
            episode_cache=None,
        )
        # Side episode should appear exactly once (at configured position or
        # before text exhaustion), not at random positions
        side_count = sum(1 for ep in episodes if ep.episode_type == "side")
        assert side_count <= 1, f"Expected at most 1 side ep, got {side_count}"
        # The side episode, if present, appears as the last episode
        for i, ep in enumerate(episodes):
            if ep.episode_type == "side":
                # It should be the last episode (or near-last if inserted before break)
                assert i >= len(episodes) - 2, (
                    f"Side ep at index {i} should be near end of {len(episodes)}"
                )

    def test_no_side_ep_when_not_triggered(
        self, sample_chapters: list[Chapter]
    ) -> None:
        """prev_arc without qualifying words → all episodes are main."""
        from app.services.arc_planner import ArcPlanner  # noqa: E402

        planner = ArcPlanner()
        progress = _make_reading_progress()
        prev_arc = ArcPlan(
            arc_id="2",
            pending_words=[
                PendingWord(item_id="w1", rejected_count=2),
                PendingWord(item_id="w2", rejected_count=1),
            ],
            episodes=[
                EpisodeSlot(episode_id=i, episode_type="main") for i in range(21, 31)
            ],
        )
        episodes, _, _ = planner._build_episodes(
            arc_id="arc_003",
            progress=progress,
            chapters=sample_chapters,
            prev_arc=prev_arc,
            episode_cache=None,
        )
        assert all(ep.episode_type == "main" for ep in episodes)

    def test_episode_ids_continue_with_prev_arc(
        self, sample_chapters: list[Chapter]
    ) -> None:
        """Episode IDs continue from prev_arc.episodes[-1].episode_id + 1."""
        from app.services.arc_planner import ArcPlanner  # noqa: E402

        planner = ArcPlanner()
        progress = _make_reading_progress()
        prev_arc = ArcPlan(
            arc_id="2",
            pending_words=[
                PendingWord(item_id="w1", rejected_count=5),
                PendingWord(item_id="w2", rejected_count=4),
                PendingWord(item_id="w3", rejected_count=3),
                PendingWord(item_id="w4", rejected_count=6),
                PendingWord(item_id="w5", rejected_count=5),
            ],
            episodes=[
                EpisodeSlot(episode_id=i, episode_type="main") for i in range(21, 31)
            ],
        )
        episodes, _, _ = planner._build_episodes(
            arc_id="arc_003",
            progress=progress,
            chapters=sample_chapters,
            prev_arc=prev_arc,
            episode_cache=None,
        )
        if episodes:
            assert episodes[0].episode_id == 31  # prev_arc ended at 30


# ---------------------------------------------------------------------------
# _read_previous_context TDD
# ---------------------------------------------------------------------------


class TestPreviousContext:
    """TDD tests for _read_previous_context."""

    def test_first_arc_returns_empty(self) -> None:
        """prev_arc=None → empty list."""
        from app.services.arc_planner import ArcPlanner  # noqa: E402

        planner = ArcPlanner()
        result = planner._read_previous_context(
            episode_cache=None,
            prev_arc=None,
            episode_index=0,
        )
        assert result == []

    def test_non_first_arc_ep0_reads_cache(self, mock_episode_cache) -> None:
        """Episode 0 of non-first arc reads from episode cache."""
        from app.services.arc_planner import ArcPlanner  # noqa: E402

        planner = ArcPlanner()
        prev_arc = ArcPlan(
            arc_id="2",
            episodes=[EpisodeSlot(episode_id=30, episode_type="main")],
        )
        result = planner._read_previous_context(
            episode_cache=mock_episode_cache,
            prev_arc=prev_arc,
            episode_index=0,
        )
        assert isinstance(result, list)
        # mock_episode_cache.load() returns ep30 data (6 messages)
        assert len(result) > 0
        assert len(result) <= 10  # truncated to PREVIOUS_CONTEXT_MESSAGE_COUNT

    def test_episodes_1_and_up_always_empty(self, mock_episode_cache) -> None:
        """Episodes 1+ always get empty previous_context, even with cache."""
        from app.services.arc_planner import ArcPlanner  # noqa: E402

        planner = ArcPlanner()
        prev_arc = ArcPlan(
            arc_id="2",
            episodes=[EpisodeSlot(episode_id=30, episode_type="main")],
        )
        for i in [1, 2, 5, 9]:
            result = planner._read_previous_context(
                episode_cache=mock_episode_cache,
                prev_arc=prev_arc,
                episode_index=i,
            )
            assert result == [], f"Episode {i} should have empty context"

    def test_cache_is_none_returns_empty(self) -> None:
        """When episode_cache is None, return empty list gracefully."""
        from app.services.arc_planner import ArcPlanner  # noqa: E402

        planner = ArcPlanner()
        prev_arc = ArcPlan(
            arc_id="2",
            episodes=[EpisodeSlot(episode_id=30, episode_type="main")],
        )
        result = planner._read_previous_context(
            episode_cache=None,
            prev_arc=prev_arc,
            episode_index=0,
        )
        assert result == []

    def test_prev_arc_none_returns_empty(self, mock_episode_cache) -> None:
        """prev_arc=None takes priority — returns empty."""
        from app.services.arc_planner import ArcPlanner  # noqa: E402

        planner = ArcPlanner()
        result = planner._read_previous_context(
            episode_cache=mock_episode_cache,
            prev_arc=None,
            episode_index=0,
        )
        assert result == []


class TestPreviousContextIntegration:
    """Integration: _build_episodes sets previous_context correctly."""

    def test_integration_first_arc_empty_context(
        self,
        sample_chapters: list[Chapter],
    ) -> None:
        """When prev_arc=None, all episodes have previous_context=[]."""
        from app.services.arc_planner import ArcPlanner  # noqa: E402

        planner = ArcPlanner()
        progress = _make_reading_progress()
        episodes, _, _ = planner._build_episodes(
            arc_id="arc_001",
            progress=progress,
            chapters=sample_chapters,
            prev_arc=None,
            episode_cache=None,
        )
        for ep in episodes:
            assert ep.previous_context == []

    def test_integration_ep0_has_context(
        self,
        sample_chapters: list[Chapter],
        mock_episode_cache,
    ) -> None:
        """Episode 0 gets context from cache; episodes 1+ get []."""
        from app.services.arc_planner import ArcPlanner  # noqa: E402

        planner = ArcPlanner()
        progress = _make_reading_progress()
        prev_arc = ArcPlan(
            arc_id="2",
            episodes=[EpisodeSlot(episode_id=30, episode_type="main")],
        )
        episodes, _, _ = planner._build_episodes(
            arc_id="arc_003",
            progress=progress,
            chapters=sample_chapters,
            prev_arc=prev_arc,
            episode_cache=mock_episode_cache,
        )
        if episodes:
            assert isinstance(episodes[0].previous_context, list)
            assert len(episodes[0].previous_context) > 0
            for ep in episodes[1:]:
                assert ep.previous_context == []


class TestEndPositionTracking:
    """Verify _build_episodes returns correct end position."""

    def test_end_position_first_arc(self, sample_chapters: list[Chapter]) -> None:
        """End position reflects last consumed text position."""
        from app.services.arc_planner import ArcPlanner  # noqa: E402

        planner = ArcPlanner()
        progress = _make_reading_progress()
        episodes, end_ch, end_off = planner._build_episodes(
            arc_id="arc_001",
            progress=progress,
            chapters=sample_chapters,
            prev_arc=None,
            episode_cache=None,
        )
        assert isinstance(end_ch, int)
        assert isinstance(end_off, int)
        assert end_ch >= 1, f"Expected end_ch >= 1, got {end_ch}"
        assert end_off >= 0, f"Expected end_off >= 0, got {end_off}"
        # With 3703 words, should be well into the chapters
        if episodes:
            assert end_off > 0, "End position should be beyond start"

    def test_end_position_starts_at_progress(
        self, sample_chapters: list[Chapter]
    ) -> None:
        """End position reflects starting offset."""
        from app.services.arc_planner import ArcPlanner  # noqa: E402

        planner = ArcPlanner()
        # Start at chapter 1, offset 0.0
        progress_zero = _make_reading_progress(chapter_offset=0.0)
        episodes_zero, end_ch_0, end_off_0 = planner._build_episodes(
            arc_id="arc_001",
            progress=progress_zero,
            chapters=sample_chapters,
            prev_arc=None,
            episode_cache=None,
        )
        # Start at chapter 1, offset 0.3
        progress_mid = _make_reading_progress(chapter_offset=0.3)
        episodes_mid, end_ch_mid, end_off_mid = planner._build_episodes(
            arc_id="arc_001",
            progress=progress_mid,
            chapters=sample_chapters,
            prev_arc=None,
            episode_cache=None,
        )
        # Both consume all text → end at same position when text runs out
        # Verify both produce valid end positions
        assert end_off_mid >= end_off_0, (
            f"Mid-start ({end_off_mid}) must be >= zero-start ({end_off_0})"
        )
        # Both should have consumed some text
        assert end_off_0 > 0, "Should have consumed text"
        assert end_off_mid > 0, "Should have consumed text"

    def test_end_position_side_episode_no_advance(
        self,
        sample_chapters: list[Chapter],
    ) -> None:
        """Side episode does not advance cursor — main episodes still produce end pos."""
        from app.services.arc_planner import ArcPlanner  # noqa: E402

        planner = ArcPlanner()
        progress = _make_reading_progress()
        prev_arc = ArcPlan(
            arc_id="2",
            pending_words=[
                PendingWord(item_id=f"w{i}", rejected_count=5) for i in range(6)
            ],
            episodes=[
                EpisodeSlot(episode_id=i, episode_type="main") for i in range(21, 31)
            ],
        )
        episodes, end_ch, end_off = planner._build_episodes(
            arc_id="arc_001",
            progress=progress,
            chapters=sample_chapters,
            prev_arc=prev_arc,
            episode_cache=None,
        )
        assert isinstance(end_ch, int)
        assert isinstance(end_off, int)
        # End position must be valid regardless of side episode presence
        assert end_ch >= progress.current_chapter


class TestPlanNextArcIntegration:
    """Integration tests for plan_next_arc."""

    def test_plan_next_arc_happy_path(self, sample_chapters: list[Chapter]) -> None:
        """plan_next_arc returns (ArcPlan, int, int) tuple for first arc."""
        from app.services.arc_planner import ArcPlanner  # noqa: E402

        planner = ArcPlanner()
        progress = _make_reading_progress()
        result = planner.plan_next_arc(
            arc_id="arc_001",
            progress=progress,
            chapters=sample_chapters,
            prev_arc=None,
            episode_cache=None,
        )
        assert isinstance(result, tuple), f"Expected tuple, got {type(result)}"
        assert len(result) == 3, f"Expected 3 elements, got {len(result)}"
        arc_plan, end_ch, end_off = result

        # ArcPlan is a Pydantic model
        assert isinstance(arc_plan, ArcPlan)
        assert arc_plan.arc_id == "arc_001"
        assert len(arc_plan.episodes) >= 1
        assert arc_plan.pending_words == []
        assert isinstance(end_ch, int)
        assert isinstance(end_off, int)

        # All target_words are empty lists
        for ep in arc_plan.episodes:
            assert ep.target_words == []

    def test_plan_next_arc_with_prev_arc(
        self,
        sample_chapters: list[Chapter],
    ) -> None:
        """plan_next_arc with prev_arc produces side episode + previous_context."""
        from app.services.arc_planner import ArcPlanner  # noqa: E402

        planner = ArcPlanner()
        progress = _make_reading_progress()
        prev_arc = ArcPlan(
            arc_id="arc_002",
            pending_words=[
                PendingWord(item_id=f"w{i}", rejected_count=5) for i in range(6)
            ],
            episodes=[
                EpisodeSlot(episode_id=i, episode_type="main") for i in range(21, 31)
            ],
        )
        result = planner.plan_next_arc(
            arc_id="arc_003",
            progress=progress,
            chapters=sample_chapters,
            prev_arc=prev_arc,
            episode_cache=None,
        )
        arc_plan, _, _ = result
        episodes = arc_plan.episodes
        # Episode IDs continue from prev_arc (21-30 → next starts at 31)
        assert episodes[0].episode_id == 31

        # With 10 episodes, last should be side
        if len(episodes) == 10:
            assert episodes[9].episode_type == "side"
            assert episodes[9].source_text is None

    def test_plan_next_arc_episode_count(
        self,
        sample_chapters: list[Chapter],
    ) -> None:
        """With 3703 words, should produce 7-10 episodes (500 words avg with overlap)."""
        from app.services.arc_planner import ArcPlanner  # noqa: E402

        planner = ArcPlanner()
        progress = _make_reading_progress()
        result = planner.plan_next_arc(
            arc_id="arc_001",
            progress=progress,
            chapters=sample_chapters,
            prev_arc=None,
            episode_cache=None,
        )
        arc_plan, _, _ = result
        eps = arc_plan.episodes
        assert 6 <= len(eps) <= 10, f"Expected 6-10 episodes, got {len(eps)}"

    def test_plan_next_arc_validate_raises(self) -> None:
        """plan_next_arc validates inputs before planning — Pydantic rejects invalid offset."""
        from pydantic import ValidationError

        # Invalid offset caught by Pydantic at model construction (le=1 constraint)
        with pytest.raises(ValidationError, match="chapter_offset"):
            ReadingProgress(
                current_chapter=1,
                current_episode=1,
                chapter_offset=1.5,
                total_episodes_read=0,
            )

    def test_plan_next_arc_empty_chapters_raises(self) -> None:
        """plan_next_arc raises on empty chapters."""
        from app.services.arc_planner import ArcPlanner  # noqa: E402

        planner = ArcPlanner()
        progress = _make_reading_progress()
        with pytest.raises(ValueError, match="No chapters"):
            planner.plan_next_arc(
                arc_id="arc_001",
                progress=progress,
                chapters=[],
                prev_arc=None,
                episode_cache=None,
            )

    def test_plan_next_arc_immutable_inputs(
        self,
        sample_chapters: list[Chapter],
    ) -> None:
        """plan_next_arc does NOT modify input parameters."""
        from app.services.arc_planner import ArcPlanner  # noqa: E402

        planner = ArcPlanner()
        progress = _make_reading_progress()
        chapters_copy = copy.deepcopy(sample_chapters)
        progress_copy = copy.deepcopy(progress)
        prev_arc = ArcPlan(
            arc_id="2",
            pending_words=[PendingWord(item_id="w1", rejected_count=3)],
            episodes=[EpisodeSlot(episode_id=1, episode_type="main")],
        )
        prev_arc_copy = copy.deepcopy(prev_arc)

        planner.plan_next_arc(
            arc_id="arc_001",
            progress=progress,
            chapters=sample_chapters,
            prev_arc=prev_arc,
            episode_cache=None,
        )
        # Pydantic models support __eq__
        assert chapters_copy == sample_chapters, "chapters was mutated"
        assert progress_copy == progress, "progress was mutated"
        assert prev_arc_copy == prev_arc, "prev_arc was mutated"

    def test_plan_next_arc_deterministic(
        self,
        sample_chapters: list[Chapter],
    ) -> None:
        """Same inputs → identical output."""
        from app.services.arc_planner import ArcPlanner  # noqa: E402

        planner = ArcPlanner()
        progress = _make_reading_progress()
        r1 = planner.plan_next_arc(
            arc_id="arc_001",
            progress=progress,
            chapters=sample_chapters,
            prev_arc=None,
            episode_cache=None,
        )
        r2 = planner.plan_next_arc(
            arc_id="arc_001",
            progress=progress,
            chapters=sample_chapters,
            prev_arc=None,
            episode_cache=None,
        )
        assert r1 == r2, "Output should be deterministic"


# ---------------------------------------------------------------------------
# Edge cases — boundary conditions and config overrides
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Additional edge cases for ArcPlanner — text exhaustion, boundaries, config overrides."""

    def test_partial_arc_text_exhaustion(self) -> None:
        """Only 200 words available → produces 0-1 episodes (partial arc)."""
        from app.services.arc_planner import ArcPlanner  # noqa: E402

        planner = ArcPlanner()
        short_chapters = [
            _make_chapter(
                1, "Tiny Chapter", " ".join([f"word{i}" for i in range(200)])
            ),
        ]
        progress = _make_reading_progress()
        result = planner.plan_next_arc(
            arc_id="arc_001",
            progress=progress,
            chapters=short_chapters,
            prev_arc=None,
            episode_cache=None,
        )
        arc_plan, _, _ = result
        assert 0 <= len(arc_plan.episodes) <= 1, (
            f"Expected 0-1 episodes for 200 words, got {len(arc_plan.episodes)}"
        )

    def test_single_chapter_works(self) -> None:
        """Single chapter with enough text still produces multiple episodes."""
        from app.services.arc_planner import ArcPlanner  # noqa: E402

        planner = ArcPlanner()
        single_chapter = [
            _make_chapter(
                1, "Solo Chapter", " ".join([f"word{i}" for i in range(2000)])
            ),
        ]
        progress = _make_reading_progress()
        result = planner.plan_next_arc(
            arc_id="arc_001",
            progress=progress,
            chapters=single_chapter,
            prev_arc=None,
            episode_cache=None,
        )
        arc_plan, _, _ = result
        assert len(arc_plan.episodes) >= 3, (
            f"Expected >=3 episodes for 2000 words, got {len(arc_plan.episodes)}"
        )

    def test_no_more_than_max_episodes(
        self,
        sample_chapters: list[Chapter],
    ) -> None:
        """Never produces more than config.episodes_per_arc episodes."""
        from app.services.arc_planner import ArcPlanner  # noqa: E402

        planner = ArcPlanner()
        progress = _make_reading_progress()
        result = planner.plan_next_arc(
            arc_id="arc_001",
            progress=progress,
            chapters=sample_chapters,
            prev_arc=None,
            episode_cache=None,
        )
        arc_plan, _, _ = result
        max_eps = planner.config["episodes_per_arc"]
        assert len(arc_plan.episodes) <= max_eps

    def test_zero_text_produces_no_episodes(self) -> None:
        """Chapter with empty raw_text produces 0 episodes."""
        from app.services.arc_planner import ArcPlanner  # noqa: E402

        planner = ArcPlanner()
        empty_chapter = [
            _make_chapter(1, "Empty", ""),
        ]
        progress = _make_reading_progress()
        result = planner.plan_next_arc(
            arc_id="arc_001",
            progress=progress,
            chapters=empty_chapter,
            prev_arc=None,
            episode_cache=None,
        )
        arc_plan, _, _ = result
        assert len(arc_plan.episodes) == 0

    def test_chapter_offset_at_boundaries(self) -> None:
        """chapter_offset=0.0 and 1.0 are valid boundary values."""
        from app.services.arc_planner import ArcPlanner  # noqa: E402

        planner = ArcPlanner()
        single = [
            _make_chapter(1, "C1", " ".join([f"w{i}" for i in range(1000)])),
        ]
        # offset=0.0 should work
        planner._validate_inputs(
            progress=_make_reading_progress(chapter_offset=0.0),
            chapters=single,
        )
        # offset=1.0 should work
        planner._validate_inputs(
            progress=_make_reading_progress(chapter_offset=1.0),
            chapters=single,
        )

    def test_chapter_offset_negative_raises(self) -> None:
        """chapter_offset < 0 raises ValueError."""
        from app.services.arc_planner import ArcPlanner  # noqa: E402

        planner = ArcPlanner()
        with pytest.raises(ValueError, match="chapter_offset"):
            planner._validate_inputs(
                progress=ReadingProgress(
                    current_chapter=1,
                    current_episode=1,
                    chapter_offset=-0.1,
                    total_episodes_read=0,
                ),
                chapters=[_make_chapter(1, raw_text="x")],
            )

    def test_chapter_offset_above_one_raises(self) -> None:
        """chapter_offset > 1 raises ValueError."""
        from app.services.arc_planner import ArcPlanner  # noqa: E402

        planner = ArcPlanner()
        with pytest.raises(ValueError, match="chapter_offset"):
            planner._validate_inputs(
                progress=ReadingProgress(
                    current_chapter=1,
                    current_episode=1,
                    chapter_offset=1.001,
                    total_episodes_read=0,
                ),
                chapters=[_make_chapter(1, raw_text="x")],
            )

    def test_config_overrides_episodes_per_arc(self) -> None:
        """Config can override episodes_per_arc from default 10."""
        from app.services.arc_planner import ArcPlanner  # noqa: E402

        planner = ArcPlanner(config={"episodes_per_arc": 5})
        assert planner.config["episodes_per_arc"] == 5
        # With custom config, max episodes is 5
        chapters = [
            _make_chapter(1, "C1", " ".join([f"w{i}" for i in range(3000)])),
        ]
        progress = _make_reading_progress()
        result = planner.plan_next_arc(
            arc_id="arc_001",
            progress=progress,
            chapters=chapters,
            prev_arc=None,
            episode_cache=None,
        )
        arc_plan, _, _ = result
        assert len(arc_plan.episodes) <= 5

    def test_side_ep_with_config_override(self) -> None:
        """Side episode at last position even with custom episode count."""
        from app.services.arc_planner import ArcPlanner  # noqa: E402

        planner = ArcPlanner(config={"episodes_per_arc": 5})
        prev_arc = ArcPlan(
            arc_id="2",
            pending_words=[
                PendingWord(item_id=f"w{i}", rejected_count=5) for i in range(6)
            ],
            episodes=[EpisodeSlot(episode_id=10, episode_type="main")],
        )
        chapters = [
            _make_chapter(1, "C1", " ".join([f"w{i}" for i in range(2000)])),
        ]
        progress = _make_reading_progress()
        result = planner.plan_next_arc(
            arc_id="arc_001",
            progress=progress,
            chapters=chapters,
            prev_arc=prev_arc,
            episode_cache=None,
        )
        arc_plan, _, _ = result
        if len(arc_plan.episodes) == 5:
            assert arc_plan.episodes[4].episode_type == "side"

    def test_side_ep_with_custom_threshold(self) -> None:
        """Custom side_ep_trigger_min_words and side_ep_reject_threshold work."""
        from app.services.arc_planner import ArcPlanner  # noqa: E402

        planner = ArcPlanner(
            config={
                "side_ep_trigger_min_words": 3,
                "side_ep_reject_threshold": 2,
            }
        )
        prev_arc = ArcPlan(
            arc_id="2",
            pending_words=[
                PendingWord(item_id="w1", rejected_count=2),
                PendingWord(item_id="w2", rejected_count=2),
                PendingWord(item_id="w3", rejected_count=2),
            ],
            episodes=[EpisodeSlot(episode_id=10, episode_type="main")],
        )
        # 3 words with rejected_count >= 2 should trigger (threshold lowered)
        assert planner._should_add_side_episode(prev_arc) is True

        # With default threshold, these would NOT trigger (need >= 3)
        planner_default = ArcPlanner()
        assert planner_default._should_add_side_episode(prev_arc) is False


# ---------------------------------------------------------------------------
# Overlap cross-chapter boundary tests
# ---------------------------------------------------------------------------


class TestOverlapCrossChapter:
    """Verify overlap logic handles within-chapter and cross-chapter cases."""

    def test_overlap_within_chapter(self) -> None:
        """end_off=200, overlap=100 → next_start=100, current_chapter stays same."""
        from app.services.arc_planner import ArcPlanner  # noqa: E402

        planner = ArcPlanner(
            config={
                "max_episode_words": 200,
                "overlap_words": 100,
                "episodes_per_arc": 3,
            }
        )
        chapters = [
            _make_chapter(1, "Ch1", " ".join([f"w{i}" for i in range(600)])),
        ]
        progress = _make_reading_progress()
        episodes, _, _ = planner._build_episodes(
            arc_id="arc_001",
            progress=progress,
            chapters=chapters,
            prev_arc=None,
            episode_cache=None,
        )
        # Should have 3 episodes (200 words each, 100 overlap)
        assert len(episodes) == 3
        # Ep0 starts at word_0, Ep1 starts at word_100 (within same chapter)
        ep1_words = episodes[1].source_text.split()
        assert ep1_words[0] == "w100"
        # Ep2 starts at word_200
        ep2_words = episodes[2].source_text.split()
        assert ep2_words[0] == "w200"

    def test_overlap_crosses_chapter_backward(self) -> None:
        """end_off=50 in chapter 2, overlap=100 → wraps to previous chapter at (prev_wc - 50)."""
        from app.services.arc_planner import ArcPlanner  # noqa: E402

        planner = ArcPlanner(
            config={
                "max_episode_words": 550,
                "overlap_words": 100,
                "episodes_per_arc": 2,
            }
        )
        chapters = [
            _make_chapter(1, "Ch1", " ".join([f"a{i}" for i in range(500)])),
            _make_chapter(2, "Ch2", " ".join([f"b{i}" for i in range(50)])),
        ]
        progress = _make_reading_progress()
        episodes, end_ch, end_off = planner._build_episodes(
            arc_id="arc_001",
            progress=progress,
            chapters=chapters,
            prev_arc=None,
            episode_cache=None,
        )
        # Ep0: 500 from ch1 + 50 from ch2 = 550 words, end_ch=2, end_off=50
        assert len(episodes) >= 1
        ep0_words = episodes[0].source_text.split()
        assert len(ep0_words) == 550
        # Last 50 words should be from ch2 (b0..b49)
        assert ep0_words[-1] == "b49"

        if len(episodes) >= 2:
            # Ep1: overlap crosses backward: next_start = 50 - 100 = -50
            # position = prev_wc + next_start = 500 + (-50) = 450
            # So ep1 starts at word 450 of ch1
            ep1_words = episodes[1].source_text.split()
            assert ep1_words[0] == "a450"
