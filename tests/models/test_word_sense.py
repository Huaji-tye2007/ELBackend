"""Tests for app.models.word_sense — WordSenseEntry, WordSense, WordSenseDB."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.models.word_sense import WordSense, WordSenseDB, WordSenseEntry


class TestWordSenseEntry:
    """Tests for WordSenseEntry model — a single sense of a word."""

    def test_valid_minimal(self) -> None:
        """WordSenseEntry with id and meaning should validate."""
        entry = WordSenseEntry(id="bank_river", meaning="河岸")
        assert entry.id == "bank_river"
        assert entry.meaning == "河岸"

    def test_valid_full(self) -> None:
        """WordSenseEntry with different id and meaning should validate."""
        entry = WordSenseEntry(id="issue_topic", meaning="议题")
        assert entry.id == "issue_topic"
        assert entry.meaning == "议题"

    def test_invalid_missing_id(self) -> None:
        """WordSenseEntry without id should raise ValidationError."""
        with pytest.raises(ValidationError):
            WordSenseEntry(meaning="测试")  # type: ignore[call-arg]

    def test_invalid_missing_meaning(self) -> None:
        """WordSenseEntry without meaning should raise ValidationError."""
        with pytest.raises(ValidationError):
            WordSenseEntry(id="test_1")  # type: ignore[call-arg]


class TestWordSense:
    """Tests for WordSense model — is_polysemous + list of senses."""

    def test_valid_single_sense(self) -> None:
        """WordSense with is_polysemous=False and one sense should validate."""
        ws = WordSense(
            is_polysemous=False,
            senses=[WordSenseEntry(id="awkward_1", meaning="尴尬的")],
        )
        assert ws.is_polysemous is False
        assert len(ws.senses) == 1
        assert ws.senses[0].id == "awkward_1"
        assert ws.senses[0].meaning == "尴尬的"

    def test_valid_polysemous(self) -> None:
        """WordSense with is_polysemous=True and multiple senses should validate."""
        ws = WordSense(
            is_polysemous=True,
            senses=[
                WordSenseEntry(id="bank_river", meaning="河岸"),
                WordSenseEntry(id="bank_finance", meaning="银行"),
            ],
        )
        assert ws.is_polysemous is True
        assert len(ws.senses) == 2
        assert ws.senses[0].id == "bank_river"
        assert ws.senses[1].meaning == "银行"

    def test_invalid_missing_is_polysemous(self) -> None:
        """WordSense without is_polysemous should raise ValidationError."""
        with pytest.raises(ValidationError):
            WordSense(senses=[WordSenseEntry(id="x", meaning="y")])  # type: ignore[call-arg]

    def test_invalid_senses_not_list(self) -> None:
        """WordSense with senses as a string should raise ValidationError."""
        with pytest.raises(ValidationError):
            WordSense(is_polysemous=False, senses="not_a_list")  # type: ignore[arg-type]


class TestWordSenseDB:
    """Tests for WordSenseDB RootModel — dict[str, WordSense]."""

    def test_valid_empty(self) -> None:
        """WordSenseDB with empty dict should validate."""
        db = WordSenseDB({})
        assert db.root == {}

    def test_valid_single_entry(self) -> None:
        """WordSenseDB with one non-polysemous word should validate."""
        db = WordSenseDB(
            {
                "awkward": WordSense(
                    is_polysemous=False,
                    senses=[WordSenseEntry(id="awkward_1", meaning="尴尬的")],
                ),
            }
        )
        assert "awkward" in db.root
        assert db.root["awkward"].is_polysemous is False
        assert len(db.root["awkward"].senses) == 1
        assert db.root["awkward"].senses[0].id == "awkward_1"

    def test_valid_polysemous_entries(self) -> None:
        """WordSenseDB with polysemous words should validate."""
        db = WordSenseDB(
            {
                "bank": WordSense(
                    is_polysemous=True,
                    senses=[
                        WordSenseEntry(id="bank_river", meaning="河岸"),
                        WordSenseEntry(id="bank_finance", meaning="银行"),
                    ],
                ),
                "glance": WordSense(
                    is_polysemous=True,
                    senses=[
                        WordSenseEntry(id="glance_look", meaning="一瞥"),
                        WordSenseEntry(id="glance_reflect", meaning="反光"),
                    ],
                ),
            }
        )
        assert db.root["bank"].is_polysemous is True
        assert len(db.root["bank"].senses) == 2
        assert db.root["bank"].senses[1].meaning == "银行"
        assert db.root["glance"].senses[0].id == "glance_look"

    def test_invalid_bad_value(self) -> None:
        """WordSenseDB with a non-WordSense dict value should raise ValidationError."""
        with pytest.raises(ValidationError):
            WordSenseDB({"bad": "not_a_word_sense"})  # type: ignore[dict-item]

    def test_invalid_bad_senses_field(self) -> None:
        """WordSenseDB with missing 'senses' in a value should raise ValidationError."""
        with pytest.raises(ValidationError):
            WordSenseDB({"bad": {"is_polysemous": False}})  # type: ignore[dict-item]

    def test_validate_from_fixture(self) -> None:
        """WordSenseDB.model_validate() the word_sense_db.json fixture (8 entries)."""
        fixture_path = Path(__file__).parent.parent / "fixtures" / "word_sense_db.json"
        raw = fixture_path.read_text(encoding="utf-8")
        data = json.loads(raw)
        db = WordSenseDB.model_validate(data)

        # total entry count
        assert len(db.root) == 10

        # spot-check polysemous word "bank"
        assert "bank" in db.root
        bank = db.root["bank"]
        assert bank.is_polysemous is True
        assert len(bank.senses) == 2
        assert bank.senses[0].id == "bank_river"
        assert bank.senses[0].meaning == "河岸"
        assert bank.senses[1].id == "bank_finance"
        assert bank.senses[1].meaning == "银行"

        # spot-check single-sense word "awkward"
        assert "awkward" in db.root
        awkward = db.root["awkward"]
        assert awkward.is_polysemous is False
        assert len(awkward.senses) == 1
        assert awkward.senses[0].id == "awkward_1"
        assert awkward.senses[0].meaning == "尴尬的"

        # dict-like access pattern verification
        assert db.root["issue"].is_polysemous is True
        assert db.root["resonate"].is_polysemous is False

    def test_roundtrip(self) -> None:
        """WordSenseDB model_dump → model_validate should produce equal data."""
        original = WordSenseDB(
            {
                "bank": WordSense(
                    is_polysemous=True,
                    senses=[
                        WordSenseEntry(id="bank_river", meaning="河岸"),
                        WordSenseEntry(id="bank_finance", meaning="银行"),
                    ],
                ),
            }
        )
        dumped = original.model_dump()
        reloaded = WordSenseDB.model_validate(dumped)
        assert reloaded.root["bank"].is_polysemous is True
        assert len(reloaded.root["bank"].senses) == 2
        assert reloaded.root["bank"].senses[0].id == "bank_river"
