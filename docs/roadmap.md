# Roadmap

Phase 1 — Healthy Human Persona. Built waterfall: each stage is specified, built,
and verified against its exit criteria before the next begins.

**Status: Stage 9 complete. Phase 1 is done, end to end.**

`persona seed` · `persona chat` · `persona trace`. The consistency suite passes: the
same question asked several ways reaches the same memory, a fact disclosed in one
session is recalled in the next, and nothing the model invents is ever remembered.

The persona speaks, remembers what it is told, and cannot remember what it makes
up. The loop is closed: a fact disclosed in one session is recalled in the next,
and a hallucinated one is not recorded at all — not because it is filtered, but
because the model's output is never offered to memory formation.

Every stage below that is marked complete passed the same gate:
`ruff check` · `ruff format --check` · `mypy src` (strict) · `pytest`.

---

## Progress

| Stage | Scope | Status | Tests |
| ----- | ----- | ------ | ----- |
| 0 | Project foundation | ✅ Complete | 6 |
| 1 | Domain models | ✅ Complete | 55 |
| 2 | Storage layer | ✅ Complete | 93 |
| 3 | Seed persona and loader | ✅ Complete | 122 |
| 3.5 | Typed links and narrative spine | ✅ Complete | 140 |
| 4 | Working memory | ✅ Complete | 163 |
| 5 | Retrieval engine and memory trace | ✅ Complete | 219 |
| 6 | LLM layer | ✅ Complete | 258 |
| 7 | Conversation loop and memory formation | ✅ Complete | 298 |
| 8 | CLI, consistency tests, documentation | ✅ Complete | 360 |
| 9 | Web frontend with memory-trace panel | ✅ Complete | 388 |

Test counts are cumulative for the whole suite at the close of that stage.

---

## Stages

### Stage 0 — Project foundation ✅

Toolchain and the configuration seam everything depends on.

`pyproject.toml` (uv, Python 3.12 pinned via `.python-version`), Ruff, strict mypy,
`config.py` (pydantic-settings), `logging.py` (structlog), package skeleton,
`Makefile` exposing `fmt` / `lint` / `typecheck` / `test` / `check`.

**Exit criteria met:** smoke test green; lint, format, and type checks clean.

---

### Stage 1 — Domain models ✅

The vocabulary of the system. Pure Pydantic v2 — no I/O, no storage, no LLM.

`MemoryBase` with the eight required fields; `SemanticMemory` / `EpisodicMemory` /
`RelationshipMemory` as a discriminated union; `Identity`; `Persona`;
`ConversationState`; `MemoryTrace`.

**Exit criteria met:** validation rules covered; mypy clean.

**Decisions.** Semantic memories require a `subject`/`attribute`/`value` triple,
not merely a summary — "memory is structured, never free text" would otherwise be
violated the moment retrieval had to parse prose. Link integrity is validated at
the `Persona` level, since only the persona can see both ends of a link; a
dangling link would let retrieval surface a nonexistent memory, which is a Phase 2
failure mode. `created_at` must be timezone-aware. `MemoryTrace.reason` is
mandatory, so an unexplained retrieval cannot be constructed.

---

### Stage 2 — Storage layer ✅

Persistence only. SQLAlchemy 2.x typed ORM over SQLite. Five tables; all three
memory types share one `memories` table with a discriminating `type` column, so
Phase 2 needs no schema migration.

Repositories translate ORM rows to Pydantic models: no ORM object escapes the
package.

**Exit criteria met:** every memory type round-trips; storage purity enforced.

**Decisions.** `relationship_repo` was folded into `memory_repo` — a relationship
*is* a memory type, and a separate repository would have been a second door into
the same table. `PersonaRepository` was added because a persona is only valid as a
unit (its links must resolve against its own memories), so saving the halves
independently could persist an invalid graph.

**Problems the gate caught.** SQLite silently destroys timezones, so a memory
written and read back would have failed model validation — fixed with a
`UTCDateTime` column type. SQLite also ignores foreign keys unless
`PRAGMA foreign_keys=ON` is set per connection, without which the memory graph
could go dangling. And a repository method named `list` shadowed the `list`
builtin inside its own annotations.

---

### Stage 3 — Seed persona and loader ✅

`data/personas/elena.yaml`, an idempotent loader, and the `persona seed` command.

Seed files address memories by human-readable key; each key resolves to a
deterministic UUID5 over `persona_id + key`. The same seed file therefore always
produces the same memory ids, which is what makes re-seeding a no-op — and lets
authoring errors name the author's key rather than an opaque UUID.

