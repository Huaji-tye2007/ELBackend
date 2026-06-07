"""Tests for app.models.chapter — Chapter and ChapterDB."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.models.chapter import Chapter, ChapterDB


class TestChapter:
    """Tests for Chapter model."""

    def test_valid_minimal(self) -> None:
        """Chapter with required fields should validate."""
        ch = Chapter(
            chapter_id=1,
            title="Test",
            raw_text="Some text.",
            summary="Summary.",
            characters=["Alice"],
            world_setting="Test world",
            estimated_reading_time=5,
        )
        assert ch.chapter_id == 1
        assert ch.title == "Test"
        assert ch.raw_text == "Some text."
        assert ch.summary == "Summary."
        assert ch.characters == ["Alice"]
        assert ch.world_setting == "Test world"
        assert ch.estimated_reading_time == 5

    def test_valid_full(self) -> None:
        """Chapter with multiple characters and longer fields should validate."""
        ch = Chapter(
            chapter_id=42,
            title="The Long Chapter",
            raw_text="A very long story..." * 10,
            summary="A detailed summary of events.",
            characters=["Alice", "Bob", "Charlie"],
            world_setting="A fantasy realm with dragons and magic.",
            estimated_reading_time=30,
        )
        assert ch.chapter_id == 42
        assert len(ch.characters) == 3
        assert ch.estimated_reading_time == 30

    def test_invalid_chapter_id_zero(self) -> None:
        """Chapter with chapter_id=0 should raise ValidationError."""
        with pytest.raises(ValidationError):
            Chapter(
                chapter_id=0,
                title="Bad",
                raw_text="Text.",
                summary="Summary.",
                characters=["Alice"],
                world_setting="World",
                estimated_reading_time=5,
            )

    def test_invalid_negative_reading_time(self) -> None:
        """Chapter with negative estimated_reading_time should raise ValidationError."""
        with pytest.raises(ValidationError):
            Chapter(
                chapter_id=1,
                title="Bad",
                raw_text="Text.",
                summary="Summary.",
                characters=["Alice"],
                world_setting="World",
                estimated_reading_time=-1,
            )

    def test_roundtrip(self) -> None:
        """Chapter dump → dict → reload should produce equal model."""
        ch = Chapter(
            chapter_id=1,
            title="Roundtrip",
            raw_text="Test raw text.",
            summary="Test summary.",
            characters=["Alice", "Bob"],
            world_setting="Test setting",
            estimated_reading_time=10,
        )
        dumped = ch.model_dump()
        reloaded = Chapter.model_validate(dumped)
        assert reloaded.chapter_id == ch.chapter_id
        assert reloaded.title == ch.title
        assert reloaded.characters == ch.characters
        assert reloaded.estimated_reading_time == ch.estimated_reading_time


class TestChapterDB:
    """Tests for ChapterDB model."""

    def test_valid_empty(self) -> None:
        """ChapterDB with empty chapters should validate."""
        db = ChapterDB(chapters=[])
        assert db.chapters == []

    def test_valid_single(self) -> None:
        """ChapterDB with one chapter should validate."""
        ch = Chapter(
            chapter_id=1,
            title="Single",
            raw_text="Text.",
            summary="Sum.",
            characters=["Alice"],
            world_setting="World",
            estimated_reading_time=5,
        )
        db = ChapterDB(chapters=[ch])
        assert len(db.chapters) == 1
        assert db.chapters[0].chapter_id == 1

    def test_roundtrip(self) -> None:
        """ChapterDB dump → dict → reload should produce equal model."""
        chapters = [
            Chapter(
                chapter_id=i,
                title=f"Ch{i}",
                raw_text=f"Text {i}",
                summary=f"Summary {i}",
                characters=["Alice"],
                world_setting="World",
                estimated_reading_time=5,
            )
            for i in range(1, 4)
        ]
        db = ChapterDB(chapters=chapters)
        dumped = db.model_dump()
        reloaded = ChapterDB.model_validate(dumped)
        assert len(reloaded.chapters) == 3
        assert reloaded.chapters[0].chapter_id == 1
        assert reloaded.chapters[2].chapter_id == 3

    def test_validate_from_fixture(self) -> None:
        """ChapterDB.model_validate() the chapter_db.json fixture (3 chapters)."""
        fixture_path = Path(__file__).parent.parent / "fixtures" / "chapter_db.json"
        data = json.loads(fixture_path.read_text(encoding="utf-8"))
        db = ChapterDB.model_validate(data)
        assert len(db.chapters) == 3
        assert db.chapters[0].chapter_id == 1
        assert db.chapters[0].title == "The Transfer Student"
        assert db.chapters[0].estimated_reading_time == 15
        assert len(db.chapters[0].characters) == 5
        assert db.chapters[1].chapter_id == 2
        assert db.chapters[2].chapter_id == 3
        assert db.chapters[2].estimated_reading_time == 20
