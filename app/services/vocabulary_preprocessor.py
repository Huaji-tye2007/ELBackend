"""VocabularyPreprocessor — word-list import and FSRS card initialization.

Reads a user-uploaded word list, consults WordSenseDB to split polysemous
words into independent ``(word, sense)`` VocabularyItems, and initialises
a fresh FSRS card for each item.
"""

from datetime import datetime, timezone

from app.models.fsrs import FsrsCard
from app.models.vocabulary import UserVocabulary, VocabularyItem
from app.models.word_sense import WordSense, WordSenseDB


class VocabularyPreprocessor:
    """Transform a raw word list into a fully initialised UserVocabulary.

    Usage::

        db = WordSenseDB.model_validate_json(...)
        preprocessor = VocabularyPreprocessor(db)
        vocab = preprocessor.preprocess("user_001", [
            {"word": "issue"},
            {"word": "bank", "meaning": "银行"},
        ])
    """

    def __init__(self, word_sense_db: WordSenseDB):
        self._db = word_sense_db

    # ── Public API ────────────────────────────────────────

    def preprocess(
        self, user_id: str, raw_items: list[dict], chapter_id: int = 1
    ) -> UserVocabulary:
        """Process a raw word list into a UserVocabulary.

        Args:
            user_id: Owner identifier.
            raw_items: List of dicts, each with ``word`` (required) and
                       optional ``meaning``.
            chapter_id: The chapter where these words are first seen.
                        Must be >= 1. Defaults to 1.

        Returns:
            UserVocabulary with one VocabularyItem per (word, sense) pair.
            Duplicate item_ids within the batch are silently skipped.
        """
        if chapter_id < 1:
            raise ValueError(f"chapter_id must be >= 1, got {chapter_id}")

        seen_ids: set[str] = set()
        vocabulary: list[VocabularyItem] = []

        for item in raw_items:
            word = (item.get("word") or "").strip().lower()
            if not word:
                continue

            user_meaning = (item.get("meaning") or "").strip() or None

            for vi in self._process_one(word, user_meaning, chapter_id):
                if vi.id not in seen_ids:
                    seen_ids.add(vi.id)
                    vocabulary.append(vi)

        return UserVocabulary(user_id=user_id, vocabulary=vocabulary)

    # ── Per-word processing ───────────────────────────────

    def _process_one(
        self, word: str, user_meaning: str | None, chapter_id: int
    ) -> list[VocabularyItem]:
        """Produce one or more VocabularyItems for a single input word."""
        if user_meaning:
            return [self._create_from_meaning(word, user_meaning, chapter_id)]
        return self._create_all_senses(word, chapter_id)

    def _create_from_meaning(
        self, word: str, meaning: str, chapter_id: int
    ) -> VocabularyItem:
        """Create a single VocabularyItem, matching *meaning* against WordSenseDB."""
        matched = self._find_matching_sense(word, meaning)
        if matched is not None:
            return self._build_item(matched.id, word, matched.meaning, chapter_id)

        # No match — treat as custom sense
        return self._build_item(f"{word}_1", word, meaning, chapter_id)

    def _create_all_senses(self, word: str, chapter_id: int) -> list[VocabularyItem]:
        """Create one VocabularyItem per sense found in WordSenseDB.

        If the word is not in the database, create a single placeholder item.
        """
        senses = self._db.get_senses(word)
        if not senses:
            # Word unknown to WordSenseDB — still create an item
            return [self._build_item(f"{word}_1", word, "", chapter_id)]
        return [self._build_item(s.id, word, s.meaning, chapter_id) for s in senses]

    # ── Helpers ───────────────────────────────────────────

    def _find_matching_sense(self, word: str, user_meaning: str) -> WordSense | None:
        """Return the sense whose meaning best matches *user_meaning*.

        Match is bidirectional substring: user_meaning in sense.meaning
        or sense.meaning in user_meaning.
        """
        for s in self._db.get_senses(word):
            if user_meaning in s.meaning or s.meaning in user_meaning:
                return s
        return None

    @staticmethod
    def _build_item(
        item_id: str, word: str, meaning: str, chapter_id: int
    ) -> VocabularyItem:
        return VocabularyItem(
            id=item_id,
            word=word,
            meaning=meaning,
            chapter_first_seen=chapter_id,
            history_window=[0],
            fsrs_card=FsrsCard(
                card_id=int(datetime.now(timezone.utc).timestamp() * 1000),
                state=1,
                due=datetime.now(timezone.utc),
                last_review=None,
                stability=None,
                difficulty=None,
            ),
        )
