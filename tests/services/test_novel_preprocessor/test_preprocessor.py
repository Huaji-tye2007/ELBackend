"""Tests for app.services.novel_preprocessor.preprocessor — NovelPreprocessor."""

from __future__ import annotations

from unittest import mock

import pytest

from app.models.chapter import Chapter
from app.services.novel_preprocessor.preprocessor import (
    NovelPreprocessor,
    _ChapterMetadataResponse,
    _build_fallback_metadata,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Sample text with regex-detectable chapter headings
SAMPLE_NOVEL_TEXT = """Chapter 1: The Transfer Student
The morning light filtered through the classroom windows, casting long rectangles of gold across the polished wooden desks. I stood at the doorway, my fingers wrapped around the strap of my bag so tightly that my knuckles had gone white. The classroom buzzed with the indistinct murmur of conversations — the kind of ambient noise that fills every high school homeroom five minutes before the bell.

Chapter 2: The Library Encounter
Three days had passed since my transfer, and I had settled into something resembling a routine. Wake up at six. Catch the 7:15 train. Arrive at school by 7:45. Sit through classes that I understood maybe half of. Eat lunch with Anna, Mei, and Kenji — a group that had somehow adopted me without any formal discussion.

Chapter 3: The Rooftop Confession
Two weeks had passed since that afternoon in the library, and something had changed between Mei and me. We were not friends, exactly — the word felt too casual, too easy for whatever this was. But we had developed a routine. Every day after school, we would meet in the library."""


def _make_mock_llm(metadata_response):
    """Create an AsyncMock LLM client that returns the given metadata."""
    mock_client = mock.AsyncMock()
    mock_client.chat_structured.return_value = metadata_response
    return mock_client


def _sample_metadata():
    """Create a sample ChapterMetadataResponse."""
    return _ChapterMetadataResponse(
        title="The Beginning",
        summary="A new student arrives at a strange school and makes unexpected friends while discovering hidden secrets about the academy.",
        characters=["Kazuhiko", "Anna", "Mei"],
        world_setting="Modern Japanese high school",
        estimated_reading_time=15,
    )


# ---------------------------------------------------------------------------
# Tests: NovelPreprocessor
# ---------------------------------------------------------------------------


class TestNovelPreprocessor:
    """Tests for ``NovelPreprocessor.preprocess()``."""

    @pytest.mark.asyncio
    async def test_successful_preprocess(self):
        """Full pipeline: regex split + LLM metadata extraction."""
        mock_llm = _make_mock_llm(_sample_metadata())
        preprocessor = NovelPreprocessor(mock_llm)

        chapters = await preprocessor.preprocess("Test Novel", SAMPLE_NOVEL_TEXT)

        assert len(chapters) == 3
        for ch in chapters:
            assert isinstance(ch, Chapter)
            assert ch.chapter_id >= 1
            assert ch.title == "The Beginning"
            assert "Kazuhiko" in ch.characters
            assert ch.world_setting == "Modern Japanese high school"
            assert ch.estimated_reading_time == 15

        # LLM was called for each chapter
        assert mock_llm.chat_structured.call_count == 3

    @pytest.mark.asyncio
    async def test_llm_metadata_fallback(self):
        """LLM fails → fallback metadata used."""
        mock_llm = mock.AsyncMock()
        mock_llm.chat_structured.side_effect = RuntimeError("LLM down")
        preprocessor = NovelPreprocessor(mock_llm)

        chapters = await preprocessor.preprocess("Test Novel", SAMPLE_NOVEL_TEXT)

        assert len(chapters) == 3
        for ch in chapters:
            assert isinstance(ch, Chapter)
            assert "Chapter" in ch.title  # fallback title pattern
            assert ch.world_setting == "Unknown"
            assert ch.estimated_reading_time >= 1

    @pytest.mark.asyncio
    async def test_empty_text_raises_value_error(self):
        """Empty raw_text raises ValueError."""
        mock_llm = _make_mock_llm(_sample_metadata())
        preprocessor = NovelPreprocessor(mock_llm)

        with pytest.raises(ValueError, match="raw_text must not be empty"):
            await preprocessor.preprocess("Empty", "")

    @pytest.mark.asyncio
    async def test_whitespace_only_raises_value_error(self):
        """Whitespace-only raw_text raises ValueError."""
        mock_llm = _make_mock_llm(_sample_metadata())
        preprocessor = NovelPreprocessor(mock_llm)

        with pytest.raises(ValueError, match="raw_text must not be empty"):
            await preprocessor.preprocess("Spaces", "   \n\t  ")

    @pytest.mark.asyncio
    async def test_single_chapter_regex_fallback_to_llm(self):
        """No regex pattern matches → falls back to LLM split."""
        mock_llm = mock.AsyncMock()

        # Setup: LLM split returns 1 chapter, metadata returns sample data
        from app.services.novel_preprocessor.chapter_splitter import (
            _ChapterSplitRequest,
            _ChapterSplitSegment,
        )

        # Called twice: once for splitting, once for metadata
        mock_llm.chat_structured.side_effect = [
            _ChapterSplitRequest(
                chapters=[
                    _ChapterSplitSegment(
                        title="Lone Chapter",
                        text="This is a single chapter without headings. "
                        "We need enough text here to meet the minimum character "
                        "threshold for a valid chapter body. So let me add more "
                        "content here to ensure we pass the validation check. "
                        "The quick brown fox jumps over the lazy dog repeatedly.",
                    ),
                ]
            ),
            _sample_metadata(),
        ]

        preprocessor = NovelPreprocessor(mock_llm)
        chapters = await preprocessor.preprocess(
            "Test Novel",
            "Just a single block of text without any chapter headings. "
            "But we need to make it long enough. " + "x" * 500,
        )

        assert len(chapters) == 1
        assert isinstance(chapters[0], Chapter)
        # Splitting was called once, metadata once
        assert mock_llm.chat_structured.call_count == 2

    @pytest.mark.asyncio
    async def test_title_parameter_is_accepted(self):
        """The title parameter is passed through (reserved for future use)."""
        mock_llm = _make_mock_llm(_sample_metadata())
        preprocessor = NovelPreprocessor(mock_llm)

        chapters = await preprocessor.preprocess("My Novel Title", SAMPLE_NOVEL_TEXT)
        assert len(chapters) == 3

    @pytest.mark.asyncio
    async def test_chapter_ids_are_sequential(self):
        """Chapter IDs are assigned sequentially starting from 1."""
        mock_llm = _make_mock_llm(_sample_metadata())
        preprocessor = NovelPreprocessor(mock_llm)

        chapters = await preprocessor.preprocess("Test", SAMPLE_NOVEL_TEXT)
        ids = [ch.chapter_id for ch in chapters]
        assert ids == [1, 2, 3]

    @pytest.mark.asyncio
    async def test_raw_text_preserved(self):
        """Each chapter's raw_text field contains the original body text."""
        mock_llm = _make_mock_llm(_sample_metadata())
        preprocessor = NovelPreprocessor(mock_llm)

        chapters = await preprocessor.preprocess("Test", SAMPLE_NOVEL_TEXT)
        for ch in chapters:
            assert len(ch.raw_text) > 0
            assert isinstance(ch.raw_text, str)

    @pytest.mark.asyncio
    async def test_constructor_accepts_llm_client(self):
        """NovelPreprocessor can be constructed with an LLM client."""
        mock_llm = _make_mock_llm(_sample_metadata())
        preprocessor = NovelPreprocessor(mock_llm)
        assert preprocessor._llm_client is mock_llm


# ---------------------------------------------------------------------------
# Tests: _build_fallback_metadata
# ---------------------------------------------------------------------------


class TestFallbackMetadata:
    """Tests for ``_build_fallback_metadata()``."""

    def test_short_text(self):
        """Short text produces estimated reading time of 1 minute."""
        text = "A short text." * 10  # ~30 words
        result = _build_fallback_metadata(1, text)
        assert result["title"] == "Chapter 1"
        assert result["characters"] == []
        assert result["world_setting"] == "Unknown"
        assert result["estimated_reading_time"] >= 1

    def test_long_text(self):
        """Longer text produces proportionally higher reading time."""
        text = "word " * 500  # 500 words
        result = _build_fallback_metadata(3, text)
        assert result["title"] == "Chapter 3"
        assert result["estimated_reading_time"] == 2  # 500/250 = 2

    def test_chapter_index_in_title(self):
        """Chapter index appears in the fallback title."""
        for i in [1, 5, 42]:
            result = _build_fallback_metadata(i, "words " * 200)
            assert str(i) in result["title"]

    def test_empty_chapter_index_zero_reading_time(self):
        """Empty text still produces valid metadata."""
        result = _build_fallback_metadata(1, "short")
        assert result["estimated_reading_time"] >= 1
        assert result["title"] == "Chapter 1"


# ---------------------------------------------------------------------------
# Tests: Pydantic response models
# ---------------------------------------------------------------------------


class TestChapterMetadataResponse:
    """Validation tests for ``_ChapterMetadataResponse``."""

    def test_minimal_valid(self):
        """Minimal valid metadata."""
        m = _ChapterMetadataResponse(
            title="Chapter One",
            summary="A short summary of what happens in this chapter during the story.",
            characters=["Alice"],
            world_setting="A dark forest",
            estimated_reading_time=5,
        )
        assert m.title == "Chapter One"
        assert len(m.characters) == 1
        assert m.estimated_reading_time == 5

    def test_no_characters(self):
        """Characters can be empty list."""
        m = _ChapterMetadataResponse(
            title="Lonely Chapter",
            summary="A very long summary that describes the events of this chapter in at least twenty characters.",
            world_setting="Empty room",
            estimated_reading_time=3,
        )
        assert m.characters == []

    def test_title_too_short(self):
        """Empty title raises ValidationError."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            _ChapterMetadataResponse(
                title="",
                summary="A valid summary with enough characters to pass minimum.",
                world_setting="Test",
                estimated_reading_time=1,
            )

    def test_summary_too_short(self):
        """Summary shorter than 20 chars raises ValidationError."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            _ChapterMetadataResponse(
                title="Ch1",
                summary="Too short",
                world_setting="Test",
                estimated_reading_time=1,
            )

    def test_reading_time_zero(self):
        """Zero reading time raises ValidationError."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            _ChapterMetadataResponse(
                title="Ch1",
                summary="A valid summary with enough characters to pass minimum.",
                world_setting="Test",
                estimated_reading_time=0,
            )

    def test_reading_time_too_high(self):
        """Reading time > 120 raises ValidationError."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            _ChapterMetadataResponse(
                title="Ch1",
                summary="A valid summary with enough characters to pass minimum.",
                world_setting="Test",
                estimated_reading_time=999,
            )

    def test_multiple_characters(self):
        """Multiple characters are accepted."""
        m = _ChapterMetadataResponse(
            title="Party Scene",
            summary="A wonderful party with many guests fills the hall with laughter and joy.",
            characters=["Alice", "Bob", "Charlie", "Diana"],
            world_setting="Grand ballroom",
            estimated_reading_time=10,
        )
        assert len(m.characters) == 4


# ---------------------------------------------------------------------------
# Tests: import works
# ---------------------------------------------------------------------------


class TestImport:
    """Verify the public import works as specified."""

    def test_from_package_import(self):
        """``from app.services.novel_preprocessor import NovelPreprocessor`` works."""
        from app.services.novel_preprocessor import NovelPreprocessor as NP

        assert NP is NovelPreprocessor
