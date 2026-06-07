"""Tests for vocabulary_scheduler/allocator.py — main/side episode word allocation."""

from __future__ import annotations

import datetime

from app.models.arc_plan import TargetWord
from app.models.fsrs import FsrsCard
from app.models.vocabulary import VocabularyItem
from app.services.vocabulary_scheduler.allocator import (
    _build_target,
    allocate_main_episode,
    allocate_side_episode,
)


def _make_fsrs_card(card_id: int = 0) -> FsrsCard:
    """Create a minimal FsrsCard for testing."""
    return FsrsCard(
        card_id=card_id,
        state=1,
        step=None,
        stability=None,
        difficulty=None,
        due=datetime.datetime(2026, 6, 6, tzinfo=datetime.timezone.utc),
        last_review=None,
    )


def _make_item(
    item_id: str, word: str = "test", meaning: str = "测试", chapter: int = 1
) -> VocabularyItem:
    return VocabularyItem(
        id=item_id,
        word=word,
        meaning=meaning,
        chapter_first_seen=chapter,
        history_window=[0, 0, 0, 0, 0],
        fsrs_card=_make_fsrs_card(),
    )


# ―――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――
# _build_target
# ―――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――


class TestBuildTarget:
    def test_build_target_word_format(self) -> None:
        item = _make_item("word_a", word="consume", meaning="消费")
        result = _build_target(item, is_new=True)

        assert isinstance(result, TargetWord)
        assert result.item_id == "word_a"
        assert result.word == "consume"
        assert result.meaning == "消费"
        assert result.is_new is True
        assert result.fsrs_card is not None

    def test_build_target_is_new_false(self) -> None:
        item = _make_item("word_b")
        result = _build_target(item, is_new=False)
        assert result.is_new is False


# ―――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――
# allocate_main_episode
# ―――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――


class TestAllocateMainEpisode:
    def test_picks_top_unseen(self) -> None:
        """5 unseen candidates scored [0.9, 0.8, 0.7, 0.6, 0.5], limit=3 → top 3."""
        items = [_make_item(f"word_{i}") for i in range(5)]
        unseen = [
            (0.9, items[0]),
            (0.8, items[1]),
            (0.7, items[2]),
            (0.6, items[3]),
            (0.5, items[4]),
        ]
        target_words, arc_new_ids = allocate_main_episode(unseen, [], episode_limit=3)

        assert len(target_words) == 3
        assert all(t.is_new for t in target_words)
        assert {t.item_id for t in target_words} == {"word_0", "word_1", "word_2"}
        assert arc_new_ids == {"word_0", "word_1", "word_2"}

    def test_picks_top_review(self) -> None:
        """5 review candidates scored [0.9, 0.8, 0.7, 0.6, 0.5], limit=3 → top 3."""
        items = [_make_item(f"rev_{i}") for i in range(5)]
        review = [
            (0.9, items[0]),
            (0.8, items[1]),
            (0.7, items[2]),
            (0.6, items[3]),
            (0.5, items[4]),
        ]
        target_words, arc_new_ids = allocate_main_episode([], review, episode_limit=3)

        assert len(target_words) == 3
        assert all(not t.is_new for t in target_words)
        assert {t.item_id for t in target_words} == {"rev_0", "rev_1", "rev_2"}
        # No new words added to arc_new_ids
        assert arc_new_ids == set()

    def test_unseen_dedup(self) -> None:
        """arc_new_ids={"word_a"} → word_a skipped, word_b picked instead."""
        item_a = _make_item("word_a", word="alpha")
        item_b = _make_item("word_b", word="beta")
        unseen = [(0.9, item_a), (0.8, item_b)]

        target_words, arc_new_ids = allocate_main_episode(
            unseen, [], episode_limit=10, arc_new_ids={"word_a"}
        )

        assert len(target_words) == 1
        assert target_words[0].item_id == "word_b"
        assert target_words[0].is_new is True
        assert arc_new_ids == {"word_a", "word_b"}

    def test_cold_start_review_empty(self) -> None:
        """No review, 15 unseen, limit=10 → 10 unseen filled, no error."""
        items = [_make_item(f"cold_{i}") for i in range(15)]
        unseen = [(1.0 - i * 0.01, items[i]) for i in range(15)]

        target_words, arc_new_ids = allocate_main_episode(unseen, [], episode_limit=10)

        assert len(target_words) == 10
        assert all(t.is_new for t in target_words)
        assert len(arc_new_ids) == 10

    def test_insufficient_candidates(self) -> None:
        """Only 3 unseen + 2 review, limit=10 → returns all 5, no error."""
        unseen_items = [_make_item(f"u{i}") for i in range(3)]
        review_items = [_make_item(f"r{i}") for i in range(2)]
        unseen = [(0.9 - i * 0.1, unseen_items[i]) for i in range(3)]
        review = [(0.8 - i * 0.1, review_items[i]) for i in range(2)]

        target_words, arc_new_ids = allocate_main_episode(
            unseen, review, episode_limit=10
        )

        assert len(target_words) == 5
        new_words = [t for t in target_words if t.is_new]
        review_words = [t for t in target_words if not t.is_new]
        assert len(new_words) == 3
        assert len(review_words) == 2

    def test_empty_pools(self) -> None:
        """No candidates → empty result, no error."""
        target_words, arc_new_ids = allocate_main_episode([], [], episode_limit=10)

        assert target_words == []
        assert arc_new_ids == set()

    def test_limits_new_and_review_separately(self) -> None:
        """15 unseen + 15 review, limit=5 → 5 new + 5 review = 10 total."""
        unseen_items = [_make_item(f"nu{i}") for i in range(15)]
        review_items = [_make_item(f"nr{i}") for i in range(15)]
        unseen = [(1.0 - i * 0.01, unseen_items[i]) for i in range(15)]
        review = [(1.0 - i * 0.01, review_items[i]) for i in range(15)]

        target_words, arc_new_ids = allocate_main_episode(
            unseen, review, episode_limit=5
        )

        assert len(target_words) == 10
        new_words = [t for t in target_words if t.is_new]
        review_words = [t for t in target_words if not t.is_new]
        assert len(new_words) == 5
        assert len(review_words) == 5
        assert len(arc_new_ids) == 5

    def test_sort_by_score_descending(self) -> None:
        """Verify unseen items picked in score-descending order."""
        items = [_make_item(f"s{i}") for i in range(5)]
        unseen = [
            (0.3, items[0]),
            (0.9, items[1]),
            (0.6, items[2]),
            (0.8, items[3]),
            (0.1, items[4]),
        ]

        target_words, _ = allocate_main_episode(unseen, [], episode_limit=3)

        picked_ids = [t.item_id for t in target_words]
        # 0.9 → s1, 0.8 → s3, 0.6 → s2
        assert picked_ids == ["s1", "s3", "s2"]

    def test_cold_start_all_new(self) -> None:
        """15 unseen, 0 review, limit=10 → all is_new=true."""
        items = [_make_item(f"cs{i}") for i in range(15)]
        unseen = [(1.0 - i * 0.01, items[i]) for i in range(15)]

        target_words, _ = allocate_main_episode(unseen, [], episode_limit=10)

        assert len(target_words) == 10
        assert all(t.is_new for t in target_words)


