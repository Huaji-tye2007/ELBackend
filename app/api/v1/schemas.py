"""HTTP request/response schemas for API v1.

These are decoupled from domain models (app/models/) to avoid leaking
internal fields to API consumers. Ref: AGENTS.md §10, §12.

Exception translation at route boundary — see AGENTS.md §15.2.
"""

from pydantic import BaseModel, Field


class WordInput(BaseModel):
    """A single word-meaning pair in a vocabulary upload request."""

    word: str
    meaning: str


class VocabularyUploadRequest(BaseModel):
    """Request body for POST /vocabulary/upload."""

    user_id: str
    items: list[WordInput] = Field(min_length=1)


class VocabularyUploadResponse(BaseModel):
    """Response body for POST /vocabulary/upload."""

    count: int = Field(ge=0)


class HealthResponse(BaseModel):
    """Response body for GET /health."""

    status: str


class ReadingLogResponse(BaseModel):
    """Response body for POST /reading/log."""

    updated: bool


class FinishEpisodeRequest(BaseModel):
    """Request body for POST /reading/finish."""

    episode_id: int = Field(ge=1)


class FinishEpisodeResponse(BaseModel):
    """Response body for POST /reading/finish."""

    vocab_updated_count: int = Field(ge=0)


class DictionaryResponse(BaseModel):
    """Response body for GET /dictionary/{word}."""

    word: str
    meaning: str
    examples: list[str] | None = None


class ArcGenerateRequest(BaseModel):
    """Request body for POST /arc/generate."""

    arc_id: str | None = None


class ArcGenerateResponse(BaseModel):
    """Response body for POST /arc/generate."""

    job_id: str
    status: str


class ErrorResponse(BaseModel):
    """Standard error response body."""

    detail: str


__all__ = [
    "WordInput",
    "VocabularyUploadRequest",
    "VocabularyUploadResponse",
    "HealthResponse",
    "ReadingLogResponse",
    "FinishEpisodeRequest",
    "FinishEpisodeResponse",
    "DictionaryResponse",
    "ArcGenerateRequest",
    "ArcGenerateResponse",
    "ErrorResponse",
]
