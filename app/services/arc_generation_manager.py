"""ArcGenerationManager — asynchronous state machine for Arc generation.

Orchestrates services 1→7 (ArcPlanner → EpisodeFormatter) in sequence
with JSON checkpoint persistence.

Ref: AGENTS.md §14 (Async Task Architecture).
"""

from __future__ import annotations

import asyncio
import datetime
import logging
import uuid

from app.core.exceptions import GenerationConflictError
from app.models.arc_generation import ArcGenerationState

logger = logging.getLogger(__name__)


class ArcGenerationManager:
    """Process-internal state machine for Arc generation.

    MVP: single-process asyncio + JSON checkpoint.  Designed such that
    the public API (start_generation, get_status) stays identical when
    migrating to Taskiq later.

    Public API:
        start_generation(arc_id, user_id) -> dict
        get_status() -> ArcGenerationState
        resume_on_startup() -> None
    """

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._state: ArcGenerationState | None = None
        self._task: asyncio.Task | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def start_generation(
        self, arc_id: str | None = None, user_id: str = "default"
    ) -> dict:
        """Start a new Arc generation job.

        Args:
            arc_id: Optional arc identifier (auto-generated if not provided).
            user_id: User identifier.

        Returns:
            Dict with ``job_id`` and ``status``.

        Raises:
            GenerationConflictError: If another generation is already running.
        """
        async with self._lock:
            if self._state is not None and self._state.phase not in (
                "COMPLETE",
                "FAILED",
                "IDLE",
            ):
                raise GenerationConflictError(
                    "A generation job is already in progress"
                )

            _arc_id = arc_id or f"arc_{uuid.uuid4().hex[:8]}"
            job_id = f"job_{uuid.uuid4().hex[:12]}"

            now = datetime.datetime.now(datetime.timezone.utc)
            self._state = ArcGenerationState(
                arc_id=_arc_id,
                phase="IDLE",
                progress={"current": 0, "total": 0},
                started_at=now,
                updated_at=now,
            )

            logger.info("Arc generation queued — arc_id=%s, job_id=%s", _arc_id, job_id)
            return {"job_id": job_id, "status": "queued"}

    async def get_status(self) -> ArcGenerationState:
        """Return the current generation state.

        If no generation has ever been started, returns an IDLE state.
        """
        if self._state is None:
            return ArcGenerationState(
                arc_id="",
                phase="IDLE",
                progress={"current": 0, "total": 0},
            )
        return self._state

    async def resume_on_startup(self) -> None:
        """Check for an incomplete run and resume it.

        In MVP, reads ``data/arc_generation_state.json`` if it exists.
        """
        from pathlib import Path

        state_path = Path("data/arc_generation_state.json")
        if not state_path.exists():
            logger.info("No checkpoint found — starting fresh.")
            return

        import json

        data = json.loads(state_path.read_text())
        self._state = ArcGenerationState.model_validate(data)

        if self._state.phase not in ("COMPLETE", "FAILED", "IDLE"):
            logger.info(
                "Resuming incomplete generation for arc_id=%s (phase=%s)",
                self._state.arc_id,
                self._state.phase,
            )
            # In MVP, we just restore state; actual resume logic will be added later.
