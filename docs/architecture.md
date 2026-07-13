# Architecture

## Vision

Build a believable digital human capable of maintaining a consistent identity and memory across conversations.

This project is NOT:

- an assistant
- an autonomous agent
- a planner

It is a conversational persona.

---

# Core Philosophy

Persona ≠ LLM

Persona =
Identity
+
Experiences
+
Memory

The LLM only verbalizes the persona.

---

# Memory Hierarchy

                Persona
                   │
        ┌──────────┼──────────┐
        │          │          │
 Identity      Working      Long-Term
               Memory        Memory

Working Memory

- Session only
- Current conversation
- Current topic
- Temporary facts

Long-Term Memory

Identity Memory

Semantic Memory

Episodic Memory

Relationship Memory

---

# Memory Flow

User Message

↓

Working Memory Updated

↓

Retrieve Relevant Memories

↓

Context Builder

↓

LLM

↓

Response

↓

Memory Formation

↓

Long-Term Memory (optional)

---

# Memory Types

Identity

Who the persona is.

Examples

- Name
- Age
- Personality
- Occupation
- Values
- Speech Style

Semantic

Facts.

Examples

- Lives in Boston
- Favorite food
- Owns a dog

Episodic

Experiences.

Examples

- Graduation
- Wedding
- Vacation

Working

Current session.

Destroyed after session ends.

---

# Memory Objects

Each memory contains

- id
- type
- created_at
- summary
- keywords
- importance
- confidence
- links

---

# Retrieval

Question

↓

Intent Detection

↓

Entity Extraction

↓

Retrieve Memories

↓

Ranking

↓

Context

↓

LLM

---

# Narrative Determinism

Retrieval is deterministic. Narrative is not.

Given the same question, retrieval returns the same memories every time. But the
connective tissue *between* memories is not stored anywhere, so the LLM writes
it — and writes it differently each session.

Ask why the persona adopted her dog. Retrieval faithfully returns two memories:
the adoption, and her father's death eight months earlier. Neither memory states
that one caused the other. That causal bridge is exactly what the model is free
to invent, and to invent inconsistently.

Worse, the guard against confabulation makes this permanent. Memory formation
refuses to persist anything the model improvised about the persona. So the
invention is never stored — and is therefore re-rolled from scratch next session.

The fix is to make the story data.

## Typed links

A link records not only *that* two memories are associated but *how*.

    caused_by         this memory happened because of the target
    led_to            this memory brought the target about
    occurred_during   this memory happened inside the span of the target
    involves          a person who took part
    concerns          this memory is about the target

The LLM is handed the relation. It verbalizes the bridge; it does not build one.

## The narrative spine

Episodic memories are dated and causally connected, so that ordering them by
`occurred_on` yields a life with no unexplained jumps. This is the persona's
ground truth. It is authored in the seed file, never generated.

A cause may not postdate its effect. The `Persona` model rejects a seed file
whose story is impossible. This is a check on the *author*, not a simulation of
temporal reasoning — a persona with an incoherent timeline is a bug, not a
symptom.

## What remains non-deterministic

Questions falling entirely outside stored memory. The persona answers naturally
and nothing is persisted, so improvised trivia may differ across sessions. This
is accepted: the spine covers the biography, so invention is confined to the
periphery.

Consequently, consistency tests assert consistency against **stored memory
only** — never against improvised detail.

---

# Memory Trace

Every response exposes internally

- Retrieved memories
- Memory types
- Retrieval reason
- Who the question was about (`self` or `caregiver`)

These traces are hidden from the user.

They exist for debugging and future cognitive simulations.

Read one back with `persona trace <persona> [--session <id>]`. A trace records the
memories **as they read at the time**, so a replay can quote a summary that has
since been rewritten (`persona seed --force`). That is correct for a log and
misleading for a memory browser, and the replay says so.

---

# Constraints

No goals.

No planning.

No task execution.

No autonomous behavior.

Only conversational responses.

---

# Who Is In The Room

Exactly two people: the persona, and the **caregiver** talking to it. Nobody else
ever speaks.

The caregiver is a **role, not an identity**. They may say "I'm the nurse" or "I'm
your doctor". They never give a name, and no code tries to learn one. So the
persona never works out *who* is speaking — it already knows, and everything the
caregiver discloses is a fact about one fixed subject.

This deletes a class of bug rather than handling it. When the speaker was a name to
be learned, a fact disclosed *before* the name was stranded on an anonymous subject
forever: nothing re-attributed it, consolidation could not merge it, and no keyword
could reach it. With a fixed subject there is no anonymous phase to be stranded in.

