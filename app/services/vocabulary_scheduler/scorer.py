"""Context scoring and final composite score computation for VocabularyScheduler.

Provides two public functions used by the scheduler pipeline:

- ``score_context``: assigns a context-fit score per candidate based on the
  source text of an episode.  When an LLM client is injected and source text
  is available, uses the LLM to rank candidates; otherwise falls back to a
  neutral 0.5 for every candidate.

- ``final_score``: combines context-fit with FSRS urgency (for review items)
  or a fixed base weight (for unseen items) into a single 0.0–1.0 score.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.models.vocabulary import VocabularyItem
from app.llm.prompts import ContextScoreResponse, make_scoring_prompt


def _parse_due(item: VocabularyItem) -> datetime:
    """Extract the FSRS card's due date from a vocabulary item.

    Args:
        item: A VocabularyItem whose ``fsrs_card.due`` is already a
            timezone-aware ``datetime`` (parsed by the FsrsCard model).

    Returns:
        The timezone-aware ``datetime`` from ``item.fsrs_card.due``.
    """
    return item.fsrs_card.due


def _compute_urgency(due_date: datetime, now: datetime) -> float:
    """Compute FSRS review urgency as a 0.0–1.0 value.

    Urgency is proportional to how many days overdue the card is, capped at
    30 days (urgency → 1.0).  Cards that are not yet due have zero urgency.

    Args:
        due_date: The FSRS card's due date (timezone-aware).
        now: The current reference time.

    Returns:
        Urgency value between 0.0 and 1.0.
    """
    delta = now - due_date
    overdue_days = delta.total_seconds() / 86400.0
    if overdue_days < 0:
        return 0.0
    return min(1.0, overdue_days / 30.0)


async def score_context(
    source_text: str | None,
    candidates: list[VocabularyItem],
    llm_client: Any = None,
) -> dict[str, float]:
    """Assign a context-fit score (0.0–1.0) to each vocabulary candidate.

    When both ``source_text`` and ``llm_client`` are provided, the LLM ranks
    candidates by how well they fit the source text.  Otherwise, every
    candidate receives a neutral 0.5.

    Args:
        source_text: The episode's source text (chapter slice), or ``None``
            for side episodes that lack context.
        candidates: List of candidate VocabularyItem objects.
        llm_client: Optional LLM client with an async ``chat_structured()`` method
            that accepts ``messages`` and ``response_model``.  When ``None``, all
            candidates receive 0.5.

    Returns:
        A dict mapping ``item_id`` → context score (0.0–1.0).
    """
    if not candidates:
        return {}

    # Fallback when source_text or llm_client is missing.
    if source_text is None or llm_client is None:
        return {item.id: 0.5 for item in candidates}

    # Convert VocabularyItem list to dicts for make_scoring_prompt (which
    # expects raw dicts with "id"/"word"/"meaning" keys).
    candidate_dicts = [c.model_dump() for c in candidates]

    try:
        prompt = make_scoring_prompt(source_text, candidate_dicts)
        response = await llm_client.chat_structured(
            messages=prompt,
            response_model=ContextScoreResponse,
        )
    except Exception:
        # Any LLM failure → fall back to neutral scores.
        return {item.id: 0.5 for item in candidates}

    # Parse LLM response into a lookup dict, applying safety filters.
    candidate_ids = {item.id for item in candidates}
    llm_scores: dict[str, float] = {}

    for entry in response.scores:
        # Skip hallucinated item_ids not in the candidate set.
        if entry.item_id not in candidate_ids:
            continue
        # Clamp score to [0.0, 1.0].
        llm_scores[entry.item_id] = max(0.0, min(1.0, entry.score))

    # Default to 0.5 for any candidate the LLM omitted.
    result: dict[str, float] = {}
    for item in candidates:
        result[item.id] = llm_scores.get(item.id, 0.5)

    return result


def final_score(item: VocabularyItem, context_score: float, now: datetime) -> float:
    """Compute the final composite scheduling score for a vocabulary item.

    The formula differs based on whether the item has been reviewed before:

    - **Unseen** (``fsrs_card.last_review`` is ``None``):
      ``0.4 × 0.3 + context_score × 0.7``
      (a small fixed base + heavily weighted by context).

    - **Review** (``fsrs_card.last_review`` is not ``None``):
      ``urgency × 0.5 + context_score × 0.5``
      where ``urgency = min(1.0, max(0, overdue_days) / 30)``.

    Args:
        item: A VocabularyItem containing ``fsrs_card``.
        context_score: The context-fit score from ``score_context`` (0.0–1.0).
        now: The current reference time.

    Returns:
        Final composite score between 0.0 and 1.0.
    """
    if item.fsrs_card.last_review is None:
        return 0.4 * 0.3 + context_score * 0.7

    due_date = item.fsrs_card.due
    urgency = _compute_urgency(due_date, now)
    return urgency * 0.5 + context_score * 0.5
