"""Dictionary endpoint: word lookup via ECDICT.

Ref: AGENTS.md §10 — endpoint table, §6 — ECDICT lemma resolution.
Exception translation: AGENTS.md §15.2.
"""

import sqlite3

from fastapi import APIRouter, Depends, HTTPException

from app.api.v1.schemas import DictionaryResponse
from app.core.dependencies import get_ecdict_db
from app.core.exceptions import ECDictUnavailableError
from app.utils.lemma import lookup_lemma

router = APIRouter(prefix="/dictionary", tags=["dictionary"])


@router.get("/{word}", response_model=DictionaryResponse)
async def lookup_word(
    word: str,
    db: sqlite3.Connection = Depends(get_ecdict_db),
) -> DictionaryResponse:
    """Look up a word in the ECDICT database.

    Returns the word's lemma, meaning, and optional example sentences.
    If the word is not found, returns HTTP 404.

    Args:
        word: The surface form to look up (e.g. "consuming", "went").
        db: ECDICT SQLite connection (injected via Depends).
    """
    try:
        row = db.execute(
            "SELECT word, translation FROM dict WHERE word = ?", (word,)
        ).fetchone()
    except sqlite3.OperationalError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Dictionary database error: {exc}",
        )

    if row is None:
        # Try lemma lookup — maybe the input is an inflected form
        try:
            lemma = lookup_lemma(word, db)
        except (ECDictUnavailableError, sqlite3.OperationalError) as exc:
            raise HTTPException(
                status_code=503,
                detail=f"Dictionary database error during lemma lookup: {exc}",
            )
        if lemma != word:
            row = db.execute(
                "SELECT word, translation FROM dict WHERE word = ?", (lemma,)
            ).fetchone()

    if row is None:
        raise HTTPException(
            status_code=404,
            detail=f"Word '{word}' not found in dictionary",
        )

    return DictionaryResponse(
        word=row["word"],
        meaning=row["translation"],
    )


__all__ = ["router"]
