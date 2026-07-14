# Sprint 1 — CDR 0.5: architectural design

Ground truth: `docs/disease_profiles/CDR05.md`. This document does not reinterpret
it; it maps each behaviour in it onto the smallest set of additions to the existing
architecture.

**Everything here is additive.** No module in `retrieval/`, `storage/`,
`memory/formation/`, `memory/working/`, `conversation/`, or `llm/` changes its
behaviour when no profile is loaded. The database schema does not change.

---

## The central idea

CDR 0.5 is, in this architecture, **not a new kind of memory. It is a gate in front
of an existing one.**

Phase 1 already computes, for every memory it retrieves, exactly the two numbers a
recall gate needs:

- **How well the question reached this memory** — `ScoreComponents.keyword_overlap`,
  already in the trace.
- **How old the memory is** — `created_at` on every memory, `occurred_on` on
  episodes.

So impairment does not need to invent a signal. It needs to *threshold* one:

> **A recent memory is recalled only when the question cues it strongly enough.
> A remote memory is always recalled.**

That single rule produces four of the clinical behaviours at once, and it explains
why the design is as small as it is. Everything below is either that rule, its data,
or the things it cannot reach (speech and orientation, which never touch memory).

---

## What gets added

Five things. Four are new files in one new package; one is an additive field on an
existing model.

| # | Addition | Extends | Determinism |
|---|----------|---------|-------------|
| 1 | `impairment/profile.py` + `data/profiles/*.yaml` | nothing — new data | Data |
| 2 | `impairment/recall.py` | `retrieval/` (wraps, does not touch) | Deterministic |
| 3 | `impairment/engine.py` | `RetrievalEngine` (same interface) | Deterministic |
| 4 | `impairment/voice.py` | `llm/context_builder.py` (adds prompt fragments) | Deterministic gating, generative prose |
| 5 | `MemoryTrace.withheld`, `RetrievedMemory.detail_withheld` | `models/trace.py` (new fields, defaulted) | Data |

Plus wiring: `Conversation` accepts a profile (defaults to healthy), and the CLI
grows `--profile`.

---

## 1. The cognitive profile — severity is data, not code

### Why

Without this, "CDR 0.5" becomes a scattering of `if stage == 0.5` through the
retrieval engine, and CDR 1 becomes a second scattering. The profile is what makes
Sprint 2B a *YAML file*, not a refactor.

### What

`data/profiles/cdr05.yaml`:

```yaml
name: cdr05
label: "CDR 0.5 — very mild"

recall:
  recent_window_days: 90      # newer than this is "recent" and therefore gateable
  cue_threshold: 0.55         # recent memory needs this much keyword_overlap to surface
  detail_threshold: 0.80      # above cue, below this → gist recalled, specifics lost

orientation:
  day_and_date: uncertain     # hedges the weekday and day-of-month
  month_and_year: confident   # still knows these
  place: confident
  person: confident

speech:
  word_finding_every_n_turns: 4   # 0 disables
  long_question_clauses: 3        # a question with more parts than this may be lost

insight: true                      # she knows she is forgetful, and may say so
```

`healthy.yaml` is the same file with `recent_window_days: 0`,
`word_finding_every_n_turns: 0`, everything `confident`, `insight: false`. **A
healthy profile must be a no-op by construction** — not a special case in the code,
but a profile whose thresholds gate nothing. That is what makes the regression
argument in §7 possible.

Loaded by a Pydantic model (`CognitiveProfile`) exactly as personas are loaded from
seed YAML. Numbers are placeholders; they get tuned by driving, not by argument.

### Trade-off

A clinically richer profile would model each CDR domain (memory, orientation,
judgement, community affairs, home/hobbies, personal care) as its own score, since
that is literally how the CDR instrument works. **I recommend against it for Sprint
1.** Four of the six boxes have no mechanism behind them yet — judgement, community
affairs and personal care are not conversational behaviours we can produce, and a
profile field with no consumer is a lie in a config file. Add the domains in the
sprint that gives them mechanisms. What we have here is the subset the conversation
can actually express.

