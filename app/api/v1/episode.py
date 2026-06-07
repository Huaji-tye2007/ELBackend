"""Episode API endpoints — serve cached episodes and cache status.

Ref: AGENTS.md §10, documents/format_spec_json.md.
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, Depends

from app.core.exceptions import NotFoundError
from app.models.episode import Episode

router = APIRouter(prefix="/episode", tags=["episode"])

# ── Cache path ────────────────────────────────────────────────────────────

EPISODE_CACHE_DIR = Path("data/EpisodeCache")


# ── Dependencies ──────────────────────────────────────────────────────────


def get_episode_cache_dir() -> Path:
    """Provide the episode cache directory path.

    Override in tests via ``app.dependency_overrides`` to point at
    a temporary directory.
    """
    return EPISODE_CACHE_DIR


# ── Routes ────────────────────────────────────────────────────────────────


@router.get("/cache/status")
def cache_status(
    cache_dir: Path = Depends(get_episode_cache_dir),
) -> dict[str, int | str | None]:
    """Return episode cache statistics.

    Returns
    -------
    dict
        - ``cached_count`` (int): Number of cached episode JSON files.
        - ``latest_episode_id`` (int | None): The highest episode ID
          found in the cache, or ``None`` if the cache is empty or
          does not exist.
    """
    if not cache_dir.is_dir():
        return {
            "cached_count": 0,
            "latest_episode_id": None,
        }

    cached: list[int] = []

    try:
        for entry in os.listdir(cache_dir):
            if entry.startswith("ep_") and entry.endswith(".json"):
                try:
                    num_str = entry[3:-5]  # "ep_42.json" → "42"
                    cached.append(int(num_str))
                except ValueError:
                    continue
    except OSError:
        pass

    cached.sort()
    return {
        "cached_count": len(cached),
        "latest_episode_id": cached[-1] if cached else None,
    }


@router.get("/{episode_id}", response_model=Episode)
def get_episode(
    episode_id: int,
    cache_dir: Path = Depends(get_episode_cache_dir),
) -> Episode:
    """Serve a cached episode in FormatSpec v3 format.

    Episodes are stored as individual JSON files in
    ``data/EpisodeCache/ep_{episode_id}.json``.

    Returns a complete :class:`Episode` with ``meta``, ``messages``,
    and ``vocab``.

    Raises:
        NotFoundError: If the episode file does not exist.
    """
    ep_path = cache_dir / f"ep_{episode_id:04d}.json"

    if not ep_path.is_file():
        raise NotFoundError(f"Episode {episode_id} not found in cache")

    return Episode.model_validate_json(ep_path.read_text(encoding="utf-8"))


__all__ = ["router", "get_episode_cache_dir"]
