"""ECDICT lemma lookup utility.

Queries ``asset/ecdict_mobile.db`` to resolve surface forms (e.g. "went")
to their base lemma (e.g. "go") via the ``exchange`` field.

No external lemmatizer (NLTK / spaCy / pyinflect / lemminflect) is used —
per AGENTS.md §6, all lemma resolution goes through ECDICT.
"""

from __future__ import annotations

import sqlite3

from app.core.exceptions import ECDictUnavailableError


def lookup_lemma(surface: str, db: sqlite3.Connection) -> str:
    """Resolve a surface word form to its base lemma via ECDICT.

    Args:
        surface: The inflected word form (e.g. ``"went"``, ``"consuming"``).
        db: An open ``sqlite3.Connection`` to ``asset/ecdict_mobile.db``.

    Returns:
        The base lemma if ``0:<lemma>`` is present in the ``exchange`` field,
        otherwise the *surface* form itself.

    Raises:
        ECDictUnavailableError: If the database is unreachable or missing the
            expected ``dict`` table (e.g. connected to a non-ECDICT file).
    """
    try:
        row = db.execute(
            "SELECT exchange FROM dict WHERE word = ?", (surface,)
        ).fetchone()
    except sqlite3.OperationalError as exc:
        raise ECDictUnavailableError(
            f"ECDICT database unavailable — failed to query dict table: {exc}"
        ) from exc

    if row is None:
        return surface

    exchange: str | None = row[0]
    if not exchange:
        return surface

    # The exchange field uses "/" as separator, e.g. "0:go/1:p/2:gone/3:going"
    for part in exchange.split("/"):
        if part.startswith("0:"):
            return part[2:]

    return surface
