"""Word index locator — finds 0-based word index via space-split, NOT character offset."""


def find_word_index(text: str, surface: str, occurrence: int = 0) -> int:
    """Return the 0-based word index of the `occurrence`-th match of `surface` in `text`.

    Words are defined by splitting `text` on spaces (`text.split(" ")`).
    This is NOT character offset — the index refers to the position in the word list.

    Args:
        text: The sentence or paragraph to search within.
        surface: The surface-form word to locate (e.g., "consuming", "bank").
        occurrence: Which occurrence to return (0-based). Default 0 means the first match.

    Returns:
        int: The 0-based word index.

    Raises:
        ValueError: If `text` is empty, or `surface` is not found at the requested occurrence.
    """
    if not text.strip():
        raise ValueError("text must not be empty or whitespace-only")

    words = text.split(" ")
    count = 0
    for idx, word in enumerate(words):
        if word == surface:
            if count == occurrence:
                return idx
            count += 1

    raise ValueError(
        f"surface '{surface}' not found at occurrence {occurrence} in text: {text!r}"
    )
