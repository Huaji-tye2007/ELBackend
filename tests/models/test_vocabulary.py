"""Tests for app.models.vocabulary — VocabularyItem and UserVocabulary."""

import json
import re
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.models.fsrs import FsrsCard
from app.models.vocabulary import UserVocabulary, VocabularyItem


class TestVocabularyItem:
    """Tests for VocabularyItem model."""

    def test_valid_minimal(self) -> None:
        """VocabularyItem with required fields and default history_window should validate."""
        vi = VocabularyItem(
            id="test_1",
            word="test",
            meaning="测试",
            chapter_first_seen=1,
            fsrs_card=FsrsCard(state=1, due=datetime.now(timezone.utc)),
        )
        assert vi.id == "test_1"
        assert vi.word == "test"
        assert vi.meaning == "测试"
        assert vi.chapter_first_seen == 1
        assert vi.history_window == [1, 1, 1, 1, 1]
        assert vi.fsrs_card.state == 1

    def test_valid_full(self) -> None:
        """VocabularyItem with all fields explicitly set should validate."""
        vi = VocabularyItem(
            id="test_2",
            word="testing",
            meaning="测试中",
            chapter_first_seen=3,
            history_window=[0, 1, 0, 1, 1],
            fsrs_card=FsrsCard(
                state=2,
                due=datetime(2026, 6, 7, tzinfo=timezone.utc),
            ),
        )
        assert vi.id == "test_2"
        assert vi.word == "testing"
        assert vi.meaning == "测试中"
        assert vi.chapter_first_seen == 3
        assert vi.history_window == [0, 1, 0, 1, 1]
        assert vi.fsrs_card.state == 2

    def test_default_history_window_is_all_ones(self) -> None:
        """VocabularyItem without history_window should default to [1,1,1,1,1]."""
        vi = VocabularyItem(
            id="new_1",
            word="newbie",
            meaning="新手",
            chapter_first_seen=5,
            fsrs_card=FsrsCard(state=1, due=datetime.now(timezone.utc)),
        )
        assert vi.history_window == [1, 1, 1, 1, 1]
        assert len(vi.history_window) == 5

    def test_invalid_chapter_first_seen_zero(self) -> None:
        """VocabularyItem with chapter_first_seen=0 should raise ValidationError."""
        with pytest.raises(ValidationError):
            VocabularyItem(
                id="bad_1",
                word="bad",
                meaning="坏",
                chapter_first_seen=0,
                fsrs_card=FsrsCard(state=1, due=datetime.now(timezone.utc)),
            )


class TestUserVocabulary:
    """Tests for UserVocabulary model."""

    def _make_item(
        self, item_id: str, word: str, meaning: str, chapter_first_seen: int = 1
    ) -> VocabularyItem:
        """Helper to create a VocabularyItem with a minimal FsrsCard."""
        return VocabularyItem(
            id=item_id,
            word=word,
            meaning=meaning,
            chapter_first_seen=chapter_first_seen,
            fsrs_card=FsrsCard(state=1, due=datetime.now(timezone.utc)),
        )

    def test_valid_minimal(self) -> None:
        """UserVocabulary with user_id and empty vocabulary should validate."""
        uv = UserVocabulary(user_id="001")
        assert uv.user_id == "001"
        assert uv.vocabulary == []
        assert uv.vocab_index == {}
        assert uv.lemma_index == {}

    def test_valid_full(self) -> None:
        """UserVocabulary with user_id and vocabulary list should validate."""
        items = [
            self._make_item("awkward_1", "awkward", "尴尬的"),
            self._make_item("meticulous_1", "meticulous", "一丝不苟的", 2),
        ]
        uv = UserVocabulary(user_id="001", vocabulary=items)
        assert uv.user_id == "001"
        assert len(uv.vocabulary) == 2
        assert uv.vocabulary[0].word == "awkward"
        assert uv.vocabulary[1].chapter_first_seen == 2

    def test_vocab_index_lookup(self) -> None:
        """vocab_index should map item_id → VocabularyItem."""
        items = [
            self._make_item("awkward_1", "awkward", "尴尬的"),
            self._make_item("meticulous_1", "meticulous", "一丝不苟的"),
        ]
        uv = UserVocabulary(user_id="001", vocabulary=items)
        idx = uv.vocab_index
        assert len(idx) == 2
        assert idx["awkward_1"].word == "awkward"
        assert idx["meticulous_1"].meaning == "一丝不苟的"

    def test_lemma_index_polysemy(self) -> None:
        """lemma_index should distinguish same-lemma different-meaning items."""
        items = [
            self._make_item("bank_river", "bank", "河岸"),
            self._make_item("bank_finance", "bank", "银行"),
            self._make_item("issue_problem", "issue", "问题"),
            self._make_item("issue_topic", "issue", "议题"),
        ]
        uv = UserVocabulary(user_id="001", vocabulary=items)
        li = uv.lemma_index
        assert len(li) == 4
        assert li[("bank", "河岸")] == "bank_river"
        assert li[("bank", "银行")] == "bank_finance"
        assert li[("issue", "问题")] == "issue_problem"
        assert li[("issue", "议题")] == "issue_topic"

    def test_full_roundtrip(self) -> None:
        """UserVocabulary dump → dict → reload should produce equal model."""
        items = [
            self._make_item("awkward_1", "awkward", "尴尬的"),
            self._make_item("meticulous_1", "meticulous", "一丝不苟的", 2),
        ]
        uv = UserVocabulary(user_id="001", vocabulary=items)
        dumped = uv.model_dump()
        reloaded = UserVocabulary.model_validate(dumped)
        assert reloaded.user_id == uv.user_id
        assert len(reloaded.vocabulary) == len(uv.vocabulary)
        assert reloaded.vocabulary[0].id == "awkward_1"
        assert reloaded.vocabulary[1].word == "meticulous"

    def test_validate_from_fixture(self) -> None:
        """UserVocabulary.model_validate() the user_vocabulary.json fixture (24 items)."""
        fixture_path = (
            Path(__file__).parent.parent / "fixtures" / "user_vocabulary.json"
        )
        raw = fixture_path.read_text(encoding="utf-8")
        # Python 3.10 datetime.fromisoformat doesn't accept 'Z' suffix — replace with +00:00
        raw = re.sub(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})Z", r"\1+00:00", raw)
        data = json.loads(raw)
        uv = UserVocabulary.model_validate(data)
        assert uv.user_id == "001"
        assert len(uv.vocabulary) == 24
        # spot-check first and last items
        assert uv.vocabulary[0].id == "awkward_1"
        assert uv.vocabulary[0].word == "awkward"
        assert uv.vocabulary[-1].id == "issue_topic"
        # verify vocab_index O(1) lookup
        assert uv.vocab_index["awkward_1"].meaning == "尴尬的"
        # verify lemma_index polysemy
        assert uv.lemma_index[("bank", "河岸")] == "bank_river"
        assert uv.lemma_index[("bank", "银行")] == "bank_finance"
        assert uv.lemma_index[("issue", "问题")] == "issue_problem"
        assert uv.lemma_index[("issue", "议题")] == "issue_topic"
