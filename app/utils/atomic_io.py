"""JSON atomic write/read utilities for crash-safe persistence.

All operations are synchronous. Uses Pydantic v2 model_dump_json() /
model_validate() for serialization and deserialization.
"""

import json
import os
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


def atomic_write_json(path: Path, model: BaseModel) -> None:
    """Atomically write a Pydantic model to a JSON file.

    Writes to a temporary file (.tmp) first, then uses os.replace() for
    atomic replacement. This guarantees that the target file is either the
    complete new content or the previous content — never a partial write.

    Args:
        path: Target JSON file path.
        model: Pydantic v2 BaseModel instance to serialize.

    Raises:
        OSError: If the temporary file cannot be written or os.replace fails.
    """
    tmp_path = path.with_suffix(".tmp")
    json_str = model.model_dump_json(indent=2)
    tmp_path.write_text(json_str, encoding="utf-8")
    os.replace(tmp_path, path)


def atomic_read_json(path: Path, model_type: type[T]) -> T:
    """Read and validate a JSON file into a Pydantic model.

    Args:
        path: JSON file path to read.
        model_type: Pydantic v2 model class for validation (e.g., FsrsCard).

    Returns:
        A validated instance of model_type.

    Raises:
        FileNotFoundError: If the file does not exist.
        json.JSONDecodeError: If the file content is not valid JSON.
        pydantic.ValidationError: If the JSON does not match the model schema.
    """
    raw = path.read_text(encoding="utf-8")
    data = json.loads(raw)
    return model_type.model_validate(data)
