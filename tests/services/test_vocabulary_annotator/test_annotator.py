"""Tests for VocabularyAnnotator service.

Ref: T4 refactor — annotator now self-derives surface forms via ECDICT
lemma lookup instead of relying on caller-provided surface_form.
"""

from __future__ import annotations

import datetime
import sqlite3
from pathlib import Path

import pytest

from app.models.episode import DialogueMessage, NarrationMessage
from app.models.fsrs import FsrsCard
from app.models.vocabulary import UserVocabulary, VocabularyItem
from app.services.vocabulary_annotator import VocabularyAnnotator


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_fsrs_card(
    last_review: datetime.datetime | None = None,
    card_id: int = 1,
) -> FsrsCard:
    """Build a minimal FsrsCard for testing."""
    return FsrsCard(
        card_id=card_id,
        state=2,
        stability=1.0,
        difficulty=0.5,
        due=datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc),
        last_review=last_review,
    )


def _make_vocab_item(
    item_id: str,
    word: str,
    meaning: str,
    last_review: datetime.datetime | None = None,
) -> VocabularyItem:
    """Build a minimal VocabularyItem for testing."""
    return VocabularyItem(
        id=item_id,
        word=word,
        meaning=meaning,
        chapter_first_seen=1,
        fsrs_card=_make_fsrs_card(last_review=last_review),
    )


@pytest.fixture(scope="module")
def ecdict_db() -> sqlite3.Connection:
    """Open the real ECDICT database for lemma derivation tests.

    Uses the default path ``asset/ecdict_mobile.db`` relative to the
    project root (tests run with ``pythonpath = .`` in pytest.ini).
    """
    db_path = Path("asset/ecdict_mobile.db")
    if not db_path.exists():
        pytest.skip("ECDICT database not available at asset/ecdict_mobile.db")
    conn = sqlite3.connect(str(db_path))
    yield conn
    conn.close()


@pytest.fixture
def user_vocab() -> UserVocabulary:
    """A UserVocabulary with two items: one never-reviewed, one already reviewed."""
    return UserVocabulary(
        user_id="test_user",
        vocabulary=[
            _make_vocab_item("consume_v1", "consume", "消费", last_review=None),
            _make_vocab_item(
                "bank_river",
                "bank",
                "河岸",
                last_review=datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc),
            ),
        ],
    )


@pytest.fixture
def annotator(
    user_vocab: UserVocabulary, ecdict_db: sqlite3.Connection
) -> VocabularyAnnotator:
    """VocabularyAnnotator initialised with the fixture vocab and ECDICT db."""
    return VocabularyAnnotator(user_vocab=user_vocab, ecdict_db=ecdict_db)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSimpleAnnotation:
    """Basic annotation: one target word in one message."""

    def test_marks_populated(self, annotator: VocabularyAnnotator) -> None:
        msg = NarrationMessage(type="narration", text="He was consuming food.")
        target_words = [
            {"lemma": "consume", "meaning": "消费", "item_id": "consume_v1"}
        ]
        shown_set: set[str] = set()

        result = annotator.annotate(
            messages=[msg],
            target_words=target_words,
            shown_set=shown_set,
        )

        assert len(result) == 1
        assert len(result[0].marks) == 1
        mark = result[0].marks[0]
        assert mark.word == "consuming"  # surface form from text
        assert mark.index == 2  # 0-based word index
        assert mark.definition == "消费"  # from VocabularyItem.meaning
        assert mark.is_new is True

    def test_punctuation_handling(self, annotator: VocabularyAnnotator) -> None:
        """Target word with trailing punctuation should still match."""
        msg = NarrationMessage(type="narration", text="She was consuming, slowly.")
        target_words = [
            {"lemma": "consume", "meaning": "消费", "item_id": "consume_v1"}
        ]

        result = annotator.annotate(
            messages=[msg],
            target_words=target_words,
            shown_set=set(),
        )

        assert len(result[0].marks) == 1
        assert result[0].marks[0].index == 2

    def test_case_insensitive(self, annotator: VocabularyAnnotator) -> None:
        """Lemma matching should be case-insensitive (Consuming → consuming → consume)."""
        msg = NarrationMessage(type="narration", text="Consuming food is nice.")
        target_words = [
            {"lemma": "consume", "meaning": "消费", "item_id": "consume_v1"}
        ]

        result = annotator.annotate(
            messages=[msg],
            target_words=target_words,
            shown_set=set(),
        )

        assert len(result[0].marks) == 1
        assert result[0].marks[0].index == 0
        assert result[0].marks[0].word == "Consuming"  # preserves original case


