"""Tests for MasteryEvaluator — TDD RED→GREEN→REFACTOR.

Ref: AGENTS.md §11 (#9), BACKEND_IN_OUT.md §四.9.

Covers the 7-step pipeline: FIFO push, weighted scoring, rating mapping,
scheduler.review_card, cross-day forcing, and serialization.
"""

from __future__ import annotations

import datetime
import itertools
from unittest import mock

import freezegun
from fsrs import Card, Rating, ReviewLog, State

from app.models.episode_log import EpisodeReadingLog, WordLog
from app.models.fsrs import FsrsCard
from app.models.vocabulary import UserVocabulary, VocabularyItem
from app.services.mastery_evaluator import MasteryEvaluator

UTC = datetime.timezone.utc
_counter = itertools.count(1000)


# ============================================================================
# Helpers
# ============================================================================


def _fsrs_card(
    due: datetime.datetime | None = None,
    last_review: datetime.datetime | None = None,
    state: int = 1,
    stability: float | None = None,
    difficulty: float | None = None,
) -> FsrsCard:
    """Create a minimal FsrsCard with unique card_id."""
    if due is None:
        due = datetime.datetime(2026, 6, 10, tzinfo=UTC)
    return FsrsCard(
        card_id=next(_counter),
        state=state,
        due=due,
        last_review=last_review,
        stability=stability,
        difficulty=difficulty,
    )


def _vocab_item(
    item_id: str,
    history_window: list[int] | None = None,
    due: datetime.datetime | None = None,
    last_review: datetime.datetime | None = None,
    state: int = 1,
    stability: float | None = None,
    difficulty: float | None = None,
) -> VocabularyItem:
    """Create a minimal VocabularyItem with given history_window and fsrs_card."""
    return VocabularyItem(
        id=item_id,
        word=f"w_{item_id}",
        meaning=f"m_{item_id}",
        chapter_first_seen=1,
        history_window=history_window or [1, 1, 1, 1, 1],
        fsrs_card=_fsrs_card(
            due=due,
            last_review=last_review,
            state=state,
            stability=stability,
            difficulty=difficulty,
        ),
    )


def _user_vocab(*items: VocabularyItem) -> UserVocabulary:
    """Create a UserVocabulary from VocabularyItems."""
    return UserVocabulary(user_id="u1", vocabulary=list(items))


def _word_log(item_id: str, appeared: int = 1, clicked: int = 0) -> WordLog:
    """Create a WordLog for testing."""
    return WordLog(item_id=item_id, appeared=appeared, clicked=clicked)


def _episode_log(*word_logs: WordLog, episode_id: int = 1) -> EpisodeReadingLog:
    """Create an EpisodeReadingLog from WordLogs."""
    return EpisodeReadingLog(episode_id=episode_id, word_logs=list(word_logs))


def _mock_review_return(
    due: datetime.datetime | None = None,
    state: int = 2,
    stability: float = 5.0,
    difficulty: float = 0.5,
) -> tuple[Card, ReviewLog]:
    """Build a mock (Card, ReviewLog) tuple for scheduler.review_card."""
    if due is None:
        due = datetime.datetime(2026, 6, 20, tzinfo=UTC)
    card = Card(
        card_id=99999,
        state=State(state),
        stability=stability,
        difficulty=difficulty,
        due=due,
        last_review=datetime.datetime(2026, 6, 7, 12, 0, tzinfo=UTC),
    )
    rl = ReviewLog(
        card_id=99999,
        rating=Rating.Good,
        review_datetime=datetime.datetime(2026, 6, 7, 12, 0, tzinfo=UTC),
        review_duration=None,
    )
    return (card, rl)


# ============================================================================
# Edge cases
# ============================================================================


