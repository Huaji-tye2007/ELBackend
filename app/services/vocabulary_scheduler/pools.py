"""Pool-building functions for Vocabulary Scheduler — separate unseen vs due-review items."""

from datetime import datetime, timezone


def _parse_due(due_str: str) -> datetime:
    """Parse a due ISO string, normalizing 'Z' suffix for Python 3.10 compatibility."""
    if due_str.endswith("Z"):
        due_str = due_str[:-1] + "+00:00"
    return datetime.fromisoformat(due_str)


def build_pools(
    user_vocab: dict, now: datetime | None = None
) -> tuple[list[dict], list[dict]]:
    """Separate vocabulary items into unseen and due-review pools.

    Args:
        user_vocab: Dict with "vocabulary" key containing list of item dicts.
                    Each item has an "fsrs_card" with "last_review" (ISO string or None)
                    and "due" (ISO string).
        now: Reference datetime for determining "due". Defaults to UTC now.

    Returns:
        Tuple of (unseen_pool, due_review_pool) — full item dicts.
        unseen_pool: items where fsrs_card.last_review is None.
        due_review_pool: items where last_review is not None AND due <= now.
    """
    if now is None:
        now = datetime.now(timezone.utc)

    unseen_pool: list[dict] = []
    due_review_pool: list[dict] = []

    for item in user_vocab["vocabulary"]:
        last_review = item["fsrs_card"].get("last_review")
        if last_review is None:
            unseen_pool.append(item)
        else:
            due_str = item["fsrs_card"]["due"]
            due_dt = _parse_due(due_str)
            if due_dt <= now:
                due_review_pool.append(item)

    return (unseen_pool, due_review_pool)


def apply_pending_overlay(
    pools: tuple[list[dict], list[dict]],
    pending_words: list[dict],
) -> tuple[list[dict], list[dict]]:
    """Reorder pools so pending words appear at front, then sort non-pending by rules.

    Pending items are moved to the front of their respective pools, preserving
    the order they appear in pending_words. After the overlay, non-pending items
    are sorted:
      - unseen_pool: by chapter_first_seen ascending
      - due_review_pool: by fsrs_card.due ascending

    If a pending item_id does not exist in the pool, it is silently ignored.

    Args:
        pools: Tuple of (unseen_pool, due_review_pool) from build_pools.
        pending_words: List of dicts with "item_id" key, e.g.
                       [{"item_id": "meticulous_1", "rejected_count": 3}, ...].

    Returns:
        Reordered (unseen_pool, due_review_pool) tuple.
    """
    unseen_pool, due_review_pool = pools

    pending_ids = {pw["item_id"] for pw in pending_words}
    pending_order = [pw["item_id"] for pw in pending_words]

    unseen_pool = _reorder_pool(
        unseen_pool,
        pending_order,
        pending_ids,
        sort_key=lambda item: item["chapter_first_seen"],
    )
    due_review_pool = _reorder_pool(
        due_review_pool,
        pending_order,
        pending_ids,
        sort_key=lambda item: item["fsrs_card"]["due"],
    )

    return (unseen_pool, due_review_pool)


def _reorder_pool(
    pool: list[dict],
    pending_order: list[str],
    pending_ids: set[str],
    sort_key,
) -> list[dict]:
    """Reorder a single pool: pending items first, then sorted non-pending.

    Args:
        pool: List of item dicts (each has "id" key).
        pending_order: Ordered list of pending item_ids determining front order.
        pending_ids: Set of pending item_ids for O(1) lookup.
        sort_key: Key function for sorting non-pending items.

    Returns:
        Reordered list with pending items at front.
    """
    pool_by_id = {item["id"]: item for item in pool}

    pending_items: list[dict] = []
    for pid in pending_order:
        if pid in pool_by_id:
            pending_items.append(pool_by_id[pid])

    non_pending_items: list[dict] = []
    for item in pool:
        if item["id"] not in pending_ids:
            non_pending_items.append(item)

    non_pending_items.sort(key=sort_key)

    return pending_items + non_pending_items
