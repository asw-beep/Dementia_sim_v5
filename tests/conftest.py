"""Shared fixtures."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date

import pytest
from sqlalchemy.orm import Session

from personasim.models import (
    EpisodicMemory,
    Identity,
    LinkRelation,
    MemoryLink,
    Persona,
    RelationshipMemory,
    SemanticMemory,
)
from personasim.storage import Database


@pytest.fixture
def database() -> Iterator[Database]:
    """A fresh file-less SQLite database per test."""
    db = Database.in_memory()
    db.create_schema()
    yield db
    db.dispose()


@pytest.fixture
def db_session(database: Database) -> Iterator[Session]:
    with database.session() as session:
        yield session


@pytest.fixture
def identity() -> Identity:
    return Identity(
        name="Elena Marsh",
        age=38,
        occupation="Cartographer",
        personality=["curious", "reserved"],
        values=["honesty", "craftsmanship"],
        speech_style="Measured and warm, prone to precise detail.",
    )


@pytest.fixture
def persona(identity: Identity) -> Persona:
    """A small persona exercising all three memory types and a cross-type link."""
    wedding = EpisodicMemory(
        summary="Married Maya on a rainy afternoon in Vermont",
        keywords=["wedding", "maya", "vermont"],
        occurred_on=date(2014, 9, 6),
        location="Vermont",
        participants=["Maya"],
        importance=0.95,
    )
    spouse = RelationshipMemory(
        summary="Maya is my spouse of a decade",
        keywords=["maya", "spouse"],
        person_name="Maya",
        relation="spouse",
        closeness=0.98,
        known_since=date(2011, 3, 1),
        links=[MemoryLink(target=wedding.id, relation=LinkRelation.CONCERNS)],
    )
    city = SemanticMemory(
        summary="Lives in Boston",
        keywords=["boston", "home"],
        subject="self",
        attribute="city",
        value="Boston",
        importance=0.7,
    )
    return Persona(identity=identity, memories=[wedding, spouse, city])
