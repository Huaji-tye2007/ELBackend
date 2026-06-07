"""Tests for app.services.vocabulary_scheduler.scorer."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest import mock

import pytest

from app.models.fsrs import FsrsCard
from app.models.vocabulary import VocabularyItem
from app.llm.prompts import ContextScoreEntry, ContextScoreResponse
from app.services.vocabulary_scheduler.scorer import (
    _compute_urgency,
    _parse_due,
    final_score,
    score_context,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FIXED_NOW = datetime(2026, 6, 10, 12, 0, 0, tzinfo=timezone.utc)
DEFAULT_DUE = datetime(2026, 6, 7, 0, 0, 0, tzinfo=timezone.utc)

_FSRS_NEW = FsrsCard(
    state=1,
    due=DEFAULT_DUE,
    last_review=None,
)

_FSRS_REVIEW = FsrsCard(
    state=2,
    due=DEFAULT_DUE,
    last_review=datetime(2026, 6, 1, 0, 0, 0, tzinfo=timezone.utc),
    stability=5.0,
    difficulty=0.5,
)


def _make_item(
    item_id: str = "awkward_1",
    due: datetime | None = None,
    last_review: datetime | None = None,
) -> VocabularyItem:
    """Build a minimal VocabularyItem for testing."""
    if due is None:
        due = DEFAULT_DUE
    fsrs = FsrsCard(
        state=2,
        due=due,
        last_review=last_review,
        stability=5.0,
        difficulty=0.5,
    )
    return VocabularyItem(
        id=item_id,
        word="awkward",
        meaning="尴尬的",
        chapter_first_seen=1,
        fsrs_card=fsrs,
    )


def _minimal_item(item_id: str) -> VocabularyItem:
    """Build a bare-minimum VocabularyItem with just an ID (for score_context tests)."""
    return VocabularyItem(
        id=item_id,
        word="test",
        meaning="测试",
        chapter_first_seen=1,
        fsrs_card=FsrsCard(
            state=2,
            due=DEFAULT_DUE,
            stability=5.0,
            difficulty=0.5,
        ),
    )


# ---------------------------------------------------------------------------
# score_context
# ---------------------------------------------------------------------------


class TestScoreContext:
    """Tests for ``score_context()`` – the context-fit scoring function."""

    async def test_source_text_none(self):
        """When source_text is None, every candidate gets 0.5."""
        result = await score_context(None, [_minimal_item("a"), _minimal_item("b")])
        assert result == {"a": 0.5, "b": 0.5}

    async def test_with_source_no_llm(self):
        """Without an LLM client, all candidates still get 0.5 (fallback)."""
        result = await score_context("Some source text", [_minimal_item("a")])
        assert result == {"a": 0.5}

    async def test_empty_candidates(self):
        """An empty candidate list returns an empty dict."""
        assert await score_context("text", []) == {}
        assert await score_context(None, []) == {}

    async def test_llm_client_fallback_when_no_source(self):
        """LLM client is ignored when source_text is None → 0.5 fallback."""
        mock_client = mock.AsyncMock()
        result = await score_context(
            None,
            [_minimal_item("x"), _minimal_item("y")],
            llm_client=mock_client,
        )
        assert result == {"x": 0.5, "y": 0.5}
        mock_client.chat_structured.assert_not_called()

    async def test_llm_client_success(self):
        """LLM client returns scores → parsed and clamped correctly."""
        mock_client = mock.AsyncMock()
        mock_client.chat_structured.return_value = ContextScoreResponse(
            scores=[
                ContextScoreEntry(item_id="a", score=0.9, reasoning="great fit"),
                ContextScoreEntry(item_id="b", score=0.3, reasoning="poor fit"),
            ]
        )
        result = await score_context(
            "source text about nature",
            [
                VocabularyItem(
                    id="a",
                    word="tree",
                    meaning="树",
                    chapter_first_seen=1,
                    fsrs_card=_FSRS_REVIEW,
                ),
                VocabularyItem(
                    id="b",
                    word="rocket",
                    meaning="火箭",
                    chapter_first_seen=1,
                    fsrs_card=_FSRS_REVIEW,
                ),
            ],
            llm_client=mock_client,
        )
        assert result == {"a": 0.9, "b": 0.3}
        mock_client.chat_structured.assert_called_once()

    async def test_llm_clamps_out_of_range_scores(self):
        """Scores outside [0.0, 1.0] are clamped (simulates LLM bypassing Pydantic)."""
        mock_client = mock.AsyncMock()
        # Use model_construct() to bypass Pydantic validation — real LLM may output
        # values slightly outside [0,1] due to floating-point or model quirks.
        entry_a = ContextScoreEntry.model_construct(item_id="a", score=1.5)
        entry_b = ContextScoreEntry.model_construct(item_id="b", score=-0.5)
        mock_client.chat_structured.return_value = ContextScoreResponse.model_construct(
            scores=[entry_a, entry_b],
        )
        result = await score_context(
            "text",
            [
                VocabularyItem(
                    id="a",
                    word="w1",
                    meaning="m1",
                    chapter_first_seen=1,
                    fsrs_card=_FSRS_REVIEW,
                ),
                VocabularyItem(
                    id="b",
                    word="w2",
                    meaning="m2",
                    chapter_first_seen=1,
                    fsrs_card=_FSRS_REVIEW,
                ),
            ],
            llm_client=mock_client,
        )
        assert result == {"a": 1.0, "b": 0.0}

    async def test_llm_missing_candidate_defaults_to_0_5(self):
        """Candidates omitted by LLM get default 0.5."""
        mock_client = mock.AsyncMock()
        mock_client.chat_structured.return_value = ContextScoreResponse(
            scores=[
                ContextScoreEntry(item_id="a", score=0.8, reasoning="ok"),
            ]
        )
        result = await score_context(
            "text",
            [
                VocabularyItem(
                    id="a",
                    word="w1",
                    meaning="m1",
                    chapter_first_seen=1,
                    fsrs_card=_FSRS_REVIEW,
                ),
                VocabularyItem(
                    id="b",
                    word="w2",
                    meaning="m2",
                    chapter_first_seen=1,
                    fsrs_card=_FSRS_REVIEW,
                ),
            ],
            llm_client=mock_client,
        )
        assert result == {"a": 0.8, "b": 0.5}

    async def test_llm_hallucinated_ids_ignored(self):
        """LLM returns ids not in candidates → ignored."""
        mock_client = mock.AsyncMock()
        mock_client.chat_structured.return_value = ContextScoreResponse(
            scores=[
                ContextScoreEntry(item_id="a", score=0.8, reasoning="ok"),
                ContextScoreEntry(item_id="ghost", score=1.0, reasoning="hallucinated"),
            ]
        )
        result = await score_context(
            "text",
            [
                VocabularyItem(
                    id="a",
                    word="w1",
                    meaning="m1",
                    chapter_first_seen=1,
                    fsrs_card=_FSRS_REVIEW,
                ),
            ],
            llm_client=mock_client,
        )
        assert result == {"a": 0.8}
        assert "ghost" not in result

    async def test_llm_exception_falls_back_to_0_5(self):
        """Any LLM exception → all candidates get 0.5."""
        mock_client = mock.AsyncMock()
        mock_client.chat_structured.side_effect = RuntimeError("LLM API down")

        result = await score_context(
            "text",
            [
                VocabularyItem(
                    id="a",
                    word="w1",
                    meaning="m1",
                    chapter_first_seen=1,
                    fsrs_card=_FSRS_REVIEW,
                ),
                VocabularyItem(
                    id="b",
                    word="w2",
                    meaning="m2",
                    chapter_first_seen=1,
                    fsrs_card=_FSRS_REVIEW,
                ),
            ],
            llm_client=mock_client,
        )
        assert result == {"a": 0.5, "b": 0.5}


# ---------------------------------------------------------------------------
# _parse_due
# ---------------------------------------------------------------------------


class TestParseDue:
    """Tests for ``_parse_due()`` – extracting due date from a VocabularyItem."""

    def test_parse_due(self):
        """Extracts the due datetime from a VocabularyItem's FsrsCard."""
        due_dt = datetime(2026, 6, 7, 0, 0, 0, tzinfo=timezone.utc)
        item = _make_item(due=due_dt)
        result = _parse_due(item)
        assert result == due_dt

    def test_parse_due_with_offset(self):
        """Works with any timezone-aware datetime (offset not relevant since
        FsrsCard stores as datetime, not string)."""
        due_dt = datetime(2026, 6, 7, 0, 0, 0, tzinfo=timezone.utc)
        item = _make_item(due=due_dt)
        result = _parse_due(item)
        assert result == due_dt


