"""Instructor-based LLM client for structured output extraction."""

from __future__ import annotations

from typing import TypeVar

import instructor
from openai import AsyncOpenAI

T = TypeVar("T")


class InstructorClient:
    """LLM client using instructor for structured Pydantic output.

    Wraps OpenAI-compatible endpoints (works with DeepSeek, Ollama, etc.).
    All LLM interactions go through ``chat_structured()`` which takes a
    Pydantic ``response_model`` and returns validated output.

    This is the **sole LLM interface** for the entire backend.  Every
    service that needs LLM access must receive an ``InstructorClient``
    via dependency injection.
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        timeout: float = 300.0,
        instructor_mode: str | instructor.Mode = instructor.Mode.JSON,
    ) -> None:
        """Initialize the client.

        Args:
            base_url: OpenAI-compatible API endpoint
                (e.g. ``"http://localhost:11434/v1"``).
            api_key: API key for the endpoint.
            model: Model name
                (e.g. ``"deepseek-v4-flash"``, ``"gpt-4o-mini"``).
            timeout: HTTP request timeout in seconds (default 300).
            instructor_mode: Instructor mode used for structured output.
                Defaults to ``JSON`` to avoid tool_choice, which some thinking
                models reject.
        """
        mode = _coerce_instructor_mode(instructor_mode)
        raw_client = AsyncOpenAI(
            base_url=base_url,
            api_key=api_key,
            timeout=timeout,
        )
        self._client = instructor.from_openai(raw_client, mode=mode)
        self._model = model
        self._mode = mode

    async def chat_structured(
        self,
        messages: list[dict],
        response_model: type[T],
        **kwargs: object,
    ) -> T:
        """Send messages and get structured Pydantic output.

        Args:
            messages: Conversation messages in OpenAI-compatible dict format
                (``[{"role": "user", "content": "..."}]``).
            response_model: Pydantic model class for structured output.
            **kwargs: Additional arguments forwarded to instructor's create call
                (e.g. ``max_tokens``, ``temperature``).

        Returns:
            Validated instance of ``response_model`` matching LLM output.

        Raises:
            instructor.exceptions.InstructorRetryException: When the LLM
                fails to produce valid structured output after retries.
            openai.APIError: On API-level errors (auth, rate-limit, etc.).
        """
        return await self._client.create(
            model=self._model,
            response_model=response_model,
            messages=messages,
            **kwargs,
        )

    @property
    def model(self) -> str:
        """The configured model name."""
        return self._model

    @property
    def mode(self) -> instructor.Mode:
        """The configured instructor structured-output mode."""
        return self._mode


def _coerce_instructor_mode(mode: str | instructor.Mode) -> instructor.Mode:
    """Convert an env-friendly mode string to ``instructor.Mode``."""
    if isinstance(mode, instructor.Mode):
        return mode
    mode_name = mode.upper()
    try:
        return getattr(instructor.Mode, mode_name)
    except AttributeError as exc:
        raise ValueError(f"Unsupported instructor mode: {mode}") from exc
