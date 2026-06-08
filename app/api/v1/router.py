"""Aggregate all API v1 sub-routers into a single FastAPI APIRouter.

Mounted by app.main at the ``/api/v1`` prefix (see ``app.main``
``include_router`` call).  This router does NOT carry its own prefix
to avoid double-mounting.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()

# ── Health ────────────────────────────────────────────────────────────

from app.api.v1.health import router as health_router  # noqa: E402

router.include_router(health_router)

# ── Vocabulary ────────────────────────────────────────────────────────

from app.api.v1.vocabulary import router as vocabulary_router  # noqa: E402

router.include_router(vocabulary_router)

# ── Novel ─────────────────────────────────────────────────────────────

try:
    from app.api.v1.novel import router as novel_router

    router.include_router(novel_router)
except ImportError:
    pass

# ── Episode ───────────────────────────────────────────────────────────

try:
    from app.api.v1.episode import router as episode_router

    router.include_router(episode_router)
except ImportError:
    pass

# ── Reading ────────────────────────────────────────────────────────────

from app.api.v1.reading import progress_router, router as reading_router  # noqa: E402

router.include_router(reading_router)
router.include_router(progress_router)

# ── Dictionary ─────────────────────────────────────────────────────────

from app.api.v1.dictionary import router as dictionary_router  # noqa: E402

router.include_router(dictionary_router)

# ── Arc ────────────────────────────────────────────────────────────────

from app.api.v1.arc import router as arc_router  # noqa: E402

router.include_router(arc_router)


__all__ = ["router"]
