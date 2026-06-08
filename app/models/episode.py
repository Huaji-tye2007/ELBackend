"""Pydantic v2 models for Episode format — FormatSpec v3 consumer output.

Ref: AGENTS.md §12 (episode.py), documents/format_spec_json.md (authoritative SoT).
"""

from typing import Literal

from pydantic import BaseModel, Field


class Meta(BaseModel):
    """Episode metadata: episode number, title, and story kind."""

    ep: int
    title: str
    kind: Literal["main", "side"]


class Mark(BaseModel):
    """A vocabulary mark anchoring a target word to its position in message text.

    Attributes:
        item_id: Stable backend vocabulary item id. Frontend should send this
            id back in reading logs so learning state can be updated without
            re-resolving surface forms through lemma lookup.
        word: Surface form as it appears in the text (e.g. "consuming", not lemma "consume").
        index: 0-based word index by split(" ") — NOT character offset.
        definition: Chinese definition matching the context.
        is_new: True if this item_id is first-seen in the whole work.
    """

    item_id: str | None = None
    word: str
    index: int = Field(ge=0)
    definition: str
    is_new: bool
    lemma: str | None = Field(default=None, exclude=True)


class NarrationMessage(BaseModel):
    """Non-dialogue content: actions, descriptions, inner thoughts.

    Rendered center-aligned, gray, subdued style.
    """

    type: Literal["narration"]
    text: str
    marks: list[Mark] = Field(default_factory=list)


class DialogueMessage(BaseModel):
    """Spoken dialogue with side indicator.

    side='right' → protagonist (right bubble, avatar + name).
    side='left' → other character (left bubble, avatar + name).
    """

    type: Literal["dialogue"]
    side: Literal["left", "right"]
    name: str
    text: str
    marks: list[Mark] = Field(default_factory=list)


class VocabEntry(BaseModel):
    """A deduplicated vocabulary item for the episode-end vocab panel.

    Derived from marks across all messages for frontend convenience.
    """

    item_id: str | None = None
    word: str
    definition: str
    is_new: bool


class Episode(BaseModel):
    """Complete FormatSpec v3 episode output consumed by the frontend.

    Top-level structure: { meta, messages, vocab }.

    Messages use discriminated union: NarrationMessage | DialogueMessage,
    auto-detected by Pydantic v2 via the non-overlapping Literal 'type' field.
    """

    meta: Meta
    messages: list[NarrationMessage | DialogueMessage]
    vocab: list[VocabEntry] = Field(default_factory=list)


# Union type alias for message types (convenient for isinstance checks)
Message = NarrationMessage | DialogueMessage


__all__ = [
    "Meta",
    "Mark",
    "NarrationMessage",
    "DialogueMessage",
    "VocabEntry",
    "Episode",
    "Message",
]
