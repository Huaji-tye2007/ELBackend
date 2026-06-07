"""Health-check endpoint: GET /health.

No dependencies — returns a static {"status": "ok"} response.
"""

from fastapi import APIRouter

from app.api.v1.schemas import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """Return service health status.

    Always returns ``{"status": "ok"}``. Used by load balancers and
    monitoring to verify the service is running.
    """
    return HealthResponse(status="ok")


__all__ = ["router"]
