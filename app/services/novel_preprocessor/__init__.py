"""Novel Preprocessor package — raw novel ingestion and chapter splitting.

Exports:
    NovelPreprocessor: Main service class for novel preprocessing.
"""

from app.services.novel_preprocessor.preprocessor import NovelPreprocessor

__all__ = ["NovelPreprocessor"]
