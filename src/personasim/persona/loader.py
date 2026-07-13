"""Loading seed files into storage.

Seeding is idempotent. Because seeded memory ids are derived from the seed key,
re-running against an already-seeded database adds nothing and changes nothing.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict

from personasim.models.memory import Memory
from personasim.models.persona import Persona
from personasim.persona.seed import PersonaSeed
from personasim.storage.database import Database
from personasim.storage.repositories.persona import PersonaRepository


class SeedError(Exception):
    """A seed file could not be read or is not valid."""


class SeedReport(BaseModel):
    """What a seeding run actually changed."""

    model_config = ConfigDict(extra="forbid")

    persona_id: str
    persona_name: str
    memories_created: int
    memories_skipped: int
    memories_updated: int = 0
    memories_stale: int = 0
    identity_updated: bool

    @property
    def was_noop(self) -> bool:
        return (
            self.memories_created == 0 and self.memories_updated == 0 and not self.identity_updated
        )

    @property
    def has_stale_memories(self) -> bool:
        """The seed file has been edited since this database was seeded.

        Reported rather than silently fixed. Seeding is idempotent by memory id,
        and ids derive from the seed *key*, so an edited summary resolves to a
        memory that already exists and is skipped — the edit never lands. An
        operator who is not told this has no way to discover it.
        """
        return self.memories_stale > 0


def read_seed_file(path: Path) -> PersonaSeed:
    """Parse and validate a seed file. Raises `SeedError` on any problem."""
    try:
        raw = yaml.safe_load(path.read_text())
    except OSError as exc:
        raise SeedError(f"cannot read seed file {path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise SeedError(f"{path} is not valid YAML: {exc}") from exc

    if not isinstance(raw, dict):
        raise SeedError(f"{path} must contain a YAML mapping at the top level")

    try:
        return PersonaSeed.model_validate(raw)
    except ValueError as exc:
        raise SeedError(f"{path} is not a valid persona seed: {exc}") from exc


def seed_persona(database: Database, persona: Persona, *, force: bool = False) -> SeedReport:
    """Write a persona into storage.

    Memories that do not exist are created. Memories that exist are *skipped* —
    seeding is idempotent — and an edited one is therefore not applied. Rather than
    let that pass in silence, a divergence is counted and reported, so the operator
    learns that the file on disk and the persona in the database disagree.

    `force` rewrites the memories the seed file names, and only those. What the
    persona *learned* is untouched: a formed memory's id is a random uuid4, which
    no seed key resolves to, so it is not in the set this function may write. That
    is not a filter — it is the shape of the id space.
    """
    with database.session() as session:
        repo = PersonaRepository(session)

        existing = repo.load(persona.id)
        identity_updated = existing is None or existing.identity != persona.identity
        if identity_updated:
            repo.identities.upsert(persona.id, persona.identity)
            session.flush()

        stored = {memory.id: memory for memory in existing.memories} if existing else {}

        created = [memory for memory in persona.memories if memory.id not in stored]
        if created:
            repo.memories.add_many(persona.id, created)

        divergent = [
            memory
            for memory in persona.memories
            if memory.id in stored and _differs(stored[memory.id], memory)
        ]

        updated: list[Memory] = []
        if force:
            for memory in divergent:
                # The persona has held this memory since it was first seeded.
                # Rewriting what it *says* must not restate when it was formed, or
                # every re-seed would quietly reset the memory's age — and Phase 5
                # is built on memories having one.
                revised = memory.model_copy(update={"created_at": stored[memory.id].created_at})
                repo.memories.update(revised)
                updated.append(revised)

        return SeedReport(
            persona_id=persona.id,
            persona_name=persona.identity.name,
            memories_created=len(created),
            memories_skipped=len(persona.memories) - len(created) - len(updated),
            memories_updated=len(updated),
            memories_stale=0 if force else len(divergent),
            identity_updated=identity_updated,
        )


def _differs(stored: Memory, authored: Memory) -> bool:
    """Whether the seed file now says something other than what was stored.

    `created_at` is excluded, and must be: `MemoryBase` stamps it at construction,
    so a memory rebuilt from an unchanged seed file differs from the stored one on
    every single run. Compare it and every memory looks edited, always.
    """
    ignore = {"created_at"}
    return stored.model_dump(exclude=ignore) != authored.model_dump(exclude=ignore)


def build_persona(seed: PersonaSeed) -> Persona:
    """Resolve a seed into a validated persona.

    `Persona` enforces the coherence of the authored story — links resolve, and a
    cause never postdates its effect — so a bad seed file fails here, loudly,
    rather than producing a persona with an impossible history.
    """
    try:
        return seed.to_persona()
    except ValueError as exc:
        raise SeedError(f"persona {seed.id!r} is incoherent: {exc}") from exc


def seed_from_file(database: Database, path: Path, *, force: bool = False) -> SeedReport:
    return seed_persona(database, build_persona(read_seed_file(path)), force=force)
