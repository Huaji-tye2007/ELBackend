"""FastAPI application entry point.

Creates the FastAPI instance, configures lifespan, CORS, exception
handlers, and mounts API routes.  All optional dependencies (router,
ArcGenerationManager) are lazy-loaded so that tests and lightweight
CLI usage do not require the full module tree to be available.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.exceptions import (
    ECDictUnavailableError,
    GenerationConflictError,
    LLMError,
    NotFoundError,
    ValidationError,
)

if TYPE_CHECKING:
    pass


# ── Lifespan ────────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan — start-up and shut-down hooks.

    On start-up, attempts to resume a partially-completed
    ``ArcGenerationManager`` run (if the service was restarted during
    generation).  On shut-down, performs graceful cleanup.
    """
    # ── Startup ─────────────────────────────────────────────────────────
    try:
        from app.core.dependencies import (
            get_arc_generation_manager,
            get_chapter_db_storage,
            get_progress,
            get_user_vocab,
        )

        mgr = get_arc_generation_manager()
        app.state.arc_manager = mgr
        await mgr.resume_on_startup()
        state = await mgr.get_status()
        if state.phase not in ("IDLE", "COMPLETE", "FAILED"):
            chapter_db = get_chapter_db_storage().load()
            await mgr.resume_pipeline(
                user_id="default",
                progress=get_progress(),
                chapters=chapter_db.chapters,
                user_vocab=get_user_vocab(),
            )
    except ImportError:
        # ArcGenerationManager not yet implemented — safe to ignore
        pass
    except Exception:
        # Any runtime error during resume must not prevent app start
        pass

    yield  # ─────────────────────────────────────────────────────────────

    # ── Shutdown ────────────────────────────────────────────────────────
    # No persistent resources to release in MVP (JSON file storage is
    # stateless per-operation).


# ── Application ─────────────────────────────────────────────────────────


app = FastAPI(
    title="ELBackend",
    description="Episodic Language Learning — FastAPI backend",
    version="1.5.0",
    lifespan=lifespan,
)

# ── CORS ────────────────────────────────────────────────────────────────

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Exception handlers ──────────────────────────────────────────────────


@app.exception_handler(NotFoundError)
async def not_found_handler(request: Request, exc: NotFoundError) -> JSONResponse:
    """Map ``NotFoundError`` → HTTP 404."""
    return JSONResponse(
        status_code=404,
        content={"detail": str(exc) or "Resource not found"},
    )


@app.exception_handler(ValidationError)
async def validation_error_handler(
    request: Request, exc: ValidationError
) -> JSONResponse:
    """Map ``ValidationError`` → HTTP 400."""
    return JSONResponse(
        status_code=400,
        content={"detail": str(exc) or "Validation failed"},
    )


@app.exception_handler(LLMError)
async def llm_error_handler(request: Request, exc: LLMError) -> JSONResponse:
    """Map ``LLMError`` → HTTP 502."""
    return JSONResponse(
        status_code=502,
        content={"detail": str(exc) or "LLM service unavailable"},
    )


@app.exception_handler(GenerationConflictError)
async def conflict_error_handler(
    request: Request, exc: GenerationConflictError
) -> JSONResponse:
    """Map ``GenerationConflictError`` → HTTP 409."""
    return JSONResponse(
        status_code=409,
        content={"detail": str(exc) or "Generation job already in progress"},
    )


@app.exception_handler(ECDictUnavailableError)
async def ecdict_error_handler(
    request: Request, exc: ECDictUnavailableError
) -> JSONResponse:
    """Map ``ECDictUnavailableError`` → HTTP 503."""
    return JSONResponse(
        status_code=503,
        content={"detail": str(exc) or "Dictionary service unavailable"},
    )


@app.exception_handler(ValueError)
async def value_error_handler(request: Request, exc: ValueError) -> JSONResponse:
    """Map stdlib ``ValueError`` → HTTP 400 (same as ValidationError)."""
    return JSONResponse(
        status_code=400,
        content={"detail": str(exc) or "Bad request"},
    )


@app.exception_handler(KeyError)
async def key_error_handler(request: Request, exc: KeyError) -> JSONResponse:
    """Map stdlib ``KeyError`` → HTTP 404 (same as NotFoundError)."""
    return JSONResponse(
        status_code=404,
        content={"detail": f"Key not found: {exc}"},
    )


# ── Health check ────────────────────────────────────────────────────────


@app.get("/health", tags=["system"])
async def health_check() -> dict[str, str]:
    """Liveness probe — returns ``{"status": "ok"}``."""
    return {"status": "ok"}


# ── Route mounting ──────────────────────────────────────────────────────

# Lazy import so that test suites can import ``app`` without the full
# ``api/v1`` sub-package being available.
try:
    from app.api.v1.router import router as v1_router

    app.include_router(v1_router, prefix="/api/v1")
except ImportError:
    pass