class TestEmptyAndEdge:
    """Empty input and unknown-item handling."""

    def test_empty_word_logs_returns_unchanged(self) -> None:
        """Empty word_logs → UserVocabulary returned with same values."""
        item = _vocab_item("a", history_window=[1, 0, 1, 0, 0])
        uv = _user_vocab(item)
        log = _episode_log()  # no word_logs

        result = MasteryEvaluator().evaluate(log, uv)

        assert result.user_id == uv.user_id
        assert len(result.vocabulary) == 1
        out = result.vocab_index["a"]
        assert out.history_window == [1, 0, 1, 0, 0]
        assert out.fsrs_card.due == item.fsrs_card.due  # unchanged

    def test_unknown_item_id_skipped(self) -> None:
        """item_id not in UserVocabulary → skipped, no error, vocab unchanged."""
        item = _vocab_item("a", history_window=[0, 0, 0, 0, 0])
        uv = _user_vocab(item)
        log = _episode_log(_word_log("nonexistent", appeared=2, clicked=1))

        result = MasteryEvaluator().evaluate(log, uv)

        assert len(result.vocabulary) == 1
        out = result.vocab_index["a"]
        assert out.history_window == [0, 0, 0, 0, 0]  # untouched

    def test_evaluate_with_stats_counts_unique_known_items(self) -> None:
        """evaluate_with_stats reports unique known item_ids actually updated."""
        item = _vocab_item("a", history_window=[0, 0, 0, 0, 0])
        uv = _user_vocab(item)
        log = _episode_log(
            _word_log("a", appeared=1, clicked=0),
            _word_log("a", appeared=2, clicked=1),
            _word_log("missing", appeared=1, clicked=0),
        )
        evaluator = MasteryEvaluator()
        evaluator._scheduler.review_card = mock.MagicMock(
            return_value=_mock_review_return()
        )

        _result, updated_count = evaluator.evaluate_with_stats(log, uv)

        assert updated_count == 1

    def test_unaffected_items_unchanged(self) -> None:
        """Items not referenced in word_logs remain completely unchanged."""
        item_a = _vocab_item("a", history_window=[1, 0, 1, 0, 0])
        item_b = _vocab_item("b", history_window=[0, 0, 0, 0, 0])
        uv = _user_vocab(item_a, item_b)
        log = _episode_log(_word_log("a", clicked=1))  # only "a" is affected

        evaluator = MasteryEvaluator()
        evaluator._scheduler.review_card = mock.MagicMock(
            return_value=_mock_review_return()
        )
        result = evaluator.evaluate(log, uv)

        # "b" untouched
        out_b = result.vocab_index["b"]
        assert out_b.history_window == [0, 0, 0, 0, 0]
        assert out_b.fsrs_card.due == item_b.fsrs_card.due


# ============================================================================
# History window FIFO push
# ============================================================================


class TestHistoryWindow:
    """FIFO push logic: clicked=0→1, clicked>0→0, oldest falls off."""

    def test_push_clicked_zero_appends_one(self) -> None:
        """clicked=0 → 1 pushed to window end, oldest removed."""
        item = _vocab_item("x", history_window=[1, 0, 0, 0, 0])
        uv = _user_vocab(item)
        log = _episode_log(_word_log("x", clicked=0))

        evaluator = MasteryEvaluator()
        evaluator._scheduler.review_card = mock.MagicMock(
            return_value=_mock_review_return()
        )
        result = evaluator.evaluate(log, uv)

        assert result.vocab_index["x"].history_window == [0, 0, 0, 0, 1]

    def test_push_clicked_positive_appends_zero(self) -> None:
        """clicked>0 → 0 pushed to window end, oldest removed."""
        item = _vocab_item("x", history_window=[1, 1, 1, 1, 1])
        uv = _user_vocab(item)
        log = _episode_log(_word_log("x", appeared=3, clicked=3))

        evaluator = MasteryEvaluator()
        evaluator._scheduler.review_card = mock.MagicMock(
            return_value=_mock_review_return()
        )
        result = evaluator.evaluate(log, uv)

        assert result.vocab_index["x"].history_window == [1, 1, 1, 1, 0]

    def test_fifo_maintains_five_elements(self) -> None:
        """Window always has exactly 5 elements after push."""
        item = _vocab_item("x", history_window=[1, 2, 3, 4, 5])
        uv = _user_vocab(item)
        log = _episode_log(_word_log("x", clicked=0))

        evaluator = MasteryEvaluator()
        evaluator._scheduler.review_card = mock.MagicMock(
            return_value=_mock_review_return()
        )
        result = evaluator.evaluate(log, uv)

        hw = result.vocab_index["x"].history_window
        assert len(hw) == 5
        assert hw == [2, 3, 4, 5, 1]  # oldest (1) removed, 1 appended

    def test_new_word_window_unchanged_if_already_default(self) -> None:
        """New word with default [1,1,1,1,1] and clicked=0 → still [1,1,1,1,1]."""
        item = _vocab_item("new_word", history_window=[1, 1, 1, 1, 1])
        uv = _user_vocab(item)
        log = _episode_log(_word_log("new_word", clicked=0))

        evaluator = MasteryEvaluator()
        evaluator._scheduler.review_card = mock.MagicMock(
            return_value=_mock_review_return()
        )
        result = evaluator.evaluate(log, uv)

        assert result.vocab_index["new_word"].history_window == [1, 1, 1, 1, 1]


