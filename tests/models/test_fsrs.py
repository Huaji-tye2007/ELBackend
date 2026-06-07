"""Tests for app.models.fsrs — FsrsCard model with fsrs.Card interop."""

import datetime

import pytest
from fsrs import Card, State
from pydantic import ValidationError

from app.models.fsrs import FsrsCard


class TestFsrsCard:
    """Tests for FsrsCard model."""

    def test_valid_minimal(self) -> None:
        """FsrsCard with minimal required fields (state=1, due) should validate."""
        now = datetime.datetime.now(datetime.timezone.utc)
        card = FsrsCard(state=1, due=now)
        assert card.state == 1
        assert card.due == now
        assert card.card_id is not None
        assert isinstance(card.card_id, int)
        assert card.step is None
        assert card.stability is None
        assert card.difficulty is None
        assert card.last_review is None

    def test_valid_full(self) -> None:
        """FsrsCard with all fields populated should validate."""
        now = datetime.datetime.now(datetime.timezone.utc)
        card = FsrsCard(
            card_id=1234567890,
            state=2,
            step=5,
            stability=3.14,
            difficulty=0.8,
            due=now,
            last_review=now - datetime.timedelta(days=1),
        )
        assert card.card_id == 1234567890
        assert card.state == 2
        assert card.step == 5
        assert card.stability == 3.14
        assert card.difficulty == 0.8
        assert card.due == now
        assert card.last_review == now - datetime.timedelta(days=1)

    def test_invalid_state_too_high(self) -> None:
        """FsrsCard(state=4) should raise ValidationError (state 1-3 only)."""
        now = datetime.datetime.now(datetime.timezone.utc)
        with pytest.raises(ValidationError):
            FsrsCard(state=4, due=now)

    def test_invalid_state_zero(self) -> None:
        """FsrsCard(state=0) should raise ValidationError (state 1-3 only)."""
        now = datetime.datetime.now(datetime.timezone.utc)
        with pytest.raises(ValidationError):
            FsrsCard(state=0, due=now)

    def test_invalid_state_negative(self) -> None:
        """FsrsCard(state=-1) should raise ValidationError."""
        now = datetime.datetime.now(datetime.timezone.utc)
        with pytest.raises(ValidationError):
            FsrsCard(state=-1, due=now)

    def test_state_learning(self) -> None:
        """FsrsCard(state=1) maps to State.Learning."""
        now = datetime.datetime.now(datetime.timezone.utc)
        card = FsrsCard(state=1, due=now)
        assert card.state == 1

    def test_state_review(self) -> None:
        """FsrsCard(state=2) maps to State.Review."""
        now = datetime.datetime.now(datetime.timezone.utc)
        card = FsrsCard(state=2, due=now)
        assert card.state == 2

    def test_state_relearning(self) -> None:
        """FsrsCard(state=3) maps to State.Relearning."""
        now = datetime.datetime.now(datetime.timezone.utc)
        card = FsrsCard(state=3, due=now)
        assert card.state == 3

    def test_card_id_auto_generated(self) -> None:
        """FsrsCard without explicit card_id should auto-generate a millisecond timestamp."""
        now = datetime.datetime.now(datetime.timezone.utc)
        card = FsrsCard(state=1, due=now)
        assert card.card_id is not None
        assert isinstance(card.card_id, int)
        # Should be a realistic millisecond timestamp (> year 2020)
        assert card.card_id > 1577836800000  # 2020-01-01 in ms

    def test_due_must_have_timezone(self) -> None:
        """FsrsCard.due should be timezone-aware (UTC)."""
        now_utc = datetime.datetime.now(datetime.timezone.utc)
        card = FsrsCard(state=1, due=now_utc)
        assert card.due.tzinfo is not None
        assert card.due.tzinfo == datetime.timezone.utc

    def test_last_review_accepts_timezone_aware(self) -> None:
        """FsrsCard.last_review with UTC datetime should validate."""
        now = datetime.datetime.now(datetime.timezone.utc)
        past = now - datetime.timedelta(days=7)
        card = FsrsCard(state=2, due=now, last_review=past)
        assert card.last_review == past
        assert card.last_review.tzinfo is not None

    def test_to_fsrs_card_learning_state(self) -> None:
        """to_fsrs_card() should produce fsrs.Card with State.Learning when state=1."""
        now = datetime.datetime.now(datetime.timezone.utc)
        card = FsrsCard(
            card_id=100,
            state=1,
            step=0,
            stability=None,
            difficulty=None,
            due=now,
            last_review=None,
        )
        fsrs_card = card.to_fsrs_card()
        assert isinstance(fsrs_card, Card)
        assert fsrs_card.state == State.Learning
        assert fsrs_card.card_id == 100
        assert fsrs_card.step == 0
        assert fsrs_card.stability is None
        assert fsrs_card.difficulty is None
        assert fsrs_card.last_review is None

    def test_to_fsrs_card_review_state(self) -> None:
        """to_fsrs_card() with state=2 produces Card with State.Review."""
        now = datetime.datetime.now(datetime.timezone.utc)
        card = FsrsCard(
            card_id=200,
            state=2,
            step=None,
            stability=5.0,
            difficulty=0.5,
            due=now,
            last_review=now - datetime.timedelta(days=3),
        )
        fsrs_card = card.to_fsrs_card()
        assert isinstance(fsrs_card, Card)
        assert fsrs_card.state == State.Review
        assert fsrs_card.card_id == 200
        assert fsrs_card.stability == 5.0
        assert fsrs_card.difficulty == 0.5

    def test_to_fsrs_card_relearning_state(self) -> None:
        """to_fsrs_card() with state=3 produces Card with State.Relearning."""
        now = datetime.datetime.now(datetime.timezone.utc)
        card = FsrsCard(
            card_id=300,
            state=3,
            step=2,
            stability=2.0,
            difficulty=0.7,
            due=now,
            last_review=now - datetime.timedelta(hours=6),
        )
        fsrs_card = card.to_fsrs_card()
        assert isinstance(fsrs_card, Card)
        assert fsrs_card.state == State.Relearning
        assert fsrs_card.step == 2

    def test_to_fsrs_card_auto_generates_card_id(self) -> None:
        """to_fsrs_card() should auto-generate card_id if not set, using ms timestamp."""
        now = datetime.datetime.now(datetime.timezone.utc)
        card = FsrsCard(state=1, due=now)
        fsrs_card = card.to_fsrs_card()
        assert fsrs_card.card_id is not None
        assert fsrs_card.card_id > 1577836800000

    def test_from_fsrs_card_roundtrip(self) -> None:
        """FsrsCard.from_fsrs_card(Card(...)) → FsrsCard should preserve all fields."""
        now = datetime.datetime.now(datetime.timezone.utc)
        past = now - datetime.timedelta(days=5)
        original = Card(
            card_id=42,
            state=State.Review,
            step=None,
            stability=4.5,
            difficulty=0.3,
            due=now,
            last_review=past,
        )
        model = FsrsCard.from_fsrs_card(original)
        assert model.card_id == 42
        assert model.state == 2  # State.Review.value
        assert model.step is None
        assert model.stability == 4.5
        assert model.difficulty == 0.3
        assert model.last_review == past

    def test_roundtrip_full_cycle(self) -> None:
        """FsrsCard → to_fsrs_card() → dict should match original Card dict."""
        now = datetime.datetime.now(datetime.timezone.utc)
        past = now - datetime.timedelta(days=10)
        original = Card(
            card_id=999,
            state=State.Learning,
            step=0,
            stability=None,
            difficulty=None,
            due=now,
            last_review=past,
        )
        model = FsrsCard.from_fsrs_card(original)
        roundtripped = model.to_fsrs_card()
        assert roundtripped.card_id == original.card_id
        assert roundtripped.state == original.state
        assert roundtripped.step == original.step
        assert roundtripped.stability == original.stability
        assert roundtripped.difficulty == original.difficulty
        # Compare dict representations for due/last_review (datetime precision)
        assert roundtripped.to_dict() == original.to_dict()

    def test_from_fsrs_card_with_none_last_review(self) -> None:
        """FsrsCard.from_fsrs_card() with last_review=None should work."""
        now = datetime.datetime.now(datetime.timezone.utc)
        original = Card(
            card_id=1,
            state=State.Learning,
            step=0,
            stability=None,
            difficulty=None,
            due=now,
            last_review=None,
        )
        model = FsrsCard.from_fsrs_card(original)
        assert model.last_review is None

    def test_model_dump_json_serializable(self) -> None:
        """FsrsCard.model_dump() should produce JSON-serializable datetime strings."""
        now = datetime.datetime.now(datetime.timezone.utc)
        card = FsrsCard(state=2, due=now, last_review=now - datetime.timedelta(days=1))
        data = card.model_dump()
        assert isinstance(data["due"], str)
        assert isinstance(data["last_review"], str)
        # Verify ISO 8601 format
        datetime.datetime.fromisoformat(data["due"])
        datetime.datetime.fromisoformat(data["last_review"])

    def test_model_dump_json_stability_and_difficulty_none(self) -> None:
        """model_dump() with stability=None, difficulty=None should output nulls."""
        now = datetime.datetime.now(datetime.timezone.utc)
        card = FsrsCard(state=1, due=now)
        data = card.model_dump()
        assert data["stability"] is None
        assert data["difficulty"] is None

    def test_card_id_can_be_explicit(self) -> None:
        """FsrsCard(card_id=55555, ...) should preserve explicit card_id."""
        now = datetime.datetime.now(datetime.timezone.utc)
        card = FsrsCard(card_id=55555, state=2, due=now)
        assert card.card_id == 55555
