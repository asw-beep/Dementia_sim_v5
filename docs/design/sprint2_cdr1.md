# Sprint 2B — CDR 1: architectural design

Ground truth: `docs/disease_profiles/CDR1.md`. This document does not reinterpret
the clinic; it maps each behaviour the clinic asks for onto a mechanism, and records
what is new versus what is only a number.

## The thesis: CDR 1 is mostly data

Sprint 2A built the machinery — a recall gate, a working-memory fade, and a set of
speech seams — all of it parameterised by a `CognitiveProfile` loaded from YAML.
The bet the whole phase is built on ("severity is data, not code") is cashed here
for the first time: **most of CDR 1 is `data/profiles/cdr1.yaml`, and no new code.**

The roadmap's one-line scope for 2B is *"working memory weaker; orientation
occasionally wrong; conversation continuity sometimes lost; retrieval more often
blocked. Nothing else changes."* Three of those four are the existing mechanisms
turned up a rung:

| 2B behaviour | Mechanism | Change |
| --- | --- | --- |
| Retrieval more often blocked | `impairment/recall.py` | data: window 90→180d, `withhold_below` 0.45→0.65, `gist_below` 0.85→1.10, `cue_weight` 0.55→0.45 |
| Working memory weaker | `impairment/hold.py` | data: `crisp_turns` 2→1, `fade_turns` 8→5 |
| Conversation continuity lost | `impairment/voice.py` (long-question) + the fade | data: `word_finding_probability` 0.12→0.30, `long_question_probability` 0.35→0.65 |
| Orientation occasionally **wrong** | `impairment/voice.py` (the clock) | **new: a third orientation level** |

So the coding surface of the whole sprint is *one new orientation level*. Everything
else is a number, and every number moves in the more-impaired direction — asserted,
not asserted-by-hand, in `test_cdr1_is_a_rung_past_cdr05`.

## The one new mechanism: time orientation `mistaken`

At CDR 0.5 orientation is `uncertain`: the clock she is handed (`render_now_impaired`)
still contains the true weekday, and the prompt tells her only that her *confidence*
in it has frayed. She second-guesses herself and lands on the right day, or near it —
*"Tuesday? … Wednesday? No — Tuesday."* Confidence degraded, fact intact.

CDR 1 is different in kind, not degree, and the clinic is explicit: *difficulty with
time relationships, occasional confusion about recent timing*, a person who can give
the wrong day and not catch it. Reusing `uncertain` would leave 2B's orientation
identical to 2A's, which contradicts the roadmap. So `Sureness` gains a third value,
`mistaken`, and `render_now_impaired` gains a branch for it.

**How it stays inside the layer's rules.** The mechanism withholds; it does not
manufacture. In the `mistaken` branch the exact weekday and date are *left out of the
frame she is given* — she cannot read off what she is not handed — and she is told to
offer the day she believes it is (sometimes wrong) or admit she has lost the thread,
without the tidy self-correction that arrives at the right answer. This is the same
discipline as the recall gate: reach is withheld, a falsehood is never injected. And
as at CDR 0.5, orientation is *injected per turn and stored nowhere* — "a stored
clock is wrong within the hour" — so no memory is touched, and the Phase 1 invariant
(formation never sees this) is untouched.

**Why a wrong day is not the confabulation the layer forbids.** The closed-cast rule
bans inventing *people, relationships, biography* — a sister she never had. Being
disoriented to the day of the week is the defining CDR symptom, asked for by name in
both the roadmap and `CDR1.md`, and it creates no permanent false memory. The two are
not in tension.

**Place and person stay confident.** `CDR1.md` keeps her oriented to place in a
familiar or structured setting; poor orientation to place is CDR 2. So `mistaken`
degrades the time axis only — month, year, place, and the person she is speaking with
remain in the frame she is handed, with easy confidence.

## What is deliberately *not* built

`CDR1.md` spans six clinical domains; four of them — judgment and problem solving,
community affairs, home and hobbies, personal care — have **no mechanism**, and get
none here. A profile field with no consumer is a lie in a config file
(`impairment/profile.py`), so those domains stay out of `cdr1.yaml` until a sprint
gives each one a consumer, never a hardcoded `if stage == 1`. They are documented in
the clinical spec so the ground truth is complete; they are absent from the engine so
the engine stays honest.

Repetition ("she asks the same thing twice") is left **emergent**, as it was at
CDR 0.5: it falls out of the fade — she does not recall she already asked — and is
turned up by the sharper `hold` numbers, not by a new "repeat" instruction. If the
drive shows it is not prominent enough, that is where a dedicated mechanism would be
argued for, empirically, with a transcript behind it — not before.

## The gate

`make check` is green: ruff, ruff format, mypy strict, and the suite (515 tests; +3
for CDR 1, and the healthy regression still proves the layer switches off to
nothing). The mechanics are done. **What remains is the sprint's real test:** the
adversarial hand-drive against a live model, judged on the CDR 1 success
criterion — *can a caregiver place her at mild dementia over a short interview, while
still recognising the same woman?* The numbers in `cdr1.yaml` are starting values and
should be expected to move once the transcript says where they are wrong. That is the
same order Sprint 2A was run in, and for the same reason: the persona fails in ways
the tests did not imagine.
