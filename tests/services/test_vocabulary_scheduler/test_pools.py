"""Tests for vocabulary_scheduler/pools.py — pool building and pending overlay."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from app.models.fsrs import FsrsCard
from app.models.vocabulary import UserVocabulary, VocabularyItem
from app.services.vocabulary_scheduler.pools import apply_pending_overlay, build_pools

FIXTURES_DIR = Path(__file__).parent.parent.parent / "fixtures"


def _load_user_vocab() -> UserVocabulary:
    """Load the user_vocabulary.json fixture as a UserVocabulary Pydantic model."""
    path = FIXTURES_DIR / "user_vocabulary.json"
    raw = path.read_text(encoding="utf-8")
    # Python 3.10 compat: datetime.fromisoformat() rejects "Z" suffix
    raw = re.sub(r"(\d{2}:\d{2}:\d{2})Z", r"\1+00:00", raw)
    data = json.loads(raw)
    return UserVocabulary.model_validate(data)


def _make_item(
    item_id: str,
    word: str = "test",
    meaning: str = "测试",
    chapter_first_seen: int = 1,
    last_review: str | None = None,
    due: str = "2026-06-01T00:00:00Z",
) -> VocabularyItem:
    """Build a minimal VocabularyItem for testing."""
    # Python 3.10 compat: replace Z with +00:00
    due_dt = datetime.fromisoformat(due.replace("Z", "+00:00"))
    last_review_dt = (
        datetime.fromisoformat(last_review.replace("Z", "+00:00"))
        if last_review
        else None
    )
    return VocabularyItem(
        id=item_id,
        word=word,
        meaning=meaning,
        chapter_first_seen=chapter_first_seen,
        history_window=[],
        fsrs_card=FsrsCard(
            card_id=1,
            state=1,
            due=due_dt,
            last_review=last_review_dt,
        ),
    )


def _make_vocab(items: list[VocabularyItem]) -> UserVocabulary:
    """Wrap items in a UserVocabulary model."""
    return UserVocabulary(user_id="test", vocabulary=items)


# ── build_pools tests ────────────────────────────────────────────────


def test_build_pools_separates_unseen_and_due():
    """Verify full fixture: unseen pool has last_review=None, due_review has due<=now."""
    data = _load_user_vocab()
    now = datetime(2026, 6, 6, 12, 0, 0, tzinfo=timezone.utc)
    unseen, due_review = build_pools(data, now)

    unseen_ids = {item.id for item in unseen}
    due_ids = {item.id for item in due_review}

    # All unseen words from fixture
    expected_unseen = {
        "awkward_1",
        "meticulous_1",
        "coherent_1",
        "invisible_1",
        "introduce_1",
        "hesitate_1",
        "glance_look",
        "murmur_1",
        "anxious_1",
        "reluctant_1",
        "bank_river",
        "bank_finance",
        "issue_problem",
        "issue_topic",
    }
    assert unseen_ids == expected_unseen, (
        f"Unexpected unseen: {unseen_ids ^ expected_unseen}"
    )

    # Due review words (due <= now 2026-06-06T12:00)
    expected_due = {
        "footstep_1",  # due 2026-06-05
        "corridor_1",  # due 2026-06-04
        "resonate_1",  # due 2026-06-05
        "ambiguous_1",  # due 2026-06-05
        "ephemeral_1",  # due 2026-06-04
        "solitary_1",  # due 2026-06-06
        "inevitable_1",  # due 2026-06-06
    }
    assert due_ids == expected_due, f"Unexpected due: {due_ids ^ expected_due}"

    # Verify whisper_1 (due 2026-06-07 > now), discreet_1 (due 2026-06-08 > now),
    # nostalgia_1 (due 2026-06-09 > now) are NOT in due_review_pool
    assert "whisper_1" not in due_ids
    assert "discreet_1" not in due_ids
    assert "nostalgia_1" not in due_ids

    # These not-due words should be in neither pool (they are not unseen, not yet due)
    # Verify they are truly excluded
    all_processed = unseen_ids | due_ids
    assert "whisper_1" not in all_processed
    assert "discreet_1" not in all_processed
    assert "nostalgia_1" not in all_processed


def test_build_pools_all_unseen_when_no_reviews():
    """All items have last_review=None → all go to unseen, due_review empty."""
    items = [
        _make_item("A", chapter_first_seen=1),
        _make_item("B", chapter_first_seen=2),
        _make_item("C", chapter_first_seen=3),
    ]
    vocab = _make_vocab(items)
    now = datetime(2026, 6, 6, 12, 0, 0, tzinfo=timezone.utc)
    unseen, due_review = build_pools(vocab, now)

    assert len(unseen) == 3
    assert len(due_review) == 0


def test_build_pools_all_due_when_all_overdue():
    """All items have last_review set and due in the past → all in due_review."""
    items = [
        _make_item("A", last_review="2026-05-01T00:00:00Z", due="2026-06-01T00:00:00Z"),
        _make_item("B", last_review="2026-05-02T00:00:00Z", due="2026-06-02T00:00:00Z"),
        _make_item("C", last_review="2026-05-03T00:00:00Z", due="2026-06-03T00:00:00Z"),
    ]
    vocab = _make_vocab(items)
    now = datetime(2026, 6, 6, 12, 0, 0, tzinfo=timezone.utc)
    unseen, due_review = build_pools(vocab, now)

    assert len(unseen) == 0
    assert len(due_review) == 3


def test_build_pools_empty_vocab():
    """Empty vocabulary → both pools empty."""
    vocab = _make_vocab([])
    now = datetime(2026, 6, 6, 12, 0, 0, tzinfo=timezone.utc)
    unseen, due_review = build_pools(vocab, now)

    assert unseen == []
    assert due_review == []


def test_build_pools_now_default():
    """Call with now=None should not raise, uses current UTC time."""
    data = _load_user_vocab()
    unseen, due_review = build_pools(data, None)

    # Should produce some pools without error
    assert isinstance(unseen, list)
    assert isinstance(due_review, list)


def test_build_pools_with_timezone_aware():
    """Due fields with different timezone-aware datetimes are parsed correctly."""
    items = [
        _make_item(
            "morning",
            last_review="2026-05-01T00:00:00+00:00",
            due="2026-06-06T06:00:00+00:00",
        ),
        _make_item(
            "noon", last_review="2026-05-02T00:00:00Z", due="2026-06-06T12:00:00Z"
        ),
        _make_item(
            "evening",
            last_review="2026-05-03T00:00:00-05:00",
            due="2026-06-06T23:00:00+00:00",
        ),
    ]
    vocab = _make_vocab(items)
    # now = 2026-06-06T12:00:00 UTC
    now = datetime(2026, 6, 6, 12, 0, 0, tzinfo=timezone.utc)
    unseen, due_review = build_pools(vocab, now)

    due_ids = {item.id for item in due_review}
    # morning: 06:00 <= 12:00 → due
    # noon: 12:00 <= 12:00 → due
    # evening: 23:00 > 12:00 → not due
    assert "morning" in due_ids
    assert "noon" in due_ids
    assert "evening" not in due_ids


# ── apply_pending_overlay tests ──────────────────────────────────────


def test_apply_pending_overlay_unseen_reorders():
    """Pending items moved to front in pending_order sequence; non-pending sorted by chapter."""
    items = [
        _make_item("A", chapter_first_seen=3),
        _make_item("B", chapter_first_seen=2),
        _make_item("C", chapter_first_seen=1),
        _make_item("D", chapter_first_seen=4),
    ]
    pools = (list(items), [])
    pending = [{"item_id": "C"}, {"item_id": "A"}]
    unseen, due_review = apply_pending_overlay(pools, pending)

    order = [item.id for item in unseen]
    # Pending in order: C, A
    # Non-pending sorted by chapter_first_seen: B(ch2), D(ch4)
    assert order == ["C", "A", "B", "D"], f"Got order: {order}"


def test_apply_pending_overlay_due_reorders():
    """Pending items moved to front in due pool; non-pending sorted by due ascending."""
    items = [
        _make_item("X", last_review="2026-01-01T00:00:00Z", due="2026-06-10T00:00:00Z"),
        _make_item("Y", last_review="2026-01-01T00:00:00Z", due="2026-06-05T00:00:00Z"),
        _make_item("Z", last_review="2026-01-01T00:00:00Z", due="2026-06-01T00:00:00Z"),
    ]
    pools = ([], list(items))
    pending = [{"item_id": "X"}]
    unseen, due_review = apply_pending_overlay(pools, pending)

    order = [item.id for item in due_review]
    # Pending: X first, then non-pending sorted by due: Z (06-01), Y (06-05)
    assert order == ["X", "Z", "Y"], f"Got order: {order}"


def test_apply_pending_overlay_pending_not_in_pool():
    """Pending item_id not in pool → silently ignored, no error."""
    items = [
        _make_item("A", chapter_first_seen=2),
        _make_item("B", chapter_first_seen=1),
    ]
    pools = (list(items), [])
    pending = [{"item_id": "NONEXISTENT"}]
    unseen, due_review = apply_pending_overlay(pools, pending)

    # Should just be sorted by chapter_first_seen
    order = [item.id for item in unseen]
    assert order == ["B", "A"], f"Got order: {order}"


def test_apply_pending_overlay_no_pending():
    """Empty pending_words → pools unchanged (just sorted by default rules)."""
    items = [
        _make_item("A", chapter_first_seen=3),
        _make_item("B", chapter_first_seen=1),
        _make_item("C", chapter_first_seen=2),
    ]
    pools = (list(items), [])
    pending: list[dict] = []
    unseen, due_review = apply_pending_overlay(pools, pending)

    order = [item.id for item in unseen]
    # Sorted by chapter_first_seen
    assert order == ["B", "C", "A"], f"Got order: {order}"


def test_apply_pending_sort_unseen_by_chapter():
    """Non-pending unseen items sorted by chapter_first_seen ascending."""
    items = [
        _make_item("ch3", chapter_first_seen=3),
        _make_item("ch1", chapter_first_seen=1),
        _make_item("ch2", chapter_first_seen=2),
    ]
    pools = (list(items), [])
    pending: list[dict] = []
    unseen, _ = apply_pending_overlay(pools, pending)

    order = [item.id for item in unseen]
    assert order == ["ch1", "ch2", "ch3"], f"Got order: {order}"


def test_apply_pending_sort_due_by_date():
    """Non-pending due items sorted by fsrs_card.due ascending."""
    items = [
        _make_item(
            "late", last_review="2026-01-01T00:00:00Z", due="2026-06-15T00:00:00Z"
        ),
        _make_item(
            "early", last_review="2026-01-01T00:00:00Z", due="2026-06-01T00:00:00Z"
        ),
        _make_item(
            "mid", last_review="2026-01-01T00:00:00Z", due="2026-06-10T00:00:00Z"
        ),
    ]
    pools = ([], list(items))
    pending: list[dict] = []
    _, due_review = apply_pending_overlay(pools, pending)

    order = [item.id for item in due_review]
    assert order == ["early", "mid", "late"], f"Got order: {order}"


def test_apply_pending_mixed_pending_and_natural_order():
    """Integration: pending items at front across both pools with correct sorting."""
    items_unseen = [
        _make_item("U3", chapter_first_seen=3),
        _make_item("U1", chapter_first_seen=1),
        _make_item("U2", chapter_first_seen=2),
        _make_item("UP", chapter_first_seen=5),
    ]
    items_due = [
        _make_item(
            "D3", last_review="2026-01-01T00:00:00Z", due="2026-06-20T00:00:00Z"
        ),
        _make_item(
            "D1", last_review="2026-01-01T00:00:00Z", due="2026-06-10T00:00:00Z"
        ),
        _make_item(
            "DP", last_review="2026-01-01T00:00:00Z", due="2026-06-30T00:00:00Z"
        ),
    ]
    pools = (list(items_unseen), list(items_due))
    pending = [{"item_id": "DP"}, {"item_id": "UP"}]
    unseen, due_review = apply_pending_overlay(pools, pending)

    unseen_order = [item.id for item in unseen]
    # UP first (pending), then sorted: U1(ch1), U2(ch2), U3(ch3)
    assert unseen_order == ["UP", "U1", "U2", "U3"], f"Got: {unseen_order}"

    due_order = [item.id for item in due_review]
    # DP first (pending), then sorted: D1(06-10), D3(06-20)
    assert due_order == ["DP", "D1", "D3"], f"Got: {due_order}"
