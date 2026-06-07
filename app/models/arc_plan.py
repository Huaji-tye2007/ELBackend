"""Pydantic v2 models for ArcPlan ecosystem: PendingWord, EpisodeSlot, ArcPlan.

Ref: documents/BACKEND_IN_OUT.md §三.7 和 AGENTS.md §12.
"""

from typing import Literal

from pydantic import BaseModel, Field

from app.models.fsrs import FsrsCard


class PendingWord(BaseModel):
    """A vocabulary item that was pending (not yet successfully placed) from a previous arc."""

    item_id: str
    rejected_count: int = Field(default=0, ge=0)


class TargetWord(BaseModel):
    """A vocabulary word targeted for inclusion in an episode."""

    item_id: str
    word: str
    meaning: str
    is_new: bool
    fsrs_card: FsrsCard | None = None


class EpisodeSlot(BaseModel):
    """A planned episode slot within an arc, carrying target words and optional context."""

    episode_id: int
    episode_type: Literal["main", "side"]
    source_text: str | None = None
    previous_context: list[dict] = Field(default_factory=list)
    target_words: list[TargetWord] = Field(default_factory=list)


class ArcPlan(BaseModel):
    """Full arc plan: arc identifier, pending words from previous arc, and episode slots."""

    arc_id: str
    pending_words: list[PendingWord] = Field(default_factory=list)
    episodes: list[EpisodeSlot] = Field(default_factory=list)


__all__ = ["PendingWord", "TargetWord", "EpisodeSlot", "ArcPlan"]
