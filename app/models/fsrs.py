"""Pydantic v2 model for FSRS flashcard state, with fsrs.Card interop.

Ref: AGENTS.md §12 (FsrsCard) and documents/BACKEND_IN_OUT.md §三.1.
"""

import datetime
from typing import Any

from fsrs import Card, State
from pydantic import BaseModel, Field, field_serializer, field_validator


class FsrsCard(BaseModel):
    """A Pydantic v2 wrapper around an FSRS flashcard state.

    Fields map 1:1 to fsrs.Card, enabling interop via to_fsrs_card() / from_fsrs_card().
    """

    model_config = {
        "json_encoders": {datetime.datetime: lambda v: v.isoformat()},
    }

    card_id: int = Field(
        default_factory=lambda: int(
            datetime.datetime.now(datetime.timezone.utc).timestamp() * 1000
        )
    )
    state: int = Field(ge=1, le=3, description="1=Learning, 2=Review, 3=Relearning")
    step: int | None = None
    stability: float | None = None
    difficulty: float | None = None
    due: datetime.datetime
    last_review: datetime.datetime | None = None

    @field_validator("due", mode="before")
    @classmethod
    def _coerce_due(cls, v: Any) -> datetime.datetime:
        """Coerce due to timezone-aware UTC datetime.

        Accepts ISO-format strings (from Card.to_dict()) and datetime objects.
        Handles Python 3.10 compatibility: replaces 'Z' suffix with '+00:00'.
        """
        if isinstance(v, str):
            # Python 3.10 fromisoformat() rejects 'Z' suffix
            v = v.replace("Z", "+00:00")
            v = datetime.datetime.fromisoformat(v)
        if v.tzinfo is None:
            raise ValueError("due must be timezone-aware")
        return v

    @field_validator("last_review", mode="before")
    @classmethod
    def _coerce_last_review(cls, v: Any) -> datetime.datetime | None:
        """Coerce last_review to timezone-aware UTC datetime or None.

        Accepts ISO-format strings, datetime objects, and None.
        Handles Python 3.10 compatibility: replaces 'Z' suffix with '+00:00'.
        """
        if v is None:
            return None
        if isinstance(v, str):
            # Python 3.10 fromisoformat() rejects 'Z' suffix
            v = v.replace("Z", "+00:00")
            v = datetime.datetime.fromisoformat(v)
        if v.tzinfo is None:
            raise ValueError("last_review must be timezone-aware when provided")
        return v

    @field_serializer("due")
    def _serialize_due(self, v: datetime.datetime) -> str:
        """Serialize due to ISO 8601 string."""
        return v.isoformat()

    @field_serializer("last_review")
    def _serialize_last_review(self, v: datetime.datetime | None) -> str | None:
        """Serialize last_review to ISO 8601 string or None."""
        return v.isoformat() if v is not None else None

    def to_fsrs_card(self) -> Card:
        """Convert this FsrsCard to a native fsrs.Card.

        Returns:
            fsrs.Card with all fields mapped. State is wrapped via State(int).
        """
        return Card(
            card_id=self.card_id,
            state=State(self.state),
            step=self.step,
            stability=self.stability,
            difficulty=self.difficulty,
            due=self.due,
            last_review=self.last_review,
        )

    @classmethod
    def from_fsrs_card(cls, card: Card) -> "FsrsCard":
        """Create an FsrsCard from a native fsrs.Card.

        Args:
            card: An fsrs.Card instance.

        Returns:
            FsrsCard with fields populated from the card's to_dict().
        """
        return cls.model_validate(card.to_dict())


__all__ = ["FsrsCard"]
