"""Instructor-based LLM client for structured output extraction."""

from __future__ import annotations

from typing import Any

import instructor
from openai import AsyncOpenAI
from openai.types.chat import ChatCompletionMessageParam


class InstructorClient:
    """LLM client using instructor for structured Pydantic output.

    Wraps OpenAI-compatible endpoints (works with DeepSeek, Ollama, etc.).
    All LLM interactions go through ``create()`` which takes a
    Pydantic ``response_model`` and returns validated output.
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        timeout: float = 300.0,
    ) -> None:
        """Initialize the client.

        Args:
            base_url: OpenAI-compatible API endpoint
                (e.g. ``"http://localhost:11434/v1"``).
            api_key: API key for the endpoint.
            model: Model name
                (e.g. ``"deepseek-v4-flash"``, ``"gpt-4o-mini"``).
            timeout: HTTP request timeout in seconds (default 300).
        """
        raw_client = AsyncOpenAI(
            base_url=base_url,
            api_key=api_key,
            timeout=timeout,
        )
        self._client = instructor.from_openai(raw_client)
        self._model = model

    async def create(
        self,
        messages: list[ChatCompletionMessageParam],
        response_model: type[Any],
        **kwargs: Any,
    ) -> Any:
        """Send messages and get structured Pydantic output.

        Args:
            messages: Conversation messages in OpenAI format
                (``[{"role": "user", "content": "..."}]``).
            response_model: Pydantic model class for structured output.
            **kwargs: Additional arguments passed to instructor's create call.

        Returns:
            Validated instance of ``response_model`` matching LLM output.
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
