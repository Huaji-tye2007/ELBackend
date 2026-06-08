"""MasteryEvaluator — 7-step FSRS pipeline for post-episode vocabulary assessment.

Ref: AGENTS.md §11 (#9), BACKEND_IN_OUT.md §四.9.

Pipeline: FIFO push → weighted score → Rating mapping → FSRS review_card
→ cross-day forcing → serialize back to FsrsCard.
"""

from __future__ import annotations

import datetime
import logging

from fsrs import Card, Rating, Scheduler

from app.models.episode_log import EpisodeReadingLog, WordLog
from app.models.fsrs import FsrsCard
from app.models.vocabulary import UserVocabulary, VocabularyItem

logger = logging.getLogger(__name__)


class MasteryEvaluator:
    """Post-episode vocabulary assessment engine.

    Processes EpisodeReadingLog entries against UserVocabulary,
    updating history_window and fsrs_card for each tracked item.

    Public API:
        evaluate(episode_log, user_vocab, now=None) -> UserVocabulary
    """

    def __init__(self) -> None:
        self._scheduler = Scheduler()
        self._weights = [0.1, 0.1, 0.2, 0.2, 0.4]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def evaluate(
        self,
        episode_log: EpisodeReadingLog,
        user_vocab: UserVocabulary,
        now: datetime.datetime | None = None,
    ) -> UserVocabulary:
        """Run the 7-step pipeline on every word_log.

        Args:
            episode_log: Per-word appearance/click data for one episode.
            user_vocab: Current vocabulary state (read-only index lookup).
            now: Reference time for cross-day forcing. Defaults to UTC now.

        Returns:
            A new UserVocabulary with updated history_window and fsrs_card
            for each processed VocabularyItem. Unknown item_ids are skipped.
        """
        updated_vocab, _updated_count = self.evaluate_with_stats(
            episode_log, user_vocab, now
        )
        return updated_vocab

    def evaluate_with_stats(
        self,
        episode_log: EpisodeReadingLog,
        user_vocab: UserVocabulary,
        now: datetime.datetime | None = None,
    ) -> tuple[UserVocabulary, int]:
        """Run the FSRS pipeline and return the updated vocabulary plus update count.

        Args:
            episode_log: Per-word appearance/click data for one episode.
            user_vocab: Current vocabulary state.
            now: Reference time for cross-day forcing. Defaults to UTC now.

        Returns:
            Tuple ``(updated_vocab, updated_count)`` where ``updated_count`` is
            the number of unique known item_ids actually processed.
        """
        if now is None:
            now = datetime.datetime.now(datetime.timezone.utc)

        vocab_index = user_vocab.vocab_index
        updated_items: list[VocabularyItem] = list(user_vocab.vocabulary)
        updated_ids: set[str] = set()

        for word_log in episode_log.word_logs:
            if self._process_one(word_log, vocab_index, updated_items, now):
                updated_ids.add(word_log.item_id)

        return (
            UserVocabulary(
                user_id=user_vocab.user_id,
                vocabulary=updated_items,
            ),
            len(updated_ids),
        )

    # ------------------------------------------------------------------
    # Internal steps
    # ------------------------------------------------------------------

    def _process_one(
        self,
        word_log: WordLog,
        vocab_index: dict[str, VocabularyItem],
        updated_items: list[VocabularyItem],
        now: datetime.datetime,
    ) -> bool:
        """Apply the 7-step algorithm to a single word_log.

        Args:
            word_log: One word's tracking data from the episode.
            vocab_index: O(1) item_id → VocabularyItem lookup.
            updated_items: Mutable list of items (modified in-place).
            now: Reference UTC datetime for cross-day forcing.
        """
        # Step 1: Look up VocabularyItem
        item = vocab_index.get(word_log.item_id)
        if item is None:
            logger.warning("Unknown item_id %s — skipping", word_log.item_id)
            return False

        # Step 2: FIFO push to history_window
        # clicked=0 → push 1 (word appeared but user didn't click → recall success)
        # clicked>0 → push 0 (user clicked for definition → recall failure)
        new_value = 1 if (word_log.appeared > 0 and word_log.clicked == 0) else 0
        new_window = item.history_window[1:] + [new_value]

        # Step 3: Weighted score
        score = sum(w * h for w, h in zip(self._weights, new_window)) / sum(
            self._weights
        )

        # Step 4: Rating mapping
        rating: Rating
        if score >= 0.8:
            rating = Rating.Good
        elif score >= 0.5:
            rating = Rating.Hard
        else:
            rating = Rating.Again

        # Step 5: Create fsrs.Card from our FsrsCard model
        card: Card = item.fsrs_card.to_fsrs_card()

        # Step 6: Call FSRS scheduler
        updated_card, _review_log = self._scheduler.review_card(card, rating)

        # Step 7: Cross-day forcing
        # If the scheduled due is still today (or earlier), push to tomorrow 00:00 UTC.
        # This enforces the "no more than one review per day" constraint.
        end_of_today = now.replace(hour=23, minute=59, second=59, microsecond=0)
        if updated_card.due <= end_of_today:
            tomorrow = datetime.datetime.combine(
                now.date() + datetime.timedelta(days=1),
                datetime.time(0, 0),
                tzinfo=datetime.timezone.utc,
            )
            updated_card.due = tomorrow

        # Step 8: Serialize back to our FsrsCard model
        new_fsrs_card = FsrsCard.from_fsrs_card(updated_card)

        # Update item in-place in the mutable list
        for i, candidate in enumerate(updated_items):
            if candidate.id == word_log.item_id:
                updated_items[i] = item.model_copy(
                    update={
                        "history_window": new_window,
                        "fsrs_card": new_fsrs_card,
                    }
                )
                return True

        # Should not reach here — item was found in vocab_index
        logger.error(
            "Item %s found in vocab_index but not in updated_items list",
            word_log.item_id,
        )
        return False