# ―――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――
# allocate_side_episode
# ―――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――


class TestAllocateSideEpisode:
    def test_pending_fills_first(self) -> None:
        """pending_item_ids=["word_b"] → word_b (0.5) picked before word_a (0.9)."""
        item_a = _make_item("word_a", word="alpha")
        item_b = _make_item("word_b", word="beta")
        unseen = [(0.9, item_a), (0.5, item_b)]

        target_words, arc_new_ids = allocate_side_episode(
            unseen, [], pending_item_ids=["word_b"], episode_limit=3
        )

        picked_ids = [t.item_id for t in target_words]
        assert picked_ids[0] == "word_b"  # pending first
        assert picked_ids[1] == "word_a"  # then higher-scored other
        assert len(target_words) == 2

    def test_pending_not_exceed_limit(self) -> None:
        """5 pending items, limit=3 → only 3 picked from pending."""
        items = [_make_item(f"p{i}") for i in range(5)]
        unseen = [(0.9 - i * 0.1, items[i]) for i in range(5)]
        pending_ids = [f"p{i}" for i in range(5)]

        target_words, arc_new_ids = allocate_side_episode(
            unseen, [], pending_item_ids=pending_ids, episode_limit=3
        )

        assert len(target_words) == 3
        assert all(t.is_new for t in target_words)
        # Top 3 by score from pending
        picked_ids = {t.item_id for t in target_words}
        assert picked_ids == {"p0", "p1", "p2"}

    def test_no_pending(self) -> None:
        """Empty pending → behaves like main allocation (no side-specific logic)."""
        items = [_make_item(f"np{i}") for i in range(5)]
        unseen = [(0.9 - i * 0.1, items[i]) for i in range(5)]
        review_items = [_make_item(f"rn{i}") for i in range(3)]
        review = [(0.8 - i * 0.1, review_items[i]) for i in range(3)]

        target_words, arc_new_ids = allocate_side_episode(
            unseen, review, pending_item_ids=[], episode_limit=3
        )

        # 3 unseen + 3 review
        assert len(target_words) == 6
        new_words = [t for t in target_words if t.is_new]
        review_words = [t for t in target_words if not t.is_new]
        assert len(new_words) == 3
        assert len(review_words) == 3

    def test_review_filled_after_new(self) -> None:
        """2 pending unseen + 10 review, limit=5 → 2 new + 5 review = 7."""
        pending_items = [_make_item("pu0", word="pu0"), _make_item("pu1", word="pu1")]
        unseen = [(0.8, pending_items[0]), (0.7, pending_items[1])]

        review_items = [_make_item(f"rv{i}") for i in range(10)]
        review = [(0.9 - i * 0.05, review_items[i]) for i in range(10)]

        target_words, arc_new_ids = allocate_side_episode(
            unseen,
            review,
            pending_item_ids=["pu0", "pu1"],
            episode_limit=5,
        )

        assert len(target_words) == 7
        new_words = [t for t in target_words if t.is_new]
        review_words = [t for t in target_words if not t.is_new]
        assert len(new_words) == 2
        assert len(review_words) == 5

        # Pending words picked first among new
        assert new_words[0].item_id == "pu0"
        assert new_words[1].item_id == "pu1"

    def test_dedup_applies_to_unseen(self) -> None:
        """arc_new_ids={"already_new"} → that item skipped for new words."""
        item_already = _make_item("already_new", word="dup")
        item_fresh = _make_item("fresh", word="fresh")
        unseen = [(0.9, item_already), (0.8, item_fresh)]

        target_words, arc_new_ids = allocate_side_episode(
            unseen,
            [],
            pending_item_ids=["already_new"],
            episode_limit=10,
            arc_new_ids={"already_new"},
        )

        # "already_new" is in arc_new_ids → skipped in pending_unseen loop
        # "fresh" is picked from other_unseen
        assert len(target_words) == 1
        assert target_words[0].item_id == "fresh"
        assert "fresh" in arc_new_ids

    def test_empty_pools_side(self) -> None:
        """Empty pools for side episode → no crash."""
        target_words, arc_new_ids = allocate_side_episode(
            [], [], pending_item_ids=[], episode_limit=10
        )
        assert target_words == []
        assert arc_new_ids == set()
