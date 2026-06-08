"""Tests for app.models.episode — Meta, Mark, NarrationMessage, DialogueMessage, VocabEntry, Episode.

Ref: AGENTS.md §16 (Testing Standards), documents/format_spec_json.md (FormatSpec v3).
"""

import json

import pytest
from pydantic import ValidationError

from app.models.episode import (
    DialogueMessage,
    Episode,
    Mark,
    Meta,
    NarrationMessage,
    VocabEntry,
)


class TestMeta:
    """Tests for Meta model."""

    def test_valid_main(self) -> None:
        meta = Meta(ep=3, title="The Glass", kind="main")
        assert meta.ep == 3
        assert meta.title == "The Glass"
        assert meta.kind == "main"

    def test_valid_side(self) -> None:
        meta = Meta(ep=5, title="Side Story", kind="side")
        assert meta.kind == "side"

    def test_invalid_kind(self) -> None:
        """kind='extra' should raise ValidationError (Literal constraint)."""
        with pytest.raises(ValidationError):
            Meta(ep=1, title="Bad", kind="extra")  # type: ignore[arg-type]


class TestMark:
    """Tests for Mark model.

    Critical constraints: index must be ge=0 (word index, not char offset).
    """

    def test_valid_new(self) -> None:
        mark = Mark(
            item_id="bank_finance",
            word="bank",
            index=1,
            definition="银行",
            is_new=True,
            lemma="bank",
        )
        dumped = mark.model_dump()
        assert mark.word == "bank"
        assert mark.index == 1
        assert mark.definition == "银行"
        assert mark.is_new is True
        assert dumped["item_id"] == "bank_finance"
        assert "lemma" not in dumped

    def test_valid_review(self) -> None:
        mark = Mark(word="footstep", index=0, definition="脚步", is_new=False)
        assert mark.is_new is False

    def test_index_zero_is_valid(self) -> None:
        """index=0 (first word in text) should be valid."""
        mark = Mark(word="The", index=0, definition="这", is_new=False)
        assert mark.index == 0

    def test_invalid_index_negative(self) -> None:
        """index=-1 should raise ValidationError (Field(ge=0))."""
        with pytest.raises(ValidationError):
            Mark(word="bad", index=-1, definition="坏", is_new=False)


class TestNarrationMessage:
    """Tests for NarrationMessage model."""

    def test_valid_with_marks(self) -> None:
        msg = NarrationMessage(
            type="narration",
            text="Footsteps approach.",
            marks=[
                Mark(word="footstep", index=0, definition="脚步", is_new=False),
            ],
        )
        assert msg.type == "narration"
        assert msg.text == "Footsteps approach."
        assert len(msg.marks) == 1
        assert msg.marks[0].word == "footstep"

    def test_valid_empty_marks(self) -> None:
        msg = NarrationMessage(type="narration", text="Hello.", marks=[])
        assert msg.marks == []

    def test_default_marks_is_empty(self) -> None:
        """NarrationMessage without marks should default to empty list."""
        msg = NarrationMessage(type="narration", text="Simple text.")
        assert msg.marks == []

    def test_invalid_type(self) -> None:
        """type='dialogue' on NarrationMessage should fail (Literal constraint)."""
        with pytest.raises(ValidationError):
            NarrationMessage(
                type="dialogue",  # type: ignore[arg-type]
                text="Bad",
                marks=[],
            )


class TestDialogueMessage:
    """Tests for DialogueMessage model.

    Critical constraints:
    - side must be Literal['left','right'] — NOT free-form
    - 'right' = protagonist, 'left' = other character
    """

    def test_valid_left(self) -> None:
        """side='left' = other character."""
        msg = DialogueMessage(
            type="dialogue",
            side="left",
            name="Anna",
            text="Hey.",
            marks=[],
        )
        assert msg.side == "left"
        assert msg.name == "Anna"

    def test_valid_right(self) -> None:
        """side='right' = protagonist."""
        msg = DialogueMessage(
            type="dialogue",
            side="right",
            name="Kazuhiko",
            text="...Nukumizu who?",
            marks=[],
        )
        assert msg.side == "right"
        assert msg.name == "Kazuhiko"

    def test_invalid_side_center(self) -> None:
        """side='center' should raise ValidationError (only left/right allowed)."""
        with pytest.raises(ValidationError):
            DialogueMessage(
                type="dialogue",
                side="center",  # type: ignore[arg-type]
                name="Bad",
                text="Bad",
                marks=[],
            )

    def test_invalid_side_empty(self) -> None:
        """side='' should raise ValidationError."""
        with pytest.raises(ValidationError):
            DialogueMessage(
                type="dialogue",
                side="",  # type: ignore[arg-type]
                name="Bad",
                text="Bad",
                marks=[],
            )

    def test_invalid_type(self) -> None:
        """type='narration' on DialogueMessage should fail."""
        with pytest.raises(ValidationError):
            DialogueMessage(
                type="narration",  # type: ignore[arg-type]
                side="left",
                name="Bad",
                text="Bad",
                marks=[],
            )

    def test_valid_with_marks(self) -> None:
        """DialogueMessage with vocabulary marks should validate."""
        msg = DialogueMessage(
            type="dialogue",
            side="right",
            name="Kazuhiko",
            text="The bank called.",
            marks=[
                Mark(word="bank", index=1, definition="银行", is_new=True),
            ],
        )
        assert msg.marks[0].word == "bank"

    def test_default_marks_is_empty(self) -> None:
        """DialogueMessage without marks should default to empty list."""
        msg = DialogueMessage(type="dialogue", side="left", name="Anna", text="Hi.")
        assert msg.marks == []