**Exit criteria met:** 27 memories created; re-running is a true no-op; the loaded
persona reconstructs identically to its source file; zero dangling links.

**Problem the gate caught.** Links round-tripped through the database in row
order, so a persona loaded from storage compared *unequal* to the one saved.
Links are semantically a set, so the model now sorts them into a canonical form.

---

### Stage 3.5 — Typed links and narrative spine ✅

An amendment to Stages 1–3, prompted by a real risk: retrieval is deterministic,
but the connective tissue *between* memories is not stored anywhere, so the LLM
invents it — differently each session.

Links became typed edges (`caused_by`, `led_to`, `occurred_during`, `involves`,
`concerns`). The episodic memories, dated and causally connected, now form a
narrative spine: a life with no unexplained jumps, authored rather than generated.
`Persona` rejects a seed whose story is impossible — a cause may not postdate its
effect.

See **Narrative Determinism** in `architecture.md` for the full reasoning.

**Exit criteria met:** the causal bridge is data
(`"adopted Compass" --caused_by--> "her father died"`); a corrupted timeline is
rejected at load with a non-zero exit code.

**Decisions.** `relation` joined the primary key on `memory_links`, because two
memories may legitimately hold more than one relation. Questions falling entirely
outside stored memory are answered freely and never persisted, so improvised
trivia may drift across sessions — accepted, because the spine covers the
biography. Consequently, consistency tests assert against **stored memory only**.

---

### Stage 4 — Working memory ✅

Session-scoped RAM: the current conversation, active topic, and facts disclosed
mid-session. Created when a session starts, destroyed when it ends. Touches no
database.

**Exit criteria met:** the window is bounded; teardown discards everything;
nothing reaches the database without passing through memory formation.

**Decisions.** The turn window is a *capacity bound, not a forgetting model*. A
turn leaving the window has already been persisted to the session log; it leaves
RAM, not existence. `turns_seen` is exposed alongside `recent_turns()` so the two
can never be conflated. Temporary facts are deliberately **not** windowed — the
window bounds the conversation, not what was learned during it. Working memory is
forbidden from importing storage, so its volatility is structural.

---

### Stage 5 — Retrieval engine and memory trace ✅

The heart of Phase 1, and the surface Phase 2 wraps without modifying.

Pipeline: `Question → Intent Detection → Entity Extraction → Retrieve → Rank → Context`.
Deliberately keyword-based: no embeddings, no vector store.

Retrieval traverses typed links, so a `caused_by` edge pulls in the memory that
explains the one the question asked about:

```
>>> Why did you adopt Compass?
    experiential_recall: 2 memories matched; on keywords ['compass'];
    1 added by following ['caused_by']
      [1.10] I took in Compass from a shelter the winter after my father died
      [1.05] I own an elderly beagle named Compass
      [0.74] My father died of a stroke in the spring...       <-caused_by-
```

**Exit criteria met:** specific questions surface specific memories; every
retrieval returns a populated trace with a human-readable reason; the engine
depends on a `MemorySource` protocol, so Phase 2 can substitute a degraded source
without touching any internals.

**Decisions.** The engine takes a `MemorySource` protocol rather than a
repository, so it runs against an in-memory persona with no database — a test
asserts both sources retrieve identically. `ScoreComponents` hold *already
weighted* contributions, so `components.total == score` for every retrieved
memory, expanded ones included; provenance (`linked_from`, `via_relation`) is what
marks a memory as explanatory rather than asked-for, never a zeroed score. Person
mentions are matched against people the persona actually knows rather than guessed
from capitalisation, so "Boston" is never mistaken for a person. `retrieval/`
cannot import `ollama` or `personasim.llm`: if the model decided what a question
was about, recall would vary between two askings of the same question.

**Problems the gate caught.** Driving the engine against Elena before writing
tests exposed three bugs the tests alone would have missed. `"hello there"`
classified as a factual question, because the small-talk check compared raw tokens
and one filler word defeated it — it now compares content words. Expanded memories
reported `score=0.0` while their components summed to `0.74`, silently violating
the `total == score` invariant. And the tokenizer left possessives intact, so
"your father's soup" produced `father's`, matched nothing, and the persona drew a
blank on a question about her own father.

(Summaries were third person until Stage 6, which found that ambiguous. They are
first person now, and the trace reads as above.)

