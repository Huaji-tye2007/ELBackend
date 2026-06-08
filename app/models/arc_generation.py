"""Pydantic v2 model for Arc generation state machine checkpoint.

Ref: AGENTS.md §12 (ArcGenerationState) and §14 (Async Architecture).
"""

import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, computed_field, field_serializer, field_validator

# Eight phases of the Arc generation state machine.
Phase = Literal[
    "IDLE",
    "PLANNING",
    "SCHEDULING",
    "GENERATING",
    "ANNOTATING",
    "FORMATTING",
    "COMPLETE",
    "FAILED",
]


class ArcGenerationState(BaseModel):
    """Checkpoint for the persistent Arc generation state machine.

    Written atomically to data/arc_generation_state.json after each phase transition.
    Public API exposed via GET /api/v1/arc/status.
    """

    arc_id: str
    phase: Phase
    progress: dict[str, int] = Field(
        default_factory=lambda: {"current": 0, "total": 0},
        description="current/total counters (e.g. episode index, total episodes)",
    )
    retry_count: int = Field(
        default=0, ge=0, description="Number of retries attempted for current phase"
    )
    intermediate_data: dict | None = Field(
        default=None,
        description="Serialized intermediate pipeline results for crash-resume support",
    )
    last_error: str | None = Field(
        default=None, description="Last error message, if phase is FAILED"
    )
    started_at: datetime.datetime | None = Field(
        default=None, description="When generation started (UTC)"
    )
    updated_at: datetime.datetime = Field(
        default_factory=lambda: datetime.datetime.now(datetime.timezone.utc),
        description="Last checkpoint write timestamp (UTC)",
    )

    # ── datetime coercion ──────────────────────────────────────────

    @field_validator("started_at", mode="before")
    @classmethod
    def _coerce_started_at(cls, v: Any) -> datetime.datetime | None:
        """Coerce started_at to timezone-aware UTC datetime or None."""
        if v is None:
            return None
        if isinstance(v, str):
            v = datetime.datetime.fromisoformat(v)
        if v.tzinfo is None:
            raise ValueError("started_at must be timezone-aware when provided")
        return v

    @field_validator("updated_at", mode="before")
    @classmethod
    def _coerce_updated_at(cls, v: Any) -> datetime.datetime:
        """Coerce updated_at to timezone-aware UTC datetime."""
        if isinstance(v, str):
            v = datetime.datetime.fromisoformat(v)
        if v.tzinfo is None:
            raise ValueError("updated_at must be timezone-aware")
        return v

    # ── datetime serialization ─────────────────────────────────────

    # ── Computed fields ──────────────────────────────────────────────

    @computed_field
    @property
    def elapsed_seconds(self) -> int:
        """Seconds elapsed since generation started."""
        if self.started_at is None:
            return 0
        return int(
            (
                datetime.datetime.now(datetime.timezone.utc) - self.started_at
            ).total_seconds()
        )

    @computed_field
    @property
    def estimated_remaining_seconds(self) -> int:
        """Estimated remaining seconds based on current progress."""
        current = self.progress.get("current", 0)
        total = self.progress.get("total", 0)
        if current == 0 or total == 0:
            return 0
        elapsed = self.elapsed_seconds
        return int(elapsed * (total - current) / current)

    # ── datetime serialization ─────────────────────────────────────

    @field_serializer("started_at")
    def _serialize_started_at(self, v: datetime.datetime | None) -> str | None:
        """Serialize started_at to ISO 8601 string or None."""
        return v.isoformat() if v is not None else None

    @field_serializer("updated_at")
    def _serialize_updated_at(self, v: datetime.datetime) -> str:
        """Serialize updated_at to ISO 8601 string."""
        return v.isoformat()


__all__ = ["ArcGenerationState"]
