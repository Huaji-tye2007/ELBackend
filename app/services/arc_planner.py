"""Arc Planner service — determines episode boundaries, source text slicing, and Arc-level story planning.

This module provides configurable constants and a pure helper function
``_slice_episode_text`` that slices a portion of source text for a single
episode based on word-based offsets and overlap.
"""

from __future__ import annotations

from typing import Any

from app.models.arc_plan import ArcPlan, EpisodeSlot, PendingWord
from app.models.chapter import Chapter
from app.models.progress import ReadingProgress

# ---------------------------------------------------------------------------
# Configuration constants
# ---------------------------------------------------------------------------

DEFAULT_EPISODES_PER_ARC = 10
"""Default number of episodes produced per Arc."""

MIN_EPISODE_WORDS = 400
"""Minimum word count for a sliced episode."""

MAX_EPISODE_WORDS = 600
"""Maximum word count for a sliced episode."""

OVERLAP_WORDS = 100
"""Number of words of backward overlap between consecutive episodes."""

SIDE_EP_REJECT_THRESHOLD = 3
"""Number of times a pending word can be rejected before being dropped from
side episodes."""

SIDE_EP_TRIGGER_MIN_WORDS = 5  # qualifying words needed to trigger side episode

SIDE_EPISODE_POSITION = -1  # -1 means "last episode" (calculated from episodes_per_arc)

PREVIOUS_CONTEXT_MESSAGE_COUNT = 10


# ---------------------------------------------------------------------------
# Pure helper functions
# ---------------------------------------------------------------------------


def _slice_episode_text(
    text: str,
    start_word_offset: int,
    min_words: int,
    max_words: int,
    overlap_words: int,
) -> tuple[str, int]:
    """Slice a portion of text from *start_word_offset* for an episode.

    Words are defined by whitespace splitting (``str.split()``).  The
    function extracts up to *max_words* words (but at least *min_words*
    when enough text remains) and returns the next start offset so that
    consecutive slices share *overlap_words* words of backward overlap.

    Args:
        text: Source text whose words are separated by whitespace.
        start_word_offset: 0-based word position to begin the slice.
        min_words: Minimum number of words to extract when enough text
            is available.
        max_words: Maximum number of words to extract.
        overlap_words: Number of words of backward overlap to bake into
            the returned *next_start_word_offset*.

    Returns:
        A tuple ``(sliced_text, next_start_word_offset)``:

        * *sliced_text* – the extracted portion as a single string.
        * *next_start_word_offset* – the 0-based word index where the
          next episode should begin (i.e. ``end_offset - overlap_words``,
          clamped to *start_word_offset*).

        When the remaining text is shorter than *min_words*, the
        function returns whatever is available.  When *start_word_offset*
        is past the end of the text, it returns ``("", 0)``.
    """
    words = text.split()
    total = len(words)
    remaining = total - start_word_offset

    if remaining <= 0:
        return ("", 0)

    # Pick end: try max_words, but never exceed what is available.
    end_offset = start_word_offset + min(remaining, max_words)
    sliced_words = words[start_word_offset:end_offset]
    sliced_text = " ".join(sliced_words)

    # Next starting position with backward overlap.
    next_start = end_offset - overlap_words
    if next_start < start_word_offset:
        next_start = start_word_offset

    return (sliced_text, next_start)


# ---------------------------------------------------------------------------
# ArcPlanner — orchestrates Arc-level planning
# ---------------------------------------------------------------------------


