"""Tests for app.core.config — LLM configuration from environment."""

from __future__ import annotations

import os
from unittest import mock


from app.core.config import get_llm_config


class TestGetLLMConfig:
    """Tests for get_llm_config function."""

    def test_returns_dict_with_expected_keys(self) -> None:
        """Should return a dict with base_url, api_key, and model keys."""
        config = get_llm_config()
        assert isinstance(config, dict)
        assert "base_url" in config
        assert "api_key" in config
        assert "model" in config

    def test_default_values(self) -> None:
        """When no env vars are set, should return documented defaults."""
        with mock.patch.dict(os.environ, {}, clear=True):
            # Re-import to pick up cleared env (dotenv already loaded, so
            # we must patch os.environ before calling)
            config = get_llm_config()
            assert config["base_url"] == "http://localhost:11434/v1"
            assert config["api_key"] == ""
            assert config["model"] == "deepseek-v4-flash"

    def test_custom_env_values(self) -> None:
        """Custom env vars should override defaults."""
        with mock.patch.dict(
            os.environ,
            {
                "LLM_BASE_URL": "https://api.example.com/v1",
                "LLM_API_KEY": "sk-custom-key",
                "LLM_MODEL": "custom-model",
            },
            clear=True,
        ):
            config = get_llm_config()
            assert config["base_url"] == "https://api.example.com/v1"
            assert config["api_key"] == "sk-custom-key"
            assert config["model"] == "custom-model"
