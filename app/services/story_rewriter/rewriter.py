"""Story Rewriter service — rewrites chapter source text into English light-novel dialogue.

Ref: AGENTS.md §11 (#5), BACKEND_IN_OUT.md §四.5.

Pipeline position: after VocabularyScheduler fills target_words, before VocabularyAnnotator.
"""

from __future__ import annotations

import logging
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.models.arc_plan import EpisodeSlot, TargetWord

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# LLM structured-output response models
# ---------------------------------------------------------------------------


class _LLMNarration(BaseModel):
    """LLM-generated narration message (non-dialogue content)."""

    type: Literal["narration"]
    text: str


class _LLMDialogue(BaseModel):
    """LLM-generated dialogue message with side and speaker info."""

    type: Literal["dialogue"]
    side: Literal["left", "right"]
    name: str
    text: str


class UsedTargetWord(BaseModel):
    """A target word actually incorporated by the LLM."""

    item_id: str
    surface: str = Field(
        min_length=1,
        description="The exact surface form used in the generated text, e.g. consumed",
    )


class _RewriteResponse(BaseModel):
    """LLM structured output — a light-novel episode with target words used.

    ``messages`` is a discriminated union: the ``type`` field (``"narration"``
    or ``"dialogue"``) tells instructor / Pydantic which model to instantiate.
    """

    messages: list[_LLMNarration | _LLMDialogue] = Field(
        default_factory=list,
        description="Ordered list of narration and dialogue messages",
    )
    target_words_used: list[UsedTargetWord] = Field(
        default_factory=list,
        description="Target words successfully incorporated, with item_id and surface form",
    )


# ---------------------------------------------------------------------------
# Public result model
# ---------------------------------------------------------------------------

from app.models.episode import DialogueMessage, NarrationMessage, Message  # noqa: E402


class RewriteResult(BaseModel):
    """Public result returned by ``StoryRewriter.rewrite_episode()``.

    Contains domain-level message models (NarrationMessage / DialogueMessage)
    with empty ``marks`` — marks are populated later by VocabularyAnnotator.
    """

    messages: list[Message]
    target_words_used: list[UsedTargetWord]


# ---------------------------------------------------------------------------
# Prompt templates
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """You are an English light-novel writer. Your task is to rewrite a story segment into a vivid, engaging English light-novel format — a mix of narration and dialogue that reads naturally, like a novel excerpt.

WRITING GUIDELINES:
1. **Narration** — Use first-person narration ("I") in past tense. Describe actions, inner thoughts, and surroundings. Keep it natural and flowing.
2. **Dialogue** — Conversations should feel real. Each dialogue message must specify:
   - "side": "right" for the protagonist (main character, the "I" narrator)
   - "side": "left" for all other characters
   - "name": the speaker's name
3. **Target words** — You will be given target vocabulary words (with Chinese meanings). Your job is to incorporate as many of them as NATURALLY as possible into the narrative. Do NOT force them — only use a word if it truly fits the scene. For each word you successfully use, report both its item_id and the exact surface form you wrote in target_words_used.
4. **Surface forms welcome** — Feel free to use the words in their natural inflected forms (e.g., "consuming", "went", "ran") — you do NOT need to use the base lemma form.
5. **Style** — Keep the English accessible (think young adult / light novel level). Vivid but not overly complex. Show emotions through actions and dialogue, not abstract descriptions.
6. **Length** — Produce a complete scene with multiple message exchanges. Aim for 6–12 messages covering both narration and dialogue.

IMPORTANT: Output ONLY valid JSON matching the required structure. Do not include any text outside the JSON."""


def _build_user_prompt(
    source_text: str,
    target_words: list[TargetWord],
    previous_context: list[dict[str, Any]] | None = None,
    episode_type: str = "main",
) -> str:
    """Build the user prompt for episode rewriting.

    Args:
        source_text: The source chapter text to rewrite (may be Chinese or English).
        target_words: Target vocabulary words to integrate.
        previous_context: Optional previous episode messages for continuity.
        episode_type: "main" or "side".

    Returns:
        A formatted user prompt string.
    """
    lines: list[str] = []

    # Episode type context
    if episode_type == "side":
        lines.append("## Episode Type: Side Episode (Bonus Story)")
        lines.append(
            "This is a side episode — a shorter, standalone bonus story. "
            "Focus on naturally integrating the target words. "
            "Keep it lighter and more fun than main episodes.\n"
        )

    # Previous context (for continuity)
    if previous_context:
        lines.append("## Previous Episode Context")
        lines.append(
            "The following messages are from the immediately preceding episode. "
            "Use this for story continuity (characters, setting, recent events)."
        )
        for i, msg in enumerate(previous_context, 1):
            role = msg.get("type", "unknown")
            if msg.get("side"):
                role += f" ({msg['side']} — {msg.get('name', '?')})"
            text = msg.get("text", "")
            # Truncate very long messages for context
            if len(text) > 200:
                text = text[:200] + "..."
            lines.append(f"  [{i}] [{role}] {text}")
        lines.append("")

    # Source text
    lines.append("## Source Text to Rewrite")
    lines.append(source_text)
    lines.append("")

    # Target words
    if target_words:
        lines.append("## Target Vocabulary Words")
        lines.append(
            "Integrate as many of the following words naturally into the story. "
            "For each word you use, report its item_id and exact surface form in target_words_used."
        )
        for tw in target_words:
            label = "NEW" if tw.is_new else "REVIEW"
            lines.append(
                f"  - item_id: {tw.item_id}, word: {tw.word} ({tw.meaning}) [{label}]"
            )
        lines.append("")

    # Output instruction
    lines.append(
        "Output a JSON object with:\n"
        '  - "messages": a list of narration/dialogue messages\n'
        '  - "target_words_used": list of objects like {"item_id": "...", "surface": "..."}'
    )

    return "\n".join(lines)


