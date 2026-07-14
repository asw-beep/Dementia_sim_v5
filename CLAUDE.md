# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project status

**`docs/roadmap.md` is the source of truth for what is built, what is next, and why each decision was made.** Read it before planning work. Phase 1 is being built waterfall: each stage is specified, built, and verified against explicit exit criteria before the next begins.

## Who is in the room

**Exactly two people: the persona, and the caregiver talking to it.** Nobody else ever speaks.

The caregiver is a **role, not an identity**. They may say "I'm the nurse" or "I'm your doctor". They never say "I'm Aswin" — names are out of scope, and no code should try to learn one. So the persona never has to work out *who* is speaking; it already knows. Everything the caregiver discloses is a fact about the same subject (`memory.formation.CAREGIVER`), whether or not they have said anything about themselves.

This deletes a class of bug rather than handling it. When the speaker was a name to be learned, a fact disclosed *before* the name was stranded on an anonymous subject forever — nothing re-attributed it, consolidation could not merge it, and no keyword could reach it. With a fixed subject there is no anonymous phase to be stranded in.

Two rules follow, and both were learned the hard way:

- **The persona must never confuse the two of them.** In the caregiver's messages, "I/me/my" always mean the caregiver; "you/your" always mean the persona. Without being told this explicitly, she answered "what do *I* do for a living?" with "I'm a cartographer".
- **Never tell the persona she is looked after.** `caregiver` is the right word for the domain and the wrong word to put in her mouth. Told she was speaking to "your caregiver, the person who looks after you", she inverted the roles outright — announced "I am your caregiver", gave away her own home as theirs, and claimed their city as her own. A healthy woman of thirty-eight has no one who looks after her, and handed that contradiction the model resolves it by swapping the two of them. Phase 1 is a **healthy** persona; keep the prompt consistent with that.

## She may improvise her Tuesday. She may not improvise her life.

`conversation/improvise.py`. She has no clock and no episodic memory of today, so
"what did you have for breakfast?" has no true answer — and left to the model she
produced oatmeal one turn, a dinner eaten before evening the next, and a reason for
that too. A different life every time she was asked.

The fix is **memory**, not silence: a value is synthesised once, written down as a
structured memory, and answered from ever after. Consistency is not asked of the
model; it is taken away from it.

This is a deliberate amendment to *"never invented by the LLM as a permanent
memory"*, and it is bounded by two things. Do not loosen either:

- **It only fires where memory is silent** (`trace.is_empty`), so an improvised
  detail can never contradict or overwrite an authored one.
- **`EVERYDAY` is exhaustive** — meals, sleep, what she is working on. There is no
  path from it to a person, a death, a job, a place she lived, or a reason why she
  did something. Ask about a sister she does not have and she still says it does not
  come to mind. **The cast stays closed: she cannot manufacture a relative and then
  believe in her for the rest of her life.**

**The date and the clock are told, not improvised.** They were improvised for a
while, and that was a mistake: "what did you have for breakfast?" has no true answer,
but *"what day is it?" does* — the system has known it all along. Making her invent a
fact sitting in `datetime.now()` was inventing for the sake of it. `render_now()`
injects it, exactly as identity is injected: a fact she is handed, not a memory she
holds. No storage — a clock is right by construction, and a stored clock is wrong
within the hour.

She is told to say it **as a person would**: "It's Monday", "just gone five" — not to
recite the ISO date. A clock reads out the minute; a person glances.

This is also the natural seam for Phase 2. A healthy person knows what day it is;
losing that is a *symptom*, and it can be degraded here without touching a single
memory.

And note what still holds: the model is asked for a *value*, never for prose that is
read back. `memory/formation/` still cannot import the LLM, and the invariant test
still enforces it. What she *says* remains unable to become what she knows.

## She is a person, not an encyclopedia

