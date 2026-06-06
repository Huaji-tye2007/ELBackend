"""Context scoring and final composite score computation for VocabularyScheduler.

Provides two public functions used by the scheduler pipeline:

- ``score_context``: assigns a context-fit score per candidate based on the
  source text of an episode.  LLM-based scoring is dependency-injected; the
  MVP implementation returns a neutral 0.5 for every candidate.

- ``final_score``: combines context-fit with FSRS urgency (for review items)
  or a fixed base weight (for unseen items) into a single 0.0–1.0 score.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any


def _parse_due(item: dict[str, Any]) -> datetime:
    """Parse an ISO-8601 due date from a vocabulary item's FSRS card.

    Args:
        item: A vocabulary-item dict that contains ``fsrs_card.due`` as an
            ISO-8601 string (e.g. ``"2026-06-07T00:00:00Z"``).

    Returns:
        A timezone-aware ``datetime`` parsed from the string.
    """
    raw = item["fsrs_card"]["due"]
    # Python 3.10's fromisoformat does not accept the "Z" suffix.
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    return datetime.fromisoformat(raw)


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


def score_context(
    source_text: str | None,
    candidates: list[dict[str, Any]],
    llm_client: Any = None,
) -> dict[str, float]:
    """Assign a context-fit score (0.0–1.0) to each vocabulary candidate.

    In the MVP, scoring is neutral (0.5 for every candidate).  When a real
    LLM client is injected in a future version, this function will use it
    to rank candidates by how well they fit ``source_text``.

    Args:
        source_text: The episode's source text (chapter slice), or ``None``
            for side episodes that lack context.
        candidates: List of candidate vocabulary items, each containing at
            least an ``"id"`` key.
        llm_client: Optional LLM client for contextual scoring (ignored in
            MVP — all candidates receive 0.5).

    Returns:
        A dict mapping ``item_id`` → context score (0.0–1.0).
    """
    if not candidates:
        return {}

    # MVP: always return neutral 0.5 regardless of source_text or llm_client.
    # Future implementation will call llm_client when both source_text and
    # llm_client are provided.
    return {item["id"]: 0.5 for item in candidates}


def final_score(item: dict[str, Any], context_score: float, now: datetime) -> float:
    """Compute the final composite scheduling score for a vocabulary item.

    The formula differs based on whether the item has been reviewed before:

    - **Unseen** (``fsrs_card.last_review`` is ``None``):
      ``0.4 × 0.3 + context_score × 0.7``
      (a small fixed base + heavily weighted by context).

    - **Review** (``fsrs_card.last_review`` is not ``None``):
      ``urgency × 0.5 + context_score × 0.5``
      where ``urgency = min(1.0, max(0, overdue_days) / 30)``.

    Args:
        item: A vocabulary-item dict containing ``fsrs_card``.
        context_score: The context-fit score from ``score_context`` (0.0–1.0).
        now: The current reference time.

    Returns:
        Final composite score between 0.0 and 1.0.
    """
    if item["fsrs_card"]["last_review"] is None:
        return 0.4 * 0.3 + context_score * 0.7

    due_date = _parse_due(item)
    urgency = _compute_urgency(due_date, now)
    return urgency * 0.5 + context_score * 0.5
