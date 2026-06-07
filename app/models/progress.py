"""Pydantic v2 model for reading progress: ReadingProgress.

Ref: AGENTS.md §12 (progress.py) and documents/BACKEND_IN_OUT.md §三.5.
"""

from pydantic import BaseModel, Field


class ReadingProgress(BaseModel):
    """Tracks the user's current reading position and overall progress."""

    current_chapter: int = Field(ge=1)
    current_episode: int = Field(ge=1)
    chapter_offset: float = Field(ge=0, le=1)
    total_episodes_read: int = Field(ge=0)


__all__ = ["ReadingProgress"]