Asked to define electrostatic force she gave a textbook answer; asked for gradient
descent she produced the LaTeX. A woman who draws maps for a living does not have the
mathematics of machine learning at her fingertips, and pretending otherwise is not a
lapse of taste — **it is the moment she stops being her and starts being the model.**

She knows what a woman of her age and trade would know: conversation, opinions, the
weather, her own craft. Not physics, medicine, computing, or higher mathematics.
Asked, she says "I wouldn't know" — plainly, without a guess.

The same rule catches ancestry, religion, politics and health, which *feel* like
things a person simply knows about herself. They are biography, and if they are not
authored she does not have them: she invented an English and Scottish descent for
herself, and a Nigerian one for her wife, on nothing at all.

## Phase 2 — one CDR stage at a time

**Do not build "dementia". Build one patient who consistently behaves like CDR 0.5.** That is a far smaller thing, and it is the whole of Sprint 2A. CDR 1, 2 and 3 are later sprints, and each must be independently shippable — a sprint that only makes sense once the next one lands is a sprint that was not scoped.

**Severity is data, not code.** Symptoms are never hardcoded and never branched on by name. A disease profile is a YAML file in `data/profiles/` (`healthy.yaml`, `cdr05.yaml`, `cdr1.yaml`, …) holding parameters — retrieval probability, orientation, language, working memory. Healthy is `1.0` across the board and must remain reachable. This is what makes a later random patient nothing more than *load persona + load profile*, and what stops "CDR 2" from becoming a pile of `if stage == 2` scattered through the engine.

**Phase 1 is untouched.** The impairment layer wraps `retrieval/`, working memory and the prompt seam; it does not edit the core, the schema, or the seed. Nothing that made Phase 1 correct may be relaxed to make Phase 2 expressive — in particular, **formation still never sees the model's output**, so an impaired persona still cannot remember something she made up.

**The trace must explain every failure.** A memory that was not recalled is not a gap in the log: the trace says it was found and withheld, and why. An unexplained failure is indistinguishable from a bug, and Phase 3's scoring report is built on exactly this.

### What Sprint 2A is, and is not

Six behaviours, and nothing else: recent episodic recall is *sometimes* impaired; remote memory stays excellent; orientation is mostly intact (a corrected "Tuesday? … Wednesday? No — Tuesday", never "where am I?"); mild word-finding trouble, occasional and not every sentence; slight repetition; and **insight is preserved** — she knows she is becoming forgetful, and that is a clinical feature of CDR 0.5, not a leak. Do not remove it.

**No impossible confabulations, ever.** Impairment means a memory is *withheld or hedged*, never that a new one is invented. The cast stays closed and the closed-cast rule from *"She may improvise her Tuesday"* is not loosened by a disease profile — a forgetful woman does not acquire a sister she never had.

Explicitly **not** in Sprint 2A, or in Phase 2 at all until its own sprint says so: disease progression, emotional or hallucination engines, stochastic failure beyond the profile parameters, medication, sundowning, wandering, agitation, ADL decline, and **caregiver scoring**. Scoring is a *consumer* of the simulator, not part of it — it is Phase 3, and building it early would let the simulator be tuned to its own scorer.

**The one success criterion for Sprint 2A:** can a caregiver tell this persona apart from the healthy one over 15–20 minutes, while still recognising her as the same person? Everything else is detail, and detail comes after that is true.

## The stage gate — non-negotiable

**Do not start the next stage while any known defect in this stage or an earlier one is open.** No "we'll fix it in Stage 9". No "known limitation" that is really a bug nobody wants to fix. A stage is finished when the system is *actually correct*, not when its checklist is ticked.

Concretely, before declaring a stage complete:

1. `make check` is green — `ruff check`, `ruff format --check`, `mypy src` (strict), `pytest`.
2. **Every open issue in `docs/roadmap.md` for this stage and all earlier stages is closed**, or has been explicitly re-scoped by the user. Re-read the "Problems the gate caught" and "Open decisions" sections; anything still true is still your problem.
3. **The persona has been driven by hand, adversarially, against a real model** — and the transcript is clean. See below.
4. Every defect found is fixed *and* pinned by a regression test that fails without the fix.