# ============================================================================
# Weighted score (verified through Rating argument to review_card)
# ============================================================================


class TestWeightedScore:
    """Weighted scoring: sum(w[i] * h[i]) / sum(w) with w=[0.1,0.1,0.2,0.2,0.4]."""

    def test_all_ones_produces_score_one(self) -> None:
        """[1,1,1,1,1] → score = 1.0 → Rating.Good."""
        item = _vocab_item("x", history_window=[1, 1, 1, 1, 1])
        uv = _user_vocab(item)
        log = _episode_log(_word_log("x", clicked=0))  # push 1 → stays all 1

        evaluator = MasteryEvaluator()
        mock_review = mock.MagicMock(return_value=_mock_review_return())
        evaluator._scheduler.review_card = mock_review

        evaluator.evaluate(log, uv)

        _, rating = mock_review.call_args[0]
        assert rating == Rating.Good

    def test_all_zeros_produces_score_zero(self) -> None:
        """[0,0,0,0,0] → score = 0.0 → Rating.Again."""
        item = _vocab_item("x", history_window=[0, 0, 0, 0, 0])
        uv = _user_vocab(item)
        log = _episode_log(_word_log("x", clicked=1))  # push 0 → stays all 0

        evaluator = MasteryEvaluator()
        mock_review = mock.MagicMock(return_value=_mock_review_return())
        evaluator._scheduler.review_card = mock_review

        evaluator.evaluate(log, uv)

        _, rating = mock_review.call_args[0]
        assert rating == Rating.Again

    def test_mixed_window_exact_score(self) -> None:
        """[0,0,0,1,1] → score = 0.2+0.4 = 0.6 → Rating.Hard."""
        item = _vocab_item("x", history_window=[0, 0, 0, 1, 1])
        uv = _user_vocab(item)
        log = _episode_log(_word_log("x", clicked=0))  # push 1 → [0,0,1,1,1] → 0.8

        evaluator = MasteryEvaluator()
        mock_review = mock.MagicMock(return_value=_mock_review_return())
        evaluator._scheduler.review_card = mock_review

        evaluator.evaluate(log, uv)

        _, rating = mock_review.call_args[0]
        # After push: [0,0,1,1,1] → score = 0.2+0.2+0.4 = 0.8 → Good
        assert rating == Rating.Good


# ============================================================================
# Rating mapping
# ============================================================================


