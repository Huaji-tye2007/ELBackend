"""Arc generation endpoints: trigger generation and poll status.

Ref: AGENTS.md §10 — endpoint table, §14 — Async Task Architecture.
Exception translation: AGENTS.md §15.2.
"""

from fastapi import APIRouter, Depends, HTTPException

from app.api.v1.schemas import ArcGenerateRequest, ArcGenerateResponse
from app.core.dependencies import (
    get_arc_generation_manager,
    get_chapter_db_storage,
    get_progress,
    get_user_vocab,
)
from app.core.exceptions import GenerationConflictError
from app.models.chapter import ChapterDB
from app.models.arc_generation import ArcGenerationState

router = APIRouter(prefix="/arc", tags=["arc"])


@router.post("/generate", response_model=ArcGenerateResponse)
async def generate_arc(
    request: ArcGenerateRequest = ArcGenerateRequest(),
    arc_manager=Depends(get_arc_generation_manager),
    user_vocab=Depends(get_user_vocab),
    progress=Depends(get_progress),
    chapters=Depends(get_chapter_db_storage),
) -> ArcGenerateResponse:
    """Manually trigger Arc generation.

    Accepts an optional ``arc_id``.  Returns a ``job_id`` and status
    ``"queued"``.  If a generation job is already in progress, returns
    HTTP 409 (conflict).

    Frontend should poll GET /arc/status for progress updates.
    """
    try:
        chapter_db: ChapterDB = chapters.load()
        if not chapter_db.chapters:
            raise HTTPException(
                status_code=400, detail="No chapter data found — upload novel first"
            )

        result = await arc_manager.start_generation(
            arc_id=request.arc_id,
            user_vocab=user_vocab,
            progress=progress,
            chapters=chapter_db.chapters,
        )
    except GenerationConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=404, detail="No chapter data found — upload novel first"
        ) from exc

    return ArcGenerateResponse(
        job_id=result["job_id"],
        status=result["status"],
    )


@router.get("/status", response_model=ArcGenerationState)
async def get_arc_status(
    arc_manager=Depends(get_arc_generation_manager),
) -> ArcGenerationState:
    """Return the current Arc generation state.

    Includes phase, progress counters, retry count, timestamps,
    and any error messages.  Frontend should poll this endpoint
    every 5–10 seconds during generation.
    """
    return await arc_manager.get_status()


__all__ = ["router"]
