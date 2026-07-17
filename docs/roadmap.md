# Roadmap

**Status: Phases 1 and 2 complete, end to end — all four CDR sprints declared
complete by the owner, and every defect the five-profile comparison drive surfaced
is fixed and pinned. Phase 3 (assessment mode) is current; Sprint 3A is scoped in
`docs/design/phase3_assessment.md`.**

Phase 1 was built waterfall, because a healthy persona is one thing and either
works or does not. Phase 2 is built in **sprints, one CDR stage each**, because
"simulate Alzheimer's" is not a deliverable and cannot be tested. Four patients,
each independently shippable:

| Phase | Sprint | Scope | Status |
| ----- | ------ | ----- | ------ |
| 1 | — | Healthy human persona | ✅ Complete |
| 2 | 2A | CDR 0.5 — very mild impairment | ✅ Complete |
| 2 | 2B | CDR 1 — mild | ✅ Complete |
| 2 | 2C | CDR 2 — moderate | ✅ Complete |
| 2 | 2D | CDR 3 — severe | ✅ Complete |
| 3 | 3A | **Assessment: the evidence ledger** (`persona assess`) | 🔶 **Current** (built; drive clean, owner sign-off pending) |
| 3 | 3B | Assessment: the blind loop — draw, worksheet, commit, reveal | ⬜ |
| 3 | 3C | Assessment: the coach — gap diff, coverage, review mode, history | ⬜ |
| 4 | — | Random patient generation (persona + profile, diagnosis hidden) | ⬜ |
| 5 | — | Longitudinal progression | ⬜ |

**The scoring system is the consumer of the simulator, not the simulator.** It is
Phase 3, and it is deliberately last of the near-term work: a simulator built
alongside its own scorer gets tuned until the scorer is happy, which proves
nothing. Build the patients first, validate each by hand, and only then score them.

Every completed item passed the same gate: `ruff check` · `ruff format --check` ·
`mypy src` (strict) · `pytest`.

---

## Phase 1 progress (complete)

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

Test counts are cumulative for the whole suite at the close of that stage. The
suite stands at **459 passing** at `phase-1-complete`, the tag Phase 2 branches
from and the point to return to if Phase 2 goes wrong.

---

## Phase 2 — cognitive impairment, one CDR stage at a time

### The shape of it

**Severity is data, not code.** No symptom is hardcoded and none is branched on by
name. A disease profile is a YAML file in `data/profiles/` holding parameters:

```
healthy.yaml     retrieval: 1.00   orientation: 1.00   language: 1.00   working_memory: 1.00
cdr05.yaml       retrieval: 0.90   orientation: 0.97   language: 0.95   working_memory: 0.90
cdr1.yaml        retrieval: 0.70   orientation: 0.90   language: 0.85   working_memory: 0.70
cdr2.yaml        …
```

Those numbers are placeholders and will be tuned by driving the persona; the
*point* is the shape. A random patient (Phase 4) then becomes nothing more than
**load persona + load profile**, and "CDR 2" never becomes a scattering of
`if stage == 2` through the retrieval engine.

**Phase 1 is not touched.** The impairment layer wraps `retrieval/`, working memory
and the prompt seam. No core change, no schema migration, no seed edit — that
promise was made in Stage 2 (all three memory types in one table, discriminated by
column) and Stage 5 (the engine lives in top-level `retrieval/` precisely because
it is the seam Phase 2 wraps). Phase 2 is where those decisions get cashed in.

**Nothing that made Phase 1 correct is relaxed to make Phase 2 expressive.**
Formation still never sees the model's output, so an impaired persona still cannot
remember something she invented. Impairment *withholds and hedges* memories; it
never manufactures them.

**The trace explains every failure.** A memory not recalled is not an absence in
the log — the trace records that it was found, that the profile suppressed it, and
why. An unexplained failure is indistinguishable from a bug, and Phase 3's report
is built directly on this.

### Sprint 2A — CDR 0.5 ✅ (declared complete by the owner)

