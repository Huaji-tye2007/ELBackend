"""Tests for app.models.arc_generation — ArcGenerationState model."""

import datetime

import pytest
from pydantic import ValidationError

from app.models.arc_generation import ArcGenerationState


class TestArcGenerationState:
    """Tests for ArcGenerationState model."""

    # ── valid state tests ──────────────────────────────────────────

    def test_valid_state(self) -> None:
        """ArcGenerationState with all fields populated should validate."""
        now = datetime.datetime.now(datetime.timezone.utc)
        state = ArcGenerationState(
            arc_id="arc_003",
            phase="GENERATING",
            progress={"current": 4, "total": 10},
            retry_count=0,
            last_error=None,
            started_at=now - datetime.timedelta(seconds=180),
            updated_at=now,
        )
        assert state.arc_id == "arc_003"
        assert state.phase == "GENERATING"
        assert state.progress == {"current": 4, "total": 10}
        assert state.retry_count == 0
        assert state.last_error is None
        assert state.started_at is not None
        assert state.updated_at is not None
        dumped = state.model_dump()
        assert "elapsed_seconds" in dumped
        assert "estimated_remaining_seconds" in dumped

    def test_valid_failed_phase(self) -> None:
        """ArcGenerationState(phase='FAILED') should validate with last_error set."""
        now = datetime.datetime.now(datetime.timezone.utc)
        state = ArcGenerationState(
            arc_id="arc_007",
            phase="FAILED",
            progress={"current": 5, "total": 10},
            retry_count=3,
            last_error="LLM timeout after 300s",
            updated_at=now,
        )
        assert state.phase == "FAILED"
        assert state.retry_count == 3
        assert state.last_error == "LLM timeout after 300s"
        assert state.started_at is None

    def test_valid_idle_phase(self) -> None:
        """ArcGenerationState(phase='IDLE') should validate with minimal fields."""
        now = datetime.datetime.now(datetime.timezone.utc)
        state = ArcGenerationState(
            arc_id="arc_001",
            phase="IDLE",
            progress={"current": 0, "total": 0},
            retry_count=0,
            updated_at=now,
        )
        assert state.phase == "IDLE"
        assert state.progress == {"current": 0, "total": 0}
        assert state.retry_count == 0
        assert state.last_error is None
        assert state.started_at is None

    def test_valid_all_phases(self) -> None:
        """All 8 valid phases should pass validation."""
        now = datetime.datetime.now(datetime.timezone.utc)
        valid_phases = [
            "IDLE",
            "PLANNING",
            "SCHEDULING",
            "GENERATING",
            "ANNOTATING",
            "FORMATTING",
            "COMPLETE",
            "FAILED",
        ]
        for phase in valid_phases:
            state = ArcGenerationState(
                arc_id="arc_test",
                phase=phase,
                progress={"current": 1, "total": 1},
                retry_count=0,
                updated_at=now,
            )
            assert state.phase == phase

    # ── invalid phase test ─────────────────────────────────────────

    def test_invalid_phase(self) -> None:
        """ArcGenerationState(phase='INVALID') should raise ValidationError."""
        now = datetime.datetime.now(datetime.timezone.utc)
        with pytest.raises(ValidationError):
            ArcGenerationState(
                arc_id="arc_bad",
                phase="INVALID",
                progress={"current": 0, "total": 0},
                retry_count=0,
                updated_at=now,
            )

    def test_invalid_phase_lowercase(self) -> None:
        """ArcGenerationState(phase='idle') should raise ValidationError (case-sensitive)."""
        now = datetime.datetime.now(datetime.timezone.utc)
        with pytest.raises(ValidationError):
            ArcGenerationState(
                arc_id="arc_bad",
                phase="idle",
                progress={"current": 0, "total": 0},
                retry_count=0,
                updated_at=now,
            )

    # ── retry_count constraint test ────────────────────────────────

    def test_retry_count_negative_raises_error(self) -> None:
        """ArcGenerationState(retry_count=-1) should raise ValidationError (ge=0)."""
        now = datetime.datetime.now(datetime.timezone.utc)
        with pytest.raises(ValidationError):
            ArcGenerationState(
                arc_id="arc_bad",
                phase="IDLE",
                progress={"current": 0, "total": 0},
                retry_count=-1,
                updated_at=now,
            )

    # ── datetime coercion tests ────────────────────────────────────

    def test_updated_at_must_have_timezone(self) -> None:
        """ArcGenerationState.updated_at should be timezone-aware (UTC)."""
        now_utc = datetime.datetime.now(datetime.timezone.utc)
        state = ArcGenerationState(
            arc_id="arc_tz",
            phase="GENERATING",
            progress={"current": 1, "total": 10},
            retry_count=0,
            updated_at=now_utc,
        )
        assert state.updated_at.tzinfo is not None
        assert state.updated_at.tzinfo == datetime.timezone.utc

    def test_started_at_accepts_timezone_aware(self) -> None:
        """ArcGenerationState.started_at with UTC datetime should validate."""
        now = datetime.datetime.now(datetime.timezone.utc)
        past = now - datetime.timedelta(minutes=5)
        state = ArcGenerationState(
            arc_id="arc_tz",
            phase="PLANNING",
            progress={"current": 0, "total": 10},
            retry_count=0,
            updated_at=now,
            started_at=past,
        )
        assert state.started_at == past
        assert state.started_at.tzinfo is not None

    def test_started_at_none_valid(self) -> None:
        """ArcGenerationState with started_at=None should validate."""
        now = datetime.datetime.now(datetime.timezone.utc)
        state = ArcGenerationState(
            arc_id="arc_none",
            phase="IDLE",
            progress={"current": 0, "total": 0},
            retry_count=0,
            updated_at=now,
            started_at=None,
        )
        assert state.started_at is None

    # ── serialization tests ────────────────────────────────────────

    def test_model_dump_json_serializable(self) -> None:
        """ArcGenerationState.model_dump() should produce JSON-serializable output."""
        now = datetime.datetime.now(datetime.timezone.utc)
        state = ArcGenerationState(
            arc_id="arc_ser",
            phase="COMPLETE",
            progress={"current": 10, "total": 10},
            retry_count=1,
            last_error=None,
            started_at=now - datetime.timedelta(minutes=10),
            updated_at=now,
        )
        data = state.model_dump()
        assert isinstance(data["updated_at"], str)
        assert isinstance(data["started_at"], str)
        assert isinstance(data["last_error"], type(None))
        assert data["phase"] == "COMPLETE"
        assert data["arc_id"] == "arc_ser"
        # Verify ISO 8601 format
        datetime.datetime.fromisoformat(data["updated_at"])
        datetime.datetime.fromisoformat(data["started_at"])

    def test_model_dump_started_at_none(self) -> None:
        """model_dump() with started_at=None should output None."""
        now = datetime.datetime.now(datetime.timezone.utc)
        state = ArcGenerationState(
            arc_id="arc_ser",
            phase="IDLE",
            progress={"current": 0, "total": 0},
            retry_count=0,
            updated_at=now,
        )
        data = state.model_dump()
        assert data["started_at"] is None
        assert isinstance(data["updated_at"], str)

    # ── roundtrip test ─────────────────────────────────────────────

    def test_roundtrip(self) -> None:
        """ArcGenerationState → model_dump → model_validate should preserve all fields."""
        now = datetime.datetime.now(datetime.timezone.utc)
        started = now - datetime.timedelta(minutes=30)
        original = ArcGenerationState(
            arc_id="arc_round",
            phase="FAILED",
            progress={"current": 3, "total": 10},
            retry_count=2,
            last_error="Connection reset",
            started_at=started,
            updated_at=now,
        )
        data = original.model_dump()
        restored = ArcGenerationState.model_validate(data)
        assert restored.arc_id == original.arc_id
        assert restored.phase == original.phase
        assert restored.progress == original.progress
        assert restored.retry_count == original.retry_count
        assert restored.last_error == original.last_error
        # Datetimes rounded through ISO serialization — compare ISO strings
        assert restored.updated_at.isoformat() == original.updated_at.isoformat()
        assert restored.started_at is not None
        assert original.started_at is not None
        assert restored.started_at.isoformat() == original.started_at.isoformat()
