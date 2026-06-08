"""VocabularyAnnotator — injects Mark objects into episode messages.

Ref: AGENTS.md §11 (module #6) and documents/BACKEND_IN_OUT.md §四.6.

Design:
  - Accepts target_words as ``{item_id, meaning, surface?}``.
  - Prefer matching the exact ``surface`` reported by StoryRewriter.
  - Falls back to ECDICT ``lookup_lemma()`` only when ``surface`` is absent.
  - ``marks.word`` stores the surface form from the text (e.g. "consuming"),
    NOT the lemma.
  - ``is_new`` is computed from ``fsrs_card.last_review`` and the intra‑episode
    ``shown_set`` (same logic as before).
"""

from __future__ import annotations

import sqlite3

from app.models.episode import DialogueMessage, Mark, NarrationMessage
from app.models.vocabulary import UserVocabulary, VocabularyItem
from app.utils.lemma import lookup_lemma

_SURFACE_PUNCTUATION = set(".,!?;:\"'")


class VocabularyAnnotator:
    """Inject vocabulary marks into message texts for frontend rendering.

    For each message text, tokenises the text, matches StoryRewriter-reported
    surface forms when available, computes ``is_new`` status, and populates
    the message's ``marks`` list. ECDICT lemma matching remains as a fallback
    for legacy target words without a surface hint.

    Attributes:
        user_vocab: The user's vocabulary state with O(1) item_id lookup.
        ecdict_db: An open ``sqlite3.Connection`` to ``asset/ecdict_mobile.db``.
    """

    def __init__(
        self, user_vocab: UserVocabulary, ecdict_db: sqlite3.Connection
    ) -> None:
        """Initialise with user vocabulary state and ECDICT connection.

        Args:
            user_vocab: UserVocabulary model containing vocab_index and
                lemma_index properties for O(1) lookups.
            ecdict_db: An open SQLite connection to the ECDICT database.
        """
        self.user_vocab = user_vocab
        self.ecdict_db = ecdict_db

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def annotate(
        self,
        messages: list[NarrationMessage | DialogueMessage],
        target_words: list[dict],
        shown_set: set[str],
    ) -> list[NarrationMessage | DialogueMessage]:
        """Annotate messages with vocabulary marks.

        Args:
            messages: Episode messages to annotate (narration or dialogue).
            target_words: List of dicts, each with ``item_id`` and optional
                ``surface``. If ``surface`` is absent, the annotator falls
                back to matching each token's ECDICT-derived lemma against
                ``target["lemma"]`` / ``target["word"]``.
            shown_set: Set of item_ids that have already appeared in this
                episode (mutated in-place when ``is_new=True`` marks are
                added).

        Returns:
            The same list of messages with ``marks`` fields populated.
            Messages without text are returned unchanged.
        """
        annotated: list[NarrationMessage | DialogueMessage] = []
        target_key_counts = _count_target_keys(target_words)

        for message_index, msg in enumerate(messages):
            marks: list[Mark] = []
            claimed_indices_by_key: dict[tuple[str, str], set[int]] = {}

            surface_tokens = _tokenize_surface(msg.text)
            surface_by_index = {idx: cleaned for cleaned, idx in surface_tokens}
            token_data: list[tuple[str, str, int]] | None = None

            for tw in target_words:
                item_id: str = tw["item_id"]
                target_surface: str | None = tw.get("surface")
                target_lemma: str = tw.get("lemma") or tw.get("word") or tw["item_id"]
                target_is_new: bool | None = tw.get("is_new")
                target_key = _target_match_key(tw)
                target_message_index: int | None = tw.get("message_index")
                target_word_index: int | None = tw.get("word_index")

                item: VocabularyItem | None = self.user_vocab.vocab_index.get(item_id)
                if item is None:
                    continue

                if target_message_index is not None or target_word_index is not None:
                    if target_message_index != message_index:
                        continue
                    if target_word_index is None:
                        continue
                    cleaned = surface_by_index.get(target_word_index)
                    if cleaned is None:
                        continue
                    if target_surface and (
                        cleaned.lower() != _normalize_surface(target_surface)
                    ):
                        continue
                    matching = [(cleaned, target_word_index)]
                elif target_surface:
                    normalized_surface = _normalize_surface(target_surface)
                    matching = [
                        (cleaned, idx)
                        for cleaned, idx in surface_tokens
                        if cleaned.lower() == normalized_surface
                    ]
                else:
                    if token_data is None:
                        token_data = _tokenize_and_lemmatize(msg.text, self.ecdict_db)
                    matching = [
                        (cleaned, idx)
                        for cleaned, lemma, idx in token_data
                        if lemma.lower() == target_lemma.lower()
                    ]

                if not matching:
                    continue
                if target_key_counts.get(target_key, 0) > 1:
                    claimed_indices = claimed_indices_by_key.setdefault(
                        target_key, set()
                    )
                    matching = [
                        (cleaned, idx)
                        for cleaned, idx in matching
                        if idx not in claimed_indices
                    ][:1]
                    claimed_indices.update(idx for _cleaned, idx in matching)
                if not matching:
                    continue

                first_new = True
                for cleaned, idx in matching:
                    is_new: bool = (
                        _compute_is_new(
                            item=item,
                            shown_set=shown_set,
                            target_is_new=target_is_new,
                        )
                        if first_new
                        else False
                    )
                    if is_new:
                        first_new = False

                    marks.append(
                        Mark(
                            word=cleaned,  # surface form from text, not lemma
                            index=idx,
                            definition=item.meaning,
                            is_new=is_new,
                            item_id=item.id,
                            lemma=item.word,
                        )
                    )

            # Sort marks by index so they appear in reading order
            marks.sort(key=lambda m: m.index)
            annotated.append(msg.model_copy(update={"marks": marks}))

        return annotated


