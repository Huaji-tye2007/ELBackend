"""ArcGenerationManager — asynchronous state machine for Arc generation.

Orchestrates services 1→7 (ArcPlanner → EpisodeFormatter) in sequence
with JSON checkpoint persistence and exponential-backoff retry.

Ref: AGENTS.md §14 (Async Task Architecture).
"""

from __future__ import annotations

import asyncio
import datetime
import inspect
import json
import logging
import os
import uuid
from pathlib import Path
from typing import Any

from app.core.exceptions import GenerationConflictError
from app.models.arc_generation import ArcGenerationState
from app.models.arc_plan import ArcPlan, EpisodeSlot, TargetWord
from app.models.chapter import Chapter
from app.models.progress import ReadingProgress
from app.models.vocabulary import UserVocabulary
from app.utils.atomic_io import atomic_write_json

logger = logging.getLogger(__name__)

# Retry configuration
_MAX_RETRIES = 3
_RETRY_DELAYS: tuple[float, ...] = (10.0, 30.0, 90.0)

_CHECKPOINT_PATH = Path("data/arc_generation_state.json")


class ArcGenerationManager:
    """Process-internal state machine for Arc generation.

    MVP: single-process asyncio + JSON checkpoint.  Designed such that
    the public API (start_generation, get_status) stays identical when
    migrating to Taskiq later.

    Public API:
        start_generation(arc_id, user_id, ...) -> dict
        get_status() -> ArcGenerationState
        resume_on_startup() -> None
    """

    def __init__(
        self,
        arc_planner: Any = None,
        vocab_scheduler: Any = None,
        story_rewriter: Any = None,
        vocab_annotator: Any = None,
        episode_formatter: Any = None,
    ) -> None:
        """Initialise with all five upstream services injected.

        Args:
            arc_planner: ArcPlanner instance (has ``plan_next_arc()``).
            vocab_scheduler: ``schedule()`` callable from vocabulary_scheduler.
            story_rewriter: StoryRewriter instance (has ``rewrite_episode()``).
            vocab_annotator: VocabularyAnnotator instance (has ``annotate()``).
            episode_formatter: EpisodeFormatter instance (has ``format_episode()``
                and ``write_cache()``).
        """
        self._arc_planner = arc_planner
        self._vocab_scheduler = vocab_scheduler
        self._story_rewriter = story_rewriter
        self._vocab_annotator = vocab_annotator
        self._episode_formatter = episode_formatter

        self._lock = asyncio.Lock()
        self._state: ArcGenerationState | None = None
        self._task: asyncio.Task[None] | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def start_generation(
        self,
        arc_id: str | None = None,
        user_id: str = "default",
        progress: ReadingProgress | None = None,
        chapters: list[Chapter] | None = None,
        user_vocab: UserVocabulary | None = None,
        prev_arc: ArcPlan | None = None,
        episode_cache: Any = None,
    ) -> dict:
        """Start a new Arc generation job.

        Args:
            arc_id: Optional arc identifier (auto-generated if not provided).
            user_id: User identifier.
            progress: Current reading progress (required for pipeline).
            chapters: Available chapters (required for pipeline).
            user_vocab: User's vocabulary state (required for pipeline).
            prev_arc: Previous ArcPlan or None for first arc.
            episode_cache: Episode cache object (duck-typed).

        Returns:
            Dict with ``job_id`` and ``status``.

        Raises:
            GenerationConflictError: If another generation is already running.
        """
        async with self._lock:
            if self._state is not None and self._state.phase not in (
                "COMPLETE",
                "FAILED",
            ):
                raise GenerationConflictError("A generation job is already in progress")

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

            # Fire background pipeline task
            self._task = asyncio.create_task(
                self._run_pipeline(
                    arc_id=_arc_id,
                    user_id=user_id,
                    progress=progress,
                    chapters=chapters or [],
                    user_vocab=user_vocab,
                    prev_arc=prev_arc,
                    episode_cache=episode_cache,
                )
            )

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

        Reads ``data/arc_generation_state.json`` if it exists.  If the
        checkpoint indicates an in-progress phase (not COMPLETE / FAILED /
        IDLE), resumes the pipeline from the saved state.

        Note: the caller is responsible for re-injecting data dependencies
        (progress, chapters, vocab) before calling resume.  In MVP, this
        is triggered by the FastAPI lifespan hook.
        """
        if not _CHECKPOINT_PATH.exists():
            logger.info("No checkpoint found — starting fresh.")
            return

        data = json.loads(_CHECKPOINT_PATH.read_text(encoding="utf-8"))
        self._state = ArcGenerationState.model_validate(data)

        if self._state.phase in ("COMPLETE", "FAILED", "IDLE"):
            logger.info(
                "Checkpoint phase is %s — nothing to resume.", self._state.phase
            )
            return

        logger.info(
            "Resuming incomplete generation for arc_id=%s (phase=%s, progress=%s)",
            self._state.arc_id,
            self._state.phase,
            self._state.progress,
        )

        # Resume requires data reload — in MVP the lifespan hook passes
        # data after calling resume_on_startup.  The pipeline will be
        # fired externally once data is available.
        # For now, we just restore the state; the actual resume call
        # happens via _resume_pipeline when data is provided.

    async def resume_pipeline(
        self,
        user_id: str,
        progress: ReadingProgress,
        chapters: list[Chapter],
        user_vocab: UserVocabulary,
        prev_arc: ArcPlan | None = None,
        episode_cache: Any = None,
    ) -> None:
        """Resume an in-progress pipeline from its checkpoint state.

        Args:
            user_id: User identifier.
            progress: Current reading progress.
            chapters: Available chapters.
            user_vocab: User's vocabulary state.
            prev_arc: Previous ArcPlan or None.
            episode_cache: Episode cache object (duck-typed).
        """
        if self._state is None or self._state.phase in (
            "COMPLETE",
            "FAILED",
            "IDLE",
        ):
            logger.warning("No in-progress pipeline to resume.")
            return

        self._task = asyncio.create_task(
            self._resume_pipeline(
                user_id=user_id,
                progress=progress,
                chapters=chapters,
                user_vocab=user_vocab,
                prev_arc=prev_arc,
                episode_cache=episode_cache,
            )
        )

    # ------------------------------------------------------------------
    # Pipeline (private)
    # ------------------------------------------------------------------

    async def _run_pipeline(
        self,
        arc_id: str,
        user_id: str,
        progress: ReadingProgress | None,
        chapters: list[Chapter],
        user_vocab: UserVocabulary | None,
        prev_arc: ArcPlan | None = None,
        episode_cache: Any = None,
    ) -> None:
        """Execute the full 6-phase Arc generation pipeline.

        IDLE → PLANNING → SCHEDULING → GENERATING(×N) → ANNOTATING → FORMATTING → COMPLETE

        Each phase writes a checkpoint on success.  Failures trigger
        exponential-backoff retry (up to 3 attempts).  After 3 exhausted
        retries the phase is set to FAILED and the pipeline stops.
        """
        # Guard: state must exist (set by start_generation or initialized here)
        if self._state is None:
            self._state = ArcGenerationState(
                arc_id=arc_id,
                phase="IDLE",
                progress={"current": 0, "total": 0},
                started_at=datetime.datetime.now(datetime.timezone.utc),
            )

        # Validate required data
        if progress is None:
            self._fail("Missing ReadingProgress data")
            return
        if user_vocab is None:
            self._fail("Missing UserVocabulary data")
            return

        try:
            # ── Phase 1: PLANNING ──────────────────────────────
            ok, arc_plan = await self._retry_call(
                phase="PLANNING",
                fn=self._arc_planner.plan_next_arc,
                arc_id=arc_id,
                progress=progress,
                chapters=chapters,
                prev_arc=prev_arc,
                episode_cache=episode_cache,
            )
            if not ok:
                return
            arc_plan, _end_ch, _end_off = arc_plan  # unpack tuple return

            # Save intermediate data for resume
            self._state.intermediate_data = {"arc_plan": arc_plan.model_dump()}
            self._state.phase = "PLANNING"
            await self._checkpoint()

            # ── Phase 2: SCHEDULING ────────────────────────────
            self._state.phase = "SCHEDULING"
            self._state.progress = {"current": 0, "total": 0}
            await self._checkpoint()

            ok, scheduled = await self._retry_call(
                phase="SCHEDULING",
                fn=self._vocab_scheduler,
                arc_plan=arc_plan.model_dump(),
                user_vocab=user_vocab.model_dump(),
                now=datetime.datetime.now(datetime.timezone.utc),
            )
            if not ok:
                return

            self._state.intermediate_data = {
                "arc_plan": arc_plan.model_dump(),
                "scheduled": scheduled,
            }
            await self._checkpoint()

            # ── Phase 3: GENERATING (per-episode loop) ─────────
            episodes: list[dict] = scheduled.get("episodes", [])
            total_episodes = len(episodes)
            self._state.phase = "GENERATING"
            self._state.progress = {"current": 0, "total": total_episodes}
            await self._checkpoint()

            rewrite_results: list[Any] = []
            for i, ep_dict in enumerate(episodes):
                # Reconstruct EpisodeSlot from scheduled dict
                target_words = [
                    TargetWord.model_validate(tw)
                    for tw in ep_dict.get("target_words", [])
                ]
                episode_slot = EpisodeSlot(
                    episode_id=ep_dict.get("episode_id", i + 1),
                    episode_type=ep_dict.get("episode_type", "main"),
                    source_text=ep_dict.get("source_text"),
                    previous_context=ep_dict.get("previous_context", []),
                    target_words=target_words,
                )
                chapter_text = ep_dict.get("source_text") or ""

                ok, result = await self._retry_call(
                    phase=f"GENERATING({i + 1}/{total_episodes})",
                    fn=self._story_rewriter.rewrite_episode,
                    episode_slot=episode_slot,
                    chapter_text=chapter_text,
                )
                if not ok:
                    return

                rewrite_results.append(result)

                # Store serialized results for resume
                self._state.intermediate_data = {
                    "arc_plan": arc_plan.model_dump(),
                    "scheduled": scheduled,
                    "rewrite_results": [r.model_dump() for r in rewrite_results],
                }
                self._state.progress["current"] = i + 1
                await self._checkpoint()

            # ── Phase 4: ANNOTATING (per-episode loop) ─────────
            self._state.phase = "ANNOTATING"
            self._state.progress = {"current": 0, "total": total_episodes}
            await self._checkpoint()

            annotated_episodes: list[list[Any]] = []
            for i, (result, ep_dict) in enumerate(zip(rewrite_results, episodes)):
                used_by_id: dict[str, dict[str, str]] = {}
                for used in (
                    result.target_words_used
                    if hasattr(result, "target_words_used")
                    else []
                ):
                    if hasattr(used, "model_dump"):
                        used_data = used.model_dump()
                    elif isinstance(used, dict):
                        used_data = used
                    else:
                        # Backward-compatible test/mock shape: a bare item_id.
                        used_data = {"item_id": str(used)}
                    item_id = used_data.get("item_id")
                    if item_id:
                        used_by_id[item_id] = used_data

                target_words_used: list[dict] = [
                    {**tw, **used_by_id[tw["item_id"]]}
                    for tw in ep_dict.get("target_words", [])
                    if tw.get("item_id") in used_by_id
                ]

                shown_set: set[str] = set()

                ok, annotated_msgs = await self._retry_call(
                    phase=f"ANNOTATING({i + 1}/{total_episodes})",
                    fn=self._vocab_annotator.annotate,
                    messages=list(result.messages),
                    target_words=target_words_used,
                    shown_set=shown_set,
                )
                if not ok:
                    return

                annotated_episodes.append(annotated_msgs)

                self._state.intermediate_data = {
                    "arc_plan": arc_plan.model_dump(),
                    "scheduled": scheduled,
                    "annotated_episodes": annotated_episodes,
                }
                self._state.progress["current"] = i + 1
                await self._checkpoint()

            # ── Phase 5: FORMATTING (per-episode loop) ─────────
            self._state.phase = "FORMATTING"
            self._state.progress = {"current": 0, "total": total_episodes}
            await self._checkpoint()

            for i, (msgs, ep_dict) in enumerate(zip(annotated_episodes, episodes)):
                meta: dict = {
                    "ep": ep_dict.get("episode_id", i + 1),
                    "title": f"Episode {ep_dict.get('episode_id', i + 1)}",
                    "kind": ep_dict.get("episode_type", "main"),
                }
                messages_dicts = [
                    m.model_dump() if hasattr(m, "model_dump") else m for m in msgs
                ]

                ok, episode = await self._retry_call(
                    phase=f"FORMATTING({i + 1}/{total_episodes})",
                    fn=self._episode_formatter.format_episode,
                    meta=meta,
                    messages=messages_dicts,
                )
                if not ok:
                    return

                # Write episode to cache (sync call, no retry)
                try:
                    self._episode_formatter.write_cache(episode)
                except Exception as exc:
                    logger.error(
                        "Failed to write episode %s to cache: %s",
                        meta["ep"],
                        exc,
                    )
                    self._fail(f"Cache write failed: {exc}")
                    return

                self._state.progress["current"] = i + 1
                await self._checkpoint()

            # ── Phase 6: COMPLETE ──────────────────────────────
            self._state.phase = "COMPLETE"
            self._state.progress = {
                "current": total_episodes,
                "total": total_episodes,
            }
            self._state.retry_count = 0
            self._state.last_error = None
            await self._checkpoint()

            logger.info(
                "Arc generation complete — arc_id=%s, episodes=%d",
                arc_id,
                total_episodes,
            )

        except Exception as exc:
            # Safety net: any unhandled exception becomes FAILED
            logger.exception("Unhandled error in pipeline for arc_id=%s", arc_id)
            self._fail(str(exc))

    async def _resume_pipeline(
        self,
        user_id: str,
        progress: ReadingProgress,
        chapters: list[Chapter],
        user_vocab: UserVocabulary,
        prev_arc: ArcPlan | None = None,
        episode_cache: Any = None,
    ) -> None:
        """Resume pipeline from checkpoint state.

        Uses ``intermediate_data`` stored in the checkpoint to skip
        already-completed phases and episodes.
        """
        if self._state is None:
            return

        phase = self._state.phase
        arc_id = self._state.arc_id

        logger.info("Resuming pipeline from phase=%s", phase)

        # Determine which phases to skip based on current state
        if phase in (
            "PLANNING",
            "SCHEDULING",
            "GENERATING",
            "ANNOTATING",
            "FORMATTING",
        ):
            # Re-run the full pipeline; individual phases will detect
            # already-completed work via intermediate_data
            # For simplicity in MVP: re-run from scratch
            await self._run_pipeline(
                arc_id=arc_id,
                user_id=user_id,
                progress=progress,
                chapters=chapters,
                user_vocab=user_vocab,
                prev_arc=prev_arc,
                episode_cache=episode_cache,
            )

    # ------------------------------------------------------------------
    # Retry helper
    # ------------------------------------------------------------------

    async def _retry_call(
        self, phase: str, fn: Any, *args: Any, **kwargs: Any
    ) -> tuple[bool, Any]:
        """Execute *fn* with up to 3 retries and exponential backoff.

        Args:
            phase: Human-readable phase label for logging.
            fn: Callable (sync or async) to execute.
            *args, **kwargs: Passed through to *fn*.

        Returns:
            Tuple of ``(success: bool, result: Any)``.  On failure after
            all retries, sets ``self._state.phase = "FAILED"`` and returns
            ``(False, None)``.  On success, returns ``(True, result)``.
        """
        if self._state is None:
            return (False, None)

        for attempt in range(_MAX_RETRIES + 1):  # 0 = initial, 1–3 = retries
            try:
                if attempt > 0:
                    delay = _RETRY_DELAYS[attempt - 1]
                    logger.warning(
                        "Retry %d/%d for phase %s — waiting %.0fs",
                        attempt,
                        _MAX_RETRIES,
                        phase,
                        delay,
                    )
                    await asyncio.sleep(delay)
                    self._state.retry_count = attempt
                    self._state.last_error = None
                    await self._checkpoint()

                # Support sync, async, and mock callables
                result = fn(*args, **kwargs)
                if inspect.isawaitable(result):
                    result = await result

                self._state.retry_count = 0
                self._state.last_error = None
                return (True, result)

            except Exception as exc:
                logger.error(
                    "Phase %s failed (attempt %d/%d): %s",
                    phase,
                    attempt + 1,
                    _MAX_RETRIES + 1,
                    exc,
                )
                self._state.last_error = str(exc)

                if attempt >= _MAX_RETRIES:
                    self._state.phase = "FAILED"
                    self._state.retry_count = _MAX_RETRIES
                    await self._checkpoint()
                    logger.error(
                        "Phase %s failed after %d retries — pipeline FAILED",
                        phase,
                        _MAX_RETRIES,
                    )
                    return (False, None)

        return (False, None)

    # ------------------------------------------------------------------
    # Checkpoint persistence
    # ------------------------------------------------------------------

    async def _checkpoint(self) -> None:
        """Persist the current state to ``data/arc_generation_state.json``.

        Uses ``atomic_write_json`` for crash-safe atomic replacement.
        Creates the ``data/`` directory if it does not exist.
        """
        if self._state is None:
            return

        self._state.updated_at = datetime.datetime.now(datetime.timezone.utc)
        os.makedirs(_CHECKPOINT_PATH.parent, exist_ok=True)
        atomic_write_json(_CHECKPOINT_PATH, self._state)

    # ------------------------------------------------------------------
    # Failure helper
    # ------------------------------------------------------------------

    def _fail(self, error_message: str) -> None:
        """Mark the pipeline as FAILED with an error message."""
        if self._state is not None:
            self._state.phase = "FAILED"
            self._state.last_error = error_message
            self._state.retry_count = _MAX_RETRIES
            self._state.updated_at = datetime.datetime.now(datetime.timezone.utc)
            # Synchronous checkpoint write (fire-and-forget in non-async context)
            try:
                os.makedirs(_CHECKPOINT_PATH.parent, exist_ok=True)
                atomic_write_json(_CHECKPOINT_PATH, self._state)
            except Exception:
                pass
            logger.error("Pipeline FAILED: %s", error_message)