---

## 2. `impairment/recall.py` — the recall gate

### Why it is needed

`CDR05.md` §"Recent Episodic Memory" is the most-affected domain: forget a recent
conversation, lose *some* details of a recent event, remember the event but not all
specifics, recall more after gentle cueing. All four are the same mechanism seen
from different angles.

### Which module it extends

None — it is a **pure function over a `MemoryTrace`**. It imports the trace model
and the profile, and nothing else. It does not import `retrieval/`, and `retrieval/`
does not import it. That is deliberate: it means the gate can be unit-tested with a
hand-built trace and no database, no engine and no LLM.

```python
def apply(trace: MemoryTrace, profile: CognitiveProfile, now: datetime) -> MemoryTrace
```

### Deterministic or probabilistic — and why

**Deterministic. Emphatically.**

The temptation is `if random() > 0.9: forget`, and it is wrong three times over:

1. **It is the wrong disease.** A coin-flip means the same question gets a different
   answer each time it is asked. That is not mild amnestic impairment; that is
   fluctuating confusion, which is CDR 2+ and is explicitly listed under *Behaviours
   to Avoid*. Real CDR 0.5 is **reliably** bad at the same things: the memory that
   was not laid down is not there on Tuesday either.
2. **It destroys the trace.** "Why did she forget that?" must have an answer better
   than "the dice said so". `CDR05.md` is a document we will eventually validate
   against clinically, and a non-reproducible simulator cannot be validated at all.
3. **It breaks the one guarantee we most need.** *"The persona remains the same
   person."* Randomness makes her a different person every session.

So "occasionally" is **not** produced by an RNG. It emerges from two real signals:

- **Most questions are not about recent events.** Ask about her wedding, her
  children, her career — the gate never fires, because those memories are decades
  old. Ask what you talked about ten minutes ago and it does. The *appearance* of
  intermittency comes from the distribution of questions, not from noise.
- **Weakly-cued questions fail where strongly-cued ones succeed.** "Do you remember
  what I told you?" carries almost no keyword signal. "Do you remember what I said
  about my daughter's operation?" carries a lot. Same memory, different outcome —
  and *that is cueing*, which the spec explicitly requires.

If, after driving her, the behaviour reads as too mechanical, the escape hatch is a
**seeded** jitter — `Random(hash(session_id, memory_id))` — which is still
reproducible. Ship without it; add it only if the drive demands it.

### The rule

For each directly-matched memory in the trace:

```
recent   = the memory is conversation-shaped AND its anchor is inside recent_window_days
cue      = components.keyword_overlap      # already computed by Phase 1 ranking

if not recent:                    → recalled in full          (remote memory preserved)
elif cue >= detail_threshold:     → recalled in full          (strong cue)
elif cue >= cue_threshold:        → recalled, detail withheld (gist, no specifics)
else:                             → withheld                  (not recalled)
```

**"Recent" is not `now - created_at`, and this matters.** An authored memory's
`created_at` is the *seed time* — in a freshly seeded database "Lives in Boston" is
five minutes old, and a naive age check would gate it and make her forget where she
lives. Phase 4 spins up fresh patients, so the freshly-seeded case is the main case.
Only **conversation-shaped** memories are gateable:

- **Episodic**, anchored on `occurred_on` (falling back to `created_at`) — a recent
  *experience* is recent whenever it happened, not whenever it was written.
- **Semantic with `subject != "self"`** — a disclosed fact, anchored on
  `created_at`, which for a disclosure *is* the moment of hearing it. This is the
  same reading the retrieval engine's own `_is_disclosed` already commits to.

Authored self-facts and relationship memories are her *life*: never recent, never
gated, at any age. That is the clinical spec's "identity and remote memory
preserved" made structural rather than probabilistic.

**Expansions follow their parent.** A link-expanded memory was never asked for; it
exists to explain the memory it hangs from. If its parent is withheld or reduced to
gist, the expansion is withheld too — otherwise `_partition` in the context builder
would render the orphan as a standalone recollection, speaking a memory that was
only retrieved to explain one she failed to recall.

