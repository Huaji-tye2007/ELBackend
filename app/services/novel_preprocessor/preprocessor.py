"""NovelPreprocessor service — ingests raw novel text and produces Chapter objects.

This module orchestrates the novel preprocessing pipeline:

1. Split raw text into chapter segments (regex first, LLM fallback).
2. For each chapter, extract metadata via LLM (title, summary, characters, etc.).
3. Build and return a list of :class:`Chapter` Pydantic models.

All operations are in-memory. No file I/O is performed by this module.
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, Field

from app.models.chapter import Chapter
from app.services.novel_preprocessor.chapter_splitter import (
    split_chapters_by_llm,
    split_chapters_regex,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# LLM response models for metadata extraction
# ---------------------------------------------------------------------------

_METADATA_SYSTEM_PROMPT = """You are a literary analyst specializing in novel analysis. Your task is to extract structured metadata from a chapter of a novel.

For the provided chapter text, extract:
- title: A concise, descriptive chapter title (3-10 words) that captures the chapter's essence
- summary: A 2-4 sentence summary of what happens in this chapter. Write in a narrative style
- characters: A list of named characters who appear or are mentioned in this chapter. Include only proper names
- world_setting: A brief description of the primary setting/location where this chapter takes place (3-12 words)
- estimated_reading_time: An estimate of reading time in minutes (integer). Assume average reading speed of 250 words per minute

