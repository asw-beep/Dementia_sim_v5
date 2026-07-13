"""The web adapter: a second front end over the Stage 7 orchestrator.

It adds no memory, no retrieval, and no persona logic. It calls `Conversation`
exactly as `persona chat` does.
"""

from personasim.web.app import create_app
from personasim.web.sessions import SessionError, SessionStore

__all__ = ["SessionError", "SessionStore", "create_app"]
