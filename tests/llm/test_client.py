"""Tests for app.llm.client.InstructorClient.

Covers initialization, the ``chat_structured()`` method, timeout handling,
error propagation, and kwargs forwarding.  All LLM calls are mocked — no
real network requests are made.
"""

from __future__ import annotations

import inspect
from unittest import mock

import pytest
from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Test response model (simulates a real use-case like ContextScoreResponse)
# ---------------------------------------------------------------------------


class _FakeResponse(BaseModel):
    """Minimal Pydantic model used as response_model in chat_structured tests."""

    value: int
    label: str


# ---------------------------------------------------------------------------
# Initialization & properties
# ---------------------------------------------------------------------------


class TestInit:
    """Tests for InstructorClient.__init__ and properties."""

    def test_init_stores_model_name_and_calls_instructor(self) -> None:
        """__init__ stores model in _model and wraps AsyncOpenAI with instructor."""
        with mock.patch("app.llm.client.instructor.from_openai") as mock_from_openai:
            with mock.patch("app.llm.client.AsyncOpenAI") as mock_async_openai:
                client = __import__(
                    "app.llm.client", fromlist=["InstructorClient"]
                ).InstructorClient(
                    base_url="http://localhost:11434/v1",
                    api_key="sk-test",
                    model="deepseek-v4-flash",
                )
                assert client._model == "deepseek-v4-flash"  # noqa: SLF001
                mock_async_openai.assert_called_once_with(
                    base_url="http://localhost:11434/v1",
                    api_key="sk-test",
                    timeout=300.0,
                )
                mock_from_openai.assert_called_once()
                assert mock_from_openai.call_args.kwargs["mode"].name == "JSON"

    def test_init_passes_custom_timeout_to_async_openai(self) -> None:
        """Custom timeout value is forwarded to AsyncOpenAI constructor."""
        with mock.patch("app.llm.client.instructor.from_openai"):
            with mock.patch("app.llm.client.AsyncOpenAI") as mock_async_openai:
                __import__(
                    "app.llm.client", fromlist=["InstructorClient"]
                ).InstructorClient(
                    base_url="http://api:8080/v1",
                    api_key="sk-custom",
                    model="gpt-4o-mini",
                    timeout=120.0,
                )
                _, kwargs = mock_async_openai.call_args
                assert kwargs["timeout"] == 120.0

    def test_model_property_returns_configured_name(self) -> None:
        """model property returns the model name passed to __init__."""
        with mock.patch("app.llm.client.instructor.from_openai"):
            with mock.patch("app.llm.client.AsyncOpenAI"):
                client = __import__(
                    "app.llm.client", fromlist=["InstructorClient"]
                ).InstructorClient(
                    base_url="http://custom:8080/v1",
                    api_key="sk-abc",
                    model="gpt-4o-mini",
                )
                assert client.model == "gpt-4o-mini"
                assert client.mode.name == "JSON"

    def test_init_accepts_custom_instructor_mode(self) -> None:
        """Custom instructor mode names are coerced and passed to instructor."""
        with mock.patch("app.llm.client.instructor.from_openai") as mock_from_openai:
            with mock.patch("app.llm.client.AsyncOpenAI"):
                client = __import__(
                    "app.llm.client", fromlist=["InstructorClient"]
                ).InstructorClient(
                    base_url="http://custom:8080/v1",
                    api_key="sk-abc",
                    model="gpt-4o-mini",
                    instructor_mode="TOOLS",
                )
                assert client.mode.name == "TOOLS"
                assert mock_from_openai.call_args.kwargs["mode"].name == "TOOLS"


# ---------------------------------------------------------------------------
# chat_structured — happy path
# ---------------------------------------------------------------------------