A withheld memory is **not deleted from the trace.** It moves to `trace.withheld`,
with the reason. This is the difference between an explanation and a hole.

The gate needs the `MemorySource` alongside the trace (ages and subjects live on
memories, not on trace entries). It stays deterministic and I/O-free — the source
it is handed is the same in-memory `PersonaMemorySource` the engine uses.

### Data flow

Unchanged, with one insertion:

```
User message → Working Memory → RetrievalEngine.retrieve()   ← Phase 1, untouched
                                        ↓ MemoryTrace
                              recall.apply(trace, profile)    ← NEW, pure
                                        ↓ MemoryTrace (some retrieved → withheld)
                              Context Builder → LLM → Response
                                        ↓
                              Memory Formation ← still reads the caregiver's text only
```

Formation is downstream of nothing here. **The gate cannot reach it**, which is what
keeps the Phase 1 guarantee intact: an impaired persona still cannot remember
something she made up, because impairment operates on *recall*, never on *storage*.
Nothing is forgotten from the database. She has the memory; she cannot reach it.
That is also clinically right — CDR 0.5 is a retrieval deficit, not an erasure.

### Which clinical items it satisfies

| `CDR05.md` item | How |
|---|---|
| "Forget a recent conversation" | Facts disclosed last session are young; a vague question fails to cue them |
| "Lose some details of a recent event" | `detail_threshold` band: gist survives, specifics do not |
| "Remember the overall event but not all specifics" | Same band — `detail_withheld` renders the summary without date/place/participants |
| "Recall additional details after gentle cueing" | A more specific question raises `keyword_overlap` past the threshold. Cueing is not simulated; it is *literally what the mechanism does* |
| "Remote memories recalled with high confidence" | `recent_window_days` — the wedding is never gateable |
| Preserved identity, family, home, occupation | Identity is injected, not retrieved. The gate never sees it |

---

## 3. `impairment/engine.py` — the wrapper

### Why

Something must own "retrieve, then gate", and it must not be `RetrievalEngine`
itself. `ImpairedRetrievalEngine` has the same single method, so `Conversation` does
not care which one it holds:

```python
class ImpairedRetrievalEngine:
    def __init__(self, inner: RetrievalEngine, profile: CognitiveProfile) -> None: ...
    def retrieve(self, query: str) -> MemoryTrace:
        return recall.apply(self._inner.retrieve(query), self._profile, now())
```

Nine lines. That is the whole "impairment layer" as far as retrieval is concerned,
and it is the strongest possible statement that Phase 1 was built with the right
seam: the docstring on `retrieval/engine.py` already predicted this class.

### Wiring

`Conversation.__init__` gains `profile: CognitiveProfile = HEALTHY`, and builds the
wrapper only when the profile gates something. Default-healthy means every existing
call site, test and the entire Phase 1 suite are unaffected without being touched.

---

## ⚠ The landmine: improvisation must not fill a suppressed memory

This is the one place where a naive implementation silently violates a Phase 1
guarantee, and it needs to be stated loudly.

`Conversation._improvise` fires when **`trace.is_empty`**. It then invents an
everyday value and *writes it to memory permanently*.

If the gate suppresses every memory for a question, the trace becomes empty — and
improvisation fires. The persona would then **invent a fact she actually has**, and
believe it forever. A forgotten lunch becomes a *fabricated* lunch, written to the
database. That is confabulation, it is on the *Behaviours to Avoid* list, and it
would be permanent.

**The fix is structural, and it is why `withheld` exists as a field rather than the
gate just dropping entries.** A trace with suppressed memories is *not* silent:

```python
@property
def memory_is_silent(self) -> bool:
    return not self.retrieved and not self.withheld   # ← withheld blocks improvisation
```

`_improvise` guards on this new property. `is_empty` itself is left with its Phase 1
meaning ("no memory supported this response") untouched — the context builder keys
its no-memory prose off it, and changing its semantics would silently alter which
prompt path an all-withheld turn takes. Two different questions get two different
properties.