> The mechanics below all shipped and `make check` is green. The adversarial drive
> and a second clinical review were the last open items (see "The drive is not
> finished" under Open issues); the owner has declared the sprint complete and
> Sprint 2B is now current. The profile numbers in `cdr05.yaml` remain data and may
> still be tuned if a later drive warrants it.


Clinical spec: `docs/disease_profiles/CDR05.md` (ground truth). Design:
`docs/design/sprint1_cdr05.md`. Built: `impairment/` (profile, recall gate, engine
wrapper, voice), `data/profiles/{healthy,cdr05}.yaml`, `persona chat --profile`,
withheld memories on the trace and in `persona trace`. All 459 Phase 1 tests pass
unmodified; 30 new tests pin the gate, the landmine (a withheld memory never
triggers improvisation), and the formation boundary. **Not done until the
adversarial drive against a real model is clean and the profile numbers are tuned.**

**Do not build "mild Alzheimer's". Build one patient who consistently behaves like
CDR 0.5.** That is a far smaller thing, and it is the whole sprint.

Six behaviours, and nothing else:

1. **Recent episodic recall is slightly impaired.** "What did we talk about
   earlier?" — sometimes recalled, sometimes missing a detail. Never an impossible
   answer.
2. **Older memories remain excellent.** The wedding is near-perfect.
3. **Orientation mostly intact.** Knows the date approximately, the place, the
   caregiver, her home. Occasionally self-corrects: *"Tuesday? … Wednesday? No —
   Tuesday."* Not *"where am I?"* — that belongs to a later sprint.
4. **Mild word-finding difficulty.** Occasional *"that thing… the… the kettle"*.
   Not every sentence.
5. **Slight repetition.** Asked about the dog twice, she may answer similarly
   again — similarly, not verbatim.
6. **Insight is preserved.** She knows she is becoming forgetful, that she loses
   words, that her daughter has noticed. This is a clinical feature of CDR 0.5, not
   a leak. **Do not remove it.**

**The one success criterion:** can a caregiver tell this persona apart from the
healthy one over 15–20 minutes, while still recognising her as the same person? If
yes, Sprint 2A ships. Finer clinical detail comes after that is true, not before.

**Acceptance criteria** — every box, or it does not ship:

- ✓ Long-term identity preserved
- ✓ Recent memory fails occasionally
- ✓ Remote memory preserved
- ✓ Orientation mostly correct
- ✓ Mild lexical retrieval difficulty
- ✓ No impossible confabulations
- ✓ The retrieval trace explains every failure
- ✓ The healthy architecture is untouched (and `healthy.yaml` still behaves exactly
  as Phase 1 did — the regression suite proves it)

### Sprint 2B — CDR 1 ✅ (declared complete by the owner)

> Two adversarial drives against qwen3:14b (16 probes, then a focused re-drive) are
> clean, and both open issues below are resolved. The owner has declared the sprint
> complete and Sprint 2C is next. `cdr1.yaml` remains data and may still be tuned.

Clinical spec: `docs/disease_profiles/CDR1.md` (ground truth). Design:
`docs/design/sprint2_cdr1.md`. Built: `data/profiles/cdr1.yaml`, a third
time-orientation level (`mistaken`) in `impairment/profile.py` and
`impairment/voice.py`, and — after the drive — one new mechanism,
`impairment/comprehension.py` (the long-question overrun, below). All Phase 1 and 2A
tests pass unmodified; new tests pin CDR 1 as a strict rung past CDR 0.5, the
`mistaken` clock, and the comprehension trim.

Same architecture, different profile. Working memory weaker; orientation
occasionally wrong; conversation continuity sometimes lost; retrieval more often
blocked. **Nothing else changes** — and almost none of it is code: three of those
four are `cdr1.yaml` numbers turned up a rung (recall window 90 → 180 days,
thresholds and word-finding raised, cueing weaker, working-memory fade sharper).
This is the first time the "severity is data, not code" bet is cashed.

**The one new mechanism — orientation `mistaken`.** CDR 0.5's `uncertain` still
handed her the true weekday, so she wavered and *landed on the right day*. CDR 1
withholds the weekday and date from the clock she is given: she offers the day she
believes it is — sometimes wrong — or admits she has lost track, and does not tidily
self-correct to an answer she no longer has. This withholds a fact she has lost hold
of; it never injects a false one, and orientation is stored nowhere, so no memory is
touched. A wrong weekday is the defining CDR symptom, not the closed-cast
confabulation the layer forbids.

**Deliberately not built.** `CDR1.md` spans six clinical domains; four of them —
judgment and problem solving, community affairs, home and hobbies, personal care —
have no mechanism, and get none here: a profile field with no consumer is a lie in a
config file, so those domains stay out of `cdr1.yaml` until a sprint gives each one a
consumer, never a hardcoded branch. Repetition stays emergent from the fade, as at
CDR 0.5, turned up by the numbers rather than by a new "repeat" instruction.

**The one success criterion** (the mirror of 2A's): can a caregiver place her at
*mild dementia* over a short interview, while still recognising the same woman? That
is judged on a transcript, and the drive is where `cdr1.yaml` gets tuned. **Judged
met** on the second structured drive (16 probes): day-of-week lost, breakfast came
back as gist only, one visible word-finding stumble, insight voiced unforced, and
the multi-part question overran — while the wedding, her mother and her brother were
recalled perfectly and she remained, unmistakably, the same woman. Closed cast and
caregiver scope held throughout; nothing was confabulated.

**Observed in the first structured drive (real model, qwen3:14b, 14 probes).** Most
of the profile landed on the first pass, which is the "severity is data" bet paying
off — the numbers moved and the behaviour moved with them, no new code:

- *Time orientation (`mistaken`)* — exactly right. The day is lost ("I'd need to
  check"), the date hedged while month and year stay confident and correct. No tidy
  self-correction, no false fact injected.
- *Recent recall* — clearly impaired: breakfast came back as gist ("the rest escapes
  me") and, probed again seven turns later, drew a blank. Cue-dependent and
  explained in the trace.
- *Delayed recall* — **1 of 3**, the clinical signature of CDR 1.
- *Remote memory* — excellent and in character. *Insight* — preserved and unforced.

The memory and orientation **numbers were left unchanged**: the transcript
validated them rather than faulting them. Tuning is not "change something"; here it
was "confirm these are right, and fix what the drive actually broke."

**Open issues from the drive** (stated, not hidden — the stage gate forbids a silent
"known limitation"):

1. **Word-finding — RESOLVED (post-generation injection).** The prompt seam could
   not deliver it: the fragment produced *zero* visible groping across the drive, and
   strengthening it to force a stumble backfired into a robotic litany — *"I know I
   had a napkin, but I cannot say what it was made of…"* for every noun, which reads
   as aphasia, not CDR 1. The fix is the mechanism this issue predicted: a light
   post-generation pass (`impairment/disfluency.py`) that injects a single groping
   hesitation into the reply the model already wrote — *"the teapot beside the — it's
   on the tip of my tongue — window"*. It fires at `word_finding_probability`, hashed
   per (session, turn) so a session replays identically; it stumbles on exactly one
   plain lowercase noun (never a name, never the opening word, so "Maya" and "Vermont"
   are safe); and it adds a **disfluency, not a fact** — formation never sees the
   reply, so the closed cast is untouched. The unreliable prompt fragment is gone; the
   profile field now feeds the injector. This was the last thing standing between 2B
   and shippable.
2. **Delayed-recall intrusion — RESOLVED (lightweight gap guard).** With the list
   faded, the model filled the gaps from nearby transcript — "apple, slice, lemon",
   the last two lifted from the breakfast answer. The fix is a single prompt fragment
   (`voice.FADED_GAP`), added only on a turn that actually faded something: it tells
   her a slipped piece is gone, to give only what she still holds, and never to borrow
   a nearby word to fill the hole. It withholds; it never invents — the same rule as
   the fade itself. A first wording named the '…' glyph and the model echoed it
   literally ("… lemon … bread …"); the shipped wording names no glyph and, re-driven,
   produced the clean CDR-1 miss: *"Table. Penny. … I cannot recall the third."* — 2
   of 3, the last declined, zero intrusion.
3. **Multi-part comprehension — RESOLVED (input trim), found in the second drive.**
   Handed a deliberately overloading five-part question, she answered *every* part
   flawlessly — the exact deficit the profile says she can no longer manage. The cause
   was the same as word-finding #1: `long_question` was a soft prompt fragment
   (*"you did not keep all of it, answer the part you are surest of"*), and I confirmed
   it *fired* that turn — qwen3:14b simply read all five parts and answered them. A
   prompt cannot deliver a comprehension deficit against a capable model. The fix is
   the input-side twin of `disfluency`: `impairment/comprehension.py` trims the
   question to its last `long_question_clauses` parts **before the model sees it**, so
   she cannot answer the earlier parts — there is nothing there to answer, the same
   structural guarantee as formation never seeing the reply. Retrieval and formation
   still read the *full* message, so a fact disclosed in a dropped clause is remembered
   though not answered; the closed cast is untouched. It fires at
   `long_question_probability`, hashed per (session, turn) so a session replays
   identically, and the trace records *"a 5-part question overran; kept only the last
   2"*. Re-driven: a five-part and a four-part question each overran to their last two
   parts, a second four-part one *coped* (usually she does — this is CDR 1, not CDR 2),
   and a short question was untouched. The soft fragment is gone from `voice.py`.

   **Delayed recall (3/3) — accepted as-is by the owner.** The second drive's
   three-word probe came back 3/3 rather than the ~1/3 the profile intends. The owner's
   call is to leave the `hold` numbers as they are; it is recorded here, not silently
   left. If a later review wants the sharper miss, it is a `hold` (`crisp_turns`/
   `fade_turns`) tuning, no new code.

**Resolved from the drive:** she called the caregiver *"my caregiver"*, which the
healthy-persona *Who is in the room* rule appeared to forbid. Decision (owner): from
Phase 2 every persona is a patient, so acknowledging a caregiver is correct, not a
leak. The rule is now universalised — the prompt wording is unchanged, but its job is
"never let her speak *as* the caregiver or hand over her own home", not "never tell
her she is looked after". See `CLAUDE.md` *Who is in the room* and `render_speaker`.

### Sprint 2C — CDR 2 ✅ (declared complete by the owner)

> Two structured drives against qwen3:14b are clean and the one issue they raised
> (the tag-aware trim, below) is resolved and pinned. The owner has declared the
> sprint complete and Sprint 2D is current. `cdr2.yaml` remains data and may still
> be tuned.

ADLs begin to degrade — **not because a prompt says so, but because cognition now
fails often enough that it shows.** Repeated questions, lost topics, uncertainty,
difficulty following an explanation. These are consequences of the profile, never
instructions in it.

Clinical spec: `docs/disease_profiles/CDR2.md` (ground truth). Design:
`docs/design/sprint3_cdr2.md`. Built: `data/profiles/cdr2.yaml`, and one new
mechanism — a **place axis** on `Orientation` (`PlaceSense = confident | hazy`) with
its branch in `impairment/voice.py`'s clock. All Phase 1, 2A and 2B tests pass
unmodified; new tests pin CDR 2 as a strict rung past CDR 1, the healthy `place`
default, the hazy-place frame, and the tag-aware trim below.

Same architecture, different profile — the third time the "severity is data" bet
pays. Everything but the place axis is a number turned up a rung: recall window
180→365d and thresholds raised (no recent memory ever crisp — `gist_below` sits above
the reach ceiling), the working-memory fade sharper (`fade_turns` 5→3, delayed recall
≈0/3), word-finding 0.30→0.45, the long-question limit 2→1 and its probability
0.65→0.85, and `insight` **flipped off** — the loss of insight `cdr1.yaml` already
named as CDR 2's.

**The one new mechanism — orientation to place (`hazy`).** CDR 1 kept place and
person confident and degraded only time; `Orientation`'s own docstring reserved place
for "the sprint that degrades them". `hazy` withholds *where she is* and *the time of
day* from the clock frame (as `mistaken` withholds the weekday), so she is oriented in
familiar surroundings but loses her bearings when they are unfamiliar or changed, and
morning runs into afternoon. It withholds a confidence she has lost; it never injects
a false place, and orientation is stored nowhere. A constant "where am I?" is CDR 3.

**Two structured drives against qwen3:14b are clean.** The place axis landed on the
first pass — *"I would say it is morning, but I cannot be certain… the hour slips"* at
5pm, *"I believe I am in my home. I cannot be certain without looking around"* — and
recall collapsed as intended (breakfast withheld or gist, delayed recall 0/3), with
frequent word-finding, an intact wedding, no confabulation, and no spontaneous insight.

**Open issue from the drive — RESOLVED (tag-aware trim).** With `long_question_clauses`
at 1, the comprehension trim kept the *last raw clause*, which is often a trailing
courtesy: *"Do you have a dog, by the way?"* trimmed to "by the way", and she answered
a non-sequitur about not knowing the day — reading as CDR 3 fluctuation, not CDR 2. The
fix teaches `impairment/comprehension.py` a curated set of discourse tags (like
`disfluency._SKIP`): a trailing tag no longer counts toward the part total (so a simple
question with a courtesy tacked on is not treated as multi-part) and is dropped rather
than kept as the sole surviving clause. Re-driven, the same probes came back clean —
*"Yes, I have a dog. His name is Compass"* — while genuine multi-part questions still
overrun to their last real part. Pinned by two regression tests.

**Deliberately not built** (same discipline as 2B): community affairs, home and
hobbies, personal care, and the planning/judgment side of executive function have no
conversational consumer and stay out of `cdr2.yaml`; executive function is expressed
only where it has one — the long-question overrun. Repetition stays emergent from the
sharper fade. "Confident about a wrong detail" and "confuse recent events with older
ones" are admitted **only** as orientation (a wrong day or place) and as loss of the
*when* — never as invented biography or an injected false timeline; the closed cast is
untouched. See `docs/design/sprint3_cdr2.md`.

**Found after sign-off, in the five-profile comparison drive — RESOLVED (anaphora-aware
trim).** Mid-session, CDR 2 denied her hobbies and her childhood home — remote,
authored memories CDR 1 recalled richly one rung earlier, and the trace showed them
*retrieved whole and in the prompt* while she denied them. The research isolated two
causes, the second decisive. First, `voice.FADED_GAP` quoted a sample phrase — *'that
part has gone from me'* — and the model made it a catchphrase (seed authoring rule 2,
rediscovered at the impairment seam) and generalised the unscoped note into denying
long-term memory; it is reworded to name its scope (this conversation only) and to
state that the memory block above it is exempt. Second, and the actual denial: with
`long_question_clauses` at 1, *"describe the home where you grew up? What do you
remember most about **it**?"* trimmed to an **anaphoric tail** — a question about an
orphaned "it", whose referent lived in the dropped clause. Retrieval read the full
message (so Rutland sat in the memory block) but the model never heard "home", and
resolved "it" against the transcript (her maps) or denied. The trim's premise — the
dropped clauses were scene-setting — is false exactly then, so
`impairment/comprehension.py` now keeps one more clause when the surviving tail leans
on a bare anaphor: a two-part anaphoric question is heard whole, a three-part one
still loses its head, and the deficit survives where it is honest. Reproduced 3/3
denied before the fix, 0/3 after, against qwen3:14b; pinned by four regression tests.

### Sprint 2D — CDR 3 ✅ (declared complete by the owner)

> The five-profile comparison drive (15 probes × 5 profiles, qwen3:14b) stood in for
> the adversarial drive, and every defect it surfaced is fixed, verified live, and
> pinned: the place recital (the place gate, below), the CDR 2 remote-memory denial
> (the anaphora-aware trim, recorded under 2C), and the healthy Q15 slip (shown to be
> a non-reproducible one-off, no change made). The owner has declared the sprint —
> and with it Phase 2 — complete. `cdr3.yaml` remains data and may still be tuned.

Severe. Retrieval largely collapses, language simplifies, orientation is poor,
recognition fails. Again: same architecture, different profile.

Clinical spec: `docs/disease_profiles/CDR3.md` (ground truth). Design:
`docs/design/sprint4_cdr3.md`. Built: `data/profiles/cdr3.yaml`, one new place rung
(`lost`), one new orientation axis (`person: unfamiliar`), one new speech field
(`simplified_language`, a per-turn register fragment), and — after the drive — one
new mechanism, `impairment/orientation.py` (the place gate, below). All Phase 1, 2A,
2B and 2C tests pass unmodified; new tests pin CDR 3 as a strict rung past CDR 2, the
person-only frame, the recognition guard, the simplified-speech note, the crisp-zero
fade, and the place gate (hazy hedges the residence, lost withholds it and its
place-naming expansion, the childhood hometown is never touched).

The fourth time the "severity is data" bet pays: two of the four collapses the
roadmap names are pure numbers, and the other two are one rung and one axis both
reserved by earlier docstrings. Everything on the recall and speech side is a knob
turned to its floor: recall window 365→730d, `withhold_below` **above the encoding
ceiling** (1.05 — an uncued recent memory is now always withheld; only fragments
remain), `cue_weight` 0.30→0.15, `fade_turns` 3→2, word-finding 0.45→0.65, the
long-question overrun 0.85→0.95, and `hold.crisp_turns` **1→0** — even the exchange
just completed now fades, the "total, cue-proof collapse of even the current
exchange" that `cdr2.yaml` named as CDR 3's.

**The new place rung — `place: lost`.** CDR 2's `hazy` withheld the time of day and
the easy confidence about place while telling her familiar surroundings still held
her. `lost` withdraws that anchor and the month, year and season with it: the frame
asserts only her own person and nothing about when or where — orientation to person
only, the clinical phrase. Same discipline as `mistaken` and `hazy`: withheld, never
falsified, stored nowhere. `sprint3_cdr2.md` promised this as "a third rung rather
than a new field", and that is exactly what it is.

**The new axis — `person: unfamiliar`.** The last orientation axis, reserved by
`Orientation`'s docstring for the sprint that degrades it. The frame stops asserting
that she knows who she is speaking with. Two hard lines keep it inside *Who is in the
room*: the **I/you split is not softened** — the fragment grounds the pronouns inside
itself, so whoever the speaker is, their "I" is them and "you" is her, and she never
crosses to their side; and it is **unfamiliarity, never misidentification** — she says
an honest "I don't know who you are" and is expressly forbidden to decide a stranger
is her daughter, which would manufacture a false fact about the closed cast.
`memory.formation.CAREGIVER` is untouched — every disclosure still lands on the same
fixed subject, whoever she believes is speaking.

**Decision — misidentification, CLOSED (accepted by the owner at sign-off).**
`CDR3.md` lists "misidentify… who is present" and "confuse people" as in-scope; a
confident wrong name ("you're my daughter") would manufacture a false fact about the
closed cast, which no severity may do. So recognition failure is honoured as *honest
non-recognition* — an "I don't know who you are", a familiar face placed
inconsistently — not a decided wrong identity. This is the one clinical feature the
architecture deliberately cannot fully express; it is stated in `CDR3.md`'s
implementation note and accepted as-is. If a later review wants more, the bounded,
non-confabulatory form (*"are you… one of the nurses?"* offered as a question, never
asserted) is the shape to argue for — in `docs/future.md`, with a transcript behind
it. **Emotional response is preserved, not suppressed:** the
spec keeps "show fear, seek comfort, appear distressed", so the orientation and
recognition fragments permit momentary, in-character unease (an earlier draft wrongly
told her the gaps did not trouble her). A *sustained* distress/agitation engine stays
out — the spec's own "delirium-like fluctuation as the main feature" to avoid.

**The one prompt fragment — `simplified_language`.** Short sentences, plain words, one
thought at a time. This project's rule is that a prompt *cannot* deliver a **deficit**
(word-finding and the long-question overrun had to move to mechanisms). But register
is not a deficit — it is a style the model follows willingly, the same seam that
already carries her speech manner from the seed — so it is tried at the prompt, with
the two standing guards (describe the manner and quote nothing; forbid the caricature
in both directions — no babbling, no decorated fluency). If the drive shows the model
declines it the way it declined groping, the fallback is a mechanical post-generation
pass — but one the transcript must *earn*, not one built on suspicion.

**Deliberately not built** (same discipline as every sprint): community affairs, home
and hobbies and personal care are at their clinical floor and still have no
conversational consumer, so they stay in `CDR3.md` and out of `cdr3.yaml`.
Misidentification, hallucination, delusion, agitation, wandering and sundowning are
either false-fact manufacture or deferred engines — recognition fails *honestly* here
and the rest is `docs/future.md` or never. Repetition stays emergent (at a two-turn
window fading from the first word it should be near-constant); a language-collapse
engine is not built unless the fragment proves too weak. See
`docs/design/sprint4_cdr3.md`.

**Open issue from the drive — RESOLVED (the place gate).** The first CDR 3 drive
showed the `lost` clock frame was not enough on its own: asked "where are you right
now?", the model retrieved her authored home address (ageless, so the recall gate
never touches it) and recited "a third-floor walk-up in Jamaica Plain" as her present
location — the address standing in for an orientation she has lost. A prompt cannot
argue the model out of a memory it has been handed (the `disfluency`/`comprehension`
lesson again), so the deficit moved to where the memory lives: `impairment/
orientation.py` degrades the *self-location* memory in the trace, exactly as the
recall gate degrades a recent one — `hazy` hedges it ("I believe I'm home"), `lost`
withholds it and any place-naming expansion (the dated "I moved to Jamaica Plain" that
retrieval pulls in to explain it). It touches only the *current* residence, never the
childhood hometown, so remote memory is preserved. Re-driven: CDR 3 now answers
"where are you?" with "I do not know", while "where did you grow up?" still surfaces
its Rutland fragment; CDR 2 hedges ("… as far as I recall"). Pinned by six tests.

**Not done until the adversarial drive against a real model is clean.** The mechanics
are green, but the sprint is judged — as 2A, 2B and 2C were — on a hand-drive against
qwen3:14b: delayed recall 0/3 with a cue that rescues nothing, the topic lost within
an exchange, day/month/season/place all gone including at home, at least one honest
failure to place the caregiver with no invented identity, speech visibly simpler than
CDR 2's, a genuine remote fragment surfacing without elaboration, constant repetition,
no insight — and, still and always, no confabulation. The numbers in `cdr3.yaml` are
starting values and should be expected to move once the transcript says where.

### Not in Phase 2 — do not build these

Disease progression, emotional engine, hallucination engine, stochastic failure
beyond the profile parameters, caregiver scoring, medication, sundowning,
wandering, agitation. Ignore them. Each is either a later phase or `docs/future.md`.

---

## Phase 3 — assessment mode (current): caregiver training through blind interview

Scope: `docs/design/phase3_assessment.md` (supersedes the first Phase 3 scope; same
foundations, sharpened into a training loop). **The loop:** a hidden profile is
drawn — *including healthy, so over-diagnosis is trained away* — the caregiver
interviews and rates as they go on a worksheet, commits, and only then sees the
actual stage with the evidence they used, missed, or never elicited. Modelled on the
Washington University CDR training protocol (blind rating against gold-standard
cases), upgraded in one way: the trainee conducts the interview rather than watching
one, so *eliciting* evidence is trained alongside reading it.

Three theses, each inherited from an earlier phase's discipline:

- **The reveal is a replay of the trace, not a judgment by a model.** Every
  mechanism already explains itself per turn in the session log; assessment
  aggregates by rule. `assessment/` may not import the LLM — the same invariant, for
  the same reason, as formation.
- **The system never diagnoses.** The actual CDR is the drawn profile, known by
  construction — never inferred from the transcript. A severity inferrer would be a
  second scorer to tune the simulator against.
- **Report only what a conversation can show.** Memory, orientation, and the
  expressed sliver of judgment are evidenced (language as supporting observation);
  community affairs, home and hobbies, and personal care are named as unobservable
  in conversation, not padded — they are off the worksheet for the same reason.

### Sprint 3A — the evidence ledger 🔶 (current — built, drive clean, owner sign-off pending)

`persona assess <persona> [--session] [--list] [--profile]`: a deterministic
per-domain report over one logged session — recall fates split remote vs recent,
orientation withholdings, overruns, word-finding cadence, and **probe coverage**
(which probe types the interview contains, and which are absent), each line naming
its turn — with, given `--profile`, the profile's intended numbers beside the
observed behaviour. CLI only; no prediction, no UI change, no new trace fields.

Built: `assessment/` (vocabulary, probes, ledger, report — a pure reader), the CLI
command, and two new invariants — `assessment/` may import neither the LLM nor
storage (the CLI hands it turns, so the package cannot quietly grow a write path),
and it joins the packages allowed to read `impairment` profiles. The note
vocabulary is pinned from **both sides**: the emitters are invoked for real in the
tests and their notes must parse, so a reworded note breaks loudly rather than
silently orphaning the ledger. The probe classifier is validated against the
fifteen-probe bank from the comparison drive. 37 new tests; `make check` green at
580.

The session log does not record which profile it ran under — that lands with 3B's
assessments table — so `--profile` lets the operator state it until then.

**Driven** against qwen3:14b: one 10-probe session per profile into a scratch
database, `persona assess` over each. The healthy report says "Nothing impaired
was observed" with full coverage and every remote memory intact; CDR 2 shows the
dissociation at a glance (remote intact beside recent-withheld with its
arithmetic, the fade accelerating 2→61 words across the session, place hedged,
four overruns, word-finding); CDR 3 differs exactly where the profiles differ
(residence *withheld* rather than hedged, the crisp-zero fade biting from turn 2,
the higher thresholds printed). Every failure in each transcript is accounted for
with its mechanism and its turn.

### Sprint 3B — the blind loop ⬜

The per-session hidden draw (uniform over all five profiles, weights held as data;
genuinely random on purpose — the hash-not-roll invariant protects `impairment/`'s
replay, and the draw's one job is to be unguessable). The five leaks sealed:
`/api/profile`, the per-message trace (`Exchange.trace` — the answer key), the
transcript download, the `run`/server log labels, and `SessionStore`'s
per-server profile. The worksheet (three domains + language + global, `CDR*.md`
anchor text beside it, optional probe guide), the commitment (end locks the
transcript, submit locks the rating), the reveal (actual + rating + raw ledger), and
an additive `assessments` table. Blindness is a UI contract, not a security
boundary, and says so.

### Sprint 3C — the coach ⬜

Three kinds of feedback, all by rule: **discriminating evidence** where rated ≠
actual (the turns whose recorded behaviour separates the two stages, phrased from
profile numbers and spec anchors); **coverage** — what was never elicited ("the day
was never asked"), the feedback only an active interview can get; **confirming
evidence** when right. Plus review mode (the trace panel unlocked over the finished
transcript) and the plain history (date, actual, rated, hit or miss — a mirror, not
a mark). The phase's success criterion: a trainee who rates wrongly can point,
after the reveal, to the turns they misread or the probes they never asked.

### Not in Phase 3 — do not build these

LLM-generated feedback or summaries; severity inference from transcripts; grades,
scores, certification or leaderboards (history only); adaptive difficulty over the
draw and an informant-interview mode for the ADL domains (both `docs/future.md`);
random persona generation (Phase 4 — the draw varies the *profile* over one authored
persona, not the *person*); progression (Phase 5); and any new symptom, mechanism,
or profile field — a gap a drive exposes is a Phase 2 amendment argued with a
transcript, never a Phase 3 feature.

---

## Phase 1 stages (complete)

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

1. No Phase 2 vocabulary anywhere in source — not even as a disabled flag. **Sprint
   2A must narrow this to the healthy core rather than delete it — see Open issues.**
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

**Graded delayed recall — 2 of 3 words, not 0 of 3 — RESOLVED (transcript fade).**
The first clinical review scored the persona at "CDR ≈ 0–0.25, not 0.5", and the
single most diagnostic probe was the three-word delayed recall: she scored 3/3 by
reading the words *verbatim out of the prompt* six turns later, through the healthy
transcript window. Shortening that window (the old `working_memory_turns: 5`) made
the probe fail honestly — but it failed **completely**, "I don't remember any
words", and a second review flagged that a flat blank is a *heavier* deficit than
CDR 0.5, where a patient drops one word and keeps two.

The original plan here was to **encode what is said in a session as episodic
memory**, so the recall gate would apply per item — but that is a change to Phase 1
*formation*, and it turned out to be unnecessary. The lighter fix, shipped in
`impairment/hold.py`, keeps the words as free text and **fades the transcript word
by word** at the prompt seam instead of truncating it: the last `crisp_turns`
exchanges are held whole (immediate registration intact), older exchanges lose words
progressively (`sha256`-hashed, so a session replays identically), and beyond
`crisp_turns + fade_turns` the exchange is gone. Partial recall falls out — 3/3 at a
short delay, 2/3 and then 1/3 as the delay grows — with Phase 1 formation untouched
and the closed-cast rule intact.

One honest bound, recorded rather than hidden: **cued recovery of a word that has
faded *completely* is not reachable** and must not be. The reviewer's "*it was a
colour → oh yes, Blue*" works only while the word partially survives; once it is gone
from the transcript there is nothing to catch on, and inventing "Blue" from a
category cue would be the confabulation the whole layer forbids. She declines the cue
("no, I don't think so") rather than manufacture the answer. If cued recovery of a
fully-lost item is ever wanted, *that* is what needs per-item episodic encoding — and
it can wait for its own sprint, no longer blocking CDR 0.5.

Until then, 0-of-3 is a slightly severe reading of CDR 0.5, and it is stated rather
than hidden.

**The drive is not finished, and the numbers are still starting values.** The
headline criterion — a caregiver tells her from the healthy persona in 15–20 minutes
while still recognising her as the same woman — is judged on a transcript, and the
second review has not happened. `data/profiles/cdr05.yaml` is data; expect to tune it.

---

## Closed issues

**Invariant 1 narrowed to the healthy core, as decided.** It banned Phase 2
vocabulary from all of `src/`; it now bans it from everything *outside*
`src/personasim/impairment/`, which is the one place that vocabulary belongs. It was
narrowed, not deleted, and it gained two siblings: `impairment/` may import neither
the LLM, nor storage, nor `random` (withholds and hedges, never manufactures — and
deterministically, or the trace lies); and the healthy core may not import
`impairment` back, except the conversation loop, whose job is composition. The
wrapper claim is still enforced by test, from both directions.

Every issue raised in Stages 5–8 is closed. The five that blocked Stage 8:

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

**Sprint 2A — CDR 0.5.** Phase 1 is done and tagged `phase-1-complete`; work happens
on the `phase-2` branch, and that tag is the way back if this goes wrong.

The first move is not code. It is `data/profiles/healthy.yaml` and a profile loader
that changes nothing — because a `healthy.yaml` of all `1.0` that leaves the Phase 1
suite green is the proof that the wrapper is a wrapper. Only once impairment can be
*switched off to nothing* is it safe to switch it on.

Then the seam: `retrieval/engine.py` is where a memory is found, scored and either
returned or not. That is where a profile suppresses recall, and where the trace must
say *"found, suppressed by profile, recency 0.9"* rather than quietly returning less.
Orientation degrades at `render_now()` — the clock is injected, not stored, exactly
so that losing the day costs no memory change. Word-finding and repetition are prompt
seams, not memory ones.

Before starting, read `CLAUDE.md` — the stage gate, *Who is in the room*, and the
closed cast are not optional, and neither is this:

**Driving beats testing, and it is not close.** Every real defect in Stages 5–8 was
found by talking to the persona; the suite was green through all of them. She
invented a pet, a mother, an umbrella at a wedding. She formed a memory *from a
question*. She heard four disclosures in a row and remembered none. She answered "I'm
a cartographer" when asked what the *caregiver* did for a living. She stored a memory
keyworded `grew` that "where did you **grow** up?" could never reach.

Tests encode the failures you already imagined. She fails in ways you did not. So:
build the instrument, go looking for trouble, and write the tests *after*, against
what actually broke.
