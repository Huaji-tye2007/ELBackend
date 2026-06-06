"""Tests for app.llm.prompts — prompt templates and scoring response models."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.llm.prompts import (
    ContextScoreEntry,
    ContextScoreResponse,
    _build_with_source,
    _build_without_source,
    make_scoring_prompt,
)


# ---------------------------------------------------------------------------
# ContextScoreEntry Pydantic validation
# ---------------------------------------------------------------------------


class TestContextScoreEntry:
    """Validation tests for ContextScoreEntry model."""

    def test_valid_minimal(self) -> None:
        """Should accept a valid entry with required fields."""
        entry = ContextScoreEntry(item_id="word_001", score=0.7)
        assert entry.item_id == "word_001"
        assert entry.score == 0.7
        assert entry.reasoning is None

    def test_valid_full(self) -> None:
        """Should accept a valid entry with all fields."""
        entry = ContextScoreEntry(
            item_id="word_002", score=1.0, reasoning="Perfect match"
        )
        assert entry.item_id == "word_002"
        assert entry.score == 1.0
        assert entry.reasoning == "Perfect match"

    def test_invalid_score_below_zero(self) -> None:
        """score < 0.0 should raise ValidationError."""
        with pytest.raises(ValidationError):
            ContextScoreEntry(item_id="word_003", score=-0.1)

    def test_invalid_score_above_one(self) -> None:
        """score > 1.0 should raise ValidationError."""
        with pytest.raises(ValidationError):
            ContextScoreEntry(item_id="word_004", score=1.1)

    def test_invalid_missing_item_id(self) -> None:
        """Missing item_id should raise ValidationError."""
        with pytest.raises(ValidationError):
            ContextScoreEntry(score=0.5)  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# ContextScoreResponse Pydantic validation
# ---------------------------------------------------------------------------


class TestContextScoreResponse:
    """Validation tests for ContextScoreResponse model."""

    def test_valid_with_entries(self) -> None:
        """Should accept a response with one or more entries."""
        response = ContextScoreResponse(
            scores=[
                ContextScoreEntry(item_id="a", score=0.5),
                ContextScoreEntry(item_id="b", score=0.8, reasoning="Better fit"),
            ]
        )
        assert len(response.scores) == 2

    def test_invalid_empty_scores_list(self) -> None:
        """Empty scores list should raise ValidationError (min_length=1)."""
        with pytest.raises(ValidationError):
            ContextScoreResponse(scores=[])


# ---------------------------------------------------------------------------
# make_scoring_prompt
# ---------------------------------------------------------------------------

_SAMPLE_CANDIDATES = [
    {"id": "go_move", "word": "go", "meaning": "去"},
    {"id": "bank_river", "word": "bank", "meaning": "河岸"},
]


class TestMakeScoringPrompt:
    """Tests for make_scoring_prompt builder function."""

    def test_with_source_text_returns_two_messages(self) -> None:
        """Should return a list of 2 messages (system + user)."""
        result = make_scoring_prompt("The quick brown fox", _SAMPLE_CANDIDATES)
        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0]["role"] == "system"
        assert result[1]["role"] == "user"

    def test_with_source_text_none_returns_two_messages(self) -> None:
        """source_text=None should still return 2 messages."""
        result = make_scoring_prompt(None, _SAMPLE_CANDIDATES)
        assert len(result) == 2
        assert result[0]["role"] == "system"
        assert result[1]["role"] == "user"

    def test_with_empty_string_source_text(self) -> None:
        """Empty string source_text should behave like None."""
        result = make_scoring_prompt("", _SAMPLE_CANDIDATES)
        assert len(result) == 2
        assert "(No source text available" in result[1]["content"]

    def test_with_whitespace_only_source_text(self) -> None:
        """Whitespace-only source_text should behave like None."""
        result = make_scoring_prompt("   \n  ", _SAMPLE_CANDIDATES)
        assert "(No source text available" in result[1]["content"]

    def test_with_long_source_text_truncated(self) -> None:
        """source_text > max_source_chars should be truncated with a note."""
        long_text = "x" * 5000
        result = make_scoring_prompt(
            long_text, _SAMPLE_CANDIDATES, max_source_chars=4000
        )
        user_content = result[1]["content"]
        assert len(long_text) > 4000
        # The full text should NOT appear — truncated plus the note
        assert long_text not in user_content
        assert "truncated" in user_content.lower()

    def test_candidates_appear_in_prompt(self) -> None:
        """Each candidate should appear by id, word, and meaning."""
        result = make_scoring_prompt("Sample text", _SAMPLE_CANDIDATES)
        user_content = result[1]["content"]
        assert "go_move" in user_content
        assert '"go"' in user_content
        assert "去" in user_content
        assert "bank_river" in user_content
        assert '"bank"' in user_content
        assert "河岸" in user_content

    def test_without_source_text_says_no_context(self) -> None:
        """When source_text is None, user content should mention no source."""
        result = make_scoring_prompt(None, _SAMPLE_CANDIDATES)
        user_content = result[1]["content"]
        assert "No source text available" in user_content


# ---------------------------------------------------------------------------
# _build_with_source
# ---------------------------------------------------------------------------


class TestBuildWithSource:
    """Tests for the internal _build_with_source helper."""

    def test_includes_source_text(self) -> None:
        """Output should include the source text."""
        output = _build_with_source("Hello world", _SAMPLE_CANDIDATES)
        assert "Hello world" in output

    def test_includes_candidate_list(self) -> None:
        """Output should include the candidate vocabulary list."""
        output = _build_with_source("Hello world", _SAMPLE_CANDIDATES)
        assert "Candidate Vocabulary" in output

    def test_each_candidate_appears_by_id_word_meaning(self) -> None:
        """Each candidate should appear with id, word, and meaning."""
        output = _build_with_source("Hello world", _SAMPLE_CANDIDATES)
        assert 'id: go_move, word: "go", meaning: "去"' in output
        assert 'id: bank_river, word: "bank", meaning: "河岸"' in output

    def test_candidate_without_meaning_field(self) -> None:
        """Candidate dict missing 'meaning' key should not crash."""
        candidates = [{"id": "test_id", "word": "test"}]
        output = _build_with_source("Some text", candidates)
        assert "test_id" in output
        assert "meaning" in output  # empty string appears as meaning: ""


# ---------------------------------------------------------------------------
# _build_without_source
# ---------------------------------------------------------------------------


class TestBedWithoutSource:
    """Tests for the internal _build_without_source helper."""

    def test_includes_no_source_message(self) -> None:
        """Output should say no source text is available."""
        output = _build_without_source(_SAMPLE_CANDIDATES)
        assert "No source text available" in output

    def test_includes_score_all_05_instruction(self) -> None:
        """Output should instruct scoring all candidates as 0.5."""
        output = _build_without_source(_SAMPLE_CANDIDATES)
        assert "score all candidates as 0.5" in output.lower()
        assert "neutral" in output.lower()

    def test_includes_candidate_list(self) -> None:
        """Output should still include the candidate vocabulary."""
        output = _build_without_source(_SAMPLE_CANDIDATES)
        assert "Candidate Vocabulary" in output
        assert "go_move" in output
        assert "bank_river" in output
