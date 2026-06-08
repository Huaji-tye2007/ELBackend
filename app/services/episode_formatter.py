"""EpisodeFormatter — assemble and cache frontend-ready episode JSON.

Takes meta, annotated messages, and vocab from upstream modules
(ArcPlanner, StoryRewriter, VocabularyAnnotator), validates every field
against the FormatSpec v3 schema, derives vocab from marks when needed,
and writes the final Episode to the Episode Cache.
"""

import os
from pathlib import Path

from app.models.episode import (
    DialogueMessage,
    Episode,
    Meta,
    NarrationMessage,
    VocabEntry,
)
from app.utils.atomic_io import atomic_write_json


class EpisodeFormatter:
    """Assemble a FormatSpec v3 Episode and persist it to cache.

    Usage::

        formatter = EpisodeFormatter(Path("data/EpisodeCache"))
        episode = formatter.format_episode(
            meta={"ep": 3, "title": "The Glass", "kind": "main"},
            messages=[...],
        )
        formatter.write_cache(episode)
    """

    def __init__(self, cache_dir: Path):
        self._cache_dir = cache_dir

    # ── Public API ────────────────────────────────────────

    def format_episode(
        self,
        meta: dict,
        messages: list[dict],
        vocab: list[dict] | None = None,
    ) -> Episode:
        """Validate and assemble an Episode from upstream dicts.

        Args:
            meta: ``{"ep": int, "title": str, "kind": "main"|"side"}``.
            messages: List of message dicts, already annotated with marks
                      by VocabularyAnnotator. Each dict must have ``type``
                      (``"narration"`` or ``"dialogue"``) and ``marks``.
            vocab: Optional pre-computed vocab list. If omitted, derived
                   automatically from ``messages[].marks``.

        Returns:
            A validated Episode ready for serialization and caching.

        Raises:
            ValidationError: If any field does not conform to FormatSpec v3.
        """
        meta_obj = Meta.model_validate(meta)
        message_objs = self._validate_messages(messages)

        if vocab is not None:
            vocab_objs = [VocabEntry.model_validate(v) for v in vocab]
        else:
            vocab_objs = self._derive_vocab(message_objs)

        return Episode(meta=meta_obj, messages=message_objs, vocab=vocab_objs)

    def write_cache(self, episode: Episode) -> Path:
        """Persist an Episode to the cache directory as ``ep_{n}.json``.

        Uses ``atomic_write_json`` for crash-safe atomic replacement.
        Ensures the cache directory exists before writing.

        Args:
            episode: The fully assembled Episode.

        Returns:
            Path to the written cache file.

        Raises:
            OSError: If the filesystem write fails.
        """
        os.makedirs(self._cache_dir, exist_ok=True)
        cache_path = self._cache_dir / f"ep_{episode.meta.ep:04d}.json"
        atomic_write_json(cache_path, episode)
        return cache_path

    # ── Vocab derivation ──────────────────────────────────

    def _derive_vocab(
        self, messages: list[NarrationMessage | DialogueMessage]
    ) -> list[VocabEntry]:
        """Build the vocab array from all messages' marks.

        Deduplicates by learning object when available (``item_id`` from
        VocabularyAnnotator), falling back to ``(lemma, definition)`` and then
        ``(word, definition)`` for manually supplied marks. If any mark for a
        given object has ``is_new=True``, the vocab entry is marked new.
        """
        seen: dict[tuple[str, str], tuple[str | None, str, str, bool]] = {}

        for msg in messages:
            for mark in msg.marks:
                if mark.item_id:
                    key = ("item_id", mark.item_id)
                elif mark.lemma:
                    key = ("lemma", f"{mark.lemma.lower()}::{mark.definition}")
                else:
                    key = ("surface", f"{mark.word.lower()}::{mark.definition}")

                previous = seen.get(key)
                if previous is None:
                    seen[key] = (
                        mark.item_id,
                        mark.word,
                        mark.definition,
                        mark.is_new,
                    )
                else:
                    item_id, word, definition, is_new = previous
                    seen[key] = (item_id, word, definition, is_new or mark.is_new)

        return [
            VocabEntry(
                item_id=item_id,
                word=word,
                definition=definition,
                is_new=is_new,
            )
            for item_id, word, definition, is_new in seen.values()
        ]

    # ── Message validation ────────────────────────────────

    @staticmethod
    def _validate_messages(raw: list[dict]) -> list[NarrationMessage | DialogueMessage]:
        """Convert raw dicts to the correct message subtype by ``type`` field."""
        messages: list[NarrationMessage | DialogueMessage] = []
        for item in raw:
            msg_type = item.get("type")
            if msg_type == "narration":
                messages.append(NarrationMessage.model_validate(item))
            elif msg_type == "dialogue":
                messages.append(DialogueMessage.model_validate(item))
            else:
                raise ValueError(
                    f"Unknown message type {msg_type!r}, expected 'narration' or 'dialogue'"
                )
        return messages


# Re-export for convenience
__all__ = ["EpisodeFormatter"]
