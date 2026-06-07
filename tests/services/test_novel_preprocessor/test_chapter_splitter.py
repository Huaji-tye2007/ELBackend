"""Tests for app.services.novel_preprocessor.chapter_splitter."""

from __future__ import annotations

import re
from unittest import mock

import pytest

from app.services.novel_preprocessor.chapter_splitter import (
    _CHAPTER_HEADING_PATTERNS,
    _ChapterSplitRequest,
    _ChapterSplitSegment,
    split_chapters_by_llm,
    split_chapters_regex,
)

# ---------------------------------------------------------------------------
# Sample texts
# ---------------------------------------------------------------------------

MULTI_CHAPTER_ENGLISH = """Chapter 1: The Beginning
This is the body of chapter one. It needs to have enough content to meet the minimum character threshold for a meaningful chapter body. So let me write some more text here to make sure we pass the 100 character limit that the splitter enforces. The quick brown fox jumps over the lazy dog.

Chapter 2: The Middle
This is the body of chapter two. Again, we need at least 100 characters in the body to be considered a valid chapter. So here is some additional text that pads this out. Lorem ipsum dolor sit amet, consectetur adipiscing elit.

Chapter 3: The End
This is the body of chapter three. And once more, we need to hit the minimum character count for the chapter body. The final chapter wraps everything up. Done."""

MULTI_CHAPTER_UPPERCASE = """CHAPTER ONE
This is the body of chapter one. It needs to have enough content to meet the minimum character threshold for a meaningful chapter body. So let me write some more text here to make sure we pass the 100 character limit.

CHAPTER TWO
This is the body of chapter two. Again, we need at least 100 characters in the body to be considered a valid chapter. So here is some additional text that pads this out. Lorem ipsum dolor sit amet, consectetur adipiscing elit."""

MULTI_CHAPTER_NUMBERED = """1. A Fresh Start
This is the body of chapter one. It needs to have enough content to meet the minimum character threshold for a meaningful chapter body. So let me write some more text here to make sure we pass the 100 character limit.

2. Growing Pains
This is the body of chapter two. Again, we need at least 100 characters in the body to be considered a valid chapter. So here is some additional text that pads this out. Lorem ipsum dolor sit amet."""

MULTI_CHAPTER_CHINESE = """第一章 新的开始
这是第一章的正文内容。为了满足最低字符数限制，我需要写足够的文字。所以我会在这里添加一些额外的内容来填充，确保通过一百个字符的限制。快速的棕色狐狸跳过了懒狗。继续写更多的内容来确保字符数达标。故事的开始总是充满希望和期待，每一个新的开始都像是一张白纸。

第二章 转折点
这是第二章的正文内容。同样地，我们需要至少一百个字符的正文才能被视为一个有效的章节。所以这里再添加一些文字。这是一个转折点的章节。命运的齿轮开始转动，主角即将面临重要的抉择。前方是一条充满挑战的道路，但也蕴藏着无限的机遇。"""

SINGLE_CHAPTER = """This is just a single block of text without any chapter headings.
It should not be splittable by the regex patterns. But it still has enough
content to meet the minimum character threshold for a meaningful body. The
text continues here with more words to make sure we exceed the 100 character
minimum that the splitter requires for validation purposes."""

SHORT_BODY_CHAPTERS = """Chapter 1: Short
Brief.

Chapter 2: Also Short
Too short.
"""

EMPTY_TEXT = ""

WHITESPACE_ONLY = "   \n\t  "


# ---------------------------------------------------------------------------
# Tests: split_chapters_regex
# ---------------------------------------------------------------------------


class TestSplitChaptersRegex:
    """Tests for ``split_chapters_regex()``."""

    def test_english_chapter_heading(self):
        """Splits text with 'Chapter N' headings."""
        result = split_chapters_regex(MULTI_CHAPTER_ENGLISH)
        assert result is not None
        assert len(result) == 3
        assert result[0][0] == "Chapter 1: The Beginning"
        assert "body of chapter one" in result[0][1]
        assert result[1][0] == "Chapter 2: The Middle"
        assert result[2][0] == "Chapter 3: The End"

    def test_uppercase_chapter_heading(self):
        """Splits text with 'CHAPTER ONE' style headings."""
        result = split_chapters_regex(MULTI_CHAPTER_UPPERCASE)
        assert result is not None
        assert len(result) == 2
        assert result[0][0] == "CHAPTER ONE"
        assert result[1][0] == "CHAPTER TWO"

    def test_numbered_chapter_heading(self):
        """Splits text with '1. Title' style headings."""
        result = split_chapters_regex(MULTI_CHAPTER_NUMBERED)
        assert result is not None
        assert len(result) == 2
        assert result[0][0] == "1. A Fresh Start"
        assert result[1][0] == "2. Growing Pains"

    def test_chinese_chapter_heading(self):
        """Splits text with Chinese '第N章' headings."""
        result = split_chapters_regex(MULTI_CHAPTER_CHINESE)
        assert result is not None
        assert len(result) == 2
        assert result[0][0] == "第一章 新的开始"
        assert result[1][0] == "第二章 转折点"

    def test_single_chapter_returns_none(self):
        """Returns None for text without chapter headings."""
        result = split_chapters_regex(SINGLE_CHAPTER)
        assert result is None

    def test_short_body_chapters_rejected(self):
        """Chapters with body shorter than 100 chars are filtered out."""
        result = split_chapters_regex(SHORT_BODY_CHAPTERS)
        assert result is None

    def test_empty_text_returns_none(self):
        """Empty text returns None (no pattern matches)."""
        result = split_chapters_regex(EMPTY_TEXT)
        assert result is None

    def test_whitespace_only_returns_none(self):
        """Whitespace-only text returns None."""
        result = split_chapters_regex(WHITESPACE_ONLY)
        assert result is None

    def test_all_patterns_have_compile(self):
        """All chapter heading patterns are compiled regex."""
        assert len(_CHAPTER_HEADING_PATTERNS) > 0
        for p in _CHAPTER_HEADING_PATTERNS:
            assert isinstance(p, re.Pattern)

    def test_regex_matches_common_formats(self):
        """Individual patterns match common chapter formats."""
        text = (
            "Chapter 1: Prologue\nA long enough body " + "x" * 100 + "\n\n"
            "Chapter 2: Main\nAnother body here " + "y" * 100
        )
        result = split_chapters_regex(text)
        assert result is not None
        assert len(result) >= 2


