"""Chapter splitting strategies — regex heuristics + LLM fallback.

Provides two public functions used by the NovelPreprocessor pipeline:

- ``split_chapters_regex``: Uses a cascade of regular expressions to split
  raw text into chapter-like segments based on common chapter heading patterns.
- ``split_chapters_by_llm``: Falls back to LLM-based splitting when regex
  fails, using the injected InstructorClient for structured output.

Both functions operate in-memory and return lists of (title, text) tuples.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Regex pattern cascade for chapter detection
# ---------------------------------------------------------------------------

_CHAPTER_HEADING_PATTERNS: list[re.Pattern] = [
    # "Chapter 1", "Chapter 10", "Chapter 123" (case-insensitive)
    re.compile(r"^Chapter\s+\d+", re.IGNORECASE | re.MULTILINE),
    # "CHAPTER ONE", "CHAPTER TWO" (uppercase words)
    re.compile(r"^CHAPTER\s+\w+", re.MULTILINE),
    # "1.", "10." standalone numbers followed by period + title
    re.compile(r"^\d+\.\s+\S", re.MULTILINE),
    # "第1章", "第 一 章" (Chinese chapter markers)
    re.compile(r"^第[一二三四五六七八九十百千\d]+\s*章", re.MULTILINE),
]

# Minimum characters for a meaningful chapter body
_MIN_CHAPTER_BODY_LENGTH = 100


# ---------------------------------------------------------------------------
# Regex-based splitting
# ---------------------------------------------------------------------------


def split_chapters_regex(raw_text: str) -> list[tuple[str, str]] | None:
    """Attempt to split *raw_text* into chapters using regex patterns.

    Tries each pattern in :data:`_CHAPTER_HEADING_PATTERNS` in order.  The
    first pattern that yields at least 2 segments with meaningful body text
    is used.  Matches are assumed to be chapter headings.

    Args:
        raw_text: The full novel text as a single string.

    Returns:
        List of ``(title, body)`` tuples if splitting succeeded, or ``None``
        if no pattern produced a valid split.  The title is the matched
        heading line; the body is everything from that heading to the next
        heading (or end of text).  Leading/trailing whitespace is stripped
        from both.
    """
    for pattern in _CHAPTER_HEADING_PATTERNS:
        chapters = _split_by_pattern(raw_text, pattern)
        if chapters and len(chapters) >= 2:
            return chapters
    return None


def _split_by_pattern(text: str, pattern: re.Pattern) -> list[tuple[str, str]] | None:
    """Split text at match positions of *pattern*.

    Returns ``None`` if fewer than 2 segments with valid body lengths are
    produced.
    """
    matches = list(pattern.finditer(text))
    if len(matches) < 2:
        return None

    chapters: list[tuple[str, str]] = []
    for i, match in enumerate(matches):
        start = match.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        segment = text[start:end]

        # Split heading line (first line) from body
        heading_end = segment.find("\n")
        if heading_end == -1:
            heading = segment.strip()
            body = ""
        else:
            heading = segment[:heading_end].strip()
            body = segment[heading_end:].strip()

        if len(body) < _MIN_CHAPTER_BODY_LENGTH:
            continue

        chapters.append((heading, body))

    if len(chapters) < 2:
        return None
    return chapters


# ---------------------------------------------------------------------------
# LLM fallback splitting
# ---------------------------------------------------------------------------

_CHAPTER_SPLIT_SYSTEM_PROMPT = """You are a novel manuscript analyst. Your task is to split a raw text into chapters.

The text may contain chapter headings like "Chapter 1", "CHAPTER ONE", "1. A New Beginning", etc.
If no clear headings exist, identify natural chapter breaks based on scene changes, time jumps,
or major narrative shifts.

For each chapter you identify, provide:
- title: A short, descriptive title (3-10 words) that captures the chapter's essence
- text: The full chapter body text, starting from the chapter beginning (including any heading found)

Do NOT summarize or rewrite the text. Keep the original wording exactly as provided.
Output each chapter as a separate entry in the list."""


class _ChapterSplitSegment(BaseModel):
    """A single chapter identified by the LLM."""

    title: str = Field(..., min_length=1, description="Chapter title (3-10 words)")
    text: str = Field(
        ..., min_length=_MIN_CHAPTER_BODY_LENGTH, description="Full chapter body text"
    )


class _ChapterSplitRequest(BaseModel):
    """LLM structured-output model for chapter splitting (internal use)."""

    chapters: list[_ChapterSplitSegment] = Field(
        ..., min_length=1, description="All chapters identified in the text"
    )


async def split_chapters_by_llm(
    raw_text: str,
    llm_client: Any,  # InstructorClient duck-type
) -> list[tuple[str, str]]:
    """Use LLM to split unstructured raw text into chapters.

    Args:
        raw_text: The full novel text as a single string.
        llm_client: An ``InstructorClient`` instance for structured LLM calls.

    Returns:
        List of ``(title, body)`` tuples extracted by the LLM.

    Raises:
        LLMError: If the LLM call fails or returns invalid data.
    """
    from app.core.exceptions import LLMError  # noqa: E402

    # Truncate text to avoid overwhelming the LLM context window
    max_chars = 30000
    truncated = raw_text[:max_chars]
    if len(raw_text) > max_chars:
        truncated += "\n\n[Note: text was truncated to 30,000 characters for analysis.]"

    messages: list[dict] = [
        {"role": "system", "content": _CHAPTER_SPLIT_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": f"Split the following novel text into chapters:\n\n{truncated}",
        },
    ]

    try:
        result: _ChapterSplitRequest = await llm_client.chat_structured(
            messages=messages,
            response_model=_ChapterSplitRequest,
            max_tokens=8192,
        )
    except Exception as exc:
        raise LLMError(f"Chapter splitting via LLM failed: {exc}") from exc

    if not result.chapters:
        raise LLMError("LLM returned zero chapters when splitting text")

    return [(ch.title, ch.text) for ch in result.chapters]
