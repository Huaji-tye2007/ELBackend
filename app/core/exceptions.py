"""Domain exception classes.

All exceptions inherit from :class:`Exception` and are raised by service-layer code.
HTTP translation happens at the API route boundary — see :ref:`app/api/v1/*.py`.
"""

from __future__ import annotations


class NotFoundError(Exception):
    """Requested resource was not found."""

    def __init__(self, message: str = "") -> None:
        super().__init__(message)


class ValidationError(Exception):
    """Input data failed validation."""

    def __init__(self, message: str = "") -> None:
        super().__init__(message)


class LLMError(Exception):
    """LLM API call failed (timeout, 5xx, rate-limit, etc.)."""

    def __init__(self, message: str = "") -> None:
        super().__init__(message)


class GenerationConflictError(Exception):
    """A generation job is already in progress."""

    def __init__(self, message: str = "") -> None:
        super().__init__(message)


class ECDictUnavailableError(Exception):
    """ECDICT database is missing or inaccessible."""

    def __init__(self, message: str = "") -> None:
        super().__init__(message)