**A defect in the seed data.** Asking "what was your first pet's name?" retrieved
her 2005 *survey job*, because that memory carried the keyword `first` — generic
enough to collide with "first pet", "first job", "first time". Removed, with a
regression test. Seed keywords are load-bearing: a lazy keyword is a spurious
memory waiting to fire.

---

### Stage 6 — LLM layer ✅

The only place that knows a model exists, and the first stage in which one runs.

`llm/base.py` (the `LLMClient` protocol, `ChatMessage`, `LLMError`), `llm/ollama.py`
(the sole module importing `ollama`), `llm/prompts.py`, `llm/context_builder.py`.

The context builder is where narrative determinism is finally cashed in. Retrieval
has already followed the typed links, so a memory that *explains* another arrives
with the relation that binds them, and is rendered beneath it:

```
Everything you can recall bearing on what was just said, in full:

Things you have lived through:
- (2019-12-14, Boston) I took in Compass from a shelter the winter after my
  father died; I named him for the only tool I trusted that year
    · this happened because of: (2019-04-11) My father died of a stroke in the
      spring; I drove to Rutland through the night and arrived too late
```

The model is handed the causal bridge in English (`caused_by` never reaches it as
a field name). It verbalizes the relation; it does not build one.

**Exit criteria met:** no module outside `llm/` imports a provider; the context
builder is tested against fakes with no model running; two live smoke tests run
against Ollama and skip when it is unavailable, so the suite stays hermetic.

**Decisions.** `LLMClient` is a protocol, not a base class, so a test double needs
no provider and no inheritance — the same reasoning as `MemorySource`. `ChatRole`
(system/user/assistant) is deliberately *not* `models.conversation.Role`
(user/persona): one is a provider's vocabulary, the other the domain's, and
collapsing them would leak the model's shape into the persona. Callers construct a
client through `llm.build_client`, so naming even the *adapter module* outside
`llm/` is forbidden — the invariant covers `personasim.llm.ollama`, not just
`ollama`. Thinking is disabled by default (`Settings.llm_thinking`): the persona
has nothing to deliberate about, since what she recalls was decided by retrieval
and who she is was decided by identity. The adapter still strips any `<think>`
block, including one split across stream chunks, because a scratchpad reaching the
user would arrive in her voice. Default temperature dropped 0.7 → 0.4: every degree
of creative freedom the model is given, it spends inventing biography.

**Problems the gate caught — none of them by the tests.** Driving the persona by
hand, as in Stage 5, is what exposed all four. The tests were written afterwards.

*She invented a pet.* Asked "what was your first pet called?", she answered
"a tabby cat named Whiskers". Nothing in memory says it. The rules said "never
invent", but a question can *smuggle in a premise*, and the model accepted it to be
helpful. The prompt now refuses premises outright, and the memory block is framed
as a boundary ("everything you can recall … in full") rather than as notes, which
a model reads as an invitation to fill the gaps.

*She invented a mother.* Asked how her mother took her father's death, she produced
her silence and her sleeplessness — a whole person, conjured by the presupposition
in a question. No prompt rule reliably stops this, because the model has no way to
know the cast is closed. It is now told: `render_cast` names every person in
relationship memory on every turn and asserts there is no one else. That is a true
statement about the persona — relationship memory is exhaustive by construction —
and it is data, not prose.

*She gave her own father away.* Handed her father's memory beside her wife's family
home, she called Robert "Maya's father". The seed's summaries were third person,
and **"her" did not mean the same person twice**: "her parents' orchard" is Maya's,
"her father" is Elena's. A human reader would misread it too. Summaries are now
written in the first person with every person named — an ambiguous referent in the
ground truth is an authoring bug, not something a prompt can repair.

*She had a catchphrase.* `speech_style` contained an illustrative quote — *will
describe a hard year as "a bit of a stretch"* — and the model reached for that exact
phrase in every answer, calling her dog and her wedding day "a bit of a stretch".
Describe the manner; never quote the words.

**A known limitation.** The persona still occasionally embroiders: refusing to
place a mother, she added that her father "was a quiet man" who "never spoke to her
about the things that mattered". The refusal holds; the trailing clause is
invention. Prompting has taken this as far as it goes. The architectural guarantee
is not that the model never says something unfounded — it is that nothing unfounded
becomes a *memory*, which is Stage 7's memory formation, and which is why its exit
criterion is that a hallucinated biographical claim forms none.

---

### Stage 7 — Conversation loop and memory formation ✅