class TestVocabEntry:
    """Tests for VocabEntry model."""

    def test_valid_new(self) -> None:
        ve = VocabEntry(word="bank", definition="河岸", is_new=True)
        assert ve.word == "bank"
        assert ve.definition == "河岸"
        assert ve.is_new is True

    def test_valid_review(self) -> None:
        ve = VocabEntry(word="footstep", definition="脚步", is_new=False)
        assert ve.is_new is False


class TestEpisode:
    """Tests for Episode model with full FormatSpec v3 roundtrip.

    Key verification: model_dump → model_validate using the authoritative
    example from documents/format_spec_json.md §完整示例.
    """

    def test_valid_minimal(self) -> None:
        """Episode with empty messages/vocab should validate."""
        ep = Episode(
            meta=Meta(ep=1, title="Start", kind="main"),
            messages=[],
            vocab=[],
        )
        assert ep.meta.ep == 1
        assert ep.messages == []
        assert ep.vocab == []

    def test_valid_full(self) -> None:
        """Full episode with narration + dialogue + vocab should validate."""
        ep = Episode(
            meta=Meta(ep=3, title="The Glass", kind="main"),
            messages=[
                NarrationMessage(
                    type="narration",
                    text="Footsteps approach. A shadow falls across my table.",
                    marks=[
                        Mark(word="footstep", index=0, definition="脚步", is_new=False),
                    ],
                ),
                DialogueMessage(
                    type="dialogue",
                    side="left",
                    name="Anna",
                    text="Hey.",
                    marks=[],
                ),
                NarrationMessage(
                    type="narration",
                    text="This is the moment my quiet invisible life ends.",
                    marks=[
                        Mark(
                            word="invisible", index=6, definition="隐形的", is_new=True
                        ),
                    ],
                ),
                DialogueMessage(
                    type="dialogue",
                    side="right",
                    name="Kazuhiko",
                    text="...Nukumizu who?",
                    marks=[],
                ),
            ],
            vocab=[
                VocabEntry(word="footstep", definition="脚步", is_new=False),
                VocabEntry(word="invisible", definition="隐形的", is_new=True),
            ],
        )
        assert ep.meta.ep == 3
        assert ep.meta.title == "The Glass"
        assert len(ep.messages) == 4
        assert ep.messages[0].type == "narration"
        assert ep.messages[1].type == "dialogue"
        assert ep.messages[1].side == "left"  # type: ignore[union-attr]
        assert ep.messages[3].side == "right"  # type: ignore[union-attr]
        assert len(ep.vocab) == 2

    def test_roundtrip_from_format_spec_example(self) -> None:
        """Episode.model_validate() the complete FormatSpec v3 example must pass."""
        data = json.loads("""{
            "meta": {
                "ep": 3,
                "title": "The Glass",
                "kind": "main"
            },
            "messages": [
                {
                    "type": "narration",
                    "text": "Footsteps approach. A shadow falls across my table.",
                    "marks": [
                        { "word": "footstep", "index": 0, "definition": "脚步", "is_new": false }
                    ]
                },
                {
                    "type": "dialogue",
                    "side": "left",
                    "name": "Anna",
                    "text": "Hey.",
                    "marks": []
                },
                {
                    "type": "dialogue",
                    "side": "left",
                    "name": "Anna",
                    "text": "You're Nukumizu, right? Class C?",
                    "marks": []
                },
                {
                    "type": "narration",
                    "text": "This is the moment my quiet invisible life ends.",
                    "marks": [
                        { "word": "invisible", "index": 6, "definition": "隐形的", "is_new": true }
                    ]
                },
                {
                    "type": "dialogue",
                    "side": "right",
                    "name": "Kazuhiko",
                    "text": "...Nukumizu who?",
                    "marks": []
                }
            ],
            "vocab": [
                { "word": "footstep", "definition": "脚步", "is_new": false },
                { "word": "invisible", "definition": "隐形的", "is_new": true }
            ]
        }""")
        ep = Episode.model_validate(data)
        assert ep.meta.ep == 3
        assert ep.meta.kind == "main"
        assert len(ep.messages) == 5
        # Verify narration message
        assert ep.messages[0].type == "narration"
        assert ep.messages[0].marks[0].word == "footstep"  # type: ignore[union-attr]
        assert ep.messages[0].marks[0].index == 0  # type: ignore[union-attr]
        # Verify dialogue message (left side)
        assert ep.messages[1].type == "dialogue"
        assert ep.messages[1].side == "left"  # type: ignore[union-attr]
        assert ep.messages[1].name == "Anna"  # type: ignore[union-attr]
        # Verify protagonist side (right)
        assert ep.messages[4].type == "dialogue"
        assert ep.messages[4].side == "right"  # type: ignore[union-attr]
        # Verify vocab
        assert len(ep.vocab) == 2
        assert ep.vocab[0].word == "footstep"

    def test_dump_roundtrip(self) -> None:
        """model_dump → model_validate should produce equivalent Episode."""
        ep = Episode(
            meta=Meta(ep=1, title="Test", kind="side"),
            messages=[
                NarrationMessage(
                    type="narration",
                    text="Test text.",
                    marks=[Mark(word="test", index=0, definition="测试", is_new=True)],
                ),
            ],
            vocab=[VocabEntry(word="test", definition="测试", is_new=True)],
        )
        dumped = ep.model_dump()
        reloaded = Episode.model_validate(dumped)
        assert reloaded.meta.ep == 1
        assert reloaded.meta.kind == "side"
        assert reloaded.messages[0].text == "Test text."  # type: ignore[union-attr]
        assert reloaded.vocab[0].word == "test"

    def test_polysemy_example(self) -> None:
        """Episode with same word, different meanings (bank=河岸 vs bank=银行) should validate."""
        ep = Episode(
            meta=Meta(ep=5, title="The River", kind="main"),
            messages=[
                NarrationMessage(
                    type="narration",
                    text="I sat down on the bank and watched the water.",
                    marks=[
                        Mark(word="bank", index=5, definition="河岸", is_new=True),
                    ],
                ),
                DialogueMessage(
                    type="dialogue",
                    side="right",
                    name="Kazuhiko",
                    text="The bank called. They want to talk about my loan.",
                    marks=[
                        Mark(word="bank", index=1, definition="银行", is_new=True),
                    ],
                ),
            ],
            vocab=[
                VocabEntry(word="bank", definition="河岸", is_new=True),
                VocabEntry(word="bank", definition="银行", is_new=True),
            ],
        )
        assert len(ep.vocab) == 2
        assert ep.vocab[0].definition == "河岸"
        assert ep.vocab[1].definition == "银行"

    def test_marks_index_maps_to_split_text(self) -> None:
        """marks.index is 0-based word index by split(' ').

        text.split(' ')[mark.index] must equal mark.word (surface form).
        """
        text = "The bank said the bank of the river was eroding."
        marks = [
            Mark(word="bank", index=1, definition="银行", is_new=True),
            Mark(word="bank", index=4, definition="河岸", is_new=True),
        ]
        assert text.split(" ")[marks[0].index] == "bank"
        assert text.split(" ")[marks[1].index] == "bank"

    def test_surface_form_not_lemma_in_mark(self) -> None:
        """Mark.word should be surface form (e.g. 'consuming'), not lemma (e.g. 'consume')."""
        mark = Mark(word="consuming", index=3, definition="消耗", is_new=True)
        assert mark.word == "consuming"
        # Verify it's NOT the lemma
        assert mark.word != "consume"

    def test_dialogue_side_right_is_protagonist(self) -> None:
        """side='right' must correspond to protagonist, 'left' to other character."""
        right_msg = DialogueMessage(
            type="dialogue", side="right", name="Kazuhiko", text="Hi."
        )
        left_msg = DialogueMessage(
            type="dialogue", side="left", name="Anna", text="Hello."
        )
        assert right_msg.side == "right"
        assert left_msg.side == "left"