class TestChatStructured:
    """Tests for InstructorClient.chat_structured()."""

    @pytest.mark.asyncio
    async def test_chat_structured_is_async_coroutine(self) -> None:
        """chat_structured() should be an async coroutine function."""
        with mock.patch("app.llm.client.instructor.from_openai"):
            with mock.patch("app.llm.client.AsyncOpenAI"):
                client = __import__(
                    "app.llm.client", fromlist=["InstructorClient"]
                ).InstructorClient(
                    base_url="http://localhost:11434/v1",
                    api_key="sk-test",
                    model="deepseek-v4-flash",
                )
        assert inspect.iscoroutinefunction(client.chat_structured)

    @pytest.mark.asyncio
    async def test_returns_validated_pydantic_model(self) -> None:
        """Successful call returns a validated instance of response_model."""
        expected = _FakeResponse(value=42, label="answer")

        # Build a mock for the inner (instructor-wrapped) client.
        mock_inner = mock.AsyncMock()
        mock_inner.create = mock.AsyncMock(return_value=expected)

        with mock.patch(
            "app.llm.client.instructor.from_openai", return_value=mock_inner
        ):
            with mock.patch("app.llm.client.AsyncOpenAI"):
                client = __import__(
                    "app.llm.client", fromlist=["InstructorClient"]
                ).InstructorClient(
                    base_url="http://api:8080/v1",
                    api_key="sk-test",
                    model="deepseek-v4-flash",
                )

        result = await client.chat_structured(
            messages=[{"role": "user", "content": "What is the answer?"}],
            response_model=_FakeResponse,
        )

        assert result == expected
        assert result.value == 42
        assert result.label == "answer"
        mock_inner.create.assert_called_once()
        # Verify the call args include model, messages, and response_model.
        call_kwargs = mock_inner.create.call_args.kwargs
        assert call_kwargs["model"] == "deepseek-v4-flash"
        assert call_kwargs["response_model"] == _FakeResponse
        assert call_kwargs["messages"] == [
            {"role": "user", "content": "What is the answer?"}
        ]

    @pytest.mark.asyncio
    async def test_forwards_extra_kwargs_to_instructor(self) -> None:
        """Extra kwargs (e.g. max_tokens, temperature) are forwarded."""
        mock_inner = mock.AsyncMock()
        mock_inner.create = mock.AsyncMock(
            return_value=_FakeResponse(value=1, label="x")
        )

        with mock.patch(
            "app.llm.client.instructor.from_openai", return_value=mock_inner
        ):
            with mock.patch("app.llm.client.AsyncOpenAI"):
                client = __import__(
                    "app.llm.client", fromlist=["InstructorClient"]
                ).InstructorClient(
                    base_url="http://api:8080/v1",
                    api_key="sk-test",
                    model="deepseek-v4-flash",
                )

        await client.chat_structured(
            messages=[{"role": "user", "content": "hi"}],
            response_model=_FakeResponse,
            max_tokens=100,
            temperature=0.7,
        )

        call_kwargs = mock_inner.create.call_args.kwargs
        assert call_kwargs["max_tokens"] == 100
        assert call_kwargs["temperature"] == 0.7


# ---------------------------------------------------------------------------
# chat_structured — error handling
# ---------------------------------------------------------------------------


class TestChatStructuredErrors:
    """Tests for error cases in InstructorClient.chat_structured()."""

    @pytest.mark.asyncio
    async def test_raises_on_instructor_retry_failure(self) -> None:
        """When instructor exhausts retries, InstructorRetryException propagates."""
        from instructor.core import InstructorRetryException

        mock_inner = mock.AsyncMock()
        mock_inner.create = mock.AsyncMock(
            side_effect=InstructorRetryException(
                "Failed after 3 retries",
                last_completion=None,
                messages=[],
                n_attempts=3,
                total_usage=0,
            )
        )

        with mock.patch(
            "app.llm.client.instructor.from_openai", return_value=mock_inner
        ):
            with mock.patch("app.llm.client.AsyncOpenAI"):
                client = __import__(
                    "app.llm.client", fromlist=["InstructorClient"]
                ).InstructorClient(
                    base_url="http://api:8080/v1",
                    api_key="sk-test",
                    model="deepseek-v4-flash",
                )

        with pytest.raises(InstructorRetryException):
            await client.chat_structured(
                messages=[{"role": "user", "content": "Say something."}],
                response_model=_FakeResponse,
            )

    @pytest.mark.asyncio
    async def test_raises_on_openai_api_error(self) -> None:
        """OpenAI API-level errors (auth, rate-limit) propagate."""
        from openai import APIError

        mock_inner = mock.AsyncMock()
        mock_inner.create = mock.AsyncMock(
            side_effect=APIError(
                message="Invalid API key",
                request=mock.MagicMock(),
                body={"error": {"message": "Invalid API key"}},
            )
        )

        with mock.patch(
            "app.llm.client.instructor.from_openai", return_value=mock_inner
        ):
            with mock.patch("app.llm.client.AsyncOpenAI"):
                client = __import__(
                    "app.llm.client", fromlist=["InstructorClient"]
                ).InstructorClient(
                    base_url="http://api:8080/v1",
                    api_key="sk-bad",
                    model="deepseek-v4-flash",
                )

        with pytest.raises(APIError):
            await client.chat_structured(
                messages=[{"role": "user", "content": "Say something."}],
                response_model=_FakeResponse,
            )

    @pytest.mark.asyncio
    async def test_raises_on_timeout(self) -> None:
        """Timeout (httpx.ReadTimeout) propagates to caller."""
        import httpx

        mock_inner = mock.AsyncMock()
        mock_inner.create = mock.AsyncMock(
            side_effect=httpx.ReadTimeout("Request timed out")
        )

        with mock.patch(
            "app.llm.client.instructor.from_openai", return_value=mock_inner
        ):
            with mock.patch("app.llm.client.AsyncOpenAI"):
                client = __import__(
                    "app.llm.client", fromlist=["InstructorClient"]
                ).InstructorClient(
                    base_url="http://api:8080/v1",
                    api_key="sk-test",
                    model="deepseek-v4-flash",
                )

        with pytest.raises(httpx.ReadTimeout):
            await client.chat_structured(
                messages=[{"role": "user", "content": "Say something."}],
                response_model=_FakeResponse,
            )