`conversation/loop.py` sequences the modules every earlier stage built alone.
`memory/formation/` is the new thinking, and the reason the stage exists.

**Formation reads the user's message. It never reads the persona's reply.**

That is the whole design. Stage 6 established that no prompt reliably stops a
model inventing biography under a leading question. So the model's output is not
an *input* to formation — not filtered, not scored, not checked, simply never
offered. A hallucinated claim cannot become a memory because there is no code path
by which it could, which is a stronger guarantee than any instruction, and the
same kind of guarantee that makes working memory volatile. An invariant test
forbids `memory/formation/` from importing the LLM at all, so a later refactor
cannot quietly hand the reply back.

Extraction is rule-based for the reason retrieval is: a model deciding what was
disclosed would decide differently on two hearings of the same sentence, and a
memory formed by a coin toss is worse than no memory. The rules trade recall for
precision on purpose — each is anchored to a disclosure verb ("my name is", "I
live in"), so a passing remark cannot become a fact. Plenty of real disclosures
slip through. A missed fact is a gap the user can repeat; an invented one is a lie
the persona repeats for the rest of its life.

**Exit criteria met:** a scripted multi-turn conversation with a fake LLM forms
exactly the expected memories; a fake instructed to invent a sister in Paris forms
**none**, and nothing reaches the database. A fact disclosed in one session is
recalled in the next.

**Decisions.** `Conversation` is a context manager, so the session is closed and
working memory discarded even if a turn raises — the one guarantee working memory
could not make for itself: it can be *unable* to persist, but it cannot make a
caller remember to tear it down. Retrieval runs against the persona held in
memory, and formation appends to it, so a fact disclosed on turn two is
retrievable on turn three with no database round trip and no second source of
truth. A turn and the memories it formed are written in one unit of work: the
session log cannot claim a turn whose memory was lost. Consolidation only touches
*unlinked* semantic memories, so it can never supersede part of the narrative
spine and can never leave a dangling link — merging two authored memories would be
editing a life, not tidying it.

**The consistency suite found what four stages of driving had not.** Written last,
against failures already met, it failed on its first run — and the failures were not
prose, they were *unreachable memories*:

- "What city are you in?" reached nothing: the `city` memory had no `city` keyword.
- "Where did you **grow** up?" reached nothing: the hometown memory was keyworded
  `grew up`, one string, and retrieval matches literally.
- **"Where are you from?" tokenized to nothing at all** — `from` was a stopword, so
  the stop list silently deleted the entire subject of the question. The stopword
  docstring warns about exactly this; the list did it anyway.
- "Any siblings?" reached nothing. Nor did "Do you have a sister?", which should
  reach the memory that says she has a *brother* — a question about a relation she
  does not have must still reach the memory that says so, or she has nothing to
  answer from.

Each is the same failure: **remembered perfectly, and unreachable forever.** It is
the quietest way this system can fail, and it took a suite to see it.

**And one architectural hole, which the live half found.** The persona and the
caregiver both have a city, a job, a family, and both are in memory. "Where do I
live?" and "Where do you live?" retrieve on the same keyword and reach both — and it
was the *model* deciding which to answer with. It decided wrongly, and
inconsistently: it answered "Where do I live?" correctly, then "Do you remember
where I live?" with *"I don't have a memory of where you live"*, and "What do I do
for a living?" with *"I am a cartographer"*.

That is not a decision a model may make. `retrieval/scope.py` now settles it from
pronouns, deterministically: look at what follows the question word, so that in "Do
you remember where **I** live?" the "you" is only the address. A question scoped to
the caregiver is **filtered**, not re-ranked — it must not be handed her life at
all, or the model reaches for the memory it finds more interesting. The mirror rule
is tempting and wrong: "what do you know about Chicago?" asks what she *knows*, and
filtering out what she was told made her forget a fact given one turn earlier.

**Problems the gate caught — again, none of them by the tests.** Driving a live
two-session conversation is what exposed every one. The tests were written after.

*She could not recall a word of it.* Session one formed "Sam lives in Chicago"
perfectly and persisted it. Session two: "I don't recall being told where you
live." The memory was keyworded `chicago, sam, city` — and "where do I live?"
tokenizes to `live`. Stored, and unfindable. Formed memories now carry the
vocabulary a *question* about them would arrive as, chosen narrowly, because the
Stage 5 lesson still binds: "for a living" belongs to occupation, or every question
about someone's job drags their address along with it.

*She nearly moved to Chicago.* A semantic memory whose subject is not `self` is a
fact about somebody else. Filed under the context builder's "Things you know about
yourself", "Sam lives in Chicago" is an instruction to the persona to live in
Chicago. Sections are now chosen by *subject*, not only by type.

*Stage 6's best idea turned on us.* Even with keywords fixed, she still refused —
because the closed cast said "The people in your life are Maya, Robert, Tom, Priya,
Dan. **There is no one else.**" Sam was not on the list. The very mechanism that
stopped her inventing a mother was making her deny the person she was talking to.
Two changes: being told a name is not learning a fact, it is *meeting* someone, so
a name now forms a **relationship** memory and the speaker joins the cast; and the
"no one else" claim is scoped to her life — a relative, a friend, a colleague —
rather than to everyone in the world. She still denies the sister she does not have.

*A finished conversation forgot which session it was.* `session_id` was read from
working memory, and `discard()` mints a fresh one — right for the RAM, wrong for
the conversation, and it made the crash-safety test pass vacuously. The session id
is now held by the `Conversation`.

---

### Stage 8 — CLI, consistency tests, documentation ✅

`persona seed --force` · `persona chat --trace` · `persona trace [--list]`, the
consistency suite, and a rewritten `architecture.md`.

The stage was deliberately run **backwards**: `persona chat` was built first as an
*instrument*, and a long adversarial multi-session conversation was driven through
it before a single consistency test was written. The reason is the pattern below,
which by Stage 7 was too consistent to keep ignoring — writing the tests first
means writing them against a model of how the persona fails, and that model has
been wrong every single time.

It found five bugs. The suite was green throughout.

**A question created a memory.** The worst defect this project has produced. Asked
*"Do I have any kids?"*, she formed the memory **"Sam has any kids"** — the
question contains the words "I have … kids", and extraction took them at face
value. A man asking whether he had children was recorded as having them. Every
disclosure verb appears intact inside the question that asks about it, so questions
are now dropped *before* the patterns run. Asking is not telling.

**She did not listen.** Told *"I'm Sam"*, *"I'm a nurse"*, *"I grew up in Vermont"*,
*"I've got two kids"* — four consecutive disclosures — she formed **nothing**, and
ended the session remembering exactly what she started with. She greeted Sam by
name and then forgot he existed. Extraction recognised only the most formal
phrasing of each thing ("my name is", "I work as", "I'm from"). The precision that
keeps invention out was never the *formality* of the phrasing — it is the
disclosure anchor and the short-noun-phrase rule, and both survive recognising the
ordinary way of saying a thing. A persona who does not listen is a worse failure
than one who over-hears, because it is the one the user notices.

**She answered the wrong person's question.** Asked *"what do I do for a living?"*
she replied *"I'm a cartographer"* — reading the user's "I" as her own, while
holding "Sam works as nurse" in the very context she had been handed. Her memories
speak of Sam in the third person, the question says "I", and **nothing joined the
two**. The prompt now says who "I" is. It fixed both directions at once: "what do I
do?" → "You're a nurse", "what do you do?" → "I'm a cartographer".

**A memory stored and unfindable, again.** "Sam is from Vermont", keyworded `grew`,
could not answer *"where did I **grow** up?"* — retrieval matches literally, and
there is no stemmer. A keyword must carry every form a question might use.

**The speaker was modelled as a name, and should never have been.** The system has
exactly two people in it — the persona and the caregiver — and the caregiver is a
*role*, not an identity: they say "I'm the nurse", never "I'm Aswin". Modelling the
speaker as a name to be learned created a bug that then had to be fixed: a fact
disclosed *before* the name was stranded on an anonymous subject forever, since
nothing re-attributed it, consolidation could not merge it, and no keyword could
reach it. Fixing the speaker to a single `CAREGIVER` subject deletes that bug
instead of handling it — there is no anonymous phase to be stranded in. Name
extraction, introductions, speaker tracking and re-attribution were all removed.

**She swapped places with the caregiver.** Told she was speaking to "your caregiver
— the person who looks after you", she inverted the roles outright: announced "I am
your caregiver", answered "where do I live?" with her *own* Boston address, and
answered "where do you live?" with the caregiver's Chicago. A healthy woman of
thirty-eight has nobody who looks after her, and handed that contradiction the
model resolved it by swapping the two of them. `caregiver` is the right word for the
domain and the wrong word to put in her mouth. She is now told plainly who is
speaking, in terms that do not fight her identity, and the pronouns land correctly
in both directions.

**A name did not claim what came before it.** (Fixed, then obsoleted by the change
above — kept because it is the reason the change was made.) Say "I live in Chicago" and *then*
"I'm Sam", and the city was stranded on an anonymous speaker forever. Nothing
re-attributed it; consolidation could not merge it away, because a different
subject is a different fact; and it carried no `sam` keyword, so a question about
Sam could never reach it. She had been told where Sam lived, held the memory for
good, and could not say so. A name now claims the facts already told, revising them
in place — same id, same age. Learning a name does not make it a different memory;
it makes it a memory about somebody.

**She was pedantically, correctly literal.** Even once retrieval found it, she
refused: the memory said Sam *was from* Vermont, the question asked where he *grew
up*, and she is under orders to add nothing. Being pedantic is the *right*
behaviour. Throwing away what the user actually said was the bug — formation had
reduced "I grew up in Vermont" to an attribute and lost the verb. It now phrases
the memory as it was told, exactly as the seed does.

---

`persona chat`, `persona seed`, `persona trace`.

Consistency suite: the persona is asked the same question, phrased several ways,
across separate sessions, and must not contradict itself; it must recall a fact
disclosed in an earlier session. Asserted against stored memory only.

**Exit criteria.** Full suite green; a coherent multi-session conversation against
local Ollama; the success criteria in `architecture.md` demonstrably met.

---

### Stage 9 — Web frontend with memory-trace panel ✅

`persona serve`. A gallery of persona cards; click one to talk to her. User on the
right, persona on the left, a **Download transcript** button (JSON, *this*
conversation only), and an **End conversation** button in the navbar.

Every persona message carries a folded `why?` — the memory trace: which memories
fired, with what scores, the typed link that dragged an explanatory memory in, and
what the turn *remembered*. Folded away by default; the point is that it is always
*there*, not always in the way.

**Exit criteria met:** FastAPI + uvicorn justified in `tech_stack.md`; the
orchestrator is untouched — a test forbids `web/` from importing `memory/`,
`retrieval/`, or the context builder, and a second one checks the browser decides
nothing.

**Decisions.** The card's two-line description is a new `Identity.description`,
**authored in the seed**. Deriving it from her memories would be the system writing
its own blurb; generating it would be the model writing her biography, which is the
one thing it may never do. The gallery returns a list and the layout assumes more
than one persona — Phase 3 adds them. Live conversations are held in a dict in the
serving process: the same reasoning that refused Redis for working memory, and it
stops holding the moment this runs behind more than one worker.

**No feelings.** There is nothing to show, because nothing measures them. Mood and
emotional salience are **Phase 4**. The only per-memory scalars are `importance`
(ranking) and `confidence` (certainty), and neither is affect — the Stage 8 clamp
explicitly *forbids* her narrating feelings not in a memory, because that was one of
the invention channels.

**The problem the drive caught.** Asked in the browser "What do I do for a living?",
she retrieved the caregiver's job correctly and answered **"I am a nurse."** She had
been told *whose* question it was and not *whose mouth the answer comes out of* —
two different things. The scope note now carries the form of the answer as well as
its subject: *"You are a nurse", never "I am a nurse"*. Three runs, three correct
answers.

---

### Stage 9 — original plan ⬜

A second adapter over the Stage 7 orchestrator, alongside the CLI. No changes to
memory, retrieval, or storage.

A conversation pane beside a live memory-trace panel: which memories fired, of
which type, with what score components and retrieval reason, and the typed links
behind any causal claim. This is the debugging surface Phase 2 needs most, since
impairment simulation is the study of how retrieval degrades.

Sequenced after the CLI on purpose: `persona trace` forces the trace into a
human-readable form first, keeping it an honest data structure rather than one
shaped around a UI component.

**Exit criteria.** Adds FastAPI + uvicorn, justified in `tech_stack.md`; the
orchestrator is untouched.

---

## Deviations from the original documents

| Decision | Reason |
| -------- | ------ |
| `qwen3:8b` is the *default*, not the only model | 8b is what a laptop can run. The GPU host runs `qwen3:14b-q4_K_M` — the model the architecture actually specified — and switching to it took a two-line `.env`, no code. That is the adapter interface doing exactly what it was built for. Prompt behaviour is noticeably better on 14b: 8b was the model that gave Elena a mother. |
| Python pinned to 3.12 | `>=3.12` resolved to 3.14.5; pinning makes builds deterministic. |
| Import package `personasim` | The documented tree would place packages named `memory`, `storage`, and `logging` on the global import path. Every documented folder name survives, nested. |
| PyYAML added | Seed files need a format. |
| hatchling added | Required for the `persona` console script. |
| `relationship_repo` folded into `memory_repo` | A relationship *is* a memory type; a separate repo is a second door into one table. |
| `memory/retrieval/` removed | The docs specified retrieval in two places. The engine lives in top-level `retrieval/`, since it orchestrates across all memory types and is the seam Phase 2 wraps. |

Everything on the deferred list — LangGraph, Mem0, Letta, FAISS, Sentence
Transformers, Neo4j, Qdrant, Redis, Pinecone, PostgreSQL — remains untouched.

---

## Invariants enforced by test, not convention

These live in `tests/test_invariants.py`. Each was verified to fail when
deliberately violated, so none is vacuous.

1. No Phase 2 vocabulary anywhere in source — not even as a disabled flag.
2. `models/` performs no I/O.
3. `storage/` imports no reasoning layer and contains no ranking logic.
4. No ORM row or `sqlalchemy` import escapes `storage/`.
5. Working memory cannot reach the database.
6. `retrieval/` never consults the LLM, so recall is reproducible.
7. Nothing outside `llm/` imports a provider — neither `ollama` nor the adapter
   module that wraps it. Construct a client with `llm.build_client`.
8. `llm/` reaches neither storage nor working memory. It renders identity, memories
   and a trace into a prompt; it cannot make what a model says into a memory.
9. `memory/formation/` never consults the LLM. What is remembered is decided by
   rule, and a formation step that could *call* a model is one that could be handed
   the model's own output — which is exactly how an invented biography would become
   a permanent memory.

---

## Open issues

**None.** Every issue raised in Stages 5–8 is closed. The five that blocked Stage 8:

1. ~~She embroiders~~ — clamped (prompt, temperature, participant roles, and the
   un-nesting of connected memories).
2. ~~"I don't have a mother"~~ — Ruth Marsh authored into the seed, with the cello
   as her causal thread.
3. ~~`persona trace` does not exist~~ — built. `--list` finds a session, and a replay
   states that it is history, not current memory.
4. ~~The consistency suite does not exist~~ — built, and it immediately earned its
   keep (below).
5. ~~`architecture.md` is stale~~ — rewritten: who is in the room, what the model may
   never decide, and how formation is structurally unable to remember a lie.

---

## Open decisions

**Re-seeding silently skipped edited memories. Resolved — `persona seed --force`.**

Seeding is idempotent by memory id, and ids derive from the seed *key*, not the
content, so an edited summary resolved to a memory that already existed and was
skipped. The edit never landed, and the CLI said *"already seeded; nothing to do"*
while discarding it. Stage 6 had just rewritten all 27 of Elena's summaries.

Settled by putting the two positions in opposition — reconcile-by-default against
leave-it-alone — and the argument turned on a single question: **how do you tell an
authored memory from one the persona learned?** The database holds both, and there
is no column that says which is which.

The answer is that no column is needed. A seeded memory's id is
`uuid5(persona_id:key)`, so it is *derivable from the seed file*: "authored" is
exactly "in the set this file resolves", and a formed memory's random uuid4 is not
in that set and cannot be. `--force` therefore writes only what the seed names, and
is structurally incapable of touching what the persona learned. That is the same
kind of guarantee as "formation never sees the model's reply" — a property of the
shape of the thing, not a filter that could be misconfigured. It is now enforced by
test rather than left as a coincidence of two code paths.

Rejected, with reasons: an `origin`/`source` column (no consumer in retrieval,
formation, or the context builder — a column only a CLI flag reads is not a domain
concept, and it would break the standing promise that Phase 2 needs no migration);
content-hashed ids (an edit would change the id and dangle every link in the
narrative spine — that is the bug, not the fix); and cascading deletion of memories
removed from a seed (unguarded, and able to dangle a link the spine depends on).

What shipped: `--force` rewrites the memories the seed names and nothing else; a
plain re-seed *counts and reports* divergence rather than swallowing it, so an
operator is told the file and the database disagree; and `created_at` is carried
forward across a rewrite, because `MemoryBase` stamps it at construction and a
naive comparison would otherwise mark every memory edited on every run — and
silently reset the age of memories that Phase 5 is built on having.

**Editing a seed after conversations have happened rewrites history.** `--force` is
a development convenience, not a migration tool. The supported operation for a
persona that has already lived is still delete-and-re-seed. A session's turns are
logged with the trace that produced them, summaries and all, so rewriting a summary
underneath leaves those traces describing memory text that no longer exists. That
is defensible for a *log* — it records what was true then — but it is a cost, not a
freebie, and `persona trace` (Stage 8) is where it will first be felt.

**A seed may not contradict itself.** Two semantic memories sharing a
(subject, attribute) are now refused at authoring time, naming both keys. This
closes a real hole: session-end consolidation reduces each duplicated
(subject, attribute) to its most recent statement and is documented above as never
touching the authored life — but it checks only that a memory is unlinked, and
*four* of Elena's authored facts qualify. Two authored facts sharing a pair would
have had one quietly deleted at the end of a conversation. The guarantee was true
by luck; it is now true by construction, since the duplicate cannot be authored.

**Elena's marriage is an authoring choice, not an architectural one.** She is
married to Maya Okonkwo, a woman. `RelationshipMemory` stores a free-text
`relation`, so nothing in the system depends on it. Maya is threaded through four
memories (`maya`, `met_maya`, `wedding`, and the wedding's `involves` edges), so
changing it means touching all of them consistently — the `Persona` validator will
catch an inconsistent edit.

---

## Seed authoring rules

Every one of these was learned by driving the persona and watching her get it
wrong. The seed file is the persona's ground truth; a defect here cannot be fixed
downstream, and each rule below is one the model *will* exploit if broken.

1. **Write summaries in the first person, and name every person.** "Her" does not
   reliably mean the same person twice. Third-person summaries made Elena hand her
   own father to her wife's family.
2. **Describe the manner of speech; never quote it.** A sample phrase in
   `speech_style` becomes a catchphrase the model repeats everywhere.
3. **Keywords are load-bearing; a generic one is a spurious memory waiting to
   fire.** `first` matched "first pet", "first job", "first time" (Stage 5).
4. **State what is true, including the negative space you care about.** Elena's dog
   memory says he "is the only pet I have ever had", so a question about her *first*
   pet has a true answer instead of an invited invention.
5. **Keywords must include what a *question* sounds like, not only what the memory
   is about.** Stage 7's version of rule 3: a memory keyworded `chicago, sam, city`
   cannot answer "where do I live?", which tokenizes to `live`. Remembered
   perfectly, unfindable forever.
6. **A fact may be stated once.** Two semantic memories sharing a
   (subject, attribute) are refused at load. A persona cannot both live in Boston
   and live in Denver, and consolidation would have silently deleted one of them.
7. **Editing a seed after conversations have happened rewrites history.** Use
   `persona seed --force` during authoring; for a persona that has already lived,
   delete the database and re-seed.
8. **Never say a persona digresses.** A `speech_style` of "drifts into talk of
   timber" is an *instruction to digress* — and with nothing true to digress with,
   the model invents. Marcus answered a question about his mother with a long line
   of Welsh makers and the sound of her voice, none of it authored. Made plain, he
   said only what he knew. Describe the manner; do not license elaboration.

**`persona new` asks all eight of these. `persona check` finds what you missed.**
Neither is optional politeness: every rule above is a defect that shipped, and was
found weeks later by talking to a persona and watching her deny her own dog.

---

## Where to pick up

**Phase 1 is complete.** Stage 9 — the web frontend with a memory-trace panel — is
the only stage left, and it is a *second adapter over work that already exists*: a
conversation pane beside a live trace panel, showing which memories fired, of which
type, with what score components and retrieval reason, and the typed links behind
any causal claim. `Conversation` and `render_session` already produce everything it
needs. **The orchestrator must not change.** Adds FastAPI + uvicorn, to be justified
in `tech_stack.md`.

Before starting it, read `CLAUDE.md` — the stage gate and *Who is in the room* are
not optional, and neither is this:

**Driving beats testing, and it is not close.** Every real defect in Stages 5–8 was
found by talking to the persona; the suite was green through all of them. She
invented a pet, a mother, an umbrella at a wedding. She formed a memory *from a
question*. She heard four disclosures in a row and remembered none. She answered "I'm
a cartographer" when asked what the *caregiver* did for a living. She stored a memory
keyworded `grew` that "where did you **grow** up?" could never reach.

Tests encode the failures you already imagined. She fails in ways you did not. So:
build the instrument, go looking for trouble, and write the tests *after*, against
what actually broke.