If a defect is genuinely being deferred, it is not a "limitation" — it is an **open decision in `docs/roadmap.md`, stated plainly**, with the reason and the cost. Silence is how a bug becomes permanent.

### Driving beats testing — this is empirical, not a slogan

Every real bug in Stages 5, 6, 7 and 8 was found by **talking to the persona**, and none by the tests written beforehand. The suite was green through all of it:

- she invented a pet ("a tabby cat named Whiskers") when asked about her first one;
- she invented an entire mother — her silence, her sleeplessness — from a question's premise;
- she gave her own father to her wife's family, because a seed pronoun was ambiguous;
- she formed a memory *from a question* ("Do I have any kids?" → "Sam has any kids");
- she heard four disclosures in a row and remembered none of them;
- she answered "I'm a cartographer" when asked what **the user** does for a living;
- she stored a memory keyworded `grew` that "where did I **grow** up?" could never reach.

Tests encode the failures you already imagined. The persona fails in ways you did not. So: **write the tests after the drive, against what actually broke.** Build the instrument first (`persona chat --trace`), then go looking for trouble — contradict her, assert false premises, ask the same thing five ways, tell her something and come back a session later.

## Commands

```bash
uv sync                  # install; pins Python 3.12 via .python-version
make check               # the stage gate: lint + typecheck + test
make fmt                 # ruff format + autofix
uv run mypy src          # strict
uv run pytest            # full suite
uv run pytest tests/test_seed.py::TestNarrativeSpine -v     # one class
uv run pytest tests/test_models.py::TestMemoryBase::test_links_are_canonically_ordered  # one test
uv run persona --database data/persona.db seed data/personas/elena.yaml
```

A stage is not complete until `ruff check`, `ruff format --check`, `mypy src`, and `pytest` are all clean.

## Project vision

This is a **Persona Simulator**: a realistic, stateful human persona that maintains identity and memory across conversations. It is explicitly **not** an assistant, autonomous agent, or planner — only a conversational persona.

Core principle: **the LLM is not the persona**. The persona exists independently as structured data; the LLM's only job is to verbalize it naturally. Everything the persona "knows" must originate from Identity, Semantic Memory, Episodic Memory, or Working Memory — never invented by the LLM as a permanent memory.

The project is built in phases, and **the Phase 1 architecture must not change in later phases**:

- **Phase 1 (done)**: healthy human persona — identity, working memory, semantic/episodic/relationship memory, memory consolidation, retrieval engine, memory trace. Tagged `phase-1-complete`; that tag is the rollback point.
- **Phase 2 (current)**: cognitive impairment layer, implemented as a wrapper around Phase 1 modules only (no core/schema changes) — degrades retrieval behaviour, not the database schema. Four sprints, one per CDR stage: **2A → CDR 0.5**, **2B → CDR 1**, **2C → CDR 2**, **2D → CDR 3**. Each ships independently.
- **Phase 3**: assessment mode — caregiver predicts a CDR, the system reveals the actual one and explains the gap per domain.
- **Phase 4**: random patient generation (persona + disease profile, diagnosis hidden).
- **Phase 5**: longitudinal progression (a patient who declines over time).

Multiple personas, emotional dynamics and memory aging are no longer numbered phases — they live in `docs/future.md` until something needs them.

Before implementing any feature, ask "does this belong to the sprint I am in?" — if not, it goes in `docs/future.md`, not into the codebase.

## Architecture

### Memory hierarchy

```
Persona
  ├── Identity        (name, age, personality, occupation, values, speech style — who the persona is)
  ├── Working Memory   (session-only: current conversation/topic, destroyed after session ends — behaves like RAM)
  └── Long-Term Memory (behaves like SSD)
        ├── Identity Memory
        ├── Semantic Memory   (facts, e.g. "lives in Boston")
        ├── Episodic Memory   (experiences, e.g. "graduation")
        └── Relationship Memory
```

