"""Application configuration loaded from environment variables."""

from __future__ import annotations

import os

from dotenv import load_dotenv


load_dotenv()


def get_llm_config() -> dict[str, str]:
    """Read LLM configuration from environment variables.

    Returns:
        Dict with keys ``base_url``, ``api_key``, ``model``.
    """
    return {
        "base_url": os.getenv("LLM_BASE_URL", "http://localhost:11434/v1"),
        "api_key": os.getenv("LLM_API_KEY", ""),
        "model": os.getenv("LLM_MODEL", "deepseek-v4-flash"),
    }
