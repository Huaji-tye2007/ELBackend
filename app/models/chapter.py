"""Pydantic v2 models for novel chapters: Chapter and ChapterDB.

Ref: AGENTS.md §12 (chapter.py) and documents/BACKEND_IN_OUT.md §三.3.
"""

from pydantic import BaseModel, Field


class Chapter(BaseModel):
    """A single chapter of the source novel.

    Each chapter represents a self-contained segment of the original text,
    with metadata for character tracking and Arc planning.
    """

    chapter_id: int = Field(ge=1)
    title: str
    raw_text: str
    summary: str
    characters: list[str]
    world_setting: str
    estimated_reading_time: int = Field(ge=0)


class ChapterDB(BaseModel):
    """Container for all chapters of a novel.

    Mirrors the JSON file structure loaded by NovelPreprocessor.
    """

    chapters: list[Chapter] = Field(default_factory=list)


__all__ = ["Chapter", "ChapterDB"]
