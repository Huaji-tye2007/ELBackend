"""Tests for app.core.exceptions — domain exception classes."""

from __future__ import annotations

import pytest

from app.core.exceptions import (
    ECDictUnavailableError,
    GenerationConflictError,
    LLMError,
    NotFoundError,
    ValidationError,
)


class TestNotFoundError:
    """Tests for NotFoundError."""

    def test_inherits_from_exception(self) -> None:
        """NotFoundError should be a subclass of Exception."""
        assert issubclass(NotFoundError, Exception)

    def test_default_message(self) -> None:
        """Default message should be empty string or None."""
        err = NotFoundError()
        assert str(err) == ""

    def test_custom_message(self) -> None:
        """Custom message should be preserved."""
        err = NotFoundError("User not found")
        assert str(err) == "User not found"

    def test_can_raise_and_catch(self) -> None:
        """Should be raiseable and catchable."""
        with pytest.raises(NotFoundError, match="missing"):
            raise NotFoundError("missing resource")

    def test_isinstance_check(self) -> None:
        """Instance should pass isinstance check against its own class."""
        err = NotFoundError("test")
        assert isinstance(err, NotFoundError)
        assert isinstance(err, Exception)


class TestValidationError:
    """Tests for ValidationError."""

    def test_inherits_from_exception(self) -> None:
        """ValidationError should be a subclass of Exception."""
        assert issubclass(ValidationError, Exception)

    def test_default_message(self) -> None:
        """Default message should be empty string or None."""
        err = ValidationError()
        assert str(err) == ""

    def test_custom_message(self) -> None:
        """Custom message should be preserved."""
        err = ValidationError("Invalid input data")
        assert str(err) == "Invalid input data"

    def test_can_raise_and_catch(self) -> None:
        """Should be raiseable and catchable."""
        with pytest.raises(ValidationError, match="bad field"):
            raise ValidationError("bad field")

    def test_isinstance_check(self) -> None:
        """Instance should pass isinstance check against its own class."""
        err = ValidationError("test")
        assert isinstance(err, ValidationError)
        assert isinstance(err, Exception)


class TestLLMError:
    """Tests for LLMError."""

    def test_inherits_from_exception(self) -> None:
        """LLMError should be a subclass of Exception."""
        assert issubclass(LLMError, Exception)

    def test_default_message(self) -> None:
        """Default message should be empty string or None."""
        err = LLMError()
        assert str(err) == ""

    def test_custom_message(self) -> None:
        """Custom message should be preserved."""
        err = LLMError("API timeout after 300s")
        assert str(err) == "API timeout after 300s"

    def test_can_raise_and_catch(self) -> None:
        """Should be raiseable and catchable."""
        with pytest.raises(LLMError, match="timeout"):
            raise LLMError("timeout exceeded")

    def test_isinstance_check(self) -> None:
        """Instance should pass isinstance check against its own class."""
        err = LLMError("test")
        assert isinstance(err, LLMError)
        assert isinstance(err, Exception)


class TestGenerationConflictError:
    """Tests for GenerationConflictError."""

    def test_inherits_from_exception(self) -> None:
        """GenerationConflictError should be a subclass of Exception."""
        assert issubclass(GenerationConflictError, Exception)

    def test_default_message(self) -> None:
        """Default message should be empty string or None."""
        err = GenerationConflictError()
        assert str(err) == ""

    def test_custom_message(self) -> None:
        """Custom message should be preserved."""
        err = GenerationConflictError("Arc generation already in progress")
        assert str(err) == "Arc generation already in progress"

    def test_can_raise_and_catch(self) -> None:
        """Should be raiseable and catchable."""
        with pytest.raises(GenerationConflictError, match="already running"):
            raise GenerationConflictError("job already running")

    def test_isinstance_check(self) -> None:
        """Instance should pass isinstance check against its own class."""
        err = GenerationConflictError("test")
        assert isinstance(err, GenerationConflictError)
        assert isinstance(err, Exception)


class TestECDictUnavailableError:
    """Tests for ECDictUnavailableError."""

    def test_inherits_from_exception(self) -> None:
        """ECDictUnavailableError should be a subclass of Exception."""
        assert issubclass(ECDictUnavailableError, Exception)

    def test_default_message(self) -> None:
        """Default message should be empty string or None."""
        err = ECDictUnavailableError()
        assert str(err) == ""

    def test_custom_message(self) -> None:
        """Custom message should be preserved."""
        err = ECDictUnavailableError(
            "ECDICT database not found at asset/ecdict_mobile.db"
        )
        assert str(err) == "ECDICT database not found at asset/ecdict_mobile.db"

    def test_can_raise_and_catch(self) -> None:
        """Should be raiseable and catchable."""
        with pytest.raises(ECDictUnavailableError, match="database missing"):
            raise ECDictUnavailableError("database missing")

    def test_isinstance_check(self) -> None:
        """Instance should pass isinstance check against its own class."""
        err = ECDictUnavailableError("test")
        assert isinstance(err, ECDictUnavailableError)
        assert isinstance(err, Exception)


class TestExceptionHierarchy:
    """Cross-cutting tests for the exception hierarchy."""

    def test_all_inherit_from_exception(self) -> None:
        """All five domain exceptions should inherit from Exception."""
        classes = [
            NotFoundError,
            ValidationError,
            LLMError,
            GenerationConflictError,
            ECDictUnavailableError,
        ]
        for cls in classes:
            assert issubclass(cls, Exception), (
                f"{cls.__name__} should inherit from Exception"
            )

    def test_pep8_naming_convention(self) -> None:
        """Exception class names should use PascalCase and end with 'Error'."""
        classes = [
            NotFoundError,
            ValidationError,
            LLMError,
            GenerationConflictError,
            ECDictUnavailableError,
        ]
        for cls in classes:
            assert cls.__name__.endswith("Error"), (
                f"{cls.__name__} should end with 'Error'"
            )
            assert cls.__name__[0].isupper(), (
                f"{cls.__name__} should start with uppercase"
            )
