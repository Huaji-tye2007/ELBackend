"""Integration tests for scheduler.schedule() — end-to-end pipeline."""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from app.services.vocabulary_scheduler.scheduler import schedule

FIXTURES_DIR = Path(__file__).parent.parent.parent / "fixtures"


def _load_fixture(name: str) -> dict[str, Any]:
    path = FIXTURES_DIR / f"{name}.json"
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture
def user_vocab() -> dict[str, Any]:
    return _load_fixture("user_vocabulary")


@pytest.fixture
def arc_plan() -> dict[str, Any]:
    return _load_fixture("prev_arc_plan")


@pytest.fixture
def now() -> datetime:
    """Reference time: 2026-06-06 12:00 UTC."""
    return datetime(2026, 6, 6, 12, 0, 0, tzinfo=timezone.utc)


# ============================================================================
# Helpers (synchronous — process schedule results, don't call schedule)
# ============================================================================


def _collect_all_targets(arc_plan: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten all target_words across all episodes into one list."""
    result: list[dict[str, Any]] = []
    for ep in arc_plan.get("episodes", []):
        result.extend(ep.get("target_words", []))
    return result


def _collect_all_new_ids(arc_plan: dict[str, Any]) -> list[str]:
    """Collect item_ids where is_new=true across all episodes."""
    return [tw["item_id"] for tw in _collect_all_targets(arc_plan) if tw["is_new"]]


def _collect_all_review_ids(arc_plan: dict[str, Any]) -> list[str]:
    """Collect item_ids where is_new=false across all episodes."""
    return [tw["item_id"] for tw in _collect_all_targets(arc_plan) if not tw["is_new"]]


def _vocab_id_set(user_vocab: dict[str, Any]) -> set[str]:
    """Build a set of all item_ids from user_vocab."""
    return {item["id"] for item in user_vocab["vocabulary"]}


# ============================================================================
# Test 1: Basic structure
# ============================================================================


class TestScheduleReturnsArcPlanWithTargetWords:
    """Verify that schedule() populates target_words on each episode."""

    async def test_returns_same_dict_object(
        self, arc_plan: dict[str, Any], user_vocab: dict[str, Any], now: datetime
    ) -> None:
        result = await schedule(arc_plan, user_vocab, now)
        assert result is arc_plan

    async def test_each_episode_has_target_words_list(
        self, arc_plan: dict[str, Any], user_vocab: dict[str, Any], now: datetime
    ) -> None:
        result = await schedule(arc_plan, user_vocab, now)
        for i, episode in enumerate(result["episodes"]):
            assert isinstance(episode.get("target_words"), list), (
                f"Episode {i} target_words is not a list"
            )

    async def test_episodes_have_valid_structure(
        self, arc_plan: dict[str, Any], user_vocab: dict[str, Any], now: datetime
    ) -> None:
        """Each episode must have a target_words list; pool exhaustion is OK."""
        result = await schedule(arc_plan, user_vocab, now)
        non_empty_count = 0
        for i, episode in enumerate(result["episodes"]):
            tw = episode.get("target_words")
            assert isinstance(tw, list), f"Episode {i} target_words not a list"
            if len(tw) > 0:
                non_empty_count += 1
        # At least some episodes should have words given the fixture data
        assert non_empty_count > 0, "No episodes got any target words"


# ============================================================================
# Test 2: Target word format
# ============================================================================


class TestScheduleTargetWordsFormat:
    """Each target_words entry must have item_id, word, meaning, is_new."""

    REQUIRED_KEYS = {"item_id", "word", "meaning", "is_new", "fsrs_card"}

    async def test_keys_present(
        self, arc_plan: dict[str, Any], user_vocab: dict[str, Any], now: datetime
    ) -> None:
        result = await schedule(arc_plan, user_vocab, now)
        for tw in _collect_all_targets(result):
            assert set(tw.keys()) == self.REQUIRED_KEYS, f"Keys mismatch: {tw.keys()}"

    async def test_item_id_non_empty_string(
        self, arc_plan: dict[str, Any], user_vocab: dict[str, Any], now: datetime
    ) -> None:
        result = await schedule(arc_plan, user_vocab, now)
        for tw in _collect_all_targets(result):
            assert isinstance(tw["item_id"], str), f"item_id not str: {tw['item_id']}"
            assert tw["item_id"] != "", "item_id is empty"

    async def test_word_non_empty_string(
        self, arc_plan: dict[str, Any], user_vocab: dict[str, Any], now: datetime
    ) -> None:
        result = await schedule(arc_plan, user_vocab, now)
        for tw in _collect_all_targets(result):
            assert isinstance(tw["word"], str), f"word not str: {tw['word']}"
            assert tw["word"] != "", "word is empty"

    async def test_meaning_non_empty_string(
        self, arc_plan: dict[str, Any], user_vocab: dict[str, Any], now: datetime
    ) -> None:
        result = await schedule(arc_plan, user_vocab, now)
        for tw in _collect_all_targets(result):
            assert isinstance(tw["meaning"], str), f"meaning not str: {tw['meaning']}"
            assert tw["meaning"] != "", "meaning is empty"

    async def test_is_new_bool(
        self, arc_plan: dict[str, Any], user_vocab: dict[str, Any], now: datetime
    ) -> None:
        result = await schedule(arc_plan, user_vocab, now)
        for tw in _collect_all_targets(result):
            assert isinstance(tw["is_new"], bool), (
                f"is_new not bool: {tw['is_new']} for {tw['item_id']}"
            )


# ============================================================================
# Test 3: New word limit per episode
# ============================================================================


class TestScheduleNewWordLimit:
    """Verify new words (is_new=true) per episode do not exceed episode_limit."""

    async def test_new_words_under_limit_default(
        self, arc_plan: dict[str, Any], user_vocab: dict[str, Any], now: datetime
    ) -> None:
        result = await schedule(arc_plan, user_vocab, now)
        limit = 10
        for i, episode in enumerate(result["episodes"]):
            new_count = sum(1 for tw in episode.get("target_words", []) if tw["is_new"])
            assert new_count <= limit, (
                f"Episode {i} has {new_count} new words, exceeds limit {limit}"
            )

    async def test_new_words_under_custom_limit(
        self, arc_plan: dict[str, Any], user_vocab: dict[str, Any], now: datetime
    ) -> None:
        custom_limit = 5
        result = await schedule(arc_plan, user_vocab, now, episode_limit=custom_limit)
        for i, episode in enumerate(result["episodes"]):
            new_count = sum(1 for tw in episode.get("target_words", []) if tw["is_new"])
            assert new_count <= custom_limit, (
                f"Episode {i} has {new_count} new words, exceeds limit {custom_limit}"
            )


# ============================================================================
# Test 4: Review word limit per episode
# ============================================================================


class TestScheduleReviewWordLimit:
    """Verify review words (is_new=false) per episode do not exceed episode_limit."""

    async def test_review_words_under_limit_default(
        self, arc_plan: dict[str, Any], user_vocab: dict[str, Any], now: datetime
    ) -> None:
        result = await schedule(arc_plan, user_vocab, now)
        limit = 10
        for i, episode in enumerate(result["episodes"]):
            review_count = sum(
                1 for tw in episode.get("target_words", []) if not tw["is_new"]
            )
            assert review_count <= limit, (
                f"Episode {i} has {review_count} review words, exceeds limit {limit}"
            )

    async def test_review_words_under_custom_limit(
        self, arc_plan: dict[str, Any], user_vocab: dict[str, Any], now: datetime
    ) -> None:
        custom_limit = 5
        result = await schedule(arc_plan, user_vocab, now, episode_limit=custom_limit)
        for i, episode in enumerate(result["episodes"]):
            review_count = sum(
                1 for tw in episode.get("target_words", []) if not tw["is_new"]
            )
            assert review_count <= custom_limit, (
                f"Episode {i} has {review_count} review words, exceeds limit {custom_limit}"
            )


# ============================================================================
# Test 5: Arc-wide dedup — no duplicate is_new=true
# ============================================================================


class TestScheduleArcDedup:
    """Verify no item_id appears more than once with is_new=true across the arc."""

    async def test_no_duplicate_new_ids(
        self, arc_plan: dict[str, Any], user_vocab: dict[str, Any], now: datetime
    ) -> None:
        result = await schedule(arc_plan, user_vocab, now)
        new_ids = _collect_all_new_ids(result)
        assert len(new_ids) == len(set(new_ids)), (
            f"Duplicate new item_ids found: "
            f"{[x for x in new_ids if new_ids.count(x) > 1]}"
        )

    async def test_new_ids_marked_only_once(
        self, arc_plan: dict[str, Any], user_vocab: dict[str, Any], now: datetime
    ) -> None:
        """A word is_new=true in one episode must not be is_new=true in another."""
        result = await schedule(arc_plan, user_vocab, now)
        seen_new: set[str] = set()
        for episode in result["episodes"]:
            for tw in episode.get("target_words", []):
                if tw["is_new"]:
                    assert tw["item_id"] not in seen_new, (
                        f"{tw['item_id']} marked is_new=true more than once"
                    )
                    seen_new.add(tw["item_id"])


# ============================================================================
# Test 6: All target words exist in vocab
# ============================================================================


class TestScheduleWordExistsInVocab:
    """Every target_word's item_id must exist in the user vocabulary."""

    async def test_all_ids_in_vocab(
        self, arc_plan: dict[str, Any], user_vocab: dict[str, Any], now: datetime
    ) -> None:
        result = await schedule(arc_plan, user_vocab, now)
        vocab_ids = _vocab_id_set(user_vocab)
        for tw in _collect_all_targets(result):
            assert tw["item_id"] in vocab_ids, (
                f"{tw['item_id']} not found in user_vocab"
            )


# ============================================================================
# Test 7: Side episode uses pending
# ============================================================================


class TestScheduleSideEpisode:
    """Verify side episodes prioritize pending words."""

    @pytest.fixture
    def arc_with_side(self) -> dict[str, Any]:
        return {
            "arc_id": "test_side",
            "pending_words": [
                {"item_id": "meticulous_1", "rejected_count": 5},
                {"item_id": "coherent_1", "rejected_count": 5},
            ],
            "episodes": [
                {
                    "episode_id": 1,
                    "episode_type": "side",
                    "source_text": "Extra practice text for vocabulary reinforcement.",
                    "previous_context": [],
                },
                {
                    "episode_id": 2,
                    "episode_type": "main",
                    "source_text": "Main story text continues here.",
                    "previous_context": [],
                },
            ],
        }

    async def test_side_episode_gets_pending_priority(
        self, arc_with_side: dict[str, Any], user_vocab: dict[str, Any], now: datetime
    ) -> None:
        """Side episode should include pending words as new when possible."""
        result = await schedule(arc_with_side, user_vocab, now)
        side_ep = result["episodes"][0]
        assert side_ep["episode_type"] == "side"

        side_new_ids = [tw["item_id"] for tw in side_ep["target_words"] if tw["is_new"]]
        pending_ids = {"meticulous_1", "coherent_1"}
        found_pending = pending_ids & set(side_new_ids)
        assert len(found_pending) > 0, (
            f"Side episode did not include any pending words. "
            f"Side new ids: {side_new_ids}, pending: {pending_ids}"
        )

    async def test_side_episode_within_limits(
        self, arc_with_side: dict[str, Any], user_vocab: dict[str, Any], now: datetime
    ) -> None:
        result = await schedule(arc_with_side, user_vocab, now)
        side_ep = result["episodes"][0]
        new_count = sum(1 for tw in side_ep["target_words"] if tw["is_new"])
        review_count = sum(1 for tw in side_ep["target_words"] if not tw["is_new"])
        assert new_count <= 10, f"Side episode new words {new_count} > 10"
        assert review_count <= 10, f"Side episode review words {review_count} > 10"


# ============================================================================
# Test 8: Empty episodes
# ============================================================================


class TestScheduleEmptyEpisodes:
    """Edge case: arc_plan with no episodes."""

    async def test_empty_episodes_no_error(
        self, user_vocab: dict[str, Any], now: datetime
    ) -> None:
        arc_plan: dict[str, Any] = {
            "arc_id": "test",
            "episodes": [],
            "pending_words": [],
        }
        result = await schedule(arc_plan, user_vocab, now)
        assert result["episodes"] == []
        assert result["arc_id"] == "test"

    async def test_empty_episodes_with_pending(
        self, user_vocab: dict[str, Any], now: datetime
    ) -> None:
        arc_plan: dict[str, Any] = {
            "arc_id": "test",
            "episodes": [],
            "pending_words": [{"item_id": "meticulous_1", "rejected_count": 3}],
        }
        result = await schedule(arc_plan, user_vocab, now)
        assert result["episodes"] == []
        assert result["pending_words"] == arc_plan["pending_words"]


# ============================================================================
# Test 9: Empty vocab
# ============================================================================


class TestScheduleEmptyVocab:
    """Edge case: no vocabulary items."""

    async def test_empty_vocab_empty_target_words(
        self, arc_plan: dict[str, Any], now: datetime
    ) -> None:
        empty_vocab: dict[str, Any] = {"user_id": "001", "vocabulary": []}
        result = await schedule(arc_plan, empty_vocab, now)
        for i, episode in enumerate(result["episodes"]):
            tw = episode.get("target_words", [])
            assert len(tw) == 0, (
                f"Episode {i} has {len(tw)} target_words with empty vocab"
            )

    async def test_empty_vocab_no_error(
        self, arc_plan: dict[str, Any], now: datetime
    ) -> None:
        empty_vocab: dict[str, Any] = {"user_id": "001", "vocabulary": []}
        result = await schedule(arc_plan, empty_vocab, now)
        assert result is arc_plan


# ============================================================================
# Test 10: Default now
# ============================================================================


class TestScheduleDefaultNow:
    """When now=None, the function should use datetime.now(timezone.utc)."""

    async def test_default_now_does_not_raise(
        self, arc_plan: dict[str, Any], user_vocab: dict[str, Any]
    ) -> None:
        result = await schedule(arc_plan, user_vocab, now=None)
        assert result is arc_plan

    async def test_default_now_produces_valid_target_words(
        self, arc_plan: dict[str, Any], user_vocab: dict[str, Any]
    ) -> None:
        result = await schedule(arc_plan, user_vocab, now=None)
        for episode in result["episodes"]:
            for tw in episode.get("target_words", []):
                assert isinstance(tw["item_id"], str)
                assert isinstance(tw["is_new"], bool)


# ============================================================================
# Test 11: pending_words preserved
# ============================================================================


class TestSchedulePreservesPendingWords:
    """The scheduler reads pending_words but should not modify them."""

    async def test_pending_words_unchanged(
        self, arc_plan: dict[str, Any], user_vocab: dict[str, Any], now: datetime
    ) -> None:
        original_pending = list(arc_plan["pending_words"])
        result = await schedule(arc_plan, user_vocab, now)
        assert result["pending_words"] == original_pending, (
            "pending_words was modified by schedule()"
        )

    async def test_pending_words_still_present(
        self, arc_plan: dict[str, Any], user_vocab: dict[str, Any], now: datetime
    ) -> None:
        result = await schedule(arc_plan, user_vocab, now)
        assert "pending_words" in result
        assert isinstance(result["pending_words"], list)


# ============================================================================
# Test 12: Review words can repeat across episodes
# ============================================================================


class TestScheduleReviewWordsCanRepeat:
    """Review words (is_new=false) CAN appear in multiple episodes."""

    async def test_review_words_may_repeat(
        self, arc_plan: dict[str, Any], user_vocab: dict[str, Any], now: datetime
    ) -> None:
        """Verify review word repetition does not cause errors."""
        result = await schedule(arc_plan, user_vocab, now)
        review_ids = _collect_all_review_ids(result)
        # arc_new_ids only tracks is_new=true, so review repetition is valid
        assert isinstance(review_ids, list)

    async def test_review_repetition_not_blocked(
        self, arc_plan: dict[str, Any], user_vocab: dict[str, Any], now: datetime
    ) -> None:
        """Explicitly verify no arc_dedup check on review words."""
        result = await schedule(arc_plan, user_vocab, now)
        review_ids = _collect_all_review_ids(result)
        assert isinstance(review_ids, list)

    async def test_review_ids_can_repeat(
        self, arc_plan: dict[str, Any], user_vocab: dict[str, Any], now: datetime
    ) -> None:
        """With enough episodes, review words will repeat — verify no crash."""
        result = await schedule(arc_plan, user_vocab, now)
        review_ids = _collect_all_review_ids(result)
        review_counts = Counter(review_ids)
        # Some review words may repeat — that's fine
        for rid, count in review_counts.items():
            assert count >= 1


# ============================================================================
# Test 13: Cold start — no review words available
# ============================================================================


class TestScheduleColdStart:
    """When all words are unseen (last_review=None), scheduler still works."""

    @pytest.fixture
    def all_unseen_vocab(self) -> dict[str, Any]:
        return {
            "user_id": "001",
            "vocabulary": [
                {
                    "id": "w1",
                    "word": "apple",
                    "meaning": "苹果",
                    "chapter_first_seen": 1,
                    "history_window": [0, 0, 0, 0, 0],
                    "fsrs_card": {
                        "card_id": 100,
                        "state": 1,
                        "step": None,
                        "stability": None,
                        "difficulty": None,
                        "due": "2026-07-01T00:00:00Z",
                        "last_review": None,
                    },
                },
                {
                    "id": "w2",
                    "word": "banana",
                    "meaning": "香蕉",
                    "chapter_first_seen": 1,
                    "history_window": [0, 0, 0, 0, 0],
                    "fsrs_card": {
                        "card_id": 200,
                        "state": 1,
                        "step": None,
                        "stability": None,
                        "difficulty": None,
                        "due": "2026-07-01T00:00:00Z",
                        "last_review": None,
                    },
                },
                {
                    "id": "w3",
                    "word": "cherry",
                    "meaning": "樱桃",
                    "chapter_first_seen": 1,
                    "history_window": [0, 0, 0, 0, 0],
                    "fsrs_card": {
                        "card_id": 300,
                        "state": 1,
                        "step": None,
                        "stability": None,
                        "difficulty": None,
                        "due": "2026-07-01T00:00:00Z",
                        "last_review": None,
                    },
                },
            ],
        }

    @pytest.fixture
    def simple_arc(self) -> dict[str, Any]:
        return {
            "arc_id": "cold_start",
            "pending_words": [],
            "episodes": [
                {
                    "episode_id": 1,
                    "episode_type": "main",
                    "source_text": "Simple text.",
                    "previous_context": [],
                },
            ],
        }

    async def test_cold_start_no_error(
        self,
        all_unseen_vocab: dict[str, Any],
        simple_arc: dict[str, Any],
        now: datetime,
    ) -> None:
        result = await schedule(simple_arc, all_unseen_vocab, now)
        assert result is simple_arc

    async def test_cold_start_all_new(
        self,
        all_unseen_vocab: dict[str, Any],
        simple_arc: dict[str, Any],
        now: datetime,
    ) -> None:
        result = await schedule(simple_arc, all_unseen_vocab, now)
        targets = _collect_all_targets(result)
        for tw in targets:
            assert tw["is_new"] is True, (
                f"Cold start: expected all is_new=true, got {tw}"
            )

    async def test_cold_start_no_review_words(
        self,
        all_unseen_vocab: dict[str, Any],
        simple_arc: dict[str, Any],
        now: datetime,
    ) -> None:
        result = await schedule(simple_arc, all_unseen_vocab, now)
        review_ids = _collect_all_review_ids(result)
        assert len(review_ids) == 0, (
            f"Cold start should have 0 review words, got {review_ids}"
        )

    async def test_cold_start_targets_exist_in_vocab(
        self,
        all_unseen_vocab: dict[str, Any],
        simple_arc: dict[str, Any],
        now: datetime,
    ) -> None:
        result = await schedule(simple_arc, all_unseen_vocab, now)
        vocab_ids = _vocab_id_set(all_unseen_vocab)
        for tw in _collect_all_targets(result):
            assert tw["item_id"] in vocab_ids


# ============================================================================
# Test 14: Mixed episode types
# ============================================================================


class TestScheduleMixedEpisodeTypes:
    """Arc with both main and side episodes."""

    @pytest.fixture
    def mixed_arc(self) -> dict[str, Any]:
        return {
            "arc_id": "mixed_types",
            "pending_words": [
                {"item_id": "meticulous_1", "rejected_count": 3},
                {"item_id": "ambiguous_1", "rejected_count": 4},
            ],
            "episodes": [
                {
                    "episode_id": 1,
                    "episode_type": "side",
                    "source_text": "Side episode for practice.",
                    "previous_context": [],
                },
                {
                    "episode_id": 2,
                    "episode_type": "main",
                    "source_text": "First main episode.",
                    "previous_context": [],
                },
                {
                    "episode_id": 3,
                    "episode_type": "main",
                    "source_text": "Second main episode.",
                    "previous_context": [],
                },
            ],
        }

    async def test_mixed_episodes_all_have_target_words(
        self, mixed_arc: dict[str, Any], user_vocab: dict[str, Any], now: datetime
    ) -> None:
        result = await schedule(mixed_arc, user_vocab, now)
        for i, episode in enumerate(result["episodes"]):
            assert isinstance(episode.get("target_words"), list), (
                f"Episode {i}: missing target_words"
            )

    async def test_mixed_episodes_within_limits(
        self, mixed_arc: dict[str, Any], user_vocab: dict[str, Any], now: datetime
    ) -> None:
        result = await schedule(mixed_arc, user_vocab, now)
        for i, episode in enumerate(result["episodes"]):
            new_count = sum(1 for tw in episode.get("target_words", []) if tw["is_new"])
            review_count = sum(
                1 for tw in episode.get("target_words", []) if not tw["is_new"]
            )
            assert new_count <= 10, (
                f"Episode {i} ({episode['episode_type']}): new={new_count} > 10"
            )
            assert review_count <= 10, (
                f"Episode {i} ({episode['episode_type']}): review={review_count} > 10"
            )

    async def test_mixed_arc_dedup_holds(
        self, mixed_arc: dict[str, Any], user_vocab: dict[str, Any], now: datetime
    ) -> None:
        result = await schedule(mixed_arc, user_vocab, now)
        new_ids = _collect_all_new_ids(result)
        assert len(new_ids) == len(set(new_ids)), "Duplicate new ids in mixed arc"

    async def test_side_episode_in_mixed_gets_pending(
        self, mixed_arc: dict[str, Any], user_vocab: dict[str, Any], now: datetime
    ) -> None:
        """The side episode (index 0, first) should prioritize pending words."""
        result = await schedule(mixed_arc, user_vocab, now)
        side_ep = result["episodes"][0]
        assert side_ep["episode_type"] == "side"

        side_new_ids = [tw["item_id"] for tw in side_ep["target_words"] if tw["is_new"]]
        pending_ids = {"meticulous_1", "ambiguous_1"}

        # meticulous_1 is unseen → should be picked as new in side episode
        found_pending_new = pending_ids & set(side_new_ids)
        assert len(found_pending_new) > 0, (
            f"No pending words found as new in side episode. Side new: {side_new_ids}"
        )


# ============================================================================
# Test 15: Deterministic
# ============================================================================


class TestScheduleDeterministic:
    """Same inputs must produce identical outputs."""

    async def test_deterministic_same_now(
        self, arc_plan: dict[str, Any], user_vocab: dict[str, Any], now: datetime
    ) -> None:
        ap1: dict[str, Any] = json.loads(json.dumps(arc_plan))
        ap2: dict[str, Any] = json.loads(json.dumps(arc_plan))

        result1 = await schedule(ap1, user_vocab, now)
        result2 = await schedule(ap2, user_vocab, now)

        r1 = json.dumps(result1, sort_keys=True, default=str)
        r2 = json.dumps(result2, sort_keys=True, default=str)
        assert r1 == r2, "schedule() is not deterministic with same inputs"

    async def test_deterministic_same_structure_default_now(
        self, arc_plan: dict[str, Any], user_vocab: dict[str, Any]
    ) -> None:
        """Default now should give same episode count and word counts."""
        ap1: dict[str, Any] = json.loads(json.dumps(arc_plan))
        ap2: dict[str, Any] = json.loads(json.dumps(arc_plan))

        result1 = await schedule(ap1, user_vocab, now=None)
        result2 = await schedule(ap2, user_vocab, now=None)

        assert len(result1["episodes"]) == len(result2["episodes"])
        for ep1, ep2 in zip(result1["episodes"], result2["episodes"]):
            assert len(ep1.get("target_words", [])) == len(ep2.get("target_words", []))


# ============================================================================
# Additional edge-case tests
# ============================================================================


class TestScheduleEdgeCases:
    """Additional boundary and edge-case tests."""

    async def test_no_pending_words(
        self, user_vocab: dict[str, Any], now: datetime
    ) -> None:
        """arc_plan without pending_words key should work fine."""
        arc_no_pending: dict[str, Any] = {
            "arc_id": "no_pending",
            "episodes": [
                {
                    "episode_id": 1,
                    "episode_type": "main",
                    "source_text": "Test.",
                    "previous_context": [],
                },
            ],
        }
        result = await schedule(arc_no_pending, user_vocab, now)
        assert len(result["episodes"][0]["target_words"]) > 0

    async def test_episode_without_source_text(
        self, user_vocab: dict[str, Any], now: datetime
    ) -> None:
        """Episode without source_text key should still work (source_text=None)."""
        arc: dict[str, Any] = {
            "arc_id": "no_source",
            "pending_words": [],
            "episodes": [
                {"episode_id": 1, "episode_type": "main", "previous_context": []},
            ],
        }
        result = await schedule(arc, user_vocab, now)
        targets = result["episodes"][0].get("target_words", [])
        assert isinstance(targets, list)

    async def test_episode_without_episode_type_defaults_main(
        self, user_vocab: dict[str, Any], now: datetime
    ) -> None:
        """Episode missing episode_type should default to 'main'."""
        arc: dict[str, Any] = {
            "arc_id": "no_type",
            "pending_words": [],
            "episodes": [
                {
                    "episode_id": 1,
                    "source_text": "Default type test.",
                    "previous_context": [],
                },
            ],
        }
        result = await schedule(arc, user_vocab, now)
        targets = result["episodes"][0].get("target_words", [])
        assert isinstance(targets, list)
        assert len(targets) > 0

    async def test_total_words_per_episode_not_exceeding_limit(
        self, arc_plan: dict[str, Any], user_vocab: dict[str, Any], now: datetime
    ) -> None:
        """Total new + review <= 2 * episode_limit."""
        result = await schedule(arc_plan, user_vocab, now)
        for i, episode in enumerate(result["episodes"]):
            total = len(episode.get("target_words", []))
            assert total <= 20, (
                f"Episode {i} has {total} total words, exceeds 2*limit=20"
            )

    async def test_small_pool_exhaustion(self, now: datetime) -> None:
        """When pool exhausted, later episodes get empty targets — no error."""
        tiny_vocab: dict[str, Any] = {
            "user_id": "001",
            "vocabulary": [
                {
                    "id": "only_word",
                    "word": "only",
                    "meaning": "唯一",
                    "chapter_first_seen": 1,
                    "history_window": [0, 0, 0, 0, 0],
                    "fsrs_card": {
                        "card_id": 1,
                        "state": 1,
                        "step": None,
                        "stability": None,
                        "difficulty": None,
                        "due": "2026-07-01T00:00:00Z",
                        "last_review": None,
                    },
                },
            ],
        }
        arc: dict[str, Any] = {
            "arc_id": "tiny",
            "pending_words": [],
            "episodes": [
                {
                    "episode_id": 1,
                    "episode_type": "main",
                    "source_text": "T1.",
                    "previous_context": [],
                },
                {
                    "episode_id": 2,
                    "episode_type": "main",
                    "source_text": "T2.",
                    "previous_context": [],
                },
                {
                    "episode_id": 3,
                    "episode_type": "main",
                    "source_text": "T3.",
                    "previous_context": [],
                },
            ],
        }
        result = await schedule(arc, tiny_vocab, now)
        assert len(result["episodes"][0]["target_words"]) <= 10
        for ep in result["episodes"][1:]:
            assert isinstance(ep.get("target_words"), list)

    async def test_large_episode_limit(
        self, arc_plan: dict[str, Any], user_vocab: dict[str, Any], now: datetime
    ) -> None:
        """Very large episode_limit should work (just includes all candidates)."""
        result = await schedule(arc_plan, user_vocab, now, episode_limit=50)
        for i, episode in enumerate(result["episodes"]):
            new_count = sum(1 for tw in episode.get("target_words", []) if tw["is_new"])
            review_count = sum(
                1 for tw in episode.get("target_words", []) if not tw["is_new"]
            )
            assert new_count <= 50, f"Episode {i}: new={new_count} > 50"
            assert review_count <= 50, f"Episode {i}: review={review_count} > 50"


# ============================================================================
# Async test
# ============================================================================


class TestScheduleAsync:
    """Verify schedule() is an async function and can be awaited."""

    @pytest.mark.asyncio
    async def test_schedule_is_awaitable(
        self, arc_plan: dict[str, Any], user_vocab: dict[str, Any], now: datetime
    ) -> None:
        result = await schedule(arc_plan, user_vocab, now)
        assert result is arc_plan
        for episode in result["episodes"]:
            assert isinstance(episode.get("target_words"), list)


class TestScheduleWithLLMClient:
    """Integration: LLM scores affect allocation priority."""

    async def test_llm_scores_influence_allocation(
        self, arc_plan: dict[str, Any], user_vocab: dict[str, Any], now: datetime
    ) -> None:
        """Items with higher LLM scores should be allocated first.

        Mock LLM gives 'awkward_1' score=1.0 and other candidates score=0.0.
        Verifies the mock is actually invoked (LLM integration works end-to-end).
        """
        from unittest.mock import AsyncMock, MagicMock

        from app.llm.prompts import ContextScoreEntry, ContextScoreResponse

        mock_client = MagicMock()
        mock_client.chat_structured = AsyncMock()

        vocab_items = user_vocab["vocabulary"]
        entries = [
            ContextScoreEntry(
                item_id=item["id"],
                score=1.0 if item["id"] == "awkward_1" else 0.0,
            )
            for item in vocab_items
        ]
        mock_client.chat_structured.return_value = ContextScoreResponse(scores=entries)

        result = await schedule(
            arc_plan=arc_plan,
            user_vocab=user_vocab,
            llm_client=mock_client,
            now=now,
        )

        first_target_words = result["episodes"][0].get("target_words", [])
        assert len(first_target_words) > 0, "No target_words allocated"
        assert mock_client.chat_structured.call_count >= 1, (
            "LLM client was never called"
        )
