"""Pydantic v2 models for user vocabulary: VocabularyItem and UserVocabulary.

Ref: AGENTS.md §12 (vocabulary.py) and documents/BACKEND_IN_OUT.md §三.2.
"""

from app.models.fsrs import FsrsCard
from pydantic import BaseModel, Field


class VocabularyItem(BaseModel):
    """A single vocabulary learning object, tracked by (word, meaning) pair.

    Each item has independent FSRS card, history window, and first-seen chapter.
    """

    id: str
    word: str
    meaning: str
    chapter_first_seen: int = Field(ge=1)
    history_window: list[int] = Field(default_factory=lambda: [1, 1, 1, 1, 1])
    fsrs_card: FsrsCard


class UserVocabulary(BaseModel):
    """The complete vocabulary state for a single user.

    Provides O(1) lookup indices for item_id and (lemma, meaning) composite keys.
    """

    user_id: str
    vocabulary: list[VocabularyItem] = Field(default_factory=list)

    @property
    def vocab_index(self) -> dict[str, VocabularyItem]:
        """O(1) index: item_id → VocabularyItem."""
        return {item.id: item for item in self.vocabulary}

    @property
    def lemma_index(self) -> dict[tuple[str, str], str]:
        """O(1) index: (lemma, meaning) → item_id.

        Handles polysemy: ("bank", "河岸") → "bank_river", ("bank", "银行") → "bank_finance".
        """
        return {(item.word, item.meaning): item.id for item in self.vocabulary}


__all__ = ["VocabularyItem", "UserVocabulary"]