---

# What The Model May Never Decide

The LLM verbalizes. It does not decide. Every question below was, at some point,
left to it — and it answered inconsistently, which is the whole reason each of
these is now a rule.

| Question | Decided by | Why not the model |
| --- | --- | --- |
| What is this question about? | `retrieval/intent.py` | Recall would vary between two askings of the same question. |
| **Whose** question is it? | `retrieval/scope.py` | Handed both her job and the caregiver's, it answered "what do *I* do for a living?" with "I am a cartographer". Pronouns settle it, and pronouns are rules. |
| Which memories answer it? | `retrieval/engine.py` | Deterministic, explainable, reproducible. |
| How are two memories related? | The typed link in the seed | Otherwise it invents the causal bridge, differently each session. |
| What is worth remembering? | `memory/formation/` | See below. |

## Scope: whose question is it

The persona and the caregiver both have a city, a job, a family, and both are in
memory. "Where do I live?" and "Where do you live?" retrieve on the same keyword and
reach both memories. The rule: look at what follows the question word. In "Do you
remember where **I** live?", the "you" is only the address — the question word is
`where`, and after it comes `I`.

A question scoped to the caregiver is **filtered**, not merely re-ranked: it must not
be handed her life at all, or the model reaches for the memory it finds more
interesting. The mirror rule is tempting and wrong — "what do you know about
Chicago?" asks what she *knows*, which includes what she was told.

---

# Memory Formation

```
User Message → Working Memory → Retrieve → Context → LLM → Response
             → Memory Formation → Long-Term Memory (optional)
```

**Formation reads the caregiver's message. It never reads the persona's reply.**

That is the whole design. A model asked about a mother the persona does not have
will produce one — her silence, her sleeplessness, all of it — and no prompt
reliably stops it. So the model's output is not an *input* here: not filtered, not
scored, not checked, simply never offered. A hallucinated biography cannot become a
memory because there is no code path by which it could, which is a stronger
guarantee than any instruction, and an invariant test forbids `memory/formation/`
from importing the LLM at all.

Extraction is rule-based for the same reason retrieval is. It trades recall for
precision: every pattern is anchored to an explicit disclosure ("I'm a…", "I live
in…"), and a **question discloses nothing** — asked "do I have any kids?", an
earlier version recorded that the caregiver *did*. Asking is not telling.

Consolidation merges near-duplicate semantic memories at session end. It touches
only *unlinked* memories, so it can never supersede part of the narrative spine, and
a seed may not state one fact twice — so an authored duplicate cannot exist for it
to find.

---

# Improvisation

She has no clock and no episodic memory of today. "What did you have for breakfast?"
has no true answer, and a persona who answers it freshly each time is not a persona,
it is a random number generator with a name.

So: **improvise once, then remember.** A value is synthesised, stored as a structured
semantic memory (`confidence 0.5` — below a memory she was told, far below one she
lived), and answered from thereafter. The second asking never reaches the model.

Bounded by two rules, and they are the entire safety argument:

| Rule | Consequence |
| --- | --- |
| Only fires when retrieval returned **nothing** | An improvised detail can never contradict or overwrite an authored one. |
| `EVERYDAY` is **exhaustive** — meals, sleep, her day, the date, the clock | There is no path from here to a person, a death, a job, or a life event. The cast stays closed. |
| The date and the clock are `session_only` | What she ate is true tomorrow; what day it is, is not. They live in the persona for one conversation and are never written down. |

The model supplies a **value**, not prose. Nothing it *says* is ever read back into
memory: `memory/formation/` still cannot import the LLM.

---

# Success Criteria

The persona should

- remain internally consistent — `tests/test_consistency.py`, asserted against
  **stored memory only**
- remember past conversations — a fact disclosed in one session is recalled in the
  next
- maintain identity — identity is injected, never generated
- answer from experience — and say plainly when it cannot

And, learned the hard way:

- **never invent a person, a reason, a feeling, or a scene.** It invented a tabby
  cat named Whiskers, a mother, and an umbrella at a wedding. What stops it is a
  clamped prompt; what makes the clamp *safe to fail* is that formation never reads
  what it says.
- **be findable.** A memory keyworded `grew` cannot answer "where did you *grow*
  up?". Remembered perfectly and unreachable forever is the quietest way this system
  fails, and the consistency suite exists to catch it.
- never contradict stored memories