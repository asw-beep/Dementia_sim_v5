# Persona Simulator

## Project Vision

This project builds a realistic, stateful human persona simulator.

The project is developed in phases.

Current development target:

Phase 1 — Healthy Human Persona

Future phases will introduce cognitive impairments, but the architecture designed in Phase 1 must remain unchanged.

---

## Core Principle

The LLM is NOT the persona.

The persona exists independently.

The LLM is only responsible for expressing the persona naturally.

Everything the persona "knows" must originate from:

- Identity
- Semantic Memory
- Episodic Memory
- Working Memory

Never invent permanent memories.

---

## Phase 1 Scope

Allowed

- Healthy memory
- Persistent persona
- Session memory
- Memory retrieval
- Memory consolidation
- Identity consistency
- Relationship tracking
- Memory traces

Not Allowed

- Dementia
- Alzheimer's
- Forgetfulness
- Confabulation
- Cognitive decline
- False memories
- Memory corruption

---

## Design Principles

1. Simplicity over complexity.
2. Every module should have one responsibility.
3. Memory is structured, never free text.
4. Retrieval is explicit.
5. Every response must be explainable.
6. Working memory behaves like RAM.
7. Long-term memory behaves like SSD.
8. Identity never depends on the LLM.

---

## Repository Structure

docs/
    architecture.md
    future.md

src/
    memory/
    retrieval/
    persona/
    conversation/

tests/

data/

---

## Coding Style

- Python
- Pydantic models
- SQLAlchemy ORM
- Type hints everywhere
- Small modules
- No premature optimization

---

## Before implementing any feature

Ask:

Does this belong to Phase 1?

If not, move it to future.md.

Never introduce Phase 2 functionality into Phase 1.