# ---------------------------------------------------------------------------
# Tests: split_chapters_by_llm
# ---------------------------------------------------------------------------


class TestSplitChaptersByLlm:
    """Tests for ``split_chapters_by_llm()``."""

    @pytest.mark.asyncio
    async def test_successful_llm_split(self):
        """LLM returns valid chapter segments."""
        mock_client = mock.AsyncMock()
        mock_client.chat_structured.return_value = _ChapterSplitRequest(
            chapters=[
                _ChapterSplitSegment(
                    title="The Beginning",
                    text="Once upon a time, there was a story that needed to be told. "
                    "This is a very long body text that must exceed one hundred characters "
                    "to pass the minimum validation threshold set by the chapter splitter. "
                    "So I am adding many more words here to ensure we meet the requirement.",
                ),
                _ChapterSplitSegment(
                    title="The Middle",
                    text="The story continued with many adventures and challenges. "
                    "Again we need enough text to exceed the minimum body length. "
                    "Let me add more content here to make sure we pass the validation. "
                    "This should be sufficient for the test to pass correctly.",
                ),
            ]
        )

        result = await split_chapters_by_llm("Some long text " + "x" * 200, mock_client)
        assert len(result) == 2
        assert result[0] == ("The Beginning", mock.ANY)
        assert result[1] == ("The Middle", mock.ANY)
        assert "Once upon a time" in result[0][1]

    @pytest.mark.asyncio
    async def test_llm_failure_raises_llm_error(self):
        """LLM exception is wrapped in LLMError."""
        from app.core.exceptions import LLMError

        mock_client = mock.AsyncMock()
        mock_client.chat_structured.side_effect = RuntimeError("API down")

        with pytest.raises(LLMError, match="Chapter splitting via LLM failed"):
            await split_chapters_by_llm("Some text " + "x" * 200, mock_client)

    @pytest.mark.asyncio
    async def test_llm_returns_empty_list(self):
        """LLM exception is raised when structured output fails."""
        from app.core.exceptions import LLMError

        mock_client = mock.AsyncMock()
        mock_client.chat_structured.side_effect = ValueError("Empty response from LLM")

        with pytest.raises(LLMError, match="Chapter splitting via LLM failed"):
            await split_chapters_by_llm("Some text " + "x" * 200, mock_client)

    @pytest.mark.asyncio
    async def test_llm_truncates_long_text(self):
        """Very long text is truncated to 30000 chars before sending to LLM."""
        mock_client = mock.AsyncMock()
        mock_client.chat_structured.return_value = _ChapterSplitRequest(
            chapters=[
                _ChapterSplitSegment(
                    title="Short",
                    text="A" * 200,
                ),
            ]
        )

        long_text = "x" * 50000
        result = await split_chapters_by_llm(long_text, mock_client)
        assert len(result) == 1

        # Verify the message sent to LLM was truncated
        call_args = mock_client.chat_structured.call_args
        user_message = call_args[1]["messages"][1]["content"]
        assert "truncated to 30,000 characters" in user_message
        assert len(user_message) < 50000


# ---------------------------------------------------------------------------
# Tests: Pydantic models
# ---------------------------------------------------------------------------


class TestChapterSplitModels:
    """Validation tests for chapter split Pydantic models."""

    def test_segment_minimal_valid(self):
        """Minimal valid segment."""
        seg = _ChapterSplitSegment(title="Prologue", text="x" * 100)
        assert seg.title == "Prologue"
        assert len(seg.text) == 100

    def test_segment_body_too_short(self):
        """Body shorter than minimum raises ValidationError."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            _ChapterSplitSegment(title="Brief", text="short")

    def test_segment_title_empty(self):
        """Empty title raises ValidationError."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            _ChapterSplitSegment(title="", text="x" * 100)

    def test_request_valid(self):
        """Valid chapter split request with 2 segments."""
        req = _ChapterSplitRequest(
            chapters=[
                _ChapterSplitSegment(title="Ch1", text="x" * 100),
                _ChapterSplitSegment(title="Ch2", text="y" * 100),
            ]
        )
        assert len(req.chapters) == 2

    def test_request_empty_chapters(self):
        """Empty chapters list raises ValidationError."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            _ChapterSplitRequest(chapters=[])
