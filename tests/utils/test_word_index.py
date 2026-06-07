"""Tests for app.utils.word_index.find_word_index."""

import pytest
from app.utils.word_index import find_word_index


class TestFindWordIndex:
    """Tests for find_word_index — space-split based, 0-based word index."""

    def test_simple_single_word(self):
        """find_word_index("The bank said", "bank") → 1."""
        result = find_word_index("The bank said", "bank")
        assert result == 1

    def test_first_word_index_zero(self):
        """First word should have index 0."""
        result = find_word_index("Hello world", "Hello")
        assert result == 0

    def test_last_word(self):
        """Last word is found correctly."""
        result = find_word_index("The bank said", "said")
        assert result == 2

    def test_multiple_occurrences(self):
        """find_word_index with occurrence param returns the N-th match."""
        result = find_word_index("a a a", "a", occurrence=2)
        assert result == 2

    def test_second_occurrence(self):
        """Second occurrence of same word."""
        result = find_word_index("the cat and the dog", "the", occurrence=1)
        assert result == 3

    def test_surface_not_found_raises_value_error(self):
        """If surface is not in text at all, raise ValueError."""
        with pytest.raises(ValueError, match="not found"):
            find_word_index("The bank said", "river")

    def test_occurrence_out_of_range_raises_value_error(self):
        """If occurrence exceeds available matches, raise ValueError."""
        with pytest.raises(ValueError, match="not found"):
            find_word_index("a a", "a", occurrence=2)

    def test_empty_text_raises_value_error(self):
        """Empty or whitespace-only text raises ValueError."""
        with pytest.raises(ValueError, match="empty"):
            find_word_index("   ", "word")

    def test_punctuation_attached_to_word_not_matched(self):
        """'bank.' is not the same as 'bank' — exact match only."""
        with pytest.raises(ValueError, match="not found"):
            find_word_index("The bank.", "bank")

    def test_surface_with_punctuation_matched_exactly(self):
        """If surface includes punctuation, it matches only that exact token."""
        result = find_word_index("The bank. said", "bank.")
        assert result == 1