Be specific and accurate. Only list characters that are explicitly named in the text."""


class _ChapterMetadataResponse(BaseModel):
    """LLM structured-output model for chapter metadata extraction."""

    title: str = Field(
        ..., min_length=1, max_length=120, description="Chapter title (3-10 words)"
    )
    summary: str = Field(
        ..., min_length=20, max_length=500, description="2-4 sentence summary"
    )
    characters: list[str] = Field(
        default_factory=list,
        description="Named characters appearing in this chapter",
    )
    world_setting: str = Field(
        ..., min_length=3, max_length=200, description="Primary setting (3-12 words)"
    )
    estimated_reading_time: int = Field(
        ...,
        ge=1,
        le=120,
        description="Estimated reading time in minutes (≈250 wpm)",
    )


# ---------------------------------------------------------------------------
# Fallback metadata (used when LLM fails)
# ---------------------------------------------------------------------------


def _build_fallback_metadata(
    chapter_index: int,
    text: str,
) -> dict[str, Any]:
    """Build minimal metadata when LLM extraction fails.

    Args:
        chapter_index: 1-based chapter number.
        text: Chapter body text.

    Returns:
        Dict with keys matching Chapter constructor fields (except chapter_id
        and raw_text which are set by the caller).
    """
    word_count = len(text.split())
    estimated_reading_time = max(1, round(word_count / 250))

    return {
        "title": f"Chapter {chapter_index}",
        "summary": f"Chapter {chapter_index} ({word_count} words).",
        "characters": [],
        "world_setting": "Unknown",
        "estimated_reading_time": estimated_reading_time,
    }


# ---------------------------------------------------------------------------
# NovelPreprocessor
# ---------------------------------------------------------------------------


class NovelPreprocessor:
    """Ingests raw novel text and produces structured Chapter objects.

    Orchestrates a two-step pipeline:

    1. **Chapter splitting** — regex heuristics first; falls back to LLM if
       no pattern matches.
    2. **Metadata extraction** — LLM-based per-chapter metadata (title,
       summary, characters, world_setting, estimated reading time).

    All LLM calls go through the injected :class:`InstructorClient`.
    On LLM failure, fallback metadata is generated from word counts.

    Usage::

        preprocessor = NovelPreprocessor(llm_client)
        chapters = await preprocessor.preprocess("My Novel", raw_text)
    """

    def __init__(self, llm_client: Any) -> None:  # InstructorClient duck-type
        """Initialise with an LLM client for metadata extraction.

        Args:
            llm_client: An ``InstructorClient`` instance (or duck-typed
                equivalent with ``chat_structured`` method).
        """
        self._llm_client = llm_client

    async def preprocess(self, title: str, raw_text: str) -> list[Chapter]:
        """Preprocess a novel's raw text into a list of :class:`Chapter` objects.

        Args:
            title: The novel's title (reserved for future use; individual
                chapter titles are extracted by the LLM).
            raw_text: The full novel text as a single string.

        Returns:
            List of :class:`Chapter` models, one per detected chapter.

        Raises:
            ValueError: If *raw_text* is empty or whitespace-only.
            LLMError: If both regex AND LLM chapter splitting fail.
        """
        stripped = raw_text.strip()
        if not stripped:
            raise ValueError("raw_text must not be empty")

        # ── Step 1: Split into chapter segments ──────────────────────
        chapter_segments = await self._split_chapters_async(stripped)

        # ── Step 2: Extract metadata for each chapter ────────────────
        chapters: list[Chapter] = []
        for i, (chap_title_hint, chap_text) in enumerate(chapter_segments, start=1):
            chapter = await self._build_chapter(
                chapter_id=i,
                title_hint=chap_title_hint,
                raw_text=chap_text,
            )
            chapters.append(chapter)

        return chapters

    # ── Internal helpers ─────────────────────────────────────────────

    async def _split_chapters_async(self, raw_text: str) -> list[tuple[str, str]]:
        """Split raw text into chapter segments — regex first, LLM fallback.

        Args:
            raw_text: The stripped raw text.

        Returns:
            List of ``(title_hint, body_text)`` tuples.

        Raises:
            LLMError: If both regex and LLM splitting fail.
        """
        result = split_chapters_regex(raw_text)
        if result is not None:
            logger.info("Regex chapter split succeeded: %d chapters found", len(result))
            return result

        logger.warning("Regex chapter split failed; falling back to LLM")
        return await split_chapters_by_llm(raw_text, self._llm_client)

    async def _build_chapter(
        self,
        chapter_id: int,
        title_hint: str,
        raw_text: str,
    ) -> Chapter:
        """Build a single Chapter from a text segment.

        Extracts metadata via LLM, with fallback on failure.

        Args:
            chapter_id: 1-based chapter number.
            title_hint: Heading text from the split step (may be used
                as fallback title).
            raw_text: The full chapter body text.

        Returns:
            A validated :class:`Chapter` model.
        """
        metadata = await self._extract_metadata(raw_text, chapter_id)

        return Chapter(
            chapter_id=chapter_id,
            title=metadata.get("title", title_hint or f"Chapter {chapter_id}"),
            raw_text=raw_text,
            summary=metadata.get("summary", ""),
            characters=metadata.get("characters", []),
            world_setting=metadata.get("world_setting", "Unknown"),
            estimated_reading_time=metadata.get("estimated_reading_time", 1),
        )

    async def _extract_metadata(
        self,
        text: str,
        chapter_index: int,
    ) -> dict[str, Any]:
        """Extract chapter metadata via LLM, or fall back to word-count estimates.

        Args:
            text: Chapter body text.
            chapter_index: 1-based chapter number (for fallback title).

        Returns:
            Dict with keys: title, summary, characters, world_setting,
            estimated_reading_time.
        """
        # Truncate text to avoid overwhelming the LLM
        max_chars = 8000
        truncated = text[:max_chars]

        messages: list[dict] = [
            {"role": "system", "content": _METADATA_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"Extract metadata for the following chapter:\n\n{truncated}",
            },
        ]

        try:
            result: _ChapterMetadataResponse = await self._llm_client.chat_structured(
                messages=messages,
                response_model=_ChapterMetadataResponse,
                max_tokens=1024,
            )
            return {
                "title": result.title,
                "summary": result.summary,
                "characters": result.characters,
                "world_setting": result.world_setting,
                "estimated_reading_time": result.estimated_reading_time,
            }
        except Exception as exc:
            logger.warning(
                "LLM metadata extraction failed for chapter %d: %s. Using fallback.",
                chapter_index,
                exc,
            )
            return _build_fallback_metadata(chapter_index, text)