class ArcPlanner:
    """Plans an Arc — determines episode boundaries and slices source text.

    Pure computation module. No LLM calls, no ECDICT, no FSRS.
    """

    def __init__(self, config: dict | None = None) -> None:
        """Initialise with optional configuration overrides.

        Args:
            config: Optional dictionary with keys matching module-level
                constants (min_episode_words, max_episode_words, etc.).
                Missing keys fall back to module defaults.
        """
        self.config: dict = {
            "episodes_per_arc": DEFAULT_EPISODES_PER_ARC,
            "min_episode_words": MIN_EPISODE_WORDS,
            "max_episode_words": MAX_EPISODE_WORDS,
            "overlap_words": OVERLAP_WORDS,
            "side_ep_reject_threshold": SIDE_EP_REJECT_THRESHOLD,
            "side_ep_trigger_min_words": SIDE_EP_TRIGGER_MIN_WORDS,
            "side_episode_position": SIDE_EPISODE_POSITION,
        }
        if config:
            self.config.update(config)

    def plan_next_arc(
        self,
        arc_id: str,
        progress: ReadingProgress,
        chapters: list[Chapter],
        prev_arc: ArcPlan | None,
        episode_cache: Any,  # JSONStorage duck-type (has .load())
    ) -> tuple[ArcPlan, int, int]:
        """Plan the next Arc — extract source text for episodes.

        Args:
            arc_id: Unique identifier for this arc (e.g. "arc_003").
            progress: ReadingProgress with current_chapter, chapter_offset.
            chapters: List of Chapter models from ChapterDB.
            prev_arc: Previous ArcPlan or None for first arc.
            episode_cache: Episode cache object (duck-typed) or None.

        Returns:
            Tuple of (ArcPlan, end_chapter_id, end_word_offset).

        Raises:
            NotImplementedError: Skeleton — implementation in later tasks.
        """
        # 1. Validate inputs
        self._validate_inputs(progress=progress, chapters=chapters)

        # 2. Build episodes
        episodes, end_chapter_id, end_word_offset = self._build_episodes(
            arc_id=arc_id,
            progress=progress,
            chapters=chapters,
            prev_arc=prev_arc,
            episode_cache=episode_cache,
        )

        # 3. Build pending_words (empty for now — filled by StoryRewriter later)
        pending_words: list[PendingWord] = []

        # 4. Construct ArcPlan
        arc_plan = ArcPlan(
            arc_id=arc_id,
            pending_words=pending_words,
            episodes=episodes,
        )

        return (arc_plan, end_chapter_id, end_word_offset)

    def _validate_inputs(
        self,
        progress: ReadingProgress,
        chapters: list[Chapter],
    ) -> None:
        """Validate input parameters before planning.

        Args:
            progress: ReadingProgress model.
            chapters: List of Chapter models.

        Raises:
            ValueError: If chapter_offset is out of [0, 1] range or
                chapters list is empty.
        """
        if not chapters:
            raise ValueError("No chapters available — ChapterDB is empty")

        offset = progress.chapter_offset
        if not (0 <= offset <= 1):
            raise ValueError(f"chapter_offset must be in [0, 1], got {offset}")

    def _extract_source_text(
        self,
        chapters: list[Chapter],
        start_chapter_id: int,
        start_word_offset: int,
        num_words: int,
    ) -> tuple[str, int, int]:
        """Extract *num_words* of text starting from a specific chapter position.

        Walks through chapters sequentially.  Crosses chapter boundaries
        when one chapter runs out of words.  Returns partial text if the
        total available text is insufficient.

        Args:
            chapters: List of Chapter models with ``chapter_id`` and ``raw_text``.
            start_chapter_id: Chapter ID to start from (1-indexed).
            start_word_offset: 0-indexed word position within start chapter.
            num_words: Number of words to extract.

        Returns:
            Tuple of ``(extracted_text, end_chapter_id, end_word_offset)``.
            *end_word_offset* is the position **after** the last extracted word
            within *end_chapter_id*.
        """
        collected: list[str] = []
        chapter_index = start_chapter_id
        end_chapter_id = start_chapter_id
        end_word_offset = start_word_offset

        while len(collected) < num_words:
            ch = next((c for c in chapters if c.chapter_id == chapter_index), None)
            if ch is None:
                break

            ch_words = ch.raw_text.split()
            remaining_needed = num_words - len(collected)

            # Determine start index within this chapter
            if chapter_index == start_chapter_id:
                start_idx = start_word_offset
            else:
                start_idx = 0

            available = len(ch_words) - start_idx

            if available >= remaining_needed:
                collected.extend(ch_words[start_idx : start_idx + remaining_needed])
                end_chapter_id = chapter_index
                end_word_offset = start_idx + remaining_needed
                return (" ".join(collected), end_chapter_id, end_word_offset)

            # Consume all remaining words from this chapter
            collected.extend(ch_words[start_idx:])
            end_chapter_id = chapter_index
            end_word_offset = len(ch_words)
            chapter_index += 1

        return (" ".join(collected), end_chapter_id, end_word_offset)

    def _should_add_side_episode(self, prev_arc: ArcPlan | None) -> bool:
        """Check whether a side episode should be created for this arc.

        A side episode is triggered when the previous arc has at least
        ``side_ep_trigger_min_words`` pending words with ``rejected_count`` >=
        ``side_ep_reject_threshold``.

        Args:
            prev_arc: Previous ArcPlan or ``None`` (first arc).

        Returns:
            ``True`` if a side episode should be created.
        """
        if prev_arc is None:
            return False

        pending = prev_arc.pending_words
        qualifying = sum(
            1
            for pw in pending
            if pw.rejected_count >= self.config["side_ep_reject_threshold"]
        )
        return qualifying >= self.config["side_ep_trigger_min_words"]

    def _read_previous_context(
        self,
        episode_cache: Any,  # JSONStorage duck-type (has async .load())
        prev_arc: ArcPlan | None,
        episode_index: int,
    ) -> list[dict]:
        """Read previous_context from episode cache for the first episode.

        Only episode 0 (the first episode in an arc) needs context from the
        previous arc's last episode.  All other episodes, and the first arc,
        return an empty list.

        Args:
            episode_cache: Episode cache object (must have ``.load()`` method
                returning episode data) or ``None``.
            prev_arc: Previous ArcPlan or ``None`` (first arc).
            episode_index: 0-based index of the current episode within the arc.

        Returns:
            List of message dicts for previous_context, or empty list.
        """
        if episode_index != 0 or prev_arc is None or episode_cache is None:
            return []

        try:
            # Get the last episode ID from the previous arc to load its cache
            prev_episodes = prev_arc.episodes
            if not prev_episodes:
                return []
            last_ep_id = prev_episodes[-1].episode_id

            cached = episode_cache.load(episode_id=last_ep_id)

            if isinstance(cached, dict):
                # Return only the last N messages as previous_context
                messages = cached.get("messages", [])
                if len(messages) > PREVIOUS_CONTEXT_MESSAGE_COUNT:
                    return messages[-PREVIOUS_CONTEXT_MESSAGE_COUNT:]
                return messages

            return []
        except Exception:
            return []

    def _build_episodes(
        self,
        arc_id: str,
        progress: ReadingProgress,
        chapters: list[Chapter],
        prev_arc: ArcPlan | None,
        episode_cache: Any,  # JSONStorage duck-type (has async .load())
    ) -> tuple[list[EpisodeSlot], int, int]:
        """Build episode slots from chapter text.

        Iterates through chapters producing episodes with backward overlap
        between consecutive main episodes.  Stops early if text is exhausted.

        Args:
            arc_id: Arc identifier (passed through to episode metadata).
            progress: ReadingProgress with current_chapter and chapter_offset (float 0-1).
            chapters: List of Chapter models from ChapterDB.
            prev_arc: Previous ArcPlan or ``None``.
            episode_cache: Episode cache object or ``None``.

        Returns:
            Tuple of ``(episodes, end_chapter_id, end_word_offset)``.
            *episodes* is a list of EpisodeSlot models.
        """
        episodes: list[EpisodeSlot] = []
        max_episodes = self.config["episodes_per_arc"]
        max_words = self.config["max_episode_words"]
        overlap = self.config["overlap_words"]

        # Compute side episode target index from config
        side_ep_index = self.config["side_episode_position"]
        if side_ep_index < 0:
            side_ep_index = max_episodes + side_ep_index  # -1 → max_episodes - 1

        # Determine starting position from progress
        current_chapter_id: int = progress.current_chapter
        chapter_offset: float = progress.chapter_offset

        start_ch = next(
            (c for c in chapters if c.chapter_id == current_chapter_id), None
        )
        if start_ch is None:
            return ([], current_chapter_id, 0)

        chapter_word_count = len(start_ch.raw_text.split())
        word_pos = int(chapter_word_count * chapter_offset)

        # Determine starting episode_id
        if prev_arc and prev_arc.episodes:
            start_ep_id = prev_arc.episodes[-1].episode_id + 1
        else:
            start_ep_id = 1

        # Last chapter for end-of-text detection
        last_chapter_id = max(c.chapter_id for c in chapters)
        last_ch = next(c for c in chapters if c.chapter_id == last_chapter_id)
        last_chapter_word_count = len(last_ch.raw_text.split())

        end_ch: int = current_chapter_id
        end_off: int = word_pos

        for ep_index in range(max_episodes):
            episode_id = start_ep_id + ep_index

            # Check for side episode at the configured position
            if ep_index == side_ep_index and self._should_add_side_episode(prev_arc):
                episode = EpisodeSlot(
                    episode_id=episode_id,
                    episode_type="side",
                    source_text=None,
                    previous_context=self._read_previous_context(
                        episode_cache=episode_cache,
                        prev_arc=prev_arc,
                        episode_index=ep_index,
                    ),
                    target_words=[],
                )
                episodes.append(episode)
                end_ch = current_chapter_id
                end_off = word_pos
                continue  # skip text extraction for side episode

            source_text, end_ch, end_off = self._extract_source_text(
                chapters=chapters,
                start_chapter_id=current_chapter_id,
                start_word_offset=word_pos,
                num_words=max_words,
            )

            source_word_count = len(source_text.split()) if source_text else 0

            # Stop if no more text available
            if source_word_count == 0:
                # If text exhausted and side episode would have been at a later
                # position, insert it now before breaking
                if self._should_add_side_episode(prev_arc):
                    side_inserted = any(ep.episode_type == "side" for ep in episodes)
                    if not side_inserted:
                        side_ep = EpisodeSlot(
                            episode_id=episode_id,
                            episode_type="side",
                            source_text=None,
                            previous_context=self._read_previous_context(
                                episode_cache=episode_cache,
                                prev_arc=prev_arc,
                                episode_index=ep_index,
                            ),
                            target_words=[],
                        )
                        episodes.append(side_ep)
                break

            # Stop after appending if we've exhausted all text
            text_exhausted = (
                end_ch == last_chapter_id and end_off >= last_chapter_word_count
            )

            episode = EpisodeSlot(
                episode_id=episode_id,
                episode_type="main",
                source_text=source_text,
                previous_context=self._read_previous_context(
                    episode_cache=episode_cache,
                    prev_arc=prev_arc,
                    episode_index=ep_index,
                ),
                target_words=[],
            )
            episodes.append(episode)

            if text_exhausted:
                # If text exhausted and side episode would have been at a later
                # position, insert it now before breaking
                if self._should_add_side_episode(prev_arc):
                    side_inserted = any(ep.episode_type == "side" for ep in episodes)
                    if not side_inserted:
                        side_ep = EpisodeSlot(
                            episode_id=episode_id + 1,
                            episode_type="side",
                            source_text=None,
                            previous_context=self._read_previous_context(
                                episode_cache=episode_cache,
                                prev_arc=prev_arc,
                                episode_index=ep_index,
                            ),
                            target_words=[],
                        )
                        episodes.append(side_ep)
                break

            # Update position for next episode with backward overlap
            if source_word_count >= overlap:
                next_start = end_off - overlap
                if next_start < 0:
                    # Backward overlap crosses chapter boundary.
                    # Example: end_off=50 in ch3, overlap=100 → next_start=-50
                    # This means we need to go 50 words before ch3's start,
                    # which is prev_wc - 50 (i.e., prev_wc + next_start since next_start = -50)
                    prev_ch_id = end_ch - 1 if end_ch > 1 else 1
                    prev_ch = next(
                        (c for c in chapters if c.chapter_id == prev_ch_id), None
                    )
                    if prev_ch:
                        prev_wc = len(prev_ch.raw_text.split())
                        word_pos = prev_wc + next_start  # negative offset
                        current_chapter_id = prev_ch_id
                    else:
                        word_pos = 0
                        current_chapter_id = end_ch
                else:
                    current_chapter_id = end_ch
                    word_pos = next_start
            else:
                current_chapter_id = end_ch
                word_pos = end_off

        return (episodes, end_ch, end_off)