class TestIsNew:
    """is_new determination logic."""

    def test_is_new_true(self, annotator: VocabularyAnnotator) -> None:
        """First occurrence of an unseen word → is_new=True."""
        msg = NarrationMessage(type="narration", text="He was consuming food.")
        target_words = [
            {"lemma": "consume", "meaning": "消费", "item_id": "consume_v1"}
        ]

        result = annotator.annotate(
            messages=[msg],
            target_words=target_words,
            shown_set=set(),
        )

        assert result[0].marks[0].is_new is True

    def test_is_new_false_already_shown(self, annotator: VocabularyAnnotator) -> None:
        """Word already in shown_set → is_new=False."""
        msg = NarrationMessage(type="narration", text="He was consuming food.")
        target_words = [
            {"lemma": "consume", "meaning": "消费", "item_id": "consume_v1"}
        ]

        result = annotator.annotate(
            messages=[msg],
            target_words=target_words,
            shown_set={"consume_v1"},
        )

        assert result[0].marks[0].is_new is False

    def test_is_new_false_already_reviewed(
        self, annotator: VocabularyAnnotator
    ) -> None:
        """Word with last_review set → is_new=False even if not in shown_set."""
        msg = NarrationMessage(type="narration", text="by the bank river.")
        target_words = [{"lemma": "bank", "meaning": "河岸", "item_id": "bank_river"}]

        result = annotator.annotate(
            messages=[msg],
            target_words=target_words,
            shown_set=set(),
        )

        assert result[0].marks[0].is_new is False

    def test_shown_set_mutated(self, annotator: VocabularyAnnotator) -> None:
        """shown_set should be mutated when is_new=True is determined."""
        msg = NarrationMessage(type="narration", text="He was consuming food.")
        target_words = [
            {"lemma": "consume", "meaning": "消费", "item_id": "consume_v1"}
        ]
        shown_set: set[str] = set()

        annotator.annotate(
            messages=[msg],
            target_words=target_words,
            shown_set=shown_set,
        )

        assert "consume_v1" in shown_set


class TestMultipleOccurrences:
    """Same word appearing multiple times in text."""

    def test_first_new_subsequent_not(self, annotator: VocabularyAnnotator) -> None:
        """Only the first occurrence of a new word gets is_new=True."""
        msg = NarrationMessage(
            type="narration",
            text="consuming consuming consuming",
        )
        target_words = [
            {"lemma": "consume", "meaning": "消费", "item_id": "consume_v1"}
        ]

        result = annotator.annotate(
            messages=[msg],
            target_words=target_words,
            shown_set=set(),
        )

        assert len(result[0].marks) == 3
        assert result[0].marks[0].is_new is True
        assert result[0].marks[1].is_new is False
        assert result[0].marks[2].is_new is False
        # indices should be 0, 1, 2
        assert [m.index for m in result[0].marks] == [0, 1, 2]


class TestSurfaceFormPreserved:
    """marks.word must store the surface form, NOT the lemma."""

    def test_surface_form_stored(self, annotator: VocabularyAnnotator) -> None:
        msg = NarrationMessage(type="narration", text="He was consuming food greedily.")
        target_words = [
            {"lemma": "consume", "meaning": "消费", "item_id": "consume_v1"}
        ]

        result = annotator.annotate(
            messages=[msg],
            target_words=target_words,
            shown_set=set(),
        )

        mark = result[0].marks[0]
        assert mark.word == "consuming"  # surface form, not lemma "consume"
        assert mark.definition == "消费"  # from VocabularyItem.meaning

    def test_rewriter_surface_hint_used(self, annotator: VocabularyAnnotator) -> None:
        """When StoryRewriter reports surface, annotator can match it directly."""
        msg = NarrationMessage(type="narration", text="He ate with calm focus.")
        target_words = [
            {
                "item_id": "consume_v1",
                "word": "consume",
                "meaning": "消费",
                "surface": "ate",
            }
        ]

        result = annotator.annotate(
            messages=[msg],
            target_words=target_words,
            shown_set=set(),
        )

        assert len(result[0].marks) == 1
        mark = result[0].marks[0]
        assert mark.item_id == "consume_v1"
        assert mark.word == "ate"
        assert mark.index == 1