Every memory object carries: `id`, `type`, `created_at`, `summary`, `keywords`, `importance`, `confidence`, `links`.

### Narrative determinism (why links are typed)

Retrieval is deterministic; the prose *between* retrieved memories is not. An untyped link says two memories are associated but not *how*, leaving the LLM to invent the causal bridge — differently each session. So `links` are typed edges (`MemoryLink`: `caused_by`, `led_to`, `occurred_during`, `involves`, `concerns`), and the dated, causally-connected episodic memories form a **narrative spine** authored in the seed file. The model verbalizes the relation; it never invents one.

`Persona` rejects a seed whose story is impossible (a cause postdating its effect). That is an authoring check, not temporal-confusion simulation.

Questions falling entirely outside stored memory are answered freely and **never persisted**, so improvised trivia may drift across sessions. This is accepted. Consistency tests therefore assert consistency against *stored memory only*.

### Message flow

```
User Message → Working Memory Updated → Retrieve Relevant Memories → Context Builder → LLM → Response → Memory Formation → Long-Term Memory (optional)
```

Retrieval sub-flow: `Question → Intent Detection → Entity Extraction → Retrieve Memories → Ranking → Context → LLM`.

### Memory trace

Every response internally exposes retrieved memories, memory types, and retrieval reason — hidden from the user, kept for debugging and future cognitive-simulation phases.

### LLM isolation rule

The rest of the system must never know which model is in use — always go through the LLM interface abstraction:

```
LLM Interface → Ollama Adapter → Qwen3:14B
```

No module outside `llm/` may call Ollama (or any model provider) directly. This is what makes future adapters (OpenAI, Anthropic, Gemini, llama.cpp, vLLM) swappable without touching business logic. The LLM is responsible for language generation only — never memory, identity, or consistency (that belongs to the persona engine).

### Planned repository structure

```
src/
    conversation/
    memory/
        identity/
        episodic/
        semantic/
        working/
        formation/
        retrieval/
    persona/
    retrieval/
    llm/
        base.py              # abstract LLM interface
        ollama.py             # Ollama adapter (only place allowed to call Ollama)
        prompts.py
        context_builder.py
    storage/
        database.py
        repositories/
        migrations/
        schemas/
    models/                   # Pydantic domain models (Persona, Identity, Episodic/Semantic/Working Memory, Relationships, Conversation State)
tests/
data/
docs/
```

`storage/` is persistence only — no retrieval logic, no persona logic. `memory/` is memory operations only.

## Tech stack

| Component | Technology |
|---|---|
| Language | Python 3.12+ |
| Local LLM runtime | Ollama, running Qwen3:14B |
| Data models | Pydantic v2 |
| ORM | SQLAlchemy 2.x |
| Database | SQLite (Phase 1) |
| Config | pydantic-settings |
| Testing | pytest |
| Logging | structlog |
| Dependency management | uv |
| Formatting/linting | Ruff |
| Type checking | mypy |

Phase 1 retrieval is keyword search + metadata filtering + importance ranking + relationship filtering — no embeddings/vector search yet (Sentence Transformers + FAISS are planned but deferred until justified by memory volume). Deliberately **not** used in Phase 1: LangGraph, Mem0, Letta, LlamaIndex, Neo4j, Qdrant, Pinecone, Redis — each was evaluated and deferred (see `docs/tech_stack.md` for the reasoning per library); don't reach for them without revisiting that reasoning first.

## Design principles

1. Simplicity over complexity; every module has one responsibility.
2. Memory is structured, never free text; retrieval is explicit.
3. Every response must be explainable (via memory trace).
4. Identity never depends on the LLM.
5. Every dependency must justify its existence — prefer no new dependency if a simple implementation covers it.
6. No goals, no planning, no task execution, no autonomous behavior — conversational responses only.
