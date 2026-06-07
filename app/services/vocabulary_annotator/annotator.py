"""VocabularyAnnotator — injects Mark objects into episode messages.

Ref: AGENTS.md §11 (module #6) and documents/BACKEND_IN_OUT.md §四.6.

Migration notes (T16):
  - Uses UserVocabulary.vocab_index / lemma_index (NOT build_indexes).
  - Uses inline lenient token matching (strips punctuation, case-insensitive).
  - find_word_index() from app.utils.word_index is for exact matching;
    the annotator needs lenient matching for natural text, so token
    iteration is done locally.
  - lookup_lemma() from app.utils.lemma is NOT needed here — target_words
    already carry item_id resolved by the VocabularyScheduler.
"""

from __future__ import annotations

from app.models.episode import DialogueMessage, Mark, NarrationMessage
from app.models.vocabulary import UserVocabulary, VocabularyItem

_SURFACE_PUNCTUATION = set(".,!?;:\"'")


class VocabularyAnnotator:
    """Inject vocabulary marks into message texts for frontend rendering.

    For each message text, finds occurrences of each target word's surface
    form, computes 0-based word indices, determines ``is_new`` status, and
    populates the message's ``marks`` list.

    Attributes:
        user_vocab: The user's vocabulary state with O(1) item_id lookup.
    """

    def __init__(self, user_vocab: UserVocabulary) -> None:
        """Initialise with user vocabulary state.

        Args:
            user_vocab: UserVocabulary model containing vocab_index and
                lemma_index properties for O(1) lookups.
        """
        self.user_vocab = user_vocab

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
            target_words: List of dicts, each with ``item_id`` and
                ``surface_form`` keys.  ``item_id`` is looked up in
                ``user_vocab.vocab_index``.
            shown_set: Set of item_ids that have already appeared in this
                episode (mutated in-place when ``is_new=True`` marks are
                added).

        Returns:
            The same list of messages with ``marks`` fields populated.
            Messages without text are returned unchanged.
        """
        annotated: list[NarrationMessage | DialogueMessage] = []

        for msg in messages:
            marks: list[Mark] = []

            for tw in target_words:
                item_id: str = tw["item_id"]
                surface_form: str = tw["surface_form"]

                item: VocabularyItem | None = self.user_vocab.vocab_index.get(item_id)
                if item is None:
                    continue

                indices = _find_word_indices(msg.text, surface_form)
                if not indices:
                    continue

                first_new = True
                for idx in indices:
                    is_new: bool = (
                        _compute_is_new(item=item, shown_set=shown_set)
                        if first_new
                        else False
                    )
                    if is_new:
                        first_new = False

                    marks.append(
                        Mark(
                            word=surface_form,
                            index=idx,
                            definition=item.meaning,
                            is_new=is_new,
                        )
                    )

            # Sort marks by index so they appear in reading order
            marks.sort(key=lambda m: m.index)
            annotated.append(msg.model_copy(update={"marks": marks}))

        return annotated


# ------------------------------------------------------------------
# Private helpers
# ------------------------------------------------------------------


def _find_word_indices(text: str, surface_form: str) -> list[int]:
    """Find 0-based word indices of a surface form in text.

    Matching is lenient: tokens have trailing punctuation stripped and
    comparison is case-insensitive.  This handles real-world text like
    ``"consuming."`` matching the target ``"consuming"``.

    Args:
        text: The message text to search within.
        surface_form: The inflected word form to locate.

    Returns:
        List of 0-based word indices where *surface_form* appears.
        Empty list if not found.
    """
    tokens = text.split()
    result: list[int] = []
    lower_surface = surface_form.lower()

    for i, tok in enumerate(tokens):
        cleaned = tok.strip("".join(_SURFACE_PUNCTUATION))
        if cleaned.lower() == lower_surface:
            result.append(i)

    return result


def _compute_is_new(
    item: VocabularyItem,
    shown_set: set[str],
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
    if item.id in shown_set:
        return False
    if item.fsrs_card.last_review is not None:
        return False
    shown_set.add(item.id)
    return True
