"""Tests for app.llm.client.InstructorClient."""

from __future__ import annotations

import inspect
from unittest import mock


from app.llm.client import InstructorClient


class TestInstructorClient:
    """Tests for InstructorClient initialization and properties."""

    def test_init_sets_model_correctly(self) -> None:
        """__init__ should store the model name in _model."""
        with mock.patch("app.llm.client.instructor.from_openai") as mock_from_openai:
            client = InstructorClient(
                base_url="http://localhost:11434/v1",
                api_key="sk-test",
                model="deepseek-v4-flash",
            )
            assert client._model == "deepseek-v4-flash"  # noqa: SLF001
            mock_from_openai.assert_called_once()

    def test_model_property_returns_configured_name(self) -> None:
        """model property should return the model name passed to __init__."""
        with mock.patch("app.llm.client.instructor.from_openai") as mock_from_openai:
            client = InstructorClient(
                base_url="http://custom:8080/v1",
                api_key="sk-abc",
                model="gpt-4o-mini",
            )
            assert client.model == "gpt-4o-mini"
            mock_from_openai.assert_called_once()

    def test_create_is_async_coroutine(self) -> None:
        """create() should be an async coroutine function."""
        with mock.patch("app.llm.client.instructor.from_openai"):
            client = InstructorClient(
                base_url="http://localhost:11434/v1",
                api_key="sk-test",
                model="deepseek-v4-flash",
            )
        assert inspect.iscoroutinefunction(client.create)