class TestDialogueMessage:
    """Annotation works on DialogueMessage as well as NarrationMessage."""

    def test_dialogue_annotated(self, annotator: VocabularyAnnotator) -> None:
        msg = DialogueMessage(
            type="dialogue",
            side="right",
            name="主角",
            text="I am consuming the food.",
        )
        target_words = [
            {"lemma": "consume", "meaning": "消费", "item_id": "consume_v1"}
        ]

        result = annotator.annotate(
            messages=[msg],
            target_words=target_words,
            shown_set=set(),
        )

        assert len(result[0].marks) == 1
        mark = result[0].marks[0]
        assert mark.word == "consuming"
        assert mark.index == 2


class TestEdgeCases:
    """Edge case and boundary tests."""

    def test_empty_messages(self, annotator: VocabularyAnnotator) -> None:
        """Empty message list → empty result."""
        result = annotator.annotate(
            messages=[],
            target_words=[
                {"lemma": "consume", "meaning": "消费", "item_id": "consume_v1"}
            ],
            shown_set=set(),
        )
        assert result == []

    def test_no_target_words(self, annotator: VocabularyAnnotator) -> None:
        """Messages with no target words → no marks added."""
        msg = NarrationMessage(type="narration", text="Just some text.")
        result = annotator.annotate(
            messages=[msg],
            target_words=[],
            shown_set=set(),
        )
        assert result[0].marks == []

    def test_unknown_item_id(self, annotator: VocabularyAnnotator) -> None:
        """Target word with unknown item_id → skipped gracefully."""
        msg = NarrationMessage(type="narration", text="Hello world.")
        target_words = [{"lemma": "hello", "meaning": "你好", "item_id": "nonexistent"}]

        result = annotator.annotate(
            messages=[msg],
            target_words=target_words,
            shown_set=set(),
        )
        assert result[0].marks == []

    def test_lemma_not_in_text(self, annotator: VocabularyAnnotator) -> None:
        """Target word whose lemma doesn't appear in any token → skipped."""
        msg = NarrationMessage(type="narration", text="No matching words here.")
        target_words = [{"lemma": "xyzzy", "meaning": "?", "item_id": "consume_v1"}]

        result = annotator.annotate(
            messages=[msg],
            target_words=target_words,
            shown_set=set(),
        )
        assert result[0].marks == []

    def test_marks_sorted_by_index(
        self, user_vocab: UserVocabulary, ecdict_db: sqlite3.Connection
    ) -> None:
        """Marks should be sorted by index regardless of target_words order."""
        # Create vocab items for "aaa" and "zzz"
        uv = UserVocabulary(
            user_id="test",
            vocabulary=[
                _make_vocab_item("aaa_v1", "aaa", "A", last_review=None),
                _make_vocab_item("zzz_v1", "zzz", "Z", last_review=None),
            ],
        )
        ann = VocabularyAnnotator(user_vocab=uv, ecdict_db=ecdict_db)

        msg = NarrationMessage(type="narration", text="zzz middle aaa end.")
        target_words = [
            {"lemma": "zzz", "meaning": "Z", "item_id": "zzz_v1"},
            {"lemma": "aaa", "meaning": "A", "item_id": "aaa_v1"},
        ]

        result = ann.annotate(
            messages=[msg],
            target_words=target_words,
            shown_set=set(),
        )

        indices = [m.index for m in result[0].marks]
        assert indices == sorted(indices), f"Marks not sorted: {indices}"

    def test_mixed_messages(self, annotator: VocabularyAnnotator) -> None:
        """Multiple messages of different types should all be annotated."""
        msgs: list[NarrationMessage | DialogueMessage] = [
            NarrationMessage(type="narration", text="He was consuming."),
            DialogueMessage(
                type="dialogue",
                side="left",
                name="配角",
                text="I see you consuming.",
            ),
        ]
        target_words = [
            {"lemma": "consume", "meaning": "消费", "item_id": "consume_v1"}
        ]
        shown_set: set[str] = set()

        result = annotator.annotate(
            messages=msgs,
            target_words=target_words,
            shown_set=shown_set,
        )

        # First occurrence is_new=True, second is_new=False
        assert result[0].marks[0].is_new is True
        assert result[1].marks[0].is_new is False

    def test_model_copy_preserves_fields(self, annotator: VocabularyAnnotator) -> None:
        """Annotated messages should preserve original type and fields."""
        msg = NarrationMessage(type="narration", text="Hello world.")
        target_words = [{"lemma": "world", "meaning": "世界", "item_id": "consume_v1"}]

        result = annotator.annotate(
            messages=[msg],
            target_words=target_words,
            shown_set=set(),
        )

        assert isinstance(result[0], NarrationMessage)
        assert result[0].type == "narration"
        assert result[0].text == "Hello world."
        assert len(result[0].marks) == 1


