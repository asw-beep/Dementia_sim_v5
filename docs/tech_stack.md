# Tech Stack

> **Project:** Persona Simulator
> **Current Phase:** Phase 1 – Healthy Human Persona
> **Language:** Python 3.12+

---

# Philosophy

Technology should serve the architecture—not define it.

Every library included in this project must solve a specific problem.

If a feature can be implemented cleanly without introducing another dependency, prefer the simpler implementation.

The architecture must remain independent of any specific LLM provider or framework.

---

# Core Technology Stack

| Component             | Technology        | Status     |
| --------------------- | ----------------- | ---------- |
| Programming Language  | Python 3.12+      | ✅ Selected |
| Local LLM Runtime     | Ollama            | ✅ Selected |
| Primary Model         | Qwen3:14B         | ✅ Selected |
| Data Models           | Pydantic v2       | ✅ Selected |
| Database ORM          | SQLAlchemy 2.x    | ✅ Selected |
| Database              | SQLite            | ✅ Selected |
| Configuration         | pydantic-settings | ✅ Selected |
| Testing               | pytest            | ✅ Selected |
| Logging               | structlog         | ✅ Selected |
| Dependency Management | uv                | ✅ Selected |
| Formatting            | Ruff              | ✅ Selected |
| Type Checking         | mypy              | ✅ Selected |

---

# LLM Runtime

## Runtime

**Ollama**

Purpose

Runs the language model completely locally.

Reasons

* No API costs
* Offline development
* Deterministic behaviour
* Easy model switching
* REST API
* Python SDK
* Cross-platform

Reference

https://ollama.com

---

## Primary Language Model

**qwen3:14b**

Runtime

Ollama

Reasons

* Excellent conversational quality
* Strong instruction following
* Very good persona consistency
* Good role-playing capability
* Long context support
* Fast enough for local inference
* Apache 2.0 licensed

The model is used only for language generation.

The model is **not** responsible for memory.

The model is **not** responsible for identity.

The model is **not** responsible for consistency.

Those belong to the Persona Engine.

---

# LLM Design Rule

The rest of the system must never know which model is being used.

Always communicate through an abstraction.

```
LLM Interface

↓

Ollama Adapter

↓

Qwen3:14B
```

Future adapters may include

* OpenAI
* Anthropic
* Gemini
* llama.cpp
* vLLM

Switching models should never require changing business logic.

---

# Programming Language

## Python 3.12+

Reasons

* Excellent AI ecosystem
* Mature tooling
* Rich NLP libraries
* Strong typing support
* Large community
* Fast development

---

# Data Validation

## Pydantic v2

Purpose

Represents every domain object.

Examples

* Persona
* Identity
* Episodic Memory
* Semantic Memory
* Working Memory
* Relationships
* Conversation State

Reasons

* Strong validation
* Type safety
* JSON serialization
* Excellent developer experience

---

# Database

## SQLite

Purpose

Persistent storage.

Reasons

* Zero configuration
* Portable
* Reliable
* ACID compliant
* Easy backups
* Perfect for Phase 1

Future

May migrate to PostgreSQL if scalability becomes necessary.

---

# ORM

## SQLAlchemy

Purpose

Database abstraction layer.

Reasons

* Mature ecosystem
* Database independence
* Excellent migration support
* Strong typing

---

# Memory Retrieval

## Phase 1

Keyword search

Metadata filtering

Importance ranking

Relationship filtering

This is sufficient for the first implementation.

---

## Phase 1.1 (Planned)

Sentence Transformers

Purpose

Semantic similarity search.

Candidate model

all-MiniLM-L6-v2

Status

Deferred.

---

## Phase 1.2 (Planned)

FAISS

Purpose

Vector similarity search.

Status

Deferred until memory volume justifies it.

---

# Project Configuration

## pydantic-settings

Purpose

Configuration management.

Stores

* Model name
* Database path
* Prompt configuration
* Debug flags
* Runtime settings

---

# Logging

## structlog

Purpose

Structured logging.

Used for

* Retrieval debugging
* Memory formation
* LLM calls
* Database operations

---

# Testing

## pytest

Used for

* Unit tests
* Integration tests
* Persona consistency tests
* Retrieval tests

---

# Formatting

## Ruff

Purpose

Formatting

Linting

Import sorting

Single tool replacing multiple utilities.

---

# Type Checking

## mypy

Purpose

Static type checking.

Required because memory objects are highly structured.