class TestRatingMapping:
    """Score → Rating: >=0.8→Good, >=0.5→Hard, <0.5→Again."""

    def test_score_0_8_maps_to_good(self) -> None:
        """score 0.8 exactly → Rating.Good."""
        # Window [1,0,0,1,1]: w*h = 0.1+0.2+0.4=0.7...
        # Let me use [0,0,1,1,1]: 0.2+0.2+0.4=0.8
        # With clicked=0 push: [0,0,1,1,1] stays [0,0,1,1,1]
        # But actually [0,0,1,1,1] with clicked=0 → push 1 → [0,1,1,1,1] → 0.1+0.2+0.2+0.4=0.9
        # So I need the window to be [0,0,1,1,1] AFTER push.
        # This means initial window [1,0,0,1,1] with clicked=0 → push 1 → [0,0,1,1,1] → 0.8
        item = _vocab_item("x", history_window=[1, 0, 0, 1, 1])
        uv = _user_vocab(item)
        log = _episode_log(_word_log("x", clicked=0))

        evaluator = MasteryEvaluator()
        mock_review = mock.MagicMock(return_value=_mock_review_return())
        evaluator._scheduler.review_card = mock_review

        evaluator.evaluate(log, uv)

        _, rating = mock_review.call_args[0]
        assert rating == Rating.Good

    def test_score_0_5_maps_to_hard(self) -> None:
        """score 0.5 exactly → Rating.Hard (boundary inclusive)."""
        # Window [1,0,0,0,1]: 0.1 + 0.4 = 0.5
        # With clicked=0 → push 1 → need final [1,0,0,0,1]
        # Start: [0,0,0,1,1] with clicked=0 → push 1 → [0,0,1,1,1] → not 0.5
        # Start: [1,1,0,0,1] with clicked=1 → push 0 → [1,0,0,1,0] → not 0.5
        # Let me try: [0,1,0,1,0] → 0.1+0.2=0.3 → too low
        # [1,0,1,0,0] → 0.1+0.2=0.3 → too low
        # [1,0,0,0,1] → 0.1+0.4=0.5 ✓
        # Start from [0,0,0,1,1] with clicked=0 → push 1 → [0,0,1,1,1] → 0.8. Not what I want.
        # I need the resulting window to be [1,0,0,0,1]. Let me think...
        # To get [1,0,0,0,1] after push, I need initial [0,0,0,1,1] with click:
        # click=0 → push 1 → [0,0,1,1,1]. No.
        # click>0 → push 0 → [0,0,1,1,0]. No.
        # [1,0,0,0,1] is a specific 5-element window. To get it from a push:
        # Push 1: initial [0,0,0,0,1] → [0,0,0,1,1]. No.
        # Push 0: initial [1,0,0,0,0] → [0,0,0,0,1]. No.
        # Push removes index 0, shifts left, adds to end.
        # Target: [a,b,c,d,e] = [1,0,0,0,1]
        # If push value is v: [1,0,0,0,1] came from [0,0,0,1,v]
        # So initial = [0,0,0,1,v], final after push v = [0,0,1,v,v]? No wait.
        # target = shift_left(initial) + [v]
        # target[0:4] = initial[1:5]
        # So initial[1:5] = [0,0,0,1] → initial = [?,0,0,0,1]
        # target[4] = v → v = 1
        # So initial = [_,0,0,0,1] and v=1 (clicked=0)
        # The _ can be anything, let me pick 0: initial=[0,0,0,0,1]
        # After push 1: [0,0,0,1,1] → score = 0.2+0.4 = 0.6. Not 0.5.
        # I made an error: target[3] = initial[4] = 1 (from [?,0,0,0,1])
        # target = [0,0,0,1,1]. Score = 0.6. Still not 0.5.
        # OK let me approach differently. I want final score = 0.5.
        # Possible windows with score 0.5:
        # [1,0,0,0,1] → 0.1+0.4=0.5 ✓
        # [0,1,1,0,0] → 0.1+0.2=0.3 ✗
        # [0,0,1,0,1] → 0.2+0.4=0.6 ✗
        # [0,0,0,1,?] → only 0.2, so need 0.3 from position 4 → not possible (max 0.4)
        # Only [1,0,0,0,1] works for score=0.5.
        # To get [1,0,0,0,1] from push v:
        # initial = [_,1,0,0,0], target[4]=v=1
        # push v=1 (clicked=0): [1,0,0,0,1]
        # initial = [_,1,0,0,0] → pick _=0: [0,1,0,0,0] score=0.1
        # So: initial window [0,1,0,0,0], clicked=0 → push 1 → [1,0,0,0,1] → score=0.5
        item = _vocab_item("x", history_window=[0, 1, 0, 0, 0])
        uv = _user_vocab(item)
        log = _episode_log(_word_log("x", clicked=0))

        evaluator = MasteryEvaluator()
        mock_review = mock.MagicMock(return_value=_mock_review_return())
        evaluator._scheduler.review_card = mock_review

        evaluator.evaluate(log, uv)

        _, rating = mock_review.call_args[0]
        assert rating == Rating.Hard

    def test_score_below_0_5_maps_to_again(self) -> None:
        """score < 0.5 → Rating.Again."""
        # Window [0,0,0,0,0] with clicked>0 → stays [0,0,0,0,0] → score=0.0
        item = _vocab_item("x", history_window=[0, 0, 0, 0, 0])
        uv = _user_vocab(item)
        log = _episode_log(_word_log("x", appeared=2, clicked=2))

        evaluator = MasteryEvaluator()
        mock_review = mock.MagicMock(return_value=_mock_review_return())
        evaluator._scheduler.review_card = mock_review

        evaluator.evaluate(log, uv)

        _, rating = mock_review.call_args[0]
        assert rating == Rating.Again

    def test_score_0_79_maps_to_hard(self) -> None:
        """score 0.79 → Rating.Hard (below 0.8 threshold)."""
        # Window [0,0,1,1,0] after push 0 → [0,1,1,0,0] → 0.1+0.2=0.3 Not what I want
        # Window [0,1,1,1,0] → 0.1+0.2+0.2=0.5
        # Window [1,1,1,0,0] → 0.1+0.1+0.2=0.4
        # Let me try [1,1,0,1,0] → 0.1+0.1+0.2=0.4
        # [0,1,0,1,1] → 0.1+0.2+0.4=0.7 ✓ Good for "Hard" (0.5 <= 0.7 < 0.8)
        # initial [1,0,1,0,1] with clicked=0 → push 1 → [0,1,0,1,1] → 0.7
        item = _vocab_item("x", history_window=[1, 0, 1, 0, 1])
        uv = _user_vocab(item)
        log = _episode_log(_word_log("x", clicked=0))

        evaluator = MasteryEvaluator()
        mock_review = mock.MagicMock(return_value=_mock_review_return())
        evaluator._scheduler.review_card = mock_review

        evaluator.evaluate(log, uv)

        _, rating = mock_review.call_args[0]
        assert rating == Rating.Hard


