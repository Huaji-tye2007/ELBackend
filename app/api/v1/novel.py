"""Novel API endpoints — upload, list, and retrieve chapters.

Ref: AGENTS.md §10, documents/BACKEND_IN_OUT.md §四.1–2.
Exception translation: AGENTS.md §15.2.
"""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends

from app.core.dependencies import (
    get_chapter_db_storage as get_configured_chapter_storage,
    get_novel_preprocessor as get_configured_novel_preprocessor,
)
from app.core.exceptions import NotFoundError
from app.db.storage import JSONStorage
from app.models.chapter import Chapter, ChapterDB

router = APIRouter(prefix="/novel", tags=["novel"])

# ── Dependencies ──────────────────────────────────────────────────────────


def get_chapter_storage() -> JSONStorage[ChapterDB]:
    """Provide JSON storage for ChapterDB."""
    return get_configured_chapter_storage()


def get_novel_preprocessor():
    """Provide a NovelPreprocessor instance from the central DI layer."""
    try:
        return get_configured_novel_preprocessor()
    except ImportError as exc:
        raise NotFoundError(f"NovelPreprocessor not available: {exc}") from exc


# ── Routes ────────────────────────────────────────────────────────────────


@router.post("/upload")
async def upload_novel(
    title: str = Body(..., min_length=1),
    raw_text: str = Body(..., min_length=1),
    preprocessor=Depends(get_novel_preprocessor),
    storage: JSONStorage[ChapterDB] = Depends(get_chapter_storage),
) -> dict[str, int]:
    """Upload a novel title and raw text, preprocess into chapters.

    The pipeline:
    1. ``NovelPreprocessor.preprocess()`` splits raw text into chapters
       and extracts metadata via LLM (with fallback on failure).
    2. The resulting ``ChapterDB`` is persisted to ``data/ChapterDB.json``.

    Returns ``{"chapter_count": N}``.
    """
    chapters: list[Chapter] = await preprocessor.preprocess(title, raw_text)
    db = ChapterDB(chapters=chapters)
    storage.save(db)
    return {"chapter_count": len(chapters)}


@router.get("/chapters", response_model=list[dict])
def get_chapters(
    storage: JSONStorage[ChapterDB] = Depends(get_chapter_storage),
) -> list[dict]:
    """List all chapters, excluding the full raw text.

    Each returned object contains: chapter_id, title, summary,
    characters, world_setting, estimated_reading_time — but **not**
    raw_text (to keep the list payload light).

    Returns an empty list if no novel has been uploaded yet.
    """
    try:
        db = storage.load()
    except FileNotFoundError:
        return []

    return [
        {
            "chapter_id": ch.chapter_id,
            "title": ch.title,
            "summary": ch.summary,
            "characters": ch.characters,
            "world_setting": ch.world_setting,
            "estimated_reading_time": ch.estimated_reading_time,
        }
        for ch in db.chapters
    ]


@router.get("/chapters/{chapter_id}", response_model=Chapter)
def get_chapter(
    chapter_id: int,
    storage: JSONStorage[ChapterDB] = Depends(get_chapter_storage),
) -> Chapter:
    """Get a single chapter by numeric ID, including raw text.

    Raises:
        NotFoundError: If the chapter DB file does not exist or the
            requested chapter_id is not found.
    """
    try:
        db = storage.load()
    except FileNotFoundError:
        raise NotFoundError("No novel has been uploaded yet") from None

    for ch in db.chapters:
        if ch.chapter_id == chapter_id:
            return ch

    raise NotFoundError(f"Chapter {chapter_id} not found")


__all__ = ["router", "get_chapter_storage", "get_novel_preprocessor"]
