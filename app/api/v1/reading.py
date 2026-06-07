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
)
from app.db.storage import JSONStorage
from app.models.episode_log import EpisodeReadingLog
from app.models.progress import ReadingProgress
from app.models.vocabulary import UserVocabulary
from app.services.mastery_evaluator import MasteryEvaluator
from app.services.reading_tracker import ReadingTracker

router = APIRouter(prefix="/reading", tags=["reading"])


# ---------------------------------------------------------------------------
# Dependency stubs (will be migrated to app.core.dependencies — T18)
# ---------------------------------------------------------------------------


def get_user_vocabulary_storage() -> JSONStorage[UserVocabulary]:
    """Return a JSONStorage[UserVocabulary] instance."""
    from pathlib import Path

    return JSONStorage(
        path=Path("data/UserVocabulary.json"),
        model=UserVocabulary,
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/progress", response_model=ReadingProgress)
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
    updated = tracker.track(log)
    return ReadingLogResponse(updated=updated)


@router.post("/finish", response_model=FinishEpisodeResponse)
async def finish_episode(
    request: FinishEpisodeRequest,
    tracker: ReadingTracker = Depends(get_reading_tracker),
    evaluator: MasteryEvaluator = Depends(get_mastery_evaluator),
    vocab_storage: JSONStorage[UserVocabulary] = Depends(get_user_vocabulary_storage),
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

    updated_vocab = evaluator.evaluate(episode_log, user_vocab)
    vocab_storage.save(updated_vocab)

    return FinishEpisodeResponse(vocab_updated_count=len(updated_vocab.vocabulary))


__all__ = ["router", "get_user_vocabulary_storage"]