# ---------------------------------------------------------------------------
# T4: New tests for ECDICT self-derivation
# ---------------------------------------------------------------------------


class TestEcdictSelfDerivation:
    """Verify that the annotator correctly derives lemmas via ECDICT."""

    def test_ecdict_derives_went_to_go(self, annotator: VocabularyAnnotator) -> None:
        """ECDICT resolves "went" → lemma "go" → matches target with lemma="go"."""
        msg = NarrationMessage(type="narration", text="He went home after work.")
        # Need a vocab item whose lemma is "go"
        uv = UserVocabulary(
            user_id="test",
            vocabulary=[
                _make_vocab_item("go_v1", "go", "去", last_review=None),
            ],
        )
        ann = VocabularyAnnotator(user_vocab=uv, ecdict_db=annotator.ecdict_db)
        target_words = [{"lemma": "go", "meaning": "去", "item_id": "go_v1"}]

        result = ann.annotate(
            messages=[msg],
            target_words=target_words,
            shown_set=set(),
        )

        assert len(result[0].marks) == 1
        mark = result[0].marks[0]
        assert mark.word == "went"  # surface form from text, NOT lemma "go"
        assert mark.index == 1  # "He"(0) "went"(1) "home"(2) ...
        assert mark.definition == "去"
        assert mark.is_new is True

    def test_multiple_inflections_same_lemma(
        self, annotator: VocabularyAnnotator
    ) -> None:
        """Different surface forms of the same lemma all get marks."""
        msg = NarrationMessage(
            type="narration",
            text="He went and has gone already.",
        )
        uv = UserVocabulary(
            user_id="test",
            vocabulary=[
                _make_vocab_item("go_v1", "go", "去", last_review=None),
            ],
        )
        ann = VocabularyAnnotator(user_vocab=uv, ecdict_db=annotator.ecdict_db)
        target_words = [{"lemma": "go", "meaning": "去", "item_id": "go_v1"}]

        result = ann.annotate(
            messages=[msg],
            target_words=target_words,
            shown_set=set(),
        )

        # "went" at index 1, "gone" at index 4
        assert len(result[0].marks) == 2
        assert result[0].marks[0].word == "went"
        assert result[0].marks[0].index == 1
        assert result[0].marks[0].is_new is True  # first occurrence
        assert result[0].marks[1].word == "gone"
        assert result[0].marks[1].index == 4
        assert result[0].marks[1].is_new is False  # already shown

    def test_lemma_no_match_in_text(self, annotator: VocabularyAnnotator) -> None:
        """Target lemma not present in text → no marks (even if related words exist)."""
        msg = NarrationMessage(type="narration", text="He was eating dinner.")
        target_words = [
            {"lemma": "consume", "meaning": "消费", "item_id": "consume_v1"}
        ]

        result = annotator.annotate(
            messages=[msg],
            target_words=target_words,
            shown_set=set(),
        )

        # "eating" → lemma "eat", NOT "consume" → no marks
        assert result[0].marks == []

    def test_ecdict_derives_banks_to_bank(self, annotator: VocabularyAnnotator) -> None:
        """ECDICT resolves plural "banks" → lemma "bank"."""
        msg = NarrationMessage(type="narration", text="The banks were open.")
        target_words = [{"lemma": "bank", "meaning": "河岸", "item_id": "bank_river"}]

        result = annotator.annotate(
            messages=[msg],
            target_words=target_words,
            shown_set=set(),
        )

        assert len(result[0].marks) == 1
        assert result[0].marks[0].word == "banks"
        assert result[0].marks[0].index == 1
