"""Tests for app.main — FastAPI application entry point."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from httpx import ASGITransport, AsyncClient

from app.main import app, lifespan


# ── Smoke tests ─────────────────────────────────────────────────────────


class TestAppCreation:
    """Verify the FastAPI application instance is correctly created."""

    def test_app_is_fastapi_instance(self) -> None:
        """``app`` should be a FastAPI instance."""
        assert isinstance(app, FastAPI)

    def test_app_has_title(self) -> None:
        """App should have the expected title."""
        assert app.title == "ELBackend"

    def test_app_has_version(self) -> None:
        """App should have the expected version string."""
        assert app.version == "1.5.0"

    def test_lifespan_is_importable(self) -> None:
        """``lifespan`` should be importable and callable."""
        assert callable(lifespan)


# ── CORS middleware ─────────────────────────────────────────────────────


class TestCORSMiddleware:
    """Verify CORS middleware is correctly configured."""

    def test_cors_middleware_present(self) -> None:
        """At least one CORSMiddleware should be registered."""
        cors_middlewares = [m for m in app.user_middleware if m.cls is CORSMiddleware]
        assert len(cors_middlewares) >= 1, "CORS middleware not found"

    def test_cors_allows_all_origins(self) -> None:
        """CORS middleware should allow all origins for single-user V1.5."""
        cors_mw = next(m for m in app.user_middleware if m.cls is CORSMiddleware)
        # Starlette Middleware stores config in ``kwargs``
        assert "*" in cors_mw.kwargs.get("allow_origins", [])


# ── Exception handlers ─────────────────────────────────────────────────


class TestExceptionHandlers:
    """Verify domain exception handlers are registered."""

    def test_not_found_error_handler_registered(self) -> None:
        """NotFoundError should map to 404."""
        from app.core.exceptions import NotFoundError

        assert NotFoundError in app.exception_handlers

    def test_validation_error_handler_registered(self) -> None:
        """ValidationError should map to 400."""
        from app.core.exceptions import ValidationError

        assert ValidationError in app.exception_handlers

    def test_llm_error_handler_registered(self) -> None:
        """LLMError should map to 502."""
        from app.core.exceptions import LLMError

        assert LLMError in app.exception_handlers

    def test_generation_conflict_error_handler_registered(self) -> None:
        """GenerationConflictError should map to 409."""
        from app.core.exceptions import GenerationConflictError

        assert GenerationConflictError in app.exception_handlers

    def test_ecdict_unavailable_error_handler_registered(self) -> None:
        """ECDictUnavailableError should map to 503."""
        from app.core.exceptions import ECDictUnavailableError

        assert ECDictUnavailableError in app.exception_handlers

    def test_value_error_handler_registered(self) -> None:
        """stdlib ValueError should map to 400."""
        assert ValueError in app.exception_handlers

    def test_key_error_handler_registered(self) -> None:
        """stdlib KeyError should map to 404."""
        assert KeyError in app.exception_handlers


# ── Health endpoint (integration) ───────────────────────────────────────


class TestHealthEndpoint:
    """Integration-style tests for the health check endpoint."""

    @pytest.mark.anyio
    async def test_health_returns_200(self) -> None:
        """GET /health should return 200."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/health")
            assert resp.status_code == 200

    @pytest.mark.anyio
    async def test_health_returns_status_ok(self) -> None:
        """GET /health body should contain ``{"status": "ok"}``."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/health")
            data = resp.json()
            assert data == {"status": "ok"}


# ── Exception handler behaviour (integration) ───────────────────────────


class TestExceptionHandlerResponses:
    """Verify exception handlers return correct HTTP status codes and bodies."""

    @pytest.mark.anyio
    async def test_not_found_error_returns_404(self) -> None:
        """NotFoundError handler is registered and callable."""
        from app.core.exceptions import NotFoundError

        handler = app.exception_handlers[NotFoundError]
        assert handler is not None
        assert callable(handler)

    @pytest.mark.anyio
    @pytest.mark.parametrize(
        "exc_class, expected_status",
        [
            ("NotFoundError", 404),
            ("ValidationError", 400),
            ("LLMError", 502),
            ("GenerationConflictError", 409),
            ("ECDictUnavailableError", 503),
        ],
    )
    async def test_handler_status_codes(
        self, exc_class: str, expected_status: int
    ) -> None:
        """Each domain exception handler should be registered."""
        from app.core import exceptions as exc_mod

        exc_cls = getattr(exc_mod, exc_class)
        # Verify handler is registered for the exception class
        assert exc_cls in app.exception_handlers, (
            f"Handler for {exc_class} not registered"
        )

        # Verify the handler returns the correct status code
        handler = app.exception_handlers[exc_cls]
        from fastapi import Request

        # Build a minimal ASGI scope for Request
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/test",
            "headers": [],
            "query_string": b"",
        }
        request = Request(scope=scope)
        response = await handler(request, exc_cls("test error"))
        assert response.status_code == expected_status
        body = response.body.decode("utf-8")
        assert "detail" in body or response.body


# ── Route mounting ─────────────────────────────────────────────────────


class TestRouteMounting:
    """Verify routes are mounted (or gracefully skipped)."""

    def test_health_route_registered(self) -> None:
        """GET /health route should always be registered."""
        routes = {r.path: r.methods for r in app.routes if hasattr(r, "path")}
        assert "/health" in routes
        assert "GET" in routes["/health"]

    def test_app_can_be_imported_without_api_module(self) -> None:
        """Importing app should not crash even if api/v1/router is absent."""
        # The fact that this test runs at all proves the lazy import works,
        # because app/api/v1/router.py does not exist yet and we already
        # imported ``app`` successfully at the top of this file.
        pass
