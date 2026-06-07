"""Story Rewriter service — rewrites source text chapters into English light-novel dialogue.

Ref: AGENTS.md §11 (#5), BACKEND_IN_OUT.md §四.5.
"""

from __future__ import annotations

from app.services.story_rewriter.rewriter import RewriteResult, StoryRewriter

__all__ = ["StoryRewriter", "RewriteResult"]
