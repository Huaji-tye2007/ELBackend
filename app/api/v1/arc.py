"""Arc generation endpoints: trigger generation and poll status.

Ref: AGENTS.md §10 — endpoint table, §14 — Async Task Architecture.
Exception translation: AGENTS.md §15.2.
"""

from fastapi import APIRouter, Depends, HTTPException

from app.api.v1.schemas import ArcGenerateRequest, ArcGenerateResponse
from app.core.dependencies import get_arc_generation_manager
from app.core.exceptions import GenerationConflictError
from app.models.arc_generation import ArcGenerationState

router = APIRouter(prefix="/arc", tags=["arc"])


@router.post("/generate", response_model=ArcGenerateResponse)
async def generate_arc(
    request: ArcGenerateRequest = ArcGenerateRequest(),
    arc_manager=Depends(get_arc_generation_manager),
) -> ArcGenerateResponse:
    """Manually trigger Arc generation.

    Accepts an optional ``arc_id``.  Returns a ``job_id`` and status
    ``"queued"``.  If a generation job is already in progress, returns
    HTTP 409 (conflict).

    Frontend should poll GET /arc/status for progress updates.
    """
    try:
        result = await arc_manager.start_generation(arc_id=request.arc_id)
    except GenerationConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

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
