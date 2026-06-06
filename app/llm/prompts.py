"""Prompt templates for LLM-based context-fit scoring.

VocabularyScheduler uses these prompts to ask an LLM to rate how well
each candidate word fits into an episode's source text.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Response model (shared with scorer.py via app.llm.prompts)
# ---------------------------------------------------------------------------


class ContextScoreEntry(BaseModel):
    """A single candidate's context-fit score with reasoning."""

    item_id: str = Field(..., min_length=1, description="Vocabulary item identifier")
    score: float = Field(..., ge=0.0, le=1.0, description="Context-fit score 0.0–1.0")
    reasoning: str | None = Field(
        default=None, description="Brief explanation (Chinese or English)"
    )


class ContextScoreResponse(BaseModel):
    """LLM structured-output response model for context-fit scoring."""

    scores: list[ContextScoreEntry] = Field(
        ..., min_length=1, description="One entry per candidate"
    )


# ---------------------------------------------------------------------------
# Prompt template
# ---------------------------------------------------------------------------

_SCORING_SYSTEM_PROMPT = """You are a language-learning content curator. Your task is to score vocabulary items by how naturally they fit into a given text context.

For each candidate word, assign a context-fit score from 0.0 to 1.0:
- 1.0 = Excellent fit: the word naturally belongs in this passage in both meaning and style
- 0.7–0.9 = Good fit: thematically relevant, could appear naturally
- 0.4–0.6 = Moderate fit: possible but not natural
- 0.1–0.3 = Poor fit: forced or unnatural in this context
- 0.0 = Completely unrelated

Consider:
1. Semantic fit — does the word's meaning relate to the passage?
2. Grammatical fit — can the word reasonably appear in this type of sentence?
3. Stylistic register — does the word match the passage's tone?

For polysemous words, use the provided Chinese meaning for disambiguation.

Return scores for ALL provided candidates. Output ONLY valid JSON."""


def make_scoring_prompt(
    source_text: str | None,
    candidates: list[dict[str, Any]],
    max_source_chars: int = 4000,
) -> list[dict[str, str]]:
    """Build OpenAI-style messages for the context-fit scoring task.

    Args:
        source_text: The episode's source text (chapter slice), or ``None``.
            If ``None`` or empty, returns a single user message stating no context.
        candidates: List of candidate vocabulary dicts, each containing
            ``id``, ``word``, and ``meaning`` keys.
        max_source_chars: Maximum characters of source_text to include
            (truncated if exceeded). Default 4000.

    Returns:
        List of message dicts in OpenAI format:
        ``[{"role": "system", "content": "..."}, {"role": "user", "content": "..."}]``
    """
    if not source_text or not source_text.strip():
        user_content = _build_without_source(candidates)
    else:
        truncated = source_text[:max_source_chars]
        if len(source_text) > max_source_chars:
            truncated += "\n\n[Note: source text was truncated.]"
        user_content = _build_with_source(truncated, candidates)

    return [
        {"role": "system", "content": _SCORING_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _build_with_source(source_text: str, candidates: list[dict[str, Any]]) -> str:
    """Build user prompt content when source text is available."""
    lines: list[str] = [
        f"## Source Text\n\n{source_text}\n",
        "## Candidate Vocabulary\n",
    ]
    for i, c in enumerate(candidates, 1):
        lines.append(
            f'{i}. id: {c["id"]}, word: "{c["word"]}", meaning: "{c.get("meaning", "")}"'
        )
    lines.append(
        "\nScore each candidate 0.0–1.0 based on how naturally it fits into the source text. "
        'Return as JSON: {"scores": [{"item_id": "...", "score": 0.0-1.0, "reasoning": "..."}]}'
    )
    return "\n".join(lines)


def _build_without_source(candidates: list[dict[str, Any]]) -> str:
    """Build user prompt content when no source text is available."""
    lines: list[str] = [
        "## Source Text\n\n(No source text available for this episode.)\n",
        "## Candidate Vocabulary\n",
    ]
    for i, c in enumerate(candidates, 1):
        lines.append(
            f'{i}. id: {c["id"]}, word: "{c["word"]}", meaning: "{c.get("meaning", "")}"'
        )
    lines.append(
        "\nWithout source context, score all candidates as 0.5 (neutral). "
        'Return as JSON: {"scores": [{"item_id": "...", "score": 0.5, "reasoning": "No context available"}]}'
    )
    return "\n".join(lines)
