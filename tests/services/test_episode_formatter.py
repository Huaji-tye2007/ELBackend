"""Tests for EpisodeFormatter service.

Ref: AGENTS.md §11 (#7), BACKEND_IN_OUT.md §四.7, FormatSpec v3.

Covers format_episode(), _derive_vocab(), _validate_messages(), and write_cache().
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from app.models.episode import (
    DialogueMessage,
    Episode,
    NarrationMessage,
)
from app.services.episode_formatter import EpisodeFormatter


# ============================================================================
# Helpers
# ============================================================================


def _make_narration(text: str, marks: list[dict] | None = None) -> dict:
    """Build a narration message dict."""
    return {
        "type": "narration",
        "text": text,
        "marks": marks or [],
    }


def _make_dialogue(
    side: str, name: str, text: str, marks: list[dict] | None = None
) -> dict:
    """Build a dialogue message dict."""
    return {
        "type": "dialogue",
        "side": side,
        "name": name,
        "text": text,
        "marks": marks or [],
    }


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def formatter(tmp_path: Path) -> EpisodeFormatter:
    """EpisodeFormatter with a temp cache directory."""
    cache_dir = tmp_path / "EpisodeCache"
    return EpisodeFormatter(cache_dir=cache_dir)


# ============================================================================
# Tests — format_episode
# ============================================================================


def test_format_narration_only(formatter: EpisodeFormatter):
    """Episode with only narration messages validates and assembles correctly."""
    meta = {"ep": 1, "title": "Arrival", "kind": "main"}
    messages = [
        _make_narration("The train screeched to a halt."),
        _make_narration("Steam billowed across the platform."),
    ]
    episode = formatter.format_episode(meta, messages)

    assert isinstance(episode, Episode)
    assert episode.meta.ep == 1
    assert episode.meta.kind == "main"
    assert len(episode.messages) == 2
    assert all(isinstance(m, NarrationMessage) for m in episode.messages)
    assert episode.vocab == []


def test_format_dialogue_only(formatter: EpisodeFormatter):
    """Episode with only dialogue messages validates and assembles correctly."""
    meta = {"ep": 2, "title": "The Encounter", "kind": "side"}
    messages = [
        _make_dialogue("right", "Me", "Hello."),
        _make_dialogue("left", "Stranger", "Hey there."),
    ]
    episode = formatter.format_episode(meta, messages)

    assert isinstance(episode, Episode)
    assert episode.meta.kind == "side"
    assert len(episode.messages) == 2
    assert all(isinstance(m, DialogueMessage) for m in episode.messages)


def test_format_mixed_messages(formatter: EpisodeFormatter):
    """Episode with both narration and dialogue messages."""
    meta = {"ep": 3, "title": "The Glass", "kind": "main"}
    messages = [
        _make_narration("Footsteps approach."),
        _make_dialogue("left", "Anna", "Hey."),
        _make_narration("She sits down."),
        _make_dialogue("right", "Me", "Hi."),
    ]
    episode = formatter.format_episode(meta, messages)

    assert len(episode.messages) == 4
    assert isinstance(episode.messages[0], NarrationMessage)
    assert isinstance(episode.messages[1], DialogueMessage)
    assert isinstance(episode.messages[2], NarrationMessage)
    assert isinstance(episode.messages[3], DialogueMessage)


# ============================================================================
# Tests — mark.index (space-split 0-based)
# ============================================================================


def test_mark_index_is_space_split_zero_based(formatter: EpisodeFormatter):
    """mark.index is 0-based by text.split(' ') — not character offset."""
    meta = {"ep": 4, "title": "Index Check", "kind": "main"}
    text = "The bank said the bank of the river was eroding."
    # "bank" at index 1 (0-based after split by spaces)
    messages = [
        _make_narration(
            text,
            marks=[{"word": "bank", "index": 1, "definition": "河岸", "is_new": True}],
        )
    ]
    episode = formatter.format_episode(meta, messages)

    mark = episode.messages[0].marks[0]
    # Verify 0-based index semantics: text.split(" ")[mark.index] == mark.word
    words = text.split(" ")
    assert words[mark.index] == mark.word
    assert mark.index == 1
    assert mark.word == "bank"


# ============================================================================
# Tests — mark.word = surface form (not lemma)
# ============================================================================


def test_mark_word_is_surface_form(formatter: EpisodeFormatter):
    """mark.word stores the surface form as it appears in text, not the lemma."""
    meta = {"ep": 5, "title": "Surface Forms", "kind": "main"}
    text = "She was consuming the last cookie."
    messages = [
        _make_narration(
            text,
            marks=[
                {"word": "consuming", "index": 2, "definition": "消耗", "is_new": True}
            ],
        )
    ]
    episode = formatter.format_episode(meta, messages)

    mark = episode.messages[0].marks[0]
    assert mark.word == "consuming"  # surface form, not lemma "consume"
    assert mark.word != "consume"  # explicitly NOT the lemma
    words = text.split(" ")
    assert words[mark.index] == "consuming"


# ============================================================================
# Tests — dialogue.side = "right" for protagonist
# ============================================================================


def test_dialogue_side_right_is_protagonist(formatter: EpisodeFormatter):
    """dialogue.side='right' maps to the protagonist (right bubble)."""
    meta = {"ep": 6, "title": "Side Check", "kind": "main"}
    messages = [
        _make_dialogue("right", "Me", "I am the protagonist."),
        _make_dialogue("left", "Stranger", "I am another character."),
    ]
    episode = formatter.format_episode(meta, messages)

    protagonist_msg = episode.messages[0]
    assert isinstance(protagonist_msg, DialogueMessage)
    assert protagonist_msg.side == "right"
    assert protagonist_msg.name == "Me"

    other_msg = episode.messages[1]
    assert isinstance(other_msg, DialogueMessage)
    assert other_msg.side == "left"
    assert other_msg.name == "Stranger"


# ============================================================================
# Tests — empty messages
# ============================================================================


def test_format_empty_messages(formatter: EpisodeFormatter):
    """Episode with no messages validates correctly (empty arrays)."""
    meta = {"ep": 7, "title": "Empty", "kind": "main"}
    episode = formatter.format_episode(meta, [])

    assert isinstance(episode, Episode)
    assert episode.messages == []
    assert episode.vocab == []


# ============================================================================
# Tests — empty vocab derivation
# ============================================================================


def test_derive_vocab_empty_when_no_marks(formatter: EpisodeFormatter):
    """Vocab is empty when no messages have marks."""
    meta = {"ep": 8, "title": "No Marks", "kind": "main"}
    messages = [
        _make_narration("Just some text without marks."),
        _make_dialogue("left", "Anna", "No marks here either."),
    ]
    # Explicitly pass vocab=None to trigger derivation
    episode = formatter.format_episode(meta, messages, vocab=None)

    assert episode.vocab == []


def test_derive_vocab_deduplicates_by_item_id(formatter: EpisodeFormatter):
    """Different surface forms for the same item_id should produce one vocab entry."""
    meta = {"ep": 9, "title": "Lemma Vocab", "kind": "main"}
    messages = [
        _make_narration(
            "She consumed it.",
            marks=[
                {
                    "word": "consumed",
                    "index": 1,
                    "definition": "消耗",
                    "is_new": True,
                    "item_id": "consume_1",
                    "lemma": "consume",
                }
            ],
        ),
        _make_narration(
            "They were consuming time.",
            marks=[
                {
                    "word": "consuming",
                    "index": 2,
                    "definition": "消耗",
                    "is_new": False,
                    "item_id": "consume_1",
                    "lemma": "consume",
                }
            ],
        ),
    ]

    episode = formatter.format_episode(meta, messages)

    assert len(episode.vocab) == 1
    assert episode.vocab[0].item_id == "consume_1"
    assert episode.vocab[0].word == "consumed"
    assert episode.vocab[0].is_new is True


# ============================================================================
# Tests — error cases
# ============================================================================


def test_invalid_message_type_raises(formatter: EpisodeFormatter):
    """Unknown message type raises ValueError."""
    meta = {"ep": 9, "title": "Bad Type", "kind": "main"}
    messages = [{"type": "unknown", "text": "Invalid"}]

    with pytest.raises(ValueError, match="Unknown message type"):
        formatter.format_episode(meta, messages)


def test_invalid_meta_kind_raises_validation_error(formatter: EpisodeFormatter):
    """Invalid meta.kind raises pydantic ValidationError."""
    meta = {"ep": 10, "title": "Bad Kind", "kind": "invalid"}
    with pytest.raises(ValidationError):
        formatter.format_episode(meta, [])


def test_write_cache_creates_file(formatter: EpisodeFormatter):
    """write_cache writes an atomic JSON file and returns its path."""
    meta = {"ep": 1, "title": "Cache Test", "kind": "main"}
    messages = [_make_narration("Test content.")]
    episode = formatter.format_episode(meta, messages)

    cache_path = formatter.write_cache(episode)

    assert cache_path.exists()
    assert cache_path.name == "ep_0001.json"
    # Verify content is valid JSON Episode
    raw = cache_path.read_text(encoding="utf-8")
    reloaded = Episode.model_validate_json(raw)
    assert reloaded.meta.ep == 1
    assert reloaded.meta.title == "Cache Test"
