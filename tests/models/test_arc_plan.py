"""Tests for app.models.arc_plan — PendingWord, EpisodeSlot, ArcPlan."""

import datetime

import pytest
from pydantic import ValidationError

from app.models.arc_plan import ArcPlan, EpisodeSlot, PendingWord, TargetWord
from app.models.fsrs import FsrsCard


class TestPendingWord:
    """Tests for PendingWord model."""

    def test_valid_minimal(self) -> None:
        """PendingWord(item_id='awkward_1', rejected_count=0) should validate."""
        pw = PendingWord(item_id="awkward_1", rejected_count=0)
        assert pw.item_id == "awkward_1"
        assert pw.rejected_count == 0

    def test_negative_rejected_raises(self) -> None:
        """PendingWord(item_id='x', rejected_count=-1) should raise ValidationError."""
        with pytest.raises(ValidationError):
            PendingWord(item_id="x", rejected_count=-1)

    def test_default_rejected_is_zero(self) -> None:
        """PendingWord(item_id='x') should default rejected_count to 0."""
        pw = PendingWord(item_id="x")
        assert pw.rejected_count == 0

    def test_rejected_count_ge_zero_constraint(self) -> None:
        """Field constraint rejected_count >= 0 enforced."""
        with pytest.raises(ValidationError):
            PendingWord(item_id="x", rejected_count=-5)


class TestTargetWord:
    """Tests for TargetWord model."""

    def test_valid(self) -> None:
        """TargetWord with all required fields validates."""
        tw = TargetWord(
            item_id="consume_1",
            word="consuming",
            meaning="消耗",
            is_new=True,
        )
        assert tw.item_id == "consume_1"
        assert tw.word == "consuming"
        assert tw.meaning == "消耗"
        assert tw.is_new is True

    def test_missing_required_raises(self) -> None:
        """TargetWord without required fields raises ValidationError."""
        with pytest.raises(ValidationError):
            TargetWord(item_id="x", word="foo")  # type: ignore[call-arg]

    def test_is_new_false(self) -> None:
        """TargetWord with is_new=False validates."""
        tw = TargetWord(
            item_id="known_1",
            word="known",
            meaning="已知",
            is_new=False,
        )
        assert tw.is_new is False

    def test_fsrs_card_default_none(self) -> None:
        """TargetWord without fsrs_card should default to None."""
        tw = TargetWord(
            item_id="known_1",
            word="known",
            meaning="已知",
            is_new=False,
        )
        assert tw.fsrs_card is None

    def test_with_fsrs_card(self) -> None:
        """TargetWord with a valid FsrsCard should store it."""
        card = FsrsCard(
            state=2,
            due=datetime.datetime(2026, 6, 10, tzinfo=datetime.timezone.utc),
            stability=3.5,
            difficulty=0.8,
        )
        tw = TargetWord(
            item_id="whisper_1",
            word="whisper",
            meaning="耳语",
            is_new=False,
            fsrs_card=card,
        )
        assert tw.fsrs_card is not None
        assert tw.fsrs_card.state == 2
        assert tw.fsrs_card.stability == 3.5

    def test_fsrs_card_roundtrip(self) -> None:
        """TargetWord with FsrsCard survives model_dump → model_validate roundtrip."""
        card = FsrsCard(
            state=1,
            due=datetime.datetime(2026, 6, 15, tzinfo=datetime.timezone.utc),
            stability=1.2,
            difficulty=0.5,
            step=0,
        )
        tw = TargetWord(
            item_id="consume_1",
            word="consuming",
            meaning="消耗",
            is_new=True,
            fsrs_card=card,
        )
        dumped = tw.model_dump()
        reloaded = TargetWord.model_validate(dumped)
        assert reloaded.fsrs_card is not None
        assert reloaded.fsrs_card.state == 1
        assert reloaded.fsrs_card.stability == 1.2


