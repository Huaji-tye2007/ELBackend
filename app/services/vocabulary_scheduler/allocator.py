"""Vocabulary allocation: distributes target words into main and side episodes."""

from __future__ import annotations

from app.models.arc_plan import TargetWord
from app.models.vocabulary import VocabularyItem


def _build_target(item: VocabularyItem, is_new: bool) -> TargetWord:
    """Build a TargetWord from a vocabulary item.

    Args:
        item: VocabularyItem with id, word, meaning, fsrs_card.
        is_new: Whether this is the first appearance of the word.

    Returns:
        A TargetWord Pydantic model with item_id, word, meaning, is_new, fsrs_card.
    """
    return TargetWord(
        item_id=item.id,
        word=item.word,
        meaning=item.meaning,
        is_new=is_new,
        fsrs_card=item.fsrs_card,
    )


def allocate_main_episode(
    unseen_scored: list[tuple[float, VocabularyItem]],
    review_scored: list[tuple[float, VocabularyItem]],
    episode_limit: int = 10,
    arc_new_ids: set[str] | None = None,
) -> tuple[list[TargetWord], set[str]]:
    """Allocate target words for a main episode.

    Args:
        unseen_scored: Scored candidates from the unseen pool, as (score, VocabularyItem) tuples.
        review_scored: Scored candidates from the review pool, as (score, VocabularyItem) tuples.
        episode_limit: Maximum number of new words AND maximum review words per episode.
        arc_new_ids: Set of item_ids already marked is_new=true in this arc (for dedup).

    Returns:
        A tuple of (target_words, updated_arc_new_ids).
        target_words is a list of TargetWord Pydantic models.
    """
    if arc_new_ids is None:
        arc_new_ids = set()
    updated_arc_new_ids: set[str] = set(arc_new_ids)

    # Sort by score descending
    unseen_sorted = sorted(unseen_scored, key=lambda x: x[0], reverse=True)
    review_sorted = sorted(review_scored, key=lambda x: x[0], reverse=True)

    target_words: list[TargetWord] = []

    # Pick unseen words (up to episode_limit)
    for _score, item in unseen_sorted:
        item_id: str = item.id
        if len(target_words) >= episode_limit:
            break
        if item_id in updated_arc_new_ids:
            continue
        target_words.append(_build_target(item, is_new=True))
        updated_arc_new_ids.add(item_id)

    # Pick review words (up to episode_limit)
    review_count = 0
    for _score, item in review_sorted:
        if review_count >= episode_limit:
            break
        target_words.append(_build_target(item, is_new=False))
        review_count += 1

    return target_words, updated_arc_new_ids


def allocate_side_episode(
    unseen_scored: list[tuple[float, VocabularyItem]],
    review_scored: list[tuple[float, VocabularyItem]],
    pending_item_ids: list[str],
    episode_limit: int = 10,
    arc_new_ids: set[str] | None = None,
) -> tuple[list[TargetWord], set[str]]:
    """Allocate target words for a side episode with pending priority.

    Args:
        unseen_scored: Scored candidates from the unseen pool, as (score, VocabularyItem) tuples.
        review_scored: Scored candidates from the review pool, as (score, VocabularyItem) tuples.
        pending_item_ids: List of item_ids that are pending (high rejected_count).
        episode_limit: Maximum number of new words AND maximum review words per episode.
        arc_new_ids: Set of item_ids already marked is_new=true in this arc (for dedup).

    Returns:
        A tuple of (target_words, updated_arc_new_ids).
        target_words is a list of TargetWord Pydantic models.
    """
    if arc_new_ids is None:
        arc_new_ids = set()
    updated_arc_new_ids: set[str] = set(arc_new_ids)

    pending_set: set[str] = set(pending_item_ids)

    # Separate unseen into pending and other
    pending_unseen: list[tuple[float, VocabularyItem]] = []
    other_unseen: list[tuple[float, VocabularyItem]] = []
    for entry in unseen_scored:
        _score, item = entry
        if item.id in pending_set:
            pending_unseen.append(entry)
        else:
            other_unseen.append(entry)

    # Sort each group by score descending
    pending_unseen.sort(key=lambda x: x[0], reverse=True)
    other_unseen.sort(key=lambda x: x[0], reverse=True)
    review_sorted = sorted(review_scored, key=lambda x: x[0], reverse=True)

    target_words: list[TargetWord] = []
    new_count = 0

    # Fill pending unseen first (up to episode_limit)
    for _score, item in pending_unseen:
        item_id: str = item.id
        if new_count >= episode_limit:
            break
        if item_id in updated_arc_new_ids:
            continue
        target_words.append(_build_target(item, is_new=True))
        updated_arc_new_ids.add(item_id)
        new_count += 1

    # Fill remaining new slots from other unseen (up to episode_limit total new)
    for _score, item in other_unseen:
        item_id = item.id
        if new_count >= episode_limit:
            break
        if item_id in updated_arc_new_ids:
            continue
        target_words.append(_build_target(item, is_new=True))
        updated_arc_new_ids.add(item_id)
        new_count += 1

    # Fill review slots (up to episode_limit)
    review_count = 0
    for _score, item in review_sorted:
        if review_count >= episode_limit:
            break
        target_words.append(_build_target(item, is_new=False))
        review_count += 1

    return target_words, updated_arc_new_ids
