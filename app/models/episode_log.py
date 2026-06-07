"""Pydantic v2 models for reading log: WordLog and EpisodeReadingLog.

Ref: AGENTS.md §12 (episode_log.py) and documents/BACKEND_IN_OUT.md §三.7.
"""

from pydantic import BaseModel, Field, model_validator


class WordLog(BaseModel):
    """A single word's appearance/click tracking within one episode.

    If ``word`` (surface form) is provided, ReadingTracker resolves it to
    ``item_id`` via ECDICT + lemma_index.  If ``item_id`` is already known
    by the client it can be sent directly — the server will not overwrite
    a non-empty ``item_id``.
    """

    item_id: str = ""
    word: str | None = None
    appeared: int = Field(ge=0)
    clicked: int = Field(ge=0)

    @model_validator(mode="after")
    def _check_clicked_le_appeared(self) -> "WordLog":
        """Validate that clicked never exceeds appeared."""
        if self.clicked > self.appeared:
            raise ValueError(
                f"clicked ({self.clicked}) must be <= appeared ({self.appeared})"
            )
        return self


class EpisodeReadingLog(BaseModel):
    """Reading behavior log for a single episode.

    Captures per-word appearance counts and click events submitted
    by the frontend upon episode completion.
    """

    episode_id: int = Field(ge=1)
    word_logs: list[WordLog]


__all__ = ["WordLog", "EpisodeReadingLog"]