---

# Dependency Management

## uv

Reasons

* Very fast
* Reliable dependency resolution
* Modern Python workflow

---

# Repository Structure

```
src/

conversation/

memory/

persona/

retrieval/

llm/

storage/

models/

tests/

docs/

data/
```

---

# LLM Folder

```
llm/

base.py

ollama.py

prompts.py

context_builder.py
```

base.py

Defines the abstract interface.

ollama.py

Implements Ollama communication.

No other module may call Ollama directly.

---

# Storage Folder

```
storage/

database.py

repositories/

migrations/

schemas/
```

Responsible only for persistence.

No retrieval logic.

No persona logic.

---

# Memory Folder

```
memory/

identity/

episodic/

semantic/

working/

formation/

retrieval/
```

Responsible only for memory operations.

---

# External Dependencies

Required

* Ollama
* Qwen3:14B
* Python

Python Libraries

* pydantic
* sqlalchemy
* pydantic-settings
* structlog
* pytest
* ruff
* mypy
* uv

---

# Explicitly Not Using (Phase 1)

These technologies are intentionally excluded.

## LangGraph

Reason

Conversation flow is simple enough to implement ourselves.

Status

Deferred.

---

## Mem0

Reason

Automatic memory extraction is outside Phase 1.

Status

Reference only.

---

## Letta (formerly MemGPT)

Reason

Inspired by its RAM/SSD memory hierarchy, but we are implementing our own memory manager to maintain complete control over the architecture.

Status

Reference only.

---

## LlamaIndex

Reason

Overkill for the current architecture.

Status

Deferred.

---

## Neo4j

Reason

Relationship graph is too small for a graph database.

Status

Deferred.

---

## Qdrant

Reason

No vector database needed initially.

Status

Deferred.

---

## Pinecone

Reason

Cloud dependency unnecessary.

Status

Deferred.

---

## Redis

Reason

Working memory exists inside the application.

Status

Deferred.

---

# Design Principles

1. The Persona exists independently of the LLM.

2. Memory exists independently of the LLM.

3. The LLM only generates language.

4. Every component has one responsibility.

5. Every dependency must justify its existence.

6. Local-first development.

7. Replaceable components.

8. Simple over clever.

9. Deterministic architecture.

10. Phase 1 focuses only on healthy human memory.

---

# Future Candidates

These technologies may be evaluated after Phase 1.

* Sentence Transformers
* FAISS
* PostgreSQL
* LangGraph
* Mem0
* Letta
* Neo4j
* Qdrant
* OpenTelemetry
* Grafana

Adoption will be based on demonstrated need—not speculation.


---

# Web (Stage 9)

## FastAPI + uvicorn

Purpose

Serve the frontend: a persona gallery, a chat pane, and the memory-trace panel.

Reasons

* The trace panel is the debugging surface Phase 2 needs most — impairment
  simulation is the study of how retrieval degrades, and you cannot study what you
  cannot see.
* Pydantic v2 is already the domain vocabulary, and FastAPI speaks it natively. The
  API models *are* the domain models; nothing is translated twice.
* The alternative was no frontend, and every defect in Stages 5–8 was found by
  talking to the persona. Lowering the cost of talking to her is the highest-value
  thing this project can buy.

Status

Selected.

Constraint

The web layer is a **second adapter over the Stage 7 orchestrator**, exactly as the
CLI is. It owns no memory, no retrieval, and no persona logic — a test enforces
that `web/` cannot import `memory/`, `retrieval/`, or the context builder. If it
grew its own idea of what she remembers, there would be two answers to every
question about her, and they would drift.

## No frontend framework

No React, no build step, no npm. Three static files, served by FastAPI.

The page holds a session id and nothing else. Every memory decision happens
server-side, in the orchestrator the CLI drives — so there is no client state worth
a framework, and a build step would buy nothing but a build step.

Revisit when the trace panel grows genuinely interactive (filtering a memory graph,
scrubbing a session), which it may in Phase 2.

## Still no Redis

Live conversations are held in a dict, in the process serving them.

This is the same reasoning as `working memory exists inside the application`, and it
still holds: working memory's volatility is a *fact* (there is no code path from it
to durable storage, and an invariant test fails if anyone adds one), and a cache
would demote it to a *promise* — a TTL somebody has to set correctly, forever.

It stops holding the moment this runs behind more than one worker process. That is
when Redis starts earning its place, and not before.