# ------------------------------------------------------------------
# Private helpers
# ------------------------------------------------------------------


def _tokenize_and_lemmatize(
    text: str,
    db: sqlite3.Connection,
) -> list[tuple[str, str, int]]:
    """Tokenize message text and resolve lemma for each token via ECDICT.

    Trailing punctuation (``.,!?;:"'``) is stripped before lemma lookup
    so that ``"consuming,"`` is treated as ``"consuming"``.

    If a capitalised token is not found in ECDICT, a lower‑cased fallback
    lookup is attempted (e.g. ``"Consuming"`` → ``"consuming"`` → lemma
    ``"consume"``).

    Args:
        text: The message text to tokenise.
        db: An open ECDICT SQLite connection.

    Returns:
        List of ``(cleaned_token, lemma, index)`` tuples.  ``cleaned_token``
        preserves original capitalisation and is used as ``marks.word``.
    """
    tokens = text.split(" ")
    result: list[tuple[str, str, int]] = []

    for i, tok in enumerate(tokens):
        cleaned = tok.strip("".join(_SURFACE_PUNCTUATION))
        if not cleaned:
            continue
        lemma = _resolve_lemma(cleaned, db)
        result.append((cleaned, lemma, i))

    return result


def _tokenize_surface(text: str) -> list[tuple[str, int]]:
    """Tokenize message text without ECDICT lookup."""
    result: list[tuple[str, int]] = []
    for i, tok in enumerate(text.split(" ")):
        cleaned = tok.strip("".join(_SURFACE_PUNCTUATION))
        if cleaned:
            result.append((cleaned, i))
    return result


def _normalize_surface(surface: str) -> str:
    """Normalize a StoryRewriter-reported surface for token matching."""
    return surface.strip("".join(_SURFACE_PUNCTUATION)).lower()


def _target_match_key(target_word: dict) -> tuple[str, str]:
    """Build the matching key used to detect same-surface polysemy.

    Multiple target words can share the same visible token, e.g. bank=河岸
    and bank=银行. Without a precise LLM-provided position, those targets
    must consume distinct token positions rather than all matching every
    occurrence.
    """
    target_surface = target_word.get("surface")
    if target_surface:
        return ("surface", _normalize_surface(target_surface))
    target_lemma = (
        target_word.get("lemma")
        or target_word.get("word")
        or target_word.get("item_id")
        or ""
    )
    return ("lemma", str(target_lemma).lower())


def _count_target_keys(target_words: list[dict]) -> dict[tuple[str, str], int]:
    counts: dict[tuple[str, str], int] = {}
    for target_word in target_words:
        key = _target_match_key(target_word)
        counts[key] = counts.get(key, 0) + 1
    return counts


def _resolve_lemma(word: str, db: sqlite3.Connection) -> str:
    """Resolve a word to its base lemma, with case‑insensitive fallback.

    Tries the word as‑is first.  If ECDICT returns the input unchanged
    (meaning the word is not in the database), a lower‑cased retry is
    attempted.  The returned lemma is always lower‑cased for consistent
    matching against target lemmas.

    Args:
        word: A cleaned token (punctuation already stripped).
        db: An open ECDICT SQLite connection.

    Returns:
        The base lemma in lower case.
    """
    lemma = lookup_lemma(word, db)
    if lemma == word and word != word.lower():
        # Capitalised form not found — try lower‑cased version
        lemma_lower = lookup_lemma(word.lower(), db)
        if lemma_lower != word.lower():
            lemma = lemma_lower
    return lemma.lower()


def _compute_is_new(
    item: VocabularyItem,
    shown_set: set[str],
    target_is_new: bool | None = None,
) -> bool:
    """Determine whether this (word, meaning) pair is new in the episode.

    A word is new when:
    1. Its FSRS card has never been reviewed (``last_review is None``).
    2. It has not yet appeared in this episode (not in *shown_set*).

    When a word is determined to be new, its *item_id* is added to
    *shown_set* as a side effect.

    Args:
        item: The VocabularyItem being checked.
        shown_set: Mutable set of item_ids already shown.  Mutated
            in-place when ``True`` is returned.

    Returns:
        ``True`` if this is the first new occurrence in the episode.
    """
    if target_is_new is False:
        return False
    if item.id in shown_set:
        return False
    if item.fsrs_card.last_review is not None:
        return False
    shown_set.add(item.id)
    return True
