"""Persistence layer.

Repositories return Pydantic domain models; ORM rows never escape this package.
"""

from personasim.storage.database import Database
from personasim.storage.repositories import (
    IdentityRepository,
    MemoryRepository,
    PersonaRepository,
    SessionRepository,
)

__all__ = [
    "Database",
    "IdentityRepository",
    "MemoryRepository",
    "PersonaRepository",
    "SessionRepository",
    "SessionSummary",
]
