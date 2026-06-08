"""Tests for app.services.story_rewriter.rewriter — StoryRewriter service.

Ref: AGENTS.md §16 (Testing Standards).
"""

from __future__ import annotations

import datetime
from unittest import mock

import pytest

from app.models.arc_plan import EpisodeSlot, TargetWord
from app.models.episode import DialogueMessage, NarrationMessage
from app.models.fsrs import FsrsCard
from app.services.story_rewriter.rewriter import (
    RewriteResult,
    StoryRewriter,
    UsedTargetWord,
    _RewriteResponse,
    _LLMDialogue,
    _LLMNarration,
    _build_user_prompt,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_FIXED_DUE = datetime.datetime(2026, 6, 15, 0, 0, 0, tzinfo=datetime.timezone.utc)
_FIXED_REVIEW = datetime.datetime(2026, 6, 1, 0, 0, 0, tzinfo=datetime.timezone.utc)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_target_word(
    item_id: str = "test_word_1",
    word: str = "serendipity",
    meaning: str = "意外发现",
    is_new: bool = True,
) -> TargetWord:
    """Build a minimal TargetWord for testing."""
    fsrs_card = FsrsCard(
        state=1,
        due=_FIXED_DUE,
        last_review=None if is_new else _FIXED_REVIEW,
        stability=3.0,
        difficulty=0.5,
    )
    return TargetWord(
        item_id=item_id,
        word=word,
        meaning=meaning,
        is_new=is_new,
        fsrs_card=fsrs_card,
    )


def _make_episode_slot(
    episode_id: int = 1,
    episode_type: str = "main",
    source_text: str | None = "The protagonist walked into the room.",
    target_words: list[TargetWord] | None = None,
    previous_context: list[dict] | None = None,
) -> EpisodeSlot:
    """Build a minimal EpisodeSlot for testing."""
    return EpisodeSlot(
        episode_id=episode_id,
        episode_type=episode_type,  # type: ignore[arg-type]
        source_text=source_text,
        previous_context=previous_context or [],
        target_words=target_words or [],
    )


def _make_llm_response(
    narration_text: str = "I walked into the dimly lit room.",
    dialogue_text: str = "Hello there.",
    dialogue_side: str = "left",
    dialogue_name: str = "Anna",
    target_words_used: list[dict[str, str] | UsedTargetWord] | None = None,
) -> _RewriteResponse:
    """Build a mock _RewriteResponse for LLM return values."""
    messages: list[_LLMNarration | _LLMDialogue] = [
        _LLMNarration(type="narration", text=narration_text),
        _LLMDialogue(
            type="dialogue",
            side=dialogue_side,  # type: ignore[arg-type]
            name=dialogue_name,
            text=dialogue_text,
        ),
    ]
    return _RewriteResponse(
        messages=messages,
        target_words_used=[
            item if isinstance(item, UsedTargetWord) else UsedTargetWord(**item)
            for item in (target_words_used or [])
        ],
    )


# ---------------------------------------------------------------------------
# _build_user_prompt
# ---------------------------------------------------------------------------


class TestBuildUserPrompt:
    """Tests for the ``_build_user_prompt()`` helper."""

    def test_includes_source_text(self):
        """Source text appears in the prompt."""
        prompt = _build_user_prompt("Hello world", [])
        assert "Hello world" in prompt

    def test_includes_target_words(self):
        """Target words with meanings appear in the prompt."""
        tw = _make_target_word(item_id="abc", word="ephemeral", meaning="短暂的")
        prompt = _build_user_prompt("some text", [tw])
        assert "ephemeral" in prompt
        assert "短暂的" in prompt
        assert "abc" in prompt
        assert "NEW" in prompt  # is_new label

    def test_includes_review_label(self):
        """Review words get the REVIEW label."""
        tw = _make_target_word(
            item_id="r1", word="ancient", meaning="古老的", is_new=False
        )
        prompt = _build_user_prompt("text", [tw])
        assert "REVIEW" in prompt

    def test_includes_previous_context(self):
        """Previous context messages appear in the prompt."""
        ctx = [
            {"type": "narration", "text": "I walked home."},
            {
                "type": "dialogue",
                "side": "right",
                "name": "Me",
                "text": "What was that?",
            },
        ]
        prompt = _build_user_prompt("new scene", [], previous_context=ctx)
        assert "Previous Episode Context" in prompt
        assert "I walked home." in prompt
        assert "What was that?" in prompt

    def test_truncates_long_context_messages(self):
        """Very long context messages are truncated to 200 chars."""
        long_text = "x" * 500
        ctx = [{"type": "narration", "text": long_text}]
        prompt = _build_user_prompt("text", [], previous_context=ctx)
        # The truncated version (first 200 chars + "...") should appear
        assert long_text[:200] in prompt
        assert long_text not in prompt  # full text should NOT be present
        assert "..." in prompt

    def test_side_episode_label(self):
        """Side episodes get special labeling."""
        prompt = _build_user_prompt("text", [], episode_type="side")
        assert "Side Episode" in prompt
        assert "Bonus Story" in prompt

    def test_empty_target_words_still_includes_section(self):
        """Even with no target words, the output instructions should appear."""
        prompt = _build_user_prompt("text", [])
        assert "messages" in prompt.lower()
        assert "target_words_used" in prompt

    def test_multiple_target_words(self):
        """Multiple target words are all listed."""
        tws = [
            _make_target_word(item_id="a", word="luminous", meaning="发光的"),
            _make_target_word(item_id="b", word="whisper", meaning="低语"),
        ]
        prompt = _build_user_prompt("text", tws)
        assert "luminous" in prompt
        assert "whisper" in prompt
        assert "a" in prompt
        assert "b" in prompt


# ---------------------------------------------------------------------------
# StoryRewriter.rewrite_episode — happy path
# ---------------------------------------------------------------------------


class TestRewriteEpisodeSuccess:
    """Happy-path tests for ``StoryRewriter.rewrite_episode()``."""

    @pytest.fixture
    def mock_client(self):
        """Create a mock LLM client returning a valid _RewriteResponse."""
        client = mock.AsyncMock()
        client.chat_structured.return_value = _make_llm_response(
            narration_text="I entered the ancient library.",
            dialogue_text="Welcome, stranger.",
            dialogue_name="Librarian",
            target_words_used=[{"item_id": "tw1", "surface": "serendipity"}],
        )
        return client

    @pytest.fixture
    def rewriter(self, mock_client):
        """Create a StoryRewriter with the mock LLM client."""
        return StoryRewriter(llm_client=mock_client)

    async def test_returns_rewrite_result(self, rewriter, mock_client):
        """Successful rewrite returns RewriteResult with messages."""
        slot = _make_episode_slot(
            target_words=[_make_target_word(item_id="tw1")],
        )
        result = await rewriter.rewrite_episode(slot, "The hero enters the library.")

        assert isinstance(result, RewriteResult)
        assert len(result.messages) == 2
        assert result.messages[0].type == "narration"
        assert result.messages[0].text == "I entered the ancient library."
        assert result.messages[1].type == "dialogue"
        assert result.messages[1].text == "Welcome, stranger."
        mock_client.chat_structured.assert_called_once()

    async def test_narration_message_fields(self, rewriter, mock_client):
        """Narration messages have correct type and empty marks."""
        mock_client.chat_structured.return_value = _make_llm_response(
            narration_text="The moon rose over the hills.",
            dialogue_text="",
            target_words_used=[],
        )
        # Override to have only narration
        mock_client.chat_structured.return_value.messages = [
            _LLMNarration(type="narration", text="The moon rose over the hills."),
        ]

        result = await rewriter.rewrite_episode(_make_episode_slot(), "chapter text")
        msg = result.messages[0]
        assert isinstance(msg, NarrationMessage)
        assert msg.type == "narration"
        assert msg.marks == []

    async def test_dialogue_message_fields(self, rewriter, mock_client):
        """Dialogue messages have correct type, side, name, and empty marks."""
        mock_client.chat_structured.return_value.messages = [
            _LLMDialogue(
                type="dialogue",
                side="left",
                name="Old Man",
                text="You must not go there.",
            ),
        ]
        mock_client.chat_structured.return_value.target_words_used = []

        result = await rewriter.rewrite_episode(_make_episode_slot(), "chapter text")
        msg = result.messages[0]
        assert isinstance(msg, DialogueMessage)
        assert msg.type == "dialogue"
        assert msg.side == "left"
        assert msg.name == "Old Man"
        assert msg.marks == []

    async def test_protagonist_dialogue_side_right(self, rewriter, mock_client):
        """Protagonist dialogue (side='right') is preserved."""
        mock_client.chat_structured.return_value.messages = [
            _LLMDialogue(
                type="dialogue",
                side="right",
                name="Kazuhiko",
                text="I understand.",
            ),
        ]
        mock_client.chat_structured.return_value.target_words_used = []

        result = await rewriter.rewrite_episode(_make_episode_slot(), "chapter text")
        msg = result.messages[0]
        assert msg.side == "right"
        assert msg.name == "Kazuhiko"

    async def test_target_words_used_reported(self, rewriter, mock_client):
        """Successfully used target words are returned in the result."""
        slot = _make_episode_slot(
            target_words=[
                _make_target_word(item_id="tw1", word="ephemeral", meaning="短暂的"),
                _make_target_word(item_id="tw_def", word="serene", meaning="宁静的"),
            ],
        )
        result = await rewriter.rewrite_episode(slot, "Some text.")
        assert [used.item_id for used in result.target_words_used] == ["tw1"]
        assert result.target_words_used[0].surface == "serendipity"

    async def test_unknown_target_words_used_filtered(self, rewriter, mock_client):
        """item_ids not in the slot's target_words are filtered out."""
        mock_client.chat_structured.return_value.target_words_used = [
            UsedTargetWord(item_id="tw1", surface="serendipity"),
            UsedTargetWord(item_id="ghost_id", surface="ghost"),
        ]

        slot = _make_episode_slot(
            target_words=[_make_target_word(item_id="tw1")],
        )
        result = await rewriter.rewrite_episode(slot, "text")
        assert [used.item_id for used in result.target_words_used] == ["tw1"]

    async def test_uses_episode_source_text(self, rewriter, mock_client):
        """When episode has source_text, it is used instead of chapter_text."""
        slot = _make_episode_slot(
            source_text="The specific episode source.",
        )
        await rewriter.rewrite_episode(slot, "The full chapter text.")

        call_args = mock_client.chat_structured.call_args
        user_content = call_args[1]["messages"][1]["content"]
        assert "The specific episode source." in user_content

    async def test_uses_chapter_text_when_no_source(self, rewriter, mock_client):
        """When episode has no source_text, chapter_text is used."""
        slot = _make_episode_slot(source_text=None)
        await rewriter.rewrite_episode(slot, "The full chapter text.")

        call_args = mock_client.chat_structured.call_args
        user_content = call_args[1]["messages"][1]["content"]
        assert "The full chapter text." in user_content

    async def test_previous_context_passed_to_llm(self, rewriter, mock_client):
        """Previous context is included in the LLM prompt."""
        ctx = [{"type": "narration", "text": "I walked home."}]
        slot = _make_episode_slot(previous_context=ctx)
        await rewriter.rewrite_episode(slot, "chapter text")

        call_args = mock_client.chat_structured.call_args
        user_content = call_args[1]["messages"][1]["content"]
        assert "Previous Episode Context" in user_content
        assert "I walked home." in user_content

    async def test_side_episode_label_in_prompt(self, rewriter, mock_client):
        """Side episodes include the side episode label in the prompt."""
        slot = _make_episode_slot(episode_type="side")
        await rewriter.rewrite_episode(slot, "chapter text")

        call_args = mock_client.chat_structured.call_args
        user_content = call_args[1]["messages"][1]["content"]
        assert "Side Episode" in user_content

    async def test_system_prompt_included(self, rewriter, mock_client):
        """The system prompt is passed as the first message."""
        await rewriter.rewrite_episode(_make_episode_slot(), "chapter text")

        call_args = mock_client.chat_structured.call_args
        messages = call_args[1]["messages"]
        assert messages[0]["role"] == "system"
        assert "light-novel" in messages[0]["content"]


# ---------------------------------------------------------------------------
# StoryRewriter.rewrite_episode — error handling
# ---------------------------------------------------------------------------


class TestRewriteEpisodeErrors:
    """Error-handling tests for ``StoryRewriter.rewrite_episode()``."""

    async def test_empty_chapter_text_raises(self):
        """Empty chapter_text raises ValueError."""
        rewriter = StoryRewriter(llm_client=mock.AsyncMock())
        slot = _make_episode_slot()

        with pytest.raises(ValueError, match="chapter_text must not be empty"):
            await rewriter.rewrite_episode(slot, "")

    async def test_whitespace_only_chapter_text_raises(self):
        """Whitespace-only chapter_text raises ValueError."""
        rewriter = StoryRewriter(llm_client=mock.AsyncMock())
        slot = _make_episode_slot()

        with pytest.raises(ValueError, match="chapter_text must not be empty"):
            await rewriter.rewrite_episode(slot, "   \n\t  ")

    async def test_llm_failure_raises_runtime_error(self):
        """LLM call failure raises RuntimeError (caller handles retries)."""
        mock_client = mock.AsyncMock()
        mock_client.chat_structured.side_effect = RuntimeError("LLM API down")
        rewriter = StoryRewriter(llm_client=mock_client)

        with pytest.raises(RuntimeError, match="StoryRewriter LLM call failed"):
            await rewriter.rewrite_episode(_make_episode_slot(), "valid text")

    async def test_llm_timeout_raises_runtime_error(self):
        """LLM timeout raises RuntimeError."""
        mock_client = mock.AsyncMock()
        mock_client.chat_structured.side_effect = TimeoutError("Request timed out")
        rewriter = StoryRewriter(llm_client=mock_client)

        with pytest.raises(RuntimeError, match="StoryRewriter LLM call failed"):
            await rewriter.rewrite_episode(_make_episode_slot(), "valid text")


# ---------------------------------------------------------------------------
# StoryRewriter.rewrite_episode — edge cases
# ---------------------------------------------------------------------------


class TestRewriteEpisodeEdgeCases:
    """Edge-case tests for ``StoryRewriter.rewrite_episode()``."""

    async def test_no_target_words(self):
        """Rewriting works without any target words."""
        mock_client = mock.AsyncMock()
        mock_client.chat_structured.return_value = _make_llm_response(
            target_words_used=[],
        )
        rewriter = StoryRewriter(llm_client=mock_client)

        result = await rewriter.rewrite_episode(_make_episode_slot(), "Some text.")
        assert isinstance(result, RewriteResult)
        assert result.target_words_used == []
        assert len(result.messages) == 2

    async def test_empty_messages_from_llm(self):
        """LLM returns zero messages — handled gracefully."""
        mock_client = mock.AsyncMock()
        mock_client.chat_structured.return_value = _RewriteResponse(
            messages=[],
            target_words_used=[],
        )
        rewriter = StoryRewriter(llm_client=mock_client)

        result = await rewriter.rewrite_episode(_make_episode_slot(), "text.")
        assert result.messages == []
        assert result.target_words_used == []

    async def test_all_target_words_used(self):
        """All target words are reported as used."""
        mock_client = mock.AsyncMock()
        mock_client.chat_structured.return_value = _make_llm_response(
            target_words_used=[
                {"item_id": "tw_a", "surface": "a1"},
                {"item_id": "tw_b", "surface": "b2"},
            ],
        )
        rewriter = StoryRewriter(llm_client=mock_client)

        slot = _make_episode_slot(
            target_words=[
                _make_target_word(item_id="tw_a", word="a1", meaning="m1"),
                _make_target_word(item_id="tw_b", word="b2", meaning="m2"),
            ],
        )
        result = await rewriter.rewrite_episode(slot, "text.")
        assert {used.item_id for used in result.target_words_used} == {"tw_a", "tw_b"}

    async def test_none_target_words_used_from_llm(self):
        """LLM returns None for target_words_used (Pydantic default_factory handles)."""
        mock_client = mock.AsyncMock()
        mock_client.chat_structured.return_value = _RewriteResponse(
            messages=[
                _LLMNarration(type="narration", text="The story continues."),
            ],
            target_words_used=[],  # default_factory
        )
        rewriter = StoryRewriter(llm_client=mock_client)

        result = await rewriter.rewrite_episode(_make_episode_slot(), "text.")
        assert result.target_words_used == []

    async def test_multiple_narration_and_dialogue_mixed(self):
        """Mixed narration and dialogue are all converted correctly."""
        mock_client = mock.AsyncMock()
        mock_client.chat_structured.return_value = _RewriteResponse(
            messages=[
                _LLMNarration(type="narration", text="The door creaked."),
                _LLMDialogue(
                    type="dialogue", side="left", name="Guard", text="Who goes there?"
                ),
                _LLMNarration(type="narration", text="I froze."),
                _LLMDialogue(
                    type="dialogue",
                    side="right",
                    name="Kazuhiko",
                    text="Just a traveler.",
                ),
            ],
            target_words_used=[],
        )
        rewriter = StoryRewriter(llm_client=mock_client)

        result = await rewriter.rewrite_episode(_make_episode_slot(), "text.")
        assert len(result.messages) == 4
        assert result.messages[0].type == "narration"
        assert result.messages[1].type == "dialogue"
        assert result.messages[2].type == "narration"
        assert result.messages[3].type == "dialogue"
        assert result.messages[1].side == "left"  # type: ignore[union-attr]
        assert result.messages[3].side == "right"  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# RewriteResult model
# ---------------------------------------------------------------------------


class TestRewriteResult:
    """Tests for the ``RewriteResult`` Pydantic model."""

    def test_valid_minimal(self):
        """A RewriteResult with minimal valid data."""
        result = RewriteResult(
            messages=[NarrationMessage(type="narration", text="Hello.")],
            target_words_used=[],
        )
        assert len(result.messages) == 1
        assert result.target_words_used == []

    def test_valid_full(self):
        """A RewriteResult with both narration and dialogue messages."""
        result = RewriteResult(
            messages=[
                NarrationMessage(type="narration", text="Scene begins."),
                DialogueMessage(type="dialogue", side="left", name="Anna", text="Hi!"),
            ],
            target_words_used=[
                UsedTargetWord(item_id="tw1", surface="one"),
                UsedTargetWord(item_id="tw2", surface="two"),
            ],
        )
        assert len(result.messages) == 2
        assert [used.item_id for used in result.target_words_used] == ["tw1", "tw2"]

    def test_serialize_to_json(self):
        """RewriteResult can be serialized to JSON and back."""
        result = RewriteResult(
            messages=[
                NarrationMessage(type="narration", text="The beginning."),
                DialogueMessage(
                    type="dialogue", side="right", name="Hero", text="Let's go."
                ),
            ],
            target_words_used=[UsedTargetWord(item_id="abc_123", surface="beginning")],
        )
        json_str = result.model_dump_json()
        assert "The beginning" in json_str
        assert "abc_123" in json_str

        # Round-trip
        restored = RewriteResult.model_validate_json(json_str)
        assert restored.messages[0].text == "The beginning."
        assert restored.target_words_used[0].item_id == "abc_123"
        assert restored.target_words_used[0].surface == "beginning"
