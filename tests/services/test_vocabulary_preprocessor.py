"""Tests for VocabularyPreprocessor — word-list import and FSRS card initialization.

Covers: empty list, single word, polysemy, user-meaning matching,
chapter_first_seen, fsrs_card defaults, deduplication, and Pydantic validation.
"""

from __future__ import annotations

import datetime

import pytest

from app.models.fsrs import FsrsCard
from app.models.vocabulary import UserVocabulary, VocabularyItem
from app.models.word_sense import WordSenseDB
from app.services.vocabulary_preprocessor import VocabularyPreprocessor


# ── Fixtures ────────────────────────────────────────────────


@pytest.fixture
def db(sample_word_sense_db: WordSenseDB) -> WordSenseDB:
    """Reuse the shared fixture from tests/conftest.py."""
    return sample_word_sense_db


@pytest.fixture
def preprocessor(db: WordSenseDB) -> VocabularyPreprocessor:
    return VocabularyPreprocessor(db)


@pytest.fixture
def frozen_now() -> datetime.datetime:
    """A fixed UTC datetime used for deterministic fsrs_card.card_id testing."""
    return datetime.datetime(2026, 6, 7, 12, 0, 0, tzinfo=datetime.timezone.utc)


# ── Test: empty list ────────────────────────────────────────


def test_preprocess_empty_list(preprocessor: VocabularyPreprocessor) -> None:
    """Empty input returns UserVocabulary with empty vocabulary."""
    result = preprocessor.preprocess("user_1", [])
    assert isinstance(result, UserVocabulary)
    assert result.user_id == "user_1"
    assert result.vocabulary == []


# ── Test: single word (not in WordSenseDB) ──────────────────


def test_preprocess_single_word_not_in_db(preprocessor: VocabularyPreprocessor) -> None:
    """Single word not in WordSenseDB creates one placeholder item."""
    result = preprocessor.preprocess("user_1", [{"word": "zoology"}])

    assert len(result.vocabulary) == 1
    item = result.vocabulary[0]
    assert item.id == "zoology_1"
    assert item.word == "zoology"
    assert item.meaning == ""
    assert item.chapter_first_seen == 1


# ── Test: single word (in WordSenseDB, non-polysemous) ──────


def test_preprocess_single_word_in_db(preprocessor: VocabularyPreprocessor) -> None:
    """Single non-polysemous word in WordSenseDB creates one item with DB sense."""
    result = preprocessor.preprocess("user_1", [{"word": "meticulous"}])

    assert len(result.vocabulary) == 1
    item = result.vocabulary[0]
    assert item.id == "meticulous_1"
    assert item.word == "meticulous"
    assert item.meaning == "一丝不苟的"


# ── Test: polysemous word ───────────────────────────────────


def test_preprocess_polysemous_word(preprocessor: VocabularyPreprocessor) -> None:
    """Polysemous word without meaning hint creates one item per sense."""
    result = preprocessor.preprocess("user_1", [{"word": "bank"}])

    assert len(result.vocabulary) == 2
    ids = {item.id for item in result.vocabulary}
    assert ids == {"bank_river", "bank_finance"}


# ── Test: user meaning match ─────────────────────────────────


def test_preprocess_user_meaning_match(preprocessor: VocabularyPreprocessor) -> None:
    """Polysemous word with meaning hint matches the correct sense."""
    result = preprocessor.preprocess("user_1", [{"word": "bank", "meaning": "银行"}])

    assert len(result.vocabulary) == 1
    item = result.vocabulary[0]
    assert item.id == "bank_finance"
    assert item.meaning == "银行"


def test_preprocess_user_meaning_no_match(preprocessor: VocabularyPreprocessor) -> None:
    """Meaning hint that does not match any DB sense creates custom sense item."""
    result = preprocessor.preprocess("user_1", [{"word": "bank", "meaning": "堤坝"}])

    assert len(result.vocabulary) == 1
    item = result.vocabulary[0]
    assert item.id == "bank_1"
    assert item.meaning == "堤坝"


# ── Test: chapter_first_seen ─────────────────────────────────


def test_chapter_first_seen_default(preprocessor: VocabularyPreprocessor) -> None:
    """Default chapter_id=1 produces chapter_first_seen=1."""
    result = preprocessor.preprocess("user_1", [{"word": "meticulous"}])
    assert result.vocabulary[0].chapter_first_seen == 1


def test_chapter_first_seen_custom(preprocessor: VocabularyPreprocessor) -> None:
    """Custom chapter_id=5 produces chapter_first_seen=5."""
    result = preprocessor.preprocess("user_1", [{"word": "meticulous"}], chapter_id=5)
    assert result.vocabulary[0].chapter_first_seen == 5


