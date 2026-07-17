# Sprint 2C — CDR 2: architectural design

Ground truth: `docs/disease_profiles/CDR2.md`. As with the two sprints before it,
this document does not reinterpret the clinic; it maps each behaviour the clinic asks
for onto a mechanism, and records what is new versus what is only a number.

## The thesis: CDR 2 is still mostly data

Sprints 2A and 2B built and turned up the machinery — a recall gate, a working-memory
fade, and four speech seams (the clock, insight, word-finding, the long-question
overrun). CDR 2 is the second time the "severity is data, not code" bet pays: **most
of CDR 2 is `data/profiles/cdr2.yaml`, and one new mechanism.**

The roadmap's one-line scope for 2C is *"cognition now fails often enough that it
shows — repeated questions, lost topics, uncertainty, difficulty following an
explanation, all consequences of the profile, never instructions in it."* Almost all
of that is the existing mechanisms turned up a rung:

| 2C behaviour (`CDR2.md`) | Mechanism | Change |
| --- | --- | --- |
| Recent memory not *retained* reliably; often not recalled even when cued | `impairment/recall.py` | data: window 180→365d, `withhold_below` 0.65→0.80, `gist_below` 1.10→1.40, `cue_weight` 0.45→0.30 |
| Forgets the topic within minutes; delayed recall ≈ 0/3 | `impairment/hold.py` | data: `fade_turns` 5→3 (`crisp_turns` stays 1) |
| Word-finding frequent and obvious | `impairment/disfluency.py` | data: `word_finding_probability` 0.30→0.45 |
| Loses multi-part instructions *quickly*; overwhelmed by sequencing | `impairment/comprehension.py` | data: `long_question_clauses` 2→1, `long_question_probability` 0.65→0.85 |
| Insight largely lost; confident about a wrong detail | `impairment/voice.py` (insight) | data: `insight` true→false |
| Orientation to **place** intermittently lost | `impairment/voice.py` (the clock) | **new: a place axis on `Orientation`** |

So the coding surface of the whole sprint is *one new orientation axis*. Every number
moves in the more-impaired direction, asserted — not asserted-by-hand — in a
`test_cdr2_is_a_rung_past_cdr1` mirroring `test_cdr1_is_a_rung_past_cdr05`.

Two of those "numbers" deserve a note, because each cashes a promise made earlier.

**`gist_below` is now above the reach ceiling, on purpose.** Reach is
`encoding + cue_weight × cue`; with `cue_weight` 0.30 and both terms bounded, reach
cannot exceed ~1.30, so a `gist_below` of 1.40 means **no recent memory ever comes
back crisp** — the best case is hedged gist, the common case is withheld. That is
`CDR2.md`'s "give partially correct but incomplete answers" made structural: the crisp
rung is simply unreachable for anything recent. Remote memory is untouched, as ever —
it is never inside `recent_window_days`, at any cue strength.

**`insight` flips to `false`, exactly as 2B's own config predicted.** `cdr1.yaml`
already carries the comment that turning insight off "is CDR 2's loss of insight, a
later severity." This is that later severity. The flag is a boolean and cannot express
"largely gone"; at CDR 2 the clinic no longer expects her to reliably notice her own
lapses, and "appear confident about a wrong detail" is the same coin's other face. The
insight fragment (fired at the moment of a withheld memory) simply stops firing. No new
code — a data flip whose only job was waiting for its stage.

## The one new mechanism: orientation to place

At CDR 1 orientation degrades on the time axis only: `day_and_date: mistaken`
withholds the weekday and date from the clock she is handed, and the frame still tells
her she knows *where she is* and *who she is with* with easy confidence. `CDR1.md`
kept place intact by design; `Orientation`'s own docstring reserves place for "the
sprint that degrades them (poor orientation to place is CDR 2, not CDR 1)." This is
that sprint, and the reserved field is the whole of the new code.

`CDR2.md` is careful about the *degree*: she still "knows the general place or setting
in a familiar environment", but is "intermittently uncertain about where they are if
the setting is unfamiliar or changes." So this is **hazy**, not lost — a person mostly
oriented at home who slips when the surroundings are strange. "Where am I?" as a
constant state is CDR 3, and stays out.

**What is added.** `Orientation` gains a second axis with its own short ladder — a
`place: Literal["confident", "hazy"]`, defaulting to `confident` so healthy, CDR 0.5
and CDR 1 are byte-for-byte unchanged. `render_now_impaired` gains a branch: under
`hazy`, the frame no longer hands her easy confidence about where she is; it tells her
that the place is usually clear in familiar surroundings but can slip when things are
unfamiliar or have changed, and — since the same disorientation blurs the part of the
day — that morning and afternoon can run together too. One field, one branch, driving
both halves of `CDR2.md`'s orientation picture. (`CDR3.md`, when it comes, adds a third
rung — `"lost"` — rather than a new field.)

