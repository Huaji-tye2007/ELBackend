"""Tests for app.utils.lemma.lookup_lemma."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from app.core.exceptions import ECDictUnavailableError
from app.utils.lemma import lookup_lemma


# Path to the real ECDICT database
ECDICT_PATH = Path(__file__).resolve().parents[2] / "asset" / "ecdict_mobile.db"


@pytest.fixture
def ecdict_db() -> sqlite3.Connection:
    """Open a connection to the real ECDICT database for testing."""
    db = sqlite3.connect(str(ECDICT_PATH))
    yield db
    db.close()


class TestLookupLemma:
    """Tests for lookup_lemma — ECDICT-based surface → lemma resolution."""

    def test_lemma_found(self, ecdict_db: sqlite3.Connection):
        """lookup_lemma("went") → "go" (0:go from exchange field)."""
        result = lookup_lemma("went", ecdict_db)
        assert result == "go"

    def test_no_lemma_marker(self, ecdict_db: sqlite3.Connection):
        """Word whose exchange field has no 0: marker returns the surface form."""
        # "table" has exchange="s:tables/d:tabled/p:tabled/i:tabling/3:tables" — no 0: marker
        result = lookup_lemma("table", ecdict_db)
        assert result == "table"

    def test_word_not_in_dict(self, ecdict_db: sqlite3.Connection):
        """Non-existent word returns the surface form itself."""
        result = lookup_lemma("xyzabc123_nonexistent", ecdict_db)
        assert result == "xyzabc123_nonexistent"

    def test_exchange_empty(self, ecdict_db: sqlite3.Connection):
        """Word with empty/None exchange returns the surface form."""
        # Use a word that exists but has no exchange field value
        # "the" likely has empty exchange in ECDICT
        row = ecdict_db.execute(
            "SELECT exchange FROM dict WHERE word = 'the'"
        ).fetchone()
        if row and row[0]:
            pytest.skip(
                "'the' has a non-empty exchange field — test needs a word with empty exchange"
            )
        result = lookup_lemma("the", ecdict_db)
        assert result == "the"

    def test_db_unavailable(self, tmp_path: Path):
        """Connecting to a non-existent DB raises ECDictUnavailableError."""
        nonexistent = tmp_path / "nonexistent.db"
        db = sqlite3.connect(str(nonexistent))
        try:
            with pytest.raises(ECDictUnavailableError):
                lookup_lemma("anyword", db)
        finally:
            db.close()
