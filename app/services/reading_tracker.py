"""ReadingTracker — tracks reading progress and episode interaction logs.

Ref: AGENTS.md §11 (#8) and documents/BACKEND_IN_OUT.md §四.8.

Maintains singleton in-memory progress state and a log store for
MasteryEvaluator consumption on episode finish.
"""

from __future__ import annotations

import logging

from app.models.episode_log import EpisodeReadingLog
from app.models.progress import ReadingProgress

logger = logging.getLogger(__name__)


class ReadingTracker:
    """Tracks reading position and word interaction logs.

    Public API:
        track(episode_log) -> bool
        get_progress() -> ReadingProgress
        get_log(episode_id) -> EpisodeReadingLog | None
    """

    def __init__(self) -> None:
        self._progress = ReadingProgress(
            current_chapter=1,
            current_episode=1,
            chapter_offset=0.0,
            total_episodes_read=0,
        )
        self._logs: dict[int, EpisodeReadingLog] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def track(self, episode_log: EpisodeReadingLog) -> bool:
        """Record an episode's reading log and update progress.

        Args:
            episode_log: Per-word appearance/click data for one episode.

        Returns:
            True if the log was successfully recorded.
        """
        logger.info(
            "Tracking episode %d with %d word logs",
            episode_log.episode_id,
            len(episode_log.word_logs),
        )
        self._logs[episode_log.episode_id] = episode_log
        self._progress = self._progress.model_copy(
            update={"total_episodes_read": self._progress.total_episodes_read + 1}
        )
        return True

    def get_progress(self) -> ReadingProgress:
        """Return the current reading progress state."""
        return self._progress

    def get_log(self, episode_id: int) -> EpisodeReadingLog | None:
        """Retrieve a previously stored episode reading log.

        Args:
            episode_id: The episode identifier to look up.

        Returns:
            The stored log, or None if no log exists for this episode.
        """
        return self._logs.get(episode_id)