"Nothing was found" and "something was found and could not be reached" are different
states, and only the first may improvise. Retrieval failure must produce *"it doesn't
come to mind"* — never an invention. This is a regression test in its own right, and
it is the highest-value test in the sprint.

---

## 4. `impairment/voice.py` — word-finding, insight, attention, orientation

Three of the clinical behaviours have nothing to do with memory: they are properties
of *speech*. They belong at the prompt seam, not the retrieval seam.

### 4a. Word-finding — the one honest compromise

`CDR05.md`: occasional pauses, hesitation, circumlocution; **intermittent**, never
aphasic.

This cannot be made deterministic, because it is a property of generated prose. Two
options:

- **(a) Prompt instruction.** Simple, natural-sounding, but frequency is a *hope*.
- **(b) Post-process the reply** — deterministically find a noun and replace it with
  a circumlocution. Frequency is exact, and the output reads like a machine did it.
  It also means the persona's words are no longer the model's words, which muddies
  every other behaviour we would be debugging.

**Recommend (a), with the frequency made deterministic at the instruction level.**
The prompt fragment is injected only on turns where `turn_index % n == 0`. So *how
often* she gropes for a word is exact and testable (we assert the fragment's presence,
not the model's prose); *how* she does it is left to the model, which is what the
model is for.

One hard constraint from Phase 1, learned the hard way (seed authoring rule 2):
**describe the manner, never quote it.** A sample phrase in a prompt becomes a
catchphrase the model repeats every turn. So the fragment says *that* she loses a
word and talks around it — it does not hand her "that thing… the… the kettle" to
recite.

Risk, stated plainly: the model may still overdo it. This is a **drive-and-tune**
behaviour, and the acceptance criterion is measured on a transcript, not asserted in
a unit test.

### 4b. Insight — tied to failure, not sprinkled

`CDR05.md` requires preserved insight, and it is the feature most likely to be
mistaken for a bug and "fixed" by someone later. It is a **clinical requirement**:
awareness of decline is what distinguishes CDR 0.5 from later stages.

The elegant version is not a random "I've been forgetful lately" — it is insight
**at the moment of failure**. When the gate withholds a memory, the context builder
already emits a no-memory block. Under an insightful profile, that block additionally
tells her that she has been forgetting things lately and may say so.

So insight is emitted *exactly when it is true* — which is the same discipline as the
memory trace, applied to speech.

### 4c. Attention — deterministic, from the input

`CDR05.md`: may lose track of lengthy questions, ask for repetition, benefit from
simplified questions.

Trigger deterministically on the **caregiver's message**, which is data we have:
count clauses/questions; above `long_question_clauses`, inject a fragment permitting
her to ask for it to be repeated or broken up. No randomness, testable without a
model, and it fails in exactly the situation the spec describes. Being a function of
the caregiver's own phrasing, it also *rewards good caregiver technique* — which is
the entire point of a training simulator.

### 4d. Orientation — degrade `render_now()`, touch no memory

`render_now()` already injects the date as a *told fact*, and its docstring already
names itself as the Phase 2 seam. Under a profile, it renders the month and year
confidently, the place and person confidently, and hedges the weekday and exact date.

"Occasionally uncertain" needs no randomness: **it only shows when she is asked**, and
caregivers only ask occasionally. The uncertainty is constant; its *visibility* is
naturally intermittent. This is the cleanest example of the design principle — the
appearance of "sometimes" falls out of the conversation, not out of an RNG.

No memory is touched, no storage is touched, and Phase 1's guarantee that a clock is
right by construction is preserved: the *clock* is still right, and the *persona's
access to it* is what is degraded.

---

## 5. Trace additions — explainability is not optional

```python
class WithheldMemory(BaseModel):
    memory_id: MemoryId
    summary: str          # for the debugger, never for the prompt
    cue_strength: float
    threshold: float
    age_days: int
    reason: str           # "recent (12d) and weakly cued (0.31 < 0.55)"

class MemoryTrace(BaseModel):
    ...
    withheld: list[WithheldMemory] = Field(default_factory=list)   # additive, defaults empty
```

`RetrievedMemory` gains `detail_withheld: bool = False`.

**No migration.** `session_turns.trace` is a JSON column and nothing queries into it
(`storage/schemas/tables.py:124`). New fields with defaults deserialise old rows
cleanly. This is the Stage 2 "no schema migration for Phase 2" promise being cashed
in exactly as designed.

The web trace panel and `persona trace` gain a "withheld" section. **A memory that
was not recalled is the single most important thing the trace can show**, because it
is what a caregiver-trainee just experienced as a symptom — and in Phase 3, it is
precisely the evidence the scoring report is built from.

---

## 6. What is deliberately NOT built

Held back, with reasons — not because they are hard, but because they are not
*Sprint 1*:

- **Repetition** ("she may ask the same thing twice"). It should **emerge** from the
  recall gate — she doesn't recall having asked — and building a dedicated repetition
  engine before checking whether it emerges is how you end up with two mechanisms
  fighting. Observe it in the drive; build it in 2B if it did not appear.
- **Per-domain CDR scoring** (judgement, community affairs, personal care) — no
  conversational mechanism yet. §1.
- **Progression, medication, sundowning, agitation, emotional dynamics** — later
  phases, and none is in `CDR05.md`.
- **Confabulation** — explicitly on the *Behaviours to Avoid* list, and structurally
  impossible anyway (formation never sees the model's output). The one route to it is
  the improvisation landmine above, which is closed.

---

## 7. Testing

### Unit — no LLM, no database

`recall.apply` is a pure function, so the entire clinical core is testable in
isolation:

- A remote memory (occurred 1994) with a weak cue → **recalled**.
- A recent memory (created 3 days ago) with a weak cue → **withheld**, with a reason.
- The same recent memory with a strong cue → **recalled**. *This is the cueing test.*
- A recent memory cued in the middle band → recalled with `detail_withheld=True`.
- `healthy.yaml` → the returned trace is **equal to the input trace**. Not "similar":
  equal.
- Profile loading, validation, and rejection of an out-of-range threshold.
- `voice`: fragment present on turn 4 and absent on turn 5; long-question fragment
  fires at 4 clauses and not at 2; orientation renders month/year confidently and
  hedges the weekday.

### Integration — `FakeLLM`, real database

The existing conversation tests already run against a fake client; these extend that
pattern:

- **The landmine test.** A question whose memories are all withheld → improvisation
  does **not** fire → no memory is formed → she says it does not come to mind. Assert
  on `Reply.formed == []`, which is a fact about the database, not about prose.
- **Disclose-then-forget.** Tell her a fact; ask about it vaguely next session → not
  recalled, and *present in `trace.withheld`*. Ask specifically → recalled. One test,
  the whole clinical thesis.
- **Formation is unimpaired.** She fails to recall a disclosure, yet the disclosure
  is still written to the database. Forgetting is retrieval-side; the memory is *there*.
  This one test is the boundary between Phase 1 and Phase 2.
- **Trace round-trips** through the JSON column with `withheld` populated.

### Regression — the load-bearing one

> **The entire Phase 1 suite (459 tests) must pass unmodified, with the healthy
> profile wired in.**

Not a new suite — *the existing one*, untouched. If a single Phase 1 test needs
editing to accommodate Sprint 1, the design is wrong and this document is wrong.
That is the mechanical proof that the layer is a wrapper and not an edit, and it is
worth more than any test we write for the new code.

Related: invariant 1 (`test_no_phase_2_concepts_in_source`) must be **narrowed to the
healthy core**, not deleted — `impairment/` is exempt, everything else stays clean.
See Open issues in `docs/roadmap.md`.

### Driving — where the real bugs are

Every real defect in Stages 5–8 was found by talking to the persona, and none by the
tests written beforehand. So: a 15–20 minute adversarial drive, against a real model,
before this ships. Contradict her. Ask the same recent thing five ways. Ask her wedding
in the middle of failing to recall lunch. Check she never once invents.

---

## 8. Acceptance criteria

Sprint 1 is complete when **all** of the following hold:

**Mechanism (asserted by test)**

- [ ] `healthy.yaml` leaves the trace bit-for-bit identical; all 459 Phase 1 tests pass unmodified.
- [ ] A memory older than `recent_window_days` is never withheld, at any cue strength.
- [ ] A recent, weakly-cued memory is withheld — and appears in `trace.withheld` with a human-readable reason.
- [ ] The same memory is recalled when the question cues it strongly. (Cueing.)
- [ ] **A withheld memory never triggers improvisation, and never causes a memory to be formed.**
- [ ] Memory formation is unaffected by the profile: a disclosure she cannot recall is still in the database.
- [ ] No schema migration was required.
- [ ] Word-finding and long-question fragments appear on exactly the turns the profile specifies.
- [ ] Orientation hedges weekday/date; month, year, place and person remain confident.

**Behaviour (assessed on a transcript, by hand)**

- [ ] She is recognisably the same person: same humour, same values, same speech.
- [ ] Remote autobiography — wedding, children, career, childhood — is accurate and detailed.
- [ ] She occasionally gropes for a word without it disrupting fluency, and never sounds aphasic.
- [ ] She never hallucinates, never confabulates, never fails to recognise family.
- [ ] She shows insight — comments on her own forgetfulness — without being prompted to.
- [ ] **The headline criterion:** a caregiver can tell her apart from the healthy persona over 15–20 minutes, while still recognising her as the same woman. If a reader of the transcript cannot, Sprint 1 is not done, regardless of the boxes above.

**Gate**

- [ ] `make check` green; every defect found in the drive fixed *and* pinned by a test that fails without the fix.

---

## 9. Observed in the first drive (real model, cdr05.yaml)

The first scripted adversarial drive ran two sessions against `qwen3:14b-q4_K_M`.
Everything above behaved as designed, and one interaction deserves a permanent note:

**The gate can withhold a memory and the persona can still answer — within one
session — and that is correct, not a bug.** Asked "do you remember how many
daughters I have?" minutes after being told, the trace shows the memory withheld
(0d old, weakly cued), yet she answered "You have two daughters": the disclosure
was still in the working-memory transcript window, and the model read it from the
conversation in front of her. Clinically this is CDR 0.5 to the letter — holding a
conversation is preserved; it is recall *across visits* that fails, and in session
two it did fail (Portland withheld on a weak cue, recovered by "where do I live?").
The trace stays honest: it describes long-term recall, and her answer came from the
room, not from memory. When a later sprint degrades working memory, the transcript
window is the parameter — not this gate.

Word-finding compliance is the one thing a scripted drive cannot judge: the
fragment was present on schedule, but the model's short replies gave it nowhere to
show. That is exactly the behaviour §4a said would need a human transcript read,
and it stays open until the structured 15–20 minute drive.

## 10. Summary of the trade-offs taken

| Choice | Simpler option taken | What we gave up | Why it is right |
|---|---|---|---|
| Recall | Deterministic cue threshold | Stochastic forgetting | Reproducible, explainable, clinically *more* accurate — CDR 0.5 is reliably bad at the same things |
| Recency | One `recent_window_days` scalar | A decay curve over memory age | A curve has four parameters and no one can defend their values yet. A window has one, and it is the thing the clinician actually means |
| Word-finding | Prompt fragment, deterministically scheduled | Post-processing the reply | Keeps the persona's words the model's words; frequency is still exact where it matters |
| Detail loss | Suppress the rendered specifics of an episode | Model partial memories in the schema | No schema change, and the memory is intact — which is what a *retrieval* deficit means |
| Profile | Four mechanisms with four parameters | Six CDR domains | A config field with no consumer is a lie. Add domains when they have mechanisms |
| Repetition | Not built — expected to emerge | A repetition engine | Two mechanisms producing one behaviour is how you get an unmaintainable simulator |
