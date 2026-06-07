"""Tests for app.models.progress — ReadingProgress."""

import pytest
from pydantic import ValidationError


# Import will fail until model is created (RED phase)
class TestReadingProgress:
    """Tests for ReadingProgress model."""

    def test_valid_minimal(self) -> None:
        """ReadingProgress with all required fields should validate."""
        from app.models.progress import ReadingProgress

        rp = ReadingProgress(
            current_chapter=1,
            current_episode=1,
            chapter_offset=0.0,
            total_episodes_read=0,
        )
        assert rp.current_chapter == 1
        assert rp.current_episode == 1
        assert rp.chapter_offset == 0.0
        assert rp.total_episodes_read == 0

    def test_valid_full(self) -> None:
        """ReadingProgress with typical mid-read values should validate."""
        from app.models.progress import ReadingProgress

        rp = ReadingProgress(
            current_chapter=3,
            current_episode=2,
            chapter_offset=0.42,
            total_episodes_read=18,
        )
        assert rp.current_chapter == 3
        assert rp.current_episode == 2
        assert rp.chapter_offset == 0.42
        assert rp.total_episodes_read == 18

    def test_valid_boundary_chapter_offset(self) -> None:
        """ReadingProgress with boundary chapter_offset 0.0 and 1.0 should validate."""
        from app.models.progress import ReadingProgress

        rp_min = ReadingProgress(
            current_chapter=1,
            current_episode=1,
            chapter_offset=0.0,
            total_episodes_read=0,
        )
        rp_max = ReadingProgress(
            current_chapter=2,
            current_episode=5,
            chapter_offset=1.0,
            total_episodes_read=100,
        )
        assert rp_min.chapter_offset == 0.0
        assert rp_max.chapter_offset == 1.0

    def test_invalid_chapter_offset_greater_than_one(self) -> None:
        """ReadingProgress with chapter_offset > 1 should raise ValidationError."""
        from app.models.progress import ReadingProgress

        with pytest.raises(ValidationError):
            ReadingProgress(
                current_chapter=1,
                current_episode=1,
                chapter_offset=1.5,
                total_episodes_read=5,
            )

    def test_invalid_chapter_offset_negative(self) -> None:
        """ReadingProgress with chapter_offset < 0 should raise ValidationError."""
        from app.models.progress import ReadingProgress

        with pytest.raises(ValidationError):
            ReadingProgress(
                current_chapter=1,
                current_episode=1,
                chapter_offset=-0.1,
                total_episodes_read=5,
            )

    def test_invalid_current_chapter_zero(self) -> None:
        """ReadingProgress with current_chapter=0 should raise ValidationError."""
        from app.models.progress import ReadingProgress

        with pytest.raises(ValidationError):
            ReadingProgress(
                current_chapter=0,
                current_episode=1,
                chapter_offset=0.5,
                total_episodes_read=5,
            )

    def test_invalid_current_episode_zero(self) -> None:
        """ReadingProgress with current_episode=0 should raise ValidationError."""
        from app.models.progress import ReadingProgress

        with pytest.raises(ValidationError):
            ReadingProgress(
                current_chapter=1,
                current_episode=0,
                chapter_offset=0.5,
                total_episodes_read=5,
            )

    def test_invalid_total_episodes_read_negative(self) -> None:
        """ReadingProgress with total_episodes_read < 0 should raise ValidationError."""
        from app.models.progress import ReadingProgress

        with pytest.raises(ValidationError):
            ReadingProgress(
                current_chapter=1,
                current_episode=1,
                chapter_offset=0.5,
                total_episodes_read=-1,
            )

    def test_full_roundtrip(self) -> None:
        """ReadingProgress dump → dict → reload should produce equal model."""
        from app.models.progress import ReadingProgress

        rp = ReadingProgress(
            current_chapter=3,
            current_episode=2,
            chapter_offset=0.42,
            total_episodes_read=18,
        )
        dumped = rp.model_dump()
        reloaded = ReadingProgress.model_validate(dumped)
        assert reloaded.current_chapter == 3
        assert reloaded.current_episode == 2
        assert reloaded.chapter_offset == 0.42
        assert reloaded.total_episodes_read == 18
