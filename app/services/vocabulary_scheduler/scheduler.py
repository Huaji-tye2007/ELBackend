"""Vocabulary Scheduler — orchestrates pool building, scoring, and allocation for an ArcPlan."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.models.vocabulary import UserVocabulary
from app.services.vocabulary_scheduler.pools import apply_pending_overlay, build_pools
from app.services.vocabulary_scheduler.scorer import final_score, score_context
from app.services.vocabulary_scheduler.allocator import (
    allocate_main_episode,
    allocate_side_episode,
)


async def schedule(
    arc_plan: dict,
    user_vocab: dict,
    now: datetime | None = None,
    episode_limit: int = 10,
    llm_client: Any = None,
) -> dict:
    """Schedule vocabulary for all episodes in an arc plan.

    Fills each episode's target_words by:
    1. Building unseen and due-review pools from user vocabulary
    2. Applying pending word priority overlay
    3. For each episode: scoring candidates, computing final scores, allocating words

    Args:
        arc_plan: ArcPlan dict with "episodes" (list of episode dicts) and
                  "pending_words" (list of {item_id, rejected_count} dicts) keys.
                  Episode dicts have "source_text" and "episode_type" ("main"/"side").
        user_vocab: UserVocabulary dict with "vocabulary" key containing list of item dicts.
        now: Reference datetime. Defaults to UTC now if None.
        episode_limit: Max new words AND max review words per episode (default 10).
        llm_client: Optional LLM client for contextual scoring. When None, falls back to 0.5 for all candidates.

    Returns:
        Updated arc_plan dict with each episode's "target_words" list populated.
        target_words entries are TargetWord Pydantic models serialized via model_dump().
    """
    if now is None:
        now = datetime.now(timezone.utc)

    # Convert input dict to UserVocabulary model
    vocab = UserVocabulary.model_validate(user_vocab)

    pending_words: list[dict] = arc_plan.get("pending_words", [])
    episodes: list[dict] = arc_plan.get("episodes", [])

    # Build pools once, then apply pending overlay (both return list[VocabularyItem])
    pools = build_pools(vocab, now)
    unseen_pool, review_pool = apply_pending_overlay(pools, pending_words)

    # Track arc-wide is_new dedup
    arc_new_ids: set[str] = set()
    arc_repeat_pool: list[Any] = []

    for episode in episodes:
        source_text: str | None = episode.get("source_text")
        episode_type: str = episode.get("episode_type", "main")

        # Take next batch from each pool (up to episode_limit * 3 candidates)
        candidate_count = episode_limit * 3
        unseen_batch = unseen_pool[:candidate_count]
        review_batch = review_pool[:candidate_count]
        repeat_batch = arc_repeat_pool[:candidate_count]

        # Score context for all candidates (batches are already list[VocabularyItem])
        all_candidates = unseen_batch + review_batch + repeat_batch
        context_scores: dict[str, float] = await score_context(
            source_text, all_candidates, llm_client
        )

        # Compute final scores for unseen candidates
        unseen_scored: list[tuple[float, Any]] = []
        for item in unseen_batch:
            cs = context_scores.get(item.id, 0.5)
            fs = final_score(item, cs, now)
            unseen_scored.append((fs, item))

        # Compute final scores for review candidates
        review_scored: list[tuple[float, Any]] = []
        for item in review_batch:
            cs = context_scores.get(item.id, 0.5)
            fs = final_score(item, cs, now)
            review_scored.append((fs, item))
        for item in repeat_batch:
            cs = context_scores.get(item.id, 0.5)
            review_scored.append((cs, item))

        # Allocate based on episode type
        if episode_type == "side":
            pending_item_ids: list[str] = [pw["item_id"] for pw in pending_words]
            target_words, arc_new_ids = allocate_side_episode(
                unseen_scored,
                review_scored,
                pending_item_ids,
                episode_limit=episode_limit,
                arc_new_ids=arc_new_ids,
            )
        else:  # main
            target_words, arc_new_ids = allocate_main_episode(
                unseen_scored,
                review_scored,
                episode_limit=episode_limit,
                arc_new_ids=arc_new_ids,
            )

        # Serialize TargetWord models back to dicts for storage in arc_plan
        episode["target_words"] = [tw.model_dump() for tw in target_words]

        review_batch_ids = {item.id for item in review_batch}
        unseen_by_id = {item.id: item for item in unseen_batch}
        consumed_unseen_ids = {tw.item_id for tw in target_words if tw.is_new}
        consumed_review_ids = {
            tw.item_id
            for tw in target_words
            if not tw.is_new and tw.item_id in review_batch_ids
        }
        unseen_pool = [
            item for item in unseen_pool if item.id not in consumed_unseen_ids
        ]
        review_pool = [
            item for item in review_pool if item.id not in consumed_review_ids
        ]

        repeat_ids = {item.id for item in arc_repeat_pool}
        for tw in target_words:
            if tw.is_new and tw.item_id in unseen_by_id and tw.item_id not in repeat_ids:
                arc_repeat_pool.append(unseen_by_id[tw.item_id])
                repeat_ids.add(tw.item_id)

    return arc_plan