def test_chapter_id_must_be_positive(preprocessor: VocabularyPreprocessor) -> None:
    """chapter_id=0 raises ValueError (must be >= 1)."""
    with pytest.raises(ValueError, match="chapter_id must be >= 1"):
        preprocessor.preprocess("user_1", [{"word": "test"}], chapter_id=0)


# ── Test: fsrs_card defaults ─────────────────────────────────


def test_fsrs_card_defaults(preprocessor: VocabularyPreprocessor) -> None:
    """New items receive fsrs_card with state=1, last_review=None, stability=None, difficulty=None."""
    result = preprocessor.preprocess("user_1", [{"word": "meticulous"}])

    card = result.vocabulary[0].fsrs_card
    assert isinstance(card, FsrsCard)
    assert card.state == 1
    assert card.last_review is None
    assert card.stability is None
    assert card.difficulty is None
    assert card.step is None
    assert card.card_id > 0  # card_id is a positive millisecond timestamp
    assert card.due is not None

    # Verify interoperability with fsrs.Card (per AGENTS.md §16.7)
    from fsrs import Card as FsrsNativeCard

    native = card.to_fsrs_card()
    assert isinstance(native, FsrsNativeCard)
    assert native.card_id == card.card_id


# ── Test: deduplication ─────────────────────────────────────


def test_deduplication(preprocessor: VocabularyPreprocessor) -> None:
    """Same word appearing twice in the batch produces only one item."""
    result = preprocessor.preprocess(
        "user_1",
        [{"word": "meticulous"}, {"word": "meticulous"}],
    )

    assert len(result.vocabulary) == 1
    assert result.vocabulary[0].id == "meticulous_1"


def test_deduplication_polysemous(preprocessor: VocabularyPreprocessor) -> None:
    """Polysemous word deduplicates correctly across the batch."""
    result = preprocessor.preprocess(
        "user_1",
        [
            {"word": "bank"},
            {"word": "bank"},
            {"word": "bank", "meaning": "银行"},
        ],
    )

    # "bank" alone → 2 items (river + finance); the second "bank" deduped;
    # "bank" with meaning "银行" → already covered by bank_finance
    assert len(result.vocabulary) == 2


# ── Test: Pydantic validation ───────────────────────────────


def test_pydantic_validation_roundtrip(preprocessor: VocabularyPreprocessor) -> None:
    """Result can be serialized to JSON and re-validated."""
    result = preprocessor.preprocess("user_1", [{"word": "bank"}])

    json_str = result.model_dump_json()
    reloaded = UserVocabulary.model_validate_json(json_str)

    assert reloaded.user_id == result.user_id
    assert len(reloaded.vocabulary) == len(result.vocabulary)
    assert reloaded.vocabulary[0].id == result.vocabulary[0].id
    assert isinstance(reloaded.vocabulary[0].fsrs_card, FsrsCard)


def test_vocabulary_item_constraints(preprocessor: VocabularyPreprocessor) -> None:
    """Produced VocabularyItems pass Pydantic field validators."""
    result = preprocessor.preprocess("user_1", [{"word": "coherent"}])
    item = result.vocabulary[0]

    # Re-validate individually
    validated = VocabularyItem.model_validate(item.model_dump())
    assert validated.chapter_first_seen >= 1
    assert isinstance(validated.fsrs_card, FsrsCard)
    assert validated.fsrs_card.state in (1, 2, 3)


# ── Test: helper methods ────────────────────────────────────


def test_find_matching_sense_exact(preprocessor: VocabularyPreprocessor) -> None:
    """_find_matching_sense with exact meaning match."""
    matched = preprocessor._find_matching_sense("bank", "银行")
    assert matched is not None
    assert matched.id == "bank_finance"


def test_find_matching_sense_substring(preprocessor: VocabularyPreprocessor) -> None:
    """_find_matching_sense with substring match."""
    matched = preprocessor._find_matching_sense("bank", "银")
    assert matched is not None
    assert matched.id == "bank_finance"


def test_find_matching_sense_no_match(preprocessor: VocabularyPreprocessor) -> None:
    """_find_matching_sense with no match returns None."""
    matched = preprocessor._find_matching_sense("bank", "动物园")
    assert matched is None


def test_create_all_senses_unknown_word(preprocessor: VocabularyPreprocessor) -> None:
    """_create_all_senses for unknown word creates placeholder."""
    items = preprocessor._create_all_senses("nonexistent", chapter_id=1)
    assert len(items) == 1
    assert items[0].id == "nonexistent_1"
    assert items[0].meaning == ""