class TestEpisodeSlot:
    """Tests for EpisodeSlot model."""

    def test_valid_minimal(self) -> None:
        """EpisodeSlot with minimal required fields validates."""
        slot = EpisodeSlot(
            episode_id=1,
            episode_type="main",
            source_text="Hello world.",
            previous_context=[],
            target_words=[],
        )
        assert slot.episode_id == 1
        assert slot.episode_type == "main"
        assert slot.source_text == "Hello world."
        assert slot.previous_context == []
        assert slot.target_words == []

    def test_invalid_episode_type_raises(self) -> None:
        """EpisodeSlot(episode_type='bonus') should raise ValidationError."""
        with pytest.raises(ValidationError):
            EpisodeSlot(
                episode_id=1,
                episode_type="bonus",
                source_text="Hello.",
                previous_context=[],
                target_words=[],
            )

    def test_side_episode_source_text_none(self) -> None:
        """EpisodeSlot with episode_type='side' and source_text=None should validate."""
        slot = EpisodeSlot(
            episode_id=2,
            episode_type="side",
            source_text=None,
            previous_context=[],
            target_words=[],
        )
        assert slot.episode_type == "side"
        assert slot.source_text is None


class TestArcPlan:
    """Tests for ArcPlan model."""

    def test_valid_full(self) -> None:
        """Full ArcPlan with arc_id, episodes, pending_words validates."""
        data = {
            "arc_id": "arc_003",
            "pending_words": [
                {"item_id": "meticulous_1", "rejected_count": 3},
                {"item_id": "coherent_1", "rejected_count": 3},
            ],
            "episodes": [
                {
                    "episode_id": 21,
                    "episode_type": "main",
                    "source_text": "The classroom buzzed...",
                    "previous_context": [],
                    "target_words": [],
                },
                {
                    "episode_id": 22,
                    "episode_type": "main",
                    "source_text": "Anna leaned across...",
                    "previous_context": [
                        {"name": "Anna", "text": "Hey, new guy."},
                    ],
                    "target_words": [
                        {
                            "item_id": "footstep_1",
                            "word": "footstep",
                            "meaning": "脚步",
                            "is_new": False,
                        },
                    ],
                },
            ],
        }
        plan = ArcPlan.model_validate(data)
        assert plan.arc_id == "arc_003"
        assert len(plan.pending_words) == 2
        assert len(plan.episodes) == 2
        assert plan.episodes[0].episode_id == 21
        assert plan.episodes[1].previous_context[0]["name"] == "Anna"

    def test_empty_episodes(self) -> None:
        """ArcPlan(arc_id='arc_001', episodes=[]) should validate (partial arc OK)."""
        plan = ArcPlan(arc_id="arc_001", episodes=[])
        assert plan.arc_id == "arc_001"
        assert plan.episodes == []
        assert plan.pending_words == []

    def test_serialize_deserialize_roundtrip(self) -> None:
        """ArcPlan dump → dict → reload produces equal model."""
        plan = ArcPlan(
            arc_id="arc_005",
            pending_words=[
                PendingWord(item_id="reluctant_1", rejected_count=3),
                PendingWord(item_id="resonate_1"),
            ],
            episodes=[
                EpisodeSlot(
                    episode_id=10,
                    episode_type="side",
                    source_text=None,
                    previous_context=[],
                    target_words=[],
                ),
            ],
        )
        dumped = plan.model_dump()
        reloaded = ArcPlan.model_validate(dumped)
        assert reloaded.arc_id == plan.arc_id
        assert len(reloaded.episodes) == len(plan.episodes)
        assert reloaded.episodes[0].episode_type == "side"
        assert reloaded.episodes[0].source_text is None
        assert len(reloaded.pending_words) == len(plan.pending_words)
        assert reloaded.pending_words[0].rejected_count == 3

    def test_validate_from_fixture(self) -> None:
        """ArcPlan can validate from prev_arc_plan.json fixture data (with str arc_id)."""
        import json
        from pathlib import Path

        fixture_path = Path(__file__).parent.parent / "fixtures" / "prev_arc_plan.json"
        data = json.loads(fixture_path.read_text(encoding="utf-8"))
        # Fixture uses int arc_id; convert to str for model validation
        data["arc_id"] = str(data["arc_id"])
        plan = ArcPlan.model_validate(data)
        assert len(plan.episodes) == 10
        assert plan.episodes[0].episode_type == "main"
        assert len(plan.pending_words) == 6

    def test_source_text_required_for_main(self) -> None:
        """Main episode without source_text (None) should still validate (source_text is optional)."""
        slot = EpisodeSlot(
            episode_id=1,
            episode_type="main",
            source_text=None,
            previous_context=[],
            target_words=[],
        )
        assert slot.source_text is None