def _build_messages(
    source_text: str,
    target_words: list[TargetWord],
    previous_context: list[dict[str, Any]] | None = None,
    episode_type: str = "main",
) -> list[dict[str, str]]:
    """Build the full OpenAI-style messages list for a rewrite call.

    Args:
        source_text: Source text to rewrite.
        target_words: Target vocabulary words.
        previous_context: Optional previous episode context.
        episode_type: "main" or "side".

    Returns:
        List of message dicts with "role" and "content" keys.
    """
    user_content = _build_user_prompt(
        source_text=source_text,
        target_words=target_words,
        previous_context=previous_context,
        episode_type=episode_type,
    )
    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]


# ---------------------------------------------------------------------------
# Service class
# ---------------------------------------------------------------------------


class StoryRewriter:
    """Rewrites chapter source text into English light-novel dialogue format.

    Uses an LLM client (injected via constructor) to generate messages that
    naturally incorporate target vocabulary words.

    The output messages have empty ``marks`` — vocabulary marks are populated
    later by ``VocabularyAnnotator``.

    Public API (AGENTS.md §11):
        async def rewrite_episode(
            self,
            episode_slot: EpisodeSlot,
            chapter_text: str,
        ) -> RewriteResult
    """

    def __init__(self, llm_client: Any) -> None:
        """Initialize the StoryRewriter.

        Args:
            llm_client: An async LLM client with a ``chat_structured()`` method
                accepting ``messages`` and ``response_model`` parameters.
                Typically an ``InstructorClient`` instance (AGENTS.md §13).
        """
        self._llm_client = llm_client

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def rewrite_episode(
        self,
        episode_slot: EpisodeSlot,
        chapter_text: str,
    ) -> RewriteResult:
        """Rewrite a single episode's source text into light-novel dialogue.

        Args:
            episode_slot: The planned episode slot with target_words, source_text,
                previous_context, and episode_type.
            chapter_text: The raw chapter text to rewrite (may span multiple episodes).

        Returns:
            RewriteResult containing the generated messages and a list of
            successfully-used target word item IDs.

        Raises:
            ValueError: If chapter_text is empty.
            RuntimeError: If the LLM call fails (no fallback — caller handles retries).
        """
        # Validate inputs — side episodes may have no source_text
        if episode_slot.episode_type != "side":
            if not chapter_text or not chapter_text.strip():
                raise ValueError("chapter_text must not be empty for non-side episodes")

        source_text = episode_slot.source_text or chapter_text
        target_words = episode_slot.target_words or []
        previous_context = episode_slot.previous_context or None
        episode_type = episode_slot.episode_type

        # Build prompt
        prompt_messages = _build_messages(
            source_text=source_text,
            target_words=target_words,
            previous_context=previous_context,
            episode_type=episode_type,
        )

        # Call LLM with structured output
        try:
            response: _RewriteResponse = await self._llm_client.chat_structured(
                messages=prompt_messages,
                response_model=_RewriteResponse,
            )
        except Exception as exc:
            logger.error(
                "LLM rewrite failed for episode %s: %s", episode_slot.episode_id, exc
            )
            raise RuntimeError(
                f"StoryRewriter LLM call failed for episode {episode_slot.episode_id}"
            ) from exc

        # Convert LLM response models to domain models
        domain_messages: list[Message] = []
        for llm_msg in response.messages:
            if llm_msg.type == "narration":
                domain_messages.append(
                    NarrationMessage(
                        type="narration",
                        text=llm_msg.text,
                        marks=[],
                    )
                )
            else:
                domain_messages.append(
                    DialogueMessage(
                        type="dialogue",
                        side=llm_msg.side,
                        name=llm_msg.name,
                        text=llm_msg.text,
                        marks=[],
                    )
                )

        # Validate target_words_used — only include item_ids that were actually in the target list
        valid_ids = {tw.item_id for tw in target_words}
        validated_used = [
            used for used in response.target_words_used if used.item_id in valid_ids
        ]

        if response.target_words_used:
            extra_ids = {used.item_id for used in response.target_words_used} - valid_ids
            if extra_ids:
                logger.warning(
                    "LLM reported target_words_used with unknown item_ids: %s",
                    extra_ids,
                )

        return RewriteResult(
            messages=domain_messages,
            target_words_used=validated_used,
        )