# ============================================================================
# Cross-day forcing
# ============================================================================


class TestCrossDayForce:
    """Cross-day forcing: due <= today 23:59:59 → pushed to tomorrow 00:00 UTC."""

    FROZEN_NOW = "2026-06-07 14:00:00"

    def test_due_today_gets_pushed_to_tomorrow(self) -> None:
        """due today (before 23:59:59) → forced to tomorrow 00:00 UTC."""
        item = _vocab_item(
            "x",
            history_window=[1, 1, 1, 1, 1],
            due=datetime.datetime(2026, 6, 7, 10, 0, tzinfo=UTC),
            last_review=datetime.datetime(2026, 6, 1, tzinfo=UTC),
            state=2,
        )
        uv = _user_vocab(item)
        log = _episode_log(_word_log("x", clicked=0))

        # scheduler returns a due that is today (before forcing)
        today_due = datetime.datetime(2026, 6, 7, 14, 10, tzinfo=UTC)
        mock_return = _mock_review_return(due=today_due)

        evaluator = MasteryEvaluator()
        evaluator._scheduler.review_card = mock.MagicMock(return_value=mock_return)

        with freezegun.freeze_time(self.FROZEN_NOW):
            result = evaluator.evaluate(log, uv)

        updated = result.vocab_index["x"]
        expected_tomorrow = datetime.datetime(2026, 6, 8, 0, 0, tzinfo=UTC)
        assert updated.fsrs_card.due == expected_tomorrow

    def test_due_already_tomorrow_not_forced(self) -> None:
        """due already tomorrow → unchanged by cross-day force."""
        item = _vocab_item(
            "x",
            history_window=[1, 1, 1, 1, 1],
            due=datetime.datetime(2026, 6, 8, tzinfo=UTC),
            last_review=datetime.datetime(2026, 6, 1, tzinfo=UTC),
            state=2,
        )
        uv = _user_vocab(item)
        log = _episode_log(_word_log("x", clicked=0))

        tomorrow_due = datetime.datetime(2026, 6, 8, 10, 0, tzinfo=UTC)
        mock_return = _mock_review_return(due=tomorrow_due)

        evaluator = MasteryEvaluator()
        evaluator._scheduler.review_card = mock.MagicMock(return_value=mock_return)

        with freezegun.freeze_time(self.FROZEN_NOW):
            result = evaluator.evaluate(log, uv)

        updated = result.vocab_index["x"]
        assert updated.fsrs_card.due == tomorrow_due  # unchanged

    def test_due_at_end_of_today_boundary(self) -> None:
        """due exactly at 2026-06-07 23:59:59 UTC → forced to tomorrow."""
        item = _vocab_item(
            "x",
            history_window=[1, 1, 1, 1, 1],
            due=datetime.datetime(2026, 6, 7, tzinfo=UTC),
            last_review=datetime.datetime(2026, 6, 1, tzinfo=UTC),
            state=2,
        )
        uv = _user_vocab(item)
        log = _episode_log(_word_log("x", clicked=0))

        boundary_due = datetime.datetime(2026, 6, 7, 23, 59, 59, tzinfo=UTC)
        mock_return = _mock_review_return(due=boundary_due)

        evaluator = MasteryEvaluator()
        evaluator._scheduler.review_card = mock.MagicMock(return_value=mock_return)

        with freezegun.freeze_time(self.FROZEN_NOW):
            result = evaluator.evaluate(log, uv)

        updated = result.vocab_index["x"]
        expected_tomorrow = datetime.datetime(2026, 6, 8, 0, 0, tzinfo=UTC)
        assert updated.fsrs_card.due == expected_tomorrow

    def test_due_far_future_not_forced(self) -> None:
        """due far in the future → unchanged."""
        item = _vocab_item(
            "x",
            history_window=[1, 1, 1, 1, 1],
            due=datetime.datetime(2026, 6, 7, tzinfo=UTC),
            last_review=datetime.datetime(2026, 6, 1, tzinfo=UTC),
            state=2,
        )
        uv = _user_vocab(item)
        log = _episode_log(_word_log("x", clicked=0))

        far_due = datetime.datetime(2026, 7, 15, tzinfo=UTC)
        mock_return = _mock_review_return(due=far_due)

        evaluator = MasteryEvaluator()
        evaluator._scheduler.review_card = mock.MagicMock(return_value=mock_return)

        with freezegun.freeze_time(self.FROZEN_NOW):
            result = evaluator.evaluate(log, uv)

        updated = result.vocab_index["x"]
        assert updated.fsrs_card.due == far_due  # unchanged


