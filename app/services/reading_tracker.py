"""ReadingTracker — record per-episode reading behaviour and update progress.

Receives word-level interaction data (appeared / clicked) from the frontend,
persists EpisodeReadingLogs, and advances ReadingProgress each time the user
completes an episode.

Ref: AGENTS.md §11 (#8) and documents/BACKEND_IN_OUT.md §四.8.
"""

from __future__ import annotations

import logging
import os
import sqlite3
from pathlib import Path

from app.core.exceptions import ECDictUnavailableError
from app.models.episode_log import EpisodeReadingLog
from app.models.progress import ReadingProgress
from app.utils.atomic_io import atomic_write_json
from app.utils.lemma import lookup_lemma

logger = logging.getLogger(__name__)


class ReadingTracker:
    """Record reading interactions and maintain progress state.

    Usage::

        tracker = ReadingTracker(Path("data"))
        progress = tracker.track(
            episode_log={"episode_id": 3, "word_logs": [...]},
            chapter_id=2,
            chapter_offset=0.42,
        )
        log = tracker.get_log(3)
        progress = tracker.get_progress()
    """

    def __init__(self, data_dir: Path):
        self._data_dir = data_dir
        self._logs_dir = data_dir / "EpisodeReadingLogs"
        self._progress_path = data_dir / "ReadingProgress.json"
        # ECDICT connection — lazy initialised on first use
        self._ecdict_db: sqlite3.Connection | None = None

    def set_ecdict_db(self, db: sqlite3.Connection) -> None:
        """Inject an ECDICT database connection for surface-form resolution.

        Without this, ``track()`` will log a warning when ``word_log.word``
        is supplied without a corresponding ``item_id``.
        """
        self._ecdict_db = db

    # ── Public API ────────────────────────────────────────

    def track(
        self,
        episode_log: EpisodeReadingLog | dict,
        chapter_id: int | None = None,
        chapter_offset: float | None = None,
    ) -> ReadingProgress:
        """Record one episode's reading log and update progress.

        Args:
            episode_log: Either an EpisodeReadingLog model instance or a dict
                matching EpisodeReadingLog schema (validated via model_validate).
            chapter_id: If provided, update ``current_chapter``.
            chapter_offset: If provided, update ``chapter_offset``.
                Must be in [0.0, 1.0].

        Returns:
            The updated ReadingProgress after recording.
        """
        if isinstance(episode_log, dict):
            log = EpisodeReadingLog.model_validate(episode_log)
        else:
            log = episode_log

        if chapter_offset is not None and not (0.0 <= chapter_offset <= 1.0):
            raise ValueError(
                f"chapter_offset must be in [0.0, 1.0], got {chapter_offset}"
            )

        # Resolve surface forms to item_id when ECDICT is available
        self._resolve_word_logs(log)

        logger.info(
            "Tracking episode %d with %d word logs", log.episode_id, len(log.word_logs)
        )

        self._save_log(log)

        progress = self._load_progress()
        self._advance_progress(progress, log.episode_id, chapter_id, chapter_offset)
        self._save_progress(progress)

        return progress

    def get_progress(self) -> ReadingProgress:
        """Return the current reading progress state (loaded from disk)."""
        return self._load_progress()

    def get_log(self, episode_id: int) -> EpisodeReadingLog | None:
        """Retrieve a previously stored episode reading log from disk.

        Args:
            episode_id: The episode identifier to look up.

        Returns:
            The stored log, or None if no log exists for this episode.
        """
        path = self._logs_dir / f"ep_{episode_id:04d}.json"
        if path.exists():
            return EpisodeReadingLog.model_validate_json(
                path.read_text(encoding="utf-8")
            )
        return None

    # ── Surface-form resolution (AGENTS.md §6 full chain) ─

    def _resolve_word_logs(self, log: EpisodeReadingLog) -> None:
        """For each WordLog with a surface ``word`` but no ``item_id``,
        attempt ECDICT-based resolution to fill in ``item_id``.

        Mutates ``log.word_logs`` in-place.
        """
        if self._ecdict_db is None:
            return

        from app.models.vocabulary import UserVocabulary

        # We need UserVocabulary to resolve (lemma, meaning) → item_id.
        # Read it lazily from the same data directory.
        try:
            uv = UserVocabulary.model_validate_json(
                (self._data_dir / "UserVocabulary.json").read_text(encoding="utf-8")
            )
        except (FileNotFoundError, OSError):
            logger.warning("UserVocabulary.json not found — cannot resolve item_ids")
            return

        lemma_index = uv.lemma_index  # dict[(lemma, meaning), item_id]

        for wl in log.word_logs:
            if wl.item_id:
                continue  # already resolved by client
            if not wl.word:
                continue  # no surface form to resolve

            item_id = self._resolve_item_id(wl.word, lemma_index)
            if item_id:
                wl.item_id = item_id
                logger.debug(
                    "Resolved surface %r → lemma %r → item_id %r",
                    wl.word,
                    lookup_lemma(wl.word, self._ecdict_db),
                    item_id,
                )
            else:
                logger.warning(
                    "Could not resolve item_id for surface %r — no matching vocabulary entry",
                    wl.word,
                )

    @staticmethod
    def _resolve_item_id(
        surface: str,
        lemma_index: dict[tuple[str, str], str],
    ) -> str | None:
        """Resolve a surface word form to an item_id via lemma_index.

        Strategy:
        1. If surface is already a lemma and matches exactly one entry → return it.
        2. Otherwise, returns ``None`` (caller decides how to handle).
        """
        # If there's exactly one entry for this lemma (single-sense word),
        # auto-resolve. For polysemous words the client should supply item_id.
        candidates = [
            item_id
            for (lemma, _meaning), item_id in lemma_index.items()
            if lemma.lower() == surface.lower()
        ]
        if len(candidates) == 1:
            return candidates[0]
        return None

    # ── Persistence ───────────────────────────────────────

    def _save_log(self, log: EpisodeReadingLog) -> None:
        os.makedirs(self._logs_dir, exist_ok=True)
        path = self._logs_dir / f"ep_{log.episode_id:04d}.json"
        atomic_write_json(path, log)

    def _load_progress(self) -> ReadingProgress:
        if self._progress_path.exists():
            return ReadingProgress.model_validate_json(
                self._progress_path.read_text(encoding="utf-8")
            )
        return ReadingProgress(
            current_chapter=1,
            current_episode=1,
            chapter_offset=0.0,
            total_episodes_read=0,
        )

    def _save_progress(self, progress: ReadingProgress) -> None:
        os.makedirs(self._data_dir, exist_ok=True)
        atomic_write_json(self._progress_path, progress)

    # ── Progress logic ────────────────────────────────────

    @staticmethod
    def _advance_progress(
        progress: ReadingProgress,
        episode_id: int,
        chapter_id: int | None,
        chapter_offset: float | None,
    ) -> None:
        progress.total_episodes_read += 1

        if chapter_id is not None:
            progress.current_chapter = chapter_id
        if chapter_offset is not None:
            progress.chapter_offset = chapter_offset

        # If the current chapter is fully consumed, roll to the next one
        if progress.chapter_offset >= 1.0:
            progress.current_chapter += 1
            progress.chapter_offset = 0.0

        progress.current_episode = episode_id + 1