# ---------------------------------------------------------------------------
# _compute_urgency
# ---------------------------------------------------------------------------


class TestComputeUrgency:
    """Tests for ``_compute_urgency()``."""

    def test_negative(self):
        """Future due date → urgency 0.0."""
        future = FIXED_NOW + timedelta(days=10)
        assert _compute_urgency(future, FIXED_NOW) == 0.0

    def test_exact_30(self):
        """30 days overdue → urgency 1.0."""
        past = FIXED_NOW - timedelta(days=30)
        assert _compute_urgency(past, FIXED_NOW) == 1.0

    def test_15_days(self):
        """15 days overdue → urgency 0.5."""
        past = FIXED_NOW - timedelta(days=15)
        assert _compute_urgency(past, FIXED_NOW) == 0.5

    def test_capped_at_1(self):
        """More than 30 days overdue → urgency caps at 1.0."""
        past = FIXED_NOW - timedelta(days=100)
        assert _compute_urgency(past, FIXED_NOW) == 1.0

    def test_exact_now(self):
        """Due exactly now → urgency 0.0."""
        assert _compute_urgency(FIXED_NOW, FIXED_NOW) == 0.0


# ---------------------------------------------------------------------------
# final_score
# ---------------------------------------------------------------------------


class TestFinalScore:
    """Tests for ``final_score()`` – the composite scheduling score."""

    def test_unseen_word(self):
        """Unseen word with context_score=0.8 → 0.4*0.3 + 0.8*0.7 = 0.68."""
        item = _make_item(last_review=None)
        result = final_score(item, context_score=0.8, now=FIXED_NOW)
        assert result == pytest.approx(0.68)

    def test_unseen_zero_context(self):
        """Unseen word with context_score=0.0 → 0.12."""
        item = _make_item(last_review=None)
        result = final_score(item, context_score=0.0, now=FIXED_NOW)
        assert result == pytest.approx(0.12)

    def test_unseen_full_context(self):
        """Unseen word with context_score=1.0 → 0.82."""
        item = _make_item(last_review=None)
        result = final_score(item, context_score=1.0, now=FIXED_NOW)
        assert result == pytest.approx(0.82)

    def test_review_overdue(self):
        """Review word 5 days overdue, context=0.8 → ~0.4833."""
        due_5_days_ago = FIXED_NOW - timedelta(days=5)
        item = _make_item(
            due=due_5_days_ago,
            last_review=datetime(2026, 6, 1, 0, 0, 0, tzinfo=timezone.utc),
        )
        result = final_score(item, context_score=0.8, now=FIXED_NOW)
        # urgency = min(1.0, 5/30) = 0.1666...
        # score = 0.1666*0.5 + 0.8*0.5 = 0.0833 + 0.4 = 0.4833
        assert result == pytest.approx(0.4833, abs=0.01)

    def test_review_30_days_overdue(self):
        """Review word 30 days overdue → urgency=1.0, score=0.9."""
        due_30_days_ago = FIXED_NOW - timedelta(days=30)
        item = _make_item(
            due=due_30_days_ago,
            last_review=datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc),
        )
        result = final_score(item, context_score=0.8, now=FIXED_NOW)
        assert result == pytest.approx(0.9, abs=0.01)

    def test_review_not_yet_due(self):
        """Review word due in 5 days → urgency=0, score=0.4."""
        due_5_days_future = FIXED_NOW + timedelta(days=5)
        item = _make_item(
            due=due_5_days_future,
            last_review=datetime(2026, 6, 1, 0, 0, 0, tzinfo=timezone.utc),
        )
        result = final_score(item, context_score=0.8, now=FIXED_NOW)
        assert result == pytest.approx(0.4, abs=0.01)

    def test_review_zero_context(self):
        """Review word 10 days overdue, context=0.0 → ~0.1667."""
        due_10_days_ago = FIXED_NOW - timedelta(days=10)
        item = _make_item(
            due=due_10_days_ago,
            last_review=datetime(2026, 5, 31, 0, 0, 0, tzinfo=timezone.utc),
        )
        result = final_score(item, context_score=0.0, now=FIXED_NOW)
        # urgency = 10/30 = 0.333...
        # score = 0.333*0.5 + 0*0.5 = 0.1667
        assert result == pytest.approx(0.1667, abs=0.01)

    def test_review_exact_due(self):
        """Review word due exactly now → urgency=0, score=0.4."""
        item = _make_item(
            due=FIXED_NOW,
            last_review=datetime(2026, 6, 1, 0, 0, 0, tzinfo=timezone.utc),
        )
        result = final_score(item, context_score=0.8, now=FIXED_NOW)
        assert result == pytest.approx(0.4, abs=0.01)
