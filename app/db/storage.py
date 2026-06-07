"""Generic JSON file storage for Pydantic v2 models.

JSONStorage[T] provides load/save operations backed by atomic_write_json
and atomic_read_json from app.utils.atomic_io. All operations are synchronous.

Ref: AGENTS.md §11, §13.
"""

from pathlib import Path
from typing import Generic, TypeVar

from pydantic import BaseModel

from app.utils.atomic_io import atomic_read_json, atomic_write_json

T = TypeVar("T", bound=BaseModel)


class JSONStorage(Generic[T]):
    """Synchronous JSON file persistence for a single Pydantic model type.

    Usage:
        storage = JSONStorage(Path("data/vocab.json"), UserVocabulary)
        vocab = storage.load()          # raises FileNotFoundError if missing
        vocab.vocabulary.append(item)
        storage.save(vocab)
    """

    def __init__(self, path: Path, model: type[T]) -> None:
        """Initialize storage for a specific path and Pydantic model type.

        Args:
            path: JSON file path for persistence.
            model: Pydantic v2 model class used for validation.
        """
        self.path = path
        self.model = model

    def load(self) -> T:
        """Read and validate the JSON file into a model instance.

        Returns:
            A validated instance of the configured model type.

        Raises:
            FileNotFoundError: If the file does not exist.
            json.JSONDecodeError: If the file content is not valid JSON.
            pydantic.ValidationError: If the JSON does not match the model schema.
        """
        return atomic_read_json(self.path, self.model)

    def save(self, obj: T) -> None:
        """Atomically write a model instance to the JSON file.

        Uses atomic_write_json internally: writes to .tmp then os.replace()
        to guarantee the file is never left in a partially-written state.

        Args:
            obj: A validated instance of the configured model type.

        Raises:
            OSError: If the temporary file cannot be written or os.replace fails.
        """
        atomic_write_json(self.path, obj)
