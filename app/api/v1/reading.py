"""Reading endpoints: progress, log, and finish.

Ref: AGENTS.md §10 — endpoint table.
Exception translation: AGENTS.md §15.2.
"""

from fastapi import APIRouter, Depends, HTTPException

from app.api.v1.schemas import (
    FinishEpisodeRequest,
    FinishEpisodeResponse,
    ReadingLogResponse,
)
from app.core.dependencies import (
    get_mastery_evaluator,
    get_reading_tracker,
    get_user_vocab_storage,
)
from app.db.storage import JSONStorage
from app.models.episode_log import EpisodeReadingLog
from app.models.progress import ReadingProgress
from app.models.vocabulary import UserVocabulary
from app.services.mastery_evaluator import MasteryEvaluator
from app.services.reading_tracker import ReadingTracker

router = APIRouter(prefix="/reading", tags=["reading"])
progress_router = APIRouter(tags=["reading"])


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/progress", response_model=ReadingProgress)
@progress_router.get("/progress", response_model=ReadingProgress)
async def get_progress(
    tracker: ReadingTracker = Depends(get_reading_tracker),
) -> ReadingProgress:
    """Return the current reading progress.

    Includes current chapter, episode, chapter offset, and total
    episodes read count.
    """
    return tracker.get_progress()


@router.post("/log", response_model=ReadingLogResponse)
async def log_reading(
    log: EpisodeReadingLog,
    tracker: ReadingTracker = Depends(get_reading_tracker),
) -> ReadingLogResponse:
    """Record frontend-reported reading behavior for an episode.

    The request body carries per-word appearance counts and click events.
    The server stores them and updates progress counters.
    """
    try:
        tracker.track(log)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ReadingLogResponse(updated=True)


@router.post("/finish", response_model=FinishEpisodeResponse)
async def finish_episode(
    request: FinishEpisodeRequest,
    tracker: ReadingTracker = Depends(get_reading_tracker),
    evaluator: MasteryEvaluator = Depends(get_mastery_evaluator),
    vocab_storage: JSONStorage[UserVocabulary] = Depends(get_user_vocab_storage),
) -> FinishEpisodeResponse:
    """Complete an episode — trigger MasteryEvaluator to update FSRS cards.

    Loads the stored reading log for this episode, loads current
    UserVocabulary, runs the 7-step FSRS pipeline, and persists
    the updated vocabulary.

    Returns the number of vocabulary items whose FSRS cards were updated.
    """
    episode_log = tracker.get_log(request.episode_id)
    if episode_log is None:
        raise HTTPException(
            status_code=404,
            detail=f"No reading log found for episode {request.episode_id}",
        )

    try:
        user_vocab = vocab_storage.load()
    except FileNotFoundError:
        raise HTTPException(
            status_code=404,
            detail="No vocabulary data found — upload vocabulary first",
        )

    if hasattr(evaluator, "evaluate_with_stats"):
        updated_vocab, updated_count = evaluator.evaluate_with_stats(
            episode_log, user_vocab
        )
    else:
        updated_vocab = evaluator.evaluate(episode_log, user_vocab)
        known_item_ids = user_vocab.vocab_index
        updated_count = len(
            {wl.item_id for wl in episode_log.word_logs if wl.item_id in known_item_ids}
        )
    vocab_storage.save(updated_vocab)

    return FinishEpisodeResponse(vocab_updated_count=updated_count)


__all__ = ["router", "progress_router"]
