"""Pydantic v2 models for word sense disambiguation: WordSense, WordSenseDB.

Ref: AGENTS.md §12 (word_sense.py) and documents/BACKEND_IN_OUT.md §三.4.
"""

from pydantic import BaseModel, RootModel


class WordSenseEntry(BaseModel):
    """A single sense of a word, with a unique identifier and meaning.

    Used as building block for WordSense.senses lists.
    The `id` is a human-readable composite key (e.g. "bank_river", "issue_topic").
    """

    id: str
    meaning: str


class WordSense(BaseModel):
    """Describes whether a lemma is polysemous and enumerates its distinct senses.

    For non-polysemous words, `senses` contains exactly one entry.
    For polysemous words, `senses` contains 2+ entries, each with a unique id.
    """

    is_polysemous: bool
    senses: list[WordSenseEntry]


class WordSenseDB(RootModel[dict[str, WordSense]]):
    """Database of word senses, mapping lemma (str) → WordSense.

    Provides O(1) lemma-level lookup. For polysemous words, the caller must
    further disambiguate among the WordSense.senses list.

    Usage:
        db = WordSenseDB.model_validate(json_data)
        senses = db.root["bank"].senses  # list[WordSenseEntry]
    """


__all__ = ["WordSenseEntry", "WordSense", "WordSenseDB"]
