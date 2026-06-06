"""Tests for app.services.vocabulary_scheduler.scorer."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

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


def _make_item(
    item_id: str = "awkward_1",
    due: str | None = None,
    last_review: str | None = None,
) -> dict:
    """Build a minimal vocabulary-item dict for testing."""
    return {
        "id": item_id,
        "word": "awkward",
        "meaning": "尴尬的",
        "fsrs_card": {
            "due": due or "2026-06-07T00:00:00Z",
            "last_review": last_review,
        },
    }


# ---------------------------------------------------------------------------
# score_context
# ---------------------------------------------------------------------------


class TestScoreContext:
    """Tests for ``score_context()`` – the context-fit scoring function."""

    def test_source_text_none(self):
        """When source_text is None, every candidate gets 0.5."""
        result = score_context(None, [{"id": "a"}, {"id": "b"}])
        assert result == {"a": 0.5, "b": 0.5}

    def test_with_source_no_llm(self):
        """Without an LLM client, all candidates still get 0.5 (fallback)."""
        result = score_context("Some source text", [{"id": "a"}])
        assert result == {"a": 0.5}

    def test_empty_candidates(self):
        """An empty candidate list returns an empty dict."""
        assert score_context("text", []) == {}
        assert score_context(None, []) == {}

    def test_llm_injected(self):
        """Interface accepts llm_client; MVP still returns 0.5 for all."""
        mock_client = object()  # minimal stand-in
        result = score_context(
            "Some text", [{"id": "x"}, {"id": "y"}], llm_client=mock_client
        )
        assert result == {"x": 0.5, "y": 0.5}


# ---------------------------------------------------------------------------
# _parse_due
# ---------------------------------------------------------------------------


class TestParseDue:
    """Tests for ``_parse_due()`` – ISO-8601 parsing of FSRS card due."""

    def test_parse_due(self):
        """Parses an ISO-8601 string to a timezone-aware datetime."""
        item = _make_item(due="2026-06-07T00:00:00Z")
        result = _parse_due(item)
        assert result == datetime(2026, 6, 7, 0, 0, 0, tzinfo=timezone.utc)

    def test_parse_due_with_offset(self):
        """Handles ISO strings with +00:00 offset notation."""
        item = _make_item(due="2026-06-07T00:00:00+00:00")
        result = _parse_due(item)
        assert result == datetime(2026, 6, 7, 0, 0, 0, tzinfo=timezone.utc)


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
        due_5_days_ago = (FIXED_NOW - timedelta(days=5)).isoformat()
        item = _make_item(due=due_5_days_ago, last_review="2026-06-01T00:00:00Z")
        result = final_score(item, context_score=0.8, now=FIXED_NOW)
        # urgency = min(1.0, 5/30) = 0.1666...
        # score = 0.1666*0.5 + 0.8*0.5 = 0.0833 + 0.4 = 0.4833
        assert result == pytest.approx(0.4833, abs=0.01)

    def test_review_30_days_overdue(self):
        """Review word 30 days overdue → urgency=1.0, score=0.9."""
        due_30_days_ago = (FIXED_NOW - timedelta(days=30)).isoformat()
        item = _make_item(due=due_30_days_ago, last_review="2026-05-01T00:00:00Z")
        result = final_score(item, context_score=0.8, now=FIXED_NOW)
        assert result == pytest.approx(0.9, abs=0.01)

    def test_review_not_yet_due(self):
        """Review word due in 5 days → urgency=0, score=0.4."""
        due_5_days_future = (FIXED_NOW + timedelta(days=5)).isoformat()
        item = _make_item(due=due_5_days_future, last_review="2026-06-01T00:00:00Z")
        result = final_score(item, context_score=0.8, now=FIXED_NOW)
        assert result == pytest.approx(0.4, abs=0.01)

    def test_review_zero_context(self):
        """Review word 10 days overdue, context=0.0 → ~0.1667."""
        due_10_days_ago = (FIXED_NOW - timedelta(days=10)).isoformat()
        item = _make_item(due=due_10_days_ago, last_review="2026-05-31T00:00:00Z")
        result = final_score(item, context_score=0.0, now=FIXED_NOW)
        # urgency = 10/30 = 0.333...
        # score = 0.333*0.5 + 0*0.5 = 0.1667
        assert result == pytest.approx(0.1667, abs=0.01)

    def test_review_exact_due(self):
        """Review word due exactly now → urgency=0, score=0.4."""
        item = _make_item(due=FIXED_NOW.isoformat(), last_review="2026-06-01T00:00:00Z")
        result = final_score(item, context_score=0.8, now=FIXED_NOW)
        assert result == pytest.approx(0.4, abs=0.01)