**How it stays inside the layer's rules.** Identical to the `mistaken` clock. Place is
*injected per turn and stored nowhere* — a stored location is wrong the moment she is
moved — so no memory is touched and the Phase 1 formation invariant is untouched. And
the mechanism **withholds**: the frame stops *asserting* a confidence she no longer
has; it never puts a false location in her mouth. She is disoriented, not lied to.

## Why "confident about a wrong detail" is not the confabulation the layer forbids

`CDR2.md` asks for two things that sound, at a glance, like the invention the whole
layer exists to prevent: *"appear confident about a wrong detail"* and *"confuse recent
events with older ones."* Both are admissible, and the boundary is the same one 2B drew
for the wrong weekday.

**The wrong detail is orientation, never biography.** The one channel for a confidently
wrong detail is the clock and the place — a wrong day stated without a hedge, a
morning she takes for an afternoon. These inject no permanent false memory and touch no
one in the cast. Inventing a *fact about her life* — a sister, a job she never held, a
wedding in the wrong decade — remains structurally impossible: formation never sees the
model's reply, the closed cast is named on every turn, and the improvisation landmine
stays closed. The wrong day was CDR 1's version of this; CDR 2 adds the wrong place.

**Timeline confusion is loss of the "when", not injection of a false one.** "Confuse
recent events with older ones" is delivered by what already exists — `mistaken` time
plus the sharper fade blur *when* things happened and in what order, so she cannot
reliably place or sequence them. What she must not do is assert a fabricated timeline
("my wedding was last year"), which would be manufacturing a false fact. The mechanisms
only ever withhold the anchor; they never forge one. So temporal confusion reads as
vagueness and lost ordering, not as a confident false date — and that is the honest,
in-scope version of the symptom.

## What is deliberately *not* built

`CDR2.md` marks four domains as now *markedly* impaired that `CDR1.md` only named:
community affairs, home and hobbies, personal care, and judgment / executive function.
As in every sprint so far, **a profile field with no consumer is a lie in a config
file**, so three of them stay out of `cdr2.yaml` entirely. They are non-conversational
— we cannot show, in a chat, that she can no longer shop alone or manage her medication
— and inventing a field the engine never reads to "look more impaired" is precisely the
dishonesty the roadmap forbids. They are documented in the clinical spec so the ground
truth is complete; they are absent from the engine so the engine stays honest.

The one exception is **executive function**, which *does* have a partial consumer:
`impairment/comprehension.py` already models "loses track of multi-part instructions"
by trimming a long question to what registered, and 2C turns it up (holds one part, not
two; overruns far more often). The rest of the executive domain — planning, sequencing,
comparing options, financial judgment — has no conversational surface and is not built.

**Repetition stays emergent**, as it was at CDR 0.5 and CDR 1. `CDR2.md` leans on it
hard — "repeat the same question many times" — and the sharper `hold` and `recall`
numbers should make it far more visible than at CDR 1: she does not recall having asked,
so she asks again. The discipline the two earlier sprints held to still holds: **do not
build a repetition engine before the drive shows the emergent version is not enough.**
Two mechanisms producing one behaviour is how a simulator becomes unmaintainable. If
the transcript shows repetition is still too thin at CDR 2's numbers, *that* is where a
dedicated mechanism is argued for — empirically, with a transcript behind it, not here.

Also out, unchanged from 2B's list: progression, hallucination and delusion, emotional
dynamics, stochastic failure beyond the profile, wandering, agitation, sundowning,
medication, and caregiver scoring. Each is a later phase or `docs/future.md`.

## The gate, and what actually decides the sprint

The mechanics are small: `cdr2.yaml`, one new orientation field and its branch, and the
tests that pin CDR 2 as a strict rung past CDR 1 and the new `place` frame. `make check`
green — ruff, ruff format, mypy strict, the suite — is table stakes, and the healthy
regression must still prove the layer switches off to nothing.

But mechanics are not the sprint. The sprint is judged, as 2A and 2B were, on **the
adversarial hand-drive against a live model**, against the CDR 2 success criterion:
*can a caregiver reasonably suspect moderate dementia within a short interview, while
still recognising the same person?* Concretely, the drive must show recent memory
failing repeatedly (not just on vague questions), delayed recall at roughly 0/3,
frequent word-finding, a lost topic within minutes, at least one confidently-wrong
orientation detail (a day or a place), visible repetition — and, still and always, an
intact wedding, an intact family, and no invented biography. The numbers in `cdr2.yaml`
are starting values and should be expected to move once the transcript says where they
are wrong. The persona fails in ways the tests did not imagine; that is why the drive,
not the suite, is the gate.
