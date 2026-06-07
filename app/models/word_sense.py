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

    Provides O(1) lemma-level lookup via convenience query methods.
    For polysemous words, the caller must further disambiguate
    among the WordSense.senses list.

    Usage:
        db = WordSenseDB.model_validate(json_data)
        entry = db.lookup("issue")
        for sense in db.get_senses("bank"):
            print(sense.id, sense.meaning)
    """

    # ── Core queries ──────────────────────────────────────

    def lookup(self, word: str) -> WordSense | None:
        """Return the WordSense entry for *word*, or None if not found.

        Args:
            word: Lemma to look up (case-insensitive, whitespace-stripped).

        Returns:
            WordSense with ``is_polysemous`` and ``senses``, or None.
        """
        return self.root.get(word.strip().lower())

    def is_polysemous(self, word: str) -> bool:
        """Return True if *word* has multiple distinct senses."""
        entry = self.lookup(word)
        return entry.is_polysemous if entry else False

    def get_senses(self, word: str) -> list[WordSenseEntry]:
        """Return all senses for *word*, empty list if not found."""
        entry = self.lookup(word)
        return entry.senses if entry else []

    def get_sense(self, word: str, sense_id: str) -> WordSenseEntry | None:
        """Return a specific sense by id, or None.

        Args:
            word: Lemma to look up.
            sense_id: Sense identifier (e.g. ``"issue_1"``).

        Returns:
            Matching WordSenseEntry, or None if word or sense not found.
        """
        for s in self.get_senses(word):
            if s.id == sense_id:
                return s
        return None

    # ── Convenience ───────────────────────────────────────

    def __contains__(self, word: str) -> bool:
        return word.strip().lower() in self.root

    def __len__(self) -> int:
        return len(self.root)

    def stats(self) -> dict:
        """Return summary statistics.

        Returns:
            dict with ``total_words``, ``polysemous_words``,
            ``single_sense_words``, ``total_senses``.
        """
        total = len(self.root)
        poly = sum(1 for e in self.root.values() if e.is_polysemous)
        total_senses = sum(len(e.senses) for e in self.root.values())
        return {
            "total_words": total,
            "polysemous_words": poly,
            "single_sense_words": total - poly,
            "total_senses": total_senses,
        }


__all__ = ["WordSenseEntry", "WordSense", "WordSenseDB"]