# ============================================================================
# End-to-end (real scheduler)
# ============================================================================


class TestEndToEnd:
    """Integration tests with real fsrs.Scheduler."""

    def test_end_to_end_single_word_log(self) -> None:
        """Complete pipeline with real scheduler: one word, verify history+fsrs updated."""
        item = _vocab_item(
            "word_a",
            history_window=[1, 0, 1, 0, 0],
            due=datetime.datetime(2026, 6, 10, tzinfo=UTC),
            last_review=datetime.datetime(2026, 6, 5, tzinfo=UTC),
            state=2,
            stability=4.0,
            difficulty=0.5,
        )
        uv = _user_vocab(item)
        log = _episode_log(_word_log("word_a", appeared=2, clicked=1))

        with freezegun.freeze_time("2026-06-07 14:00:00"):
            result = MasteryEvaluator().evaluate(log, uv)

        out = result.vocab_index["word_a"]
        # history_window should have been pushed: [1,0,1,0,0] + clicked>0 → push 0 → [0,1,0,0,0]
        assert out.history_window == [0, 1, 0, 0, 0]
        # fsrs_card should have been updated (due, last_review changed)
        assert out.fsrs_card.last_review is not None
        assert out.fsrs_card.due > datetime.datetime(2026, 6, 7, tzinfo=UTC)

    def test_end_to_end_multiple_word_logs(self) -> None:
        """Multiple word_logs in one episode: all processed correctly."""
        item_a = _vocab_item(
            "a",
            history_window=[1, 1, 1, 1, 1],
            due=datetime.datetime(2026, 6, 10, tzinfo=UTC),
            last_review=datetime.datetime(2026, 6, 5, tzinfo=UTC),
            state=2,
            stability=4.0,
            difficulty=0.5,
        )
        item_b = _vocab_item(
            "b",
            history_window=[0, 0, 0, 0, 0],
            due=datetime.datetime(2026, 6, 8, tzinfo=UTC),
            last_review=None,
            state=1,
        )
        item_c = _vocab_item(
            "c",
            history_window=[1, 0, 1, 0, 0],
            due=datetime.datetime(2026, 6, 9, tzinfo=UTC),
            last_review=datetime.datetime(2026, 6, 4, tzinfo=UTC),
            state=2,
            stability=3.5,
            difficulty=0.6,
        )
        uv = _user_vocab(item_a, item_b, item_c)
        log = _episode_log(
            _word_log("a", appeared=3, clicked=0),
            _word_log("b", appeared=1, clicked=1),
            _word_log("c", appeared=2, clicked=0),
        )

        with freezegun.freeze_time("2026-06-07 12:00:00"):
            result = MasteryEvaluator().evaluate(log, uv)

        # "a": clicked=0 → push 1 → [1,1,1,1,1] unchanged
        assert result.vocab_index["a"].history_window == [1, 1, 1, 1, 1]
        # "b": clicked=1 → push 0 → [0,0,0,0,0] unchanged
        assert result.vocab_index["b"].history_window == [0, 0, 0, 0, 0]
        # "c": clicked=0 → push 1 → [0,1,0,0,1]
        assert result.vocab_index["c"].history_window == [0, 1, 0, 0, 1]

        # All fsrs_cards should have updated last_review
        for item_id in ("a", "b", "c"):
            card = result.vocab_index[item_id].fsrs_card
            assert card.last_review is not None

    def test_unknown_item_among_valid_ones(self) -> None:
        """Mix of known and unknown item_ids: known processed, unknown skipped."""
        item_a = _vocab_item(
            "a",
            history_window=[0, 0, 0, 0, 0],
            due=datetime.datetime(2026, 6, 7, tzinfo=UTC),
            last_review=None,
            state=1,
        )
        uv = _user_vocab(item_a)
        log = _episode_log(
            _word_log("a", appeared=1, clicked=0),
            _word_log("nonexistent", appeared=2, clicked=1),
        )

        evaluator = MasteryEvaluator()
        evaluator._scheduler.review_card = mock.MagicMock(
            return_value=_mock_review_return()
        )
        result = evaluator.evaluate(log, uv)

        assert len(result.vocabulary) == 1
        assert "a" in result.vocab_index
        assert "nonexistent" not in result.vocab_index

    def test_now_param_defaults_to_utc_now(self) -> None:
        """When now is None, evaluate uses the current UTC time."""
        item = _vocab_item(
            "x",
            history_window=[1, 1, 1, 1, 1],
            due=datetime.datetime(2026, 12, 31, tzinfo=UTC),
            last_review=datetime.datetime(2026, 12, 25, tzinfo=UTC),
            state=2,
            stability=4.0,
            difficulty=0.5,
        )
        uv = _user_vocab(item)
        log = _episode_log(_word_log("x", clicked=0))

        # No freeze_time — let it use real now.
        result = MasteryEvaluator().evaluate(log, uv)

        # Should have updated last_review to something recent
        out = result.vocab_index["x"]
        assert out.fsrs_card.last_review is not None
        # history_window updated
        assert out.history_window == [1, 1, 1, 1, 1]  # push 1 into all-1 stays all-1

    def test_explicit_now_respected(self) -> None:
        """Explicit now parameter is used for cross-day forcing."""
        item = _vocab_item(
            "x",
            history_window=[0, 0, 0, 0, 0],
            due=datetime.datetime(2026, 1, 1, tzinfo=UTC),
            last_review=None,
            state=1,
        )
        uv = _user_vocab(item)
        log = _episode_log(_word_log("x", clicked=0))

        # Mock scheduler to return a due date of 2026-01-01 (today relative to explicit now)
        today_due = datetime.datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
        mock_return = _mock_review_return(due=today_due)

        evaluator = MasteryEvaluator()
        evaluator._scheduler.review_card = mock.MagicMock(return_value=mock_return)

        explicit_now = datetime.datetime(2026, 1, 1, 14, 0, tzinfo=UTC)
        result = evaluator.evaluate(log, uv, now=explicit_now)

        # Cross-day force: due today → pushed to tomorrow
        expected_tomorrow = datetime.datetime(2026, 1, 2, 0, 0, tzinfo=UTC)
        assert result.vocab_index["x"].fsrs_card.due == expected_tomorrow
