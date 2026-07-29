# Sprint 2D — CDR 3: architectural design

Ground truth: `docs/disease_profiles/CDR3.md`. As with the three sprints before it,
this document does not reinterpret the clinic; it maps each behaviour the clinic asks
for onto a mechanism, and records what is new versus what is only a number.

## The thesis, for the last time: CDR 3 is still mostly data

Three sprints built the machinery — a recall gate, a working-memory fade, the clock,
insight, word-finding on the output, the long-question trim on the input, and a place
axis. CDR 3 is the final and hardest test of the "severity is data" bet, because the
roadmap's one-line scope names four collapses: *"retrieval largely collapses, language
simplifies, orientation is poor, recognition fails."* Two of the four are numbers.
The other two are one rung and one axis, both promised in earlier sprints' docstrings,
plus one prompt fragment — and the fragment needs a defence, given this project's
history with prompt fragments. It gets one below.

| 2D behaviour (`CDR3.md`) | Mechanism | Change |
| --- | --- | --- |
| Only fragments remain; no usable new learning; cueing barely helps | `impairment/recall.py` | data: window 365→730d, `withhold_below` 0.80→1.05 (**above the encoding ceiling** — see below), `gist_below` 1.40→1.50, `cue_weight` 0.30→0.15 |
| Forgets the exchange while it is happening; delayed recall 0/3, cue-proof | `impairment/hold.py` | data: `crisp_turns` 1→**0**, `fade_turns` 3→2 — even the current exchange fades, the promise `cdr2.yaml` made ("total, cue-proof collapse of even the current exchange is CDR 3") |
| Cannot follow any multi-part question | `impairment/comprehension.py` | data: `long_question_probability` 0.85→0.95 (`long_question_clauses` stays 1 — the floor; 0 means *off*, not "holds nothing") |
| Word-finding frequent, speech effortful | `impairment/disfluency.py` | data: `word_finding_probability` 0.45→0.65 |
| Orientation to person only — place gone even at home, season and month gone | `impairment/voice.py` (the clock) | **new rung: `place: lost`** — the third rung `sprint3_cdr2.md` promised ("adds a third rung rather than a new field") |
| Recognition of the caregiver inconsistent | `impairment/voice.py` (the frame) | **new axis: `person: unfamiliar`** — the last orientation axis, reserved by `Orientation`'s docstring for "the sprint that degrades them" |
| Language simplifies | `impairment/voice.py` (a fragment) | **new: `speech.simplified_language`**, a per-turn style note |
| No insight | already `false` since CDR 2 | none |

## The two numbers that are really structure

**`withhold_below` is now above the encoding ceiling, on purpose.** Encoding is in
[0, 1); with `cue_weight` 0.15, reach cannot exceed ~1.15. A `withhold_below` of 1.05
therefore means an *uncued or weakly-cued* recent memory is **always** withheld —
encoding alone can never reach 1.05 — and only a squarely-aimed question landing on a
well-laid-down memory (encoding ≳ 0.90, cue ≈ 1.0) climbs past it, into gist and
never further (`gist_below` 1.50 stays above the ceiling too). That *is* "only
fragments remain": the common case is a blank, the best case is the shape of a thing
without its particulars, and nothing recent is ever crisp or even confidently hedged.
Cueing is not zeroed — `cue_weight` 0.15 keeps the fragment reachable — because a
cue that could never work would make the caregiver's best clinical tool inert, and
CDR3.md asks for *inconsistent* fragments, not a wall.

**`crisp_turns: 0` cashes the promise `cdr2.yaml` recorded.** Every profile so far
held the most recent exchange whole, because immediate registration outlasts
retention. At CDR 3 registration itself is failing: with `crisp_turns` 0, even the
exchange just completed fades (at 1/3 per word, rising to 2/3 one turn back, gone in
two), so she can lose the thread *while it is still the thread*. The mechanism needed
no change — `_fade_probability` already handles a zero crisp span — which is the
"severity is data" bet paying for the fourth time. The delayed-recall probe now fails
completely and cue-proof: by the time the probe arrives the words are not faded, they
are outside the window, and a cue has nothing to catch on. `hold.py`'s own docstring
called that "a different, later disease" when CDR 0.5 was being built. This is that
disease.

## The new rung: `place: lost`

`hazy` (CDR 2) withheld the time of day and the easy confidence about place, while
telling her that familiar surroundings still held her. `lost` withdraws that anchor
too: the frame no longer hands her the month, the year, the season, the part of day,
or where she is — **orientation to person only**, exactly the clinical phrase. What
the frame still asserts is the one thing that holds: who she is.

Same discipline as `mistaken` and `hazy`, unchanged: the frame **withholds** the
certainty she has lost; it never injects a false month or a false place, and
orientation is stored nowhere, so no memory is touched. She says "I don't know where
I am" or offers a guess marked as one — she is never *told* she is somewhere she is
not.

**The frame was not enough — the place gate (`impairment/orientation.py`), added after
the drive.** The first CDR 3 drive exposed the same failure `disfluency` and
`comprehension` were built for: a prompt cannot deliver a deficit against a memory the
model has been handed. Asked "where are you right now?", she recited "a third-floor
walk-up in Jamaica Plain" — her *authored* home address, which the recall gate rightly
never touches (it is ageless, so "where do you live?" works at every stage), rendered
straight into the prompt where the `lost` frame could not override it. The recall gate
degrades recent memory by *age*; nothing degraded the always-retrievable residence when
place orientation frayed. The place gate is that missing seam: whenever `place` is not
`confident`, it degrades the self-location memory in the trace — `hazy` **hedges** it
(the certainty goes, the content stays), `lost` **withholds** it and, mirroring the
recall gate's two passes, any expansion pulled in to explain it (the dated "I moved to
Jamaica Plain"). It is keyed on a curated set of location attributes (`city`,
`residence`, …) that deliberately excludes `hometown`, so the childhood home — remote
memory, preserved — is never touched, and it only ever withholds or hedges, never
invents. Re-driven clean: CDR 3 answers "where are you?" with "I do not know" while
"where did you grow up?" still surfaces its Rutland fragment.

## The last axis: `person: unfamiliar`

Recognition failing is the one CDR 3 symptom that touches the *Who is in the room*
rule, so its boundaries matter more than its prose.

**What it does.** The frame stops asserting that she knows who she is speaking with,
and tells her instead that the person's identity does not always come to her — she
may not know whether she has met them, and should say so honestly when she does not.

**What it must never do, and how that is kept.** Two hard lines:

1. **The I/you split is not softened.** The role-inversion bug — she once announced
   "I am your caregiver" and handed over her own home — was fixed by telling her
   plainly who is speaking, and failed recognition must not reopen it. So the
   fragment carries the pronoun grounding *inside itself*: whoever this person is,
   their "I" is always them and "you" is always her. She may not know *who* is
   speaking; she always knows it is not herself.
2. **Unfamiliarity, never misidentification.** Real patients misidentify — a nurse
   becomes a daughter — and `CDR3.md` lists exactly this ("misidentify… who is
   present", "confuse people") as an in-scope clinical feature. But a confident wrong
   name manufactures a false fact about a closed cast, and no severity loosens that
   rule. So this is **the one clinical feature the closed-cast rule cannot fully
   express**, and it is honoured the only way the architecture permits: as *honest
   non-recognition* — "I don't know who you are", a familiar face placed
   inconsistently — rather than a decided wrong identity. The fragment forbids the
   guess in as many words. This gap is recorded, not hidden: it is written into
   `CDR3.md`'s own implementation note and flagged as an open decision in the roadmap,
   so the stage gate does not treat a real divergence as silence. (Setting or
   situation may still be misjudged — place is injected and stored nowhere, so she may
   believe she is somewhere she is not; that is orientation, not confabulation.)

`memory.formation.CAREGIVER` is untouched: every disclosure still lands on the same
fixed subject, whoever she believes is speaking. Recognition is a property of *this
turn's speech*, exactly like the clock — which is why it lives in `voice.py` and
stores nothing.

## The fragment: `simplified_language` — and why a prompt can carry it

This project's record with prompt fragments is the reason `disfluency.py` and
`comprehension.py` exist: a soft note could not make qwen3:14b grope for a word or
drop part of a question. The lesson generalises as: **a prompt cannot make a capable
model perform a *deficit* — fail at something it can do.** It does not generalise to
register. Short sentences, plain vocabulary, one thought at a time is a *style*, the
kind of instruction a model follows willingly and observably — the same seam that
already carries her speech manner from the seed. So `simplified_language` is a
per-turn system-prompt fragment, constant like the clock rather than fired like
insight.

The fragment carries its own two guards, both learned elsewhere: it describes the
manner and quotes nothing (seed authoring rule 2 — a sample phrase becomes a
catchphrase), and it forbids the caricature in both directions — no babbling or
performed confusion, and no decorated fluency. If the drive shows the model declines
the register the way it declined the groping, the fallback is mechanical (a
post-generation pass, `disfluency`'s sibling) — but that is a mechanism the drive
must *earn*, not one built on suspicion.

## What is deliberately *not* built

The same discipline as every sprint, and at CDR 3 the temptations are stronger:

- **Community affairs, home and hobbies, personal care** — now at their clinical
  floor ("no pretence of independent function", "requires much help") and still
  without a conversational consumer. They stay in `CDR3.md` and out of `cdr3.yaml`.
  A parameter nothing reads is a lie in a config file, at every severity.
- **Misidentification** — a ground-truth CDR 3 feature (`CDR3.md`), not a deferred
  one, but the one the closed-cast rule cannot fully express: it is honoured as honest
  non-recognition rather than a decided wrong name (see the person axis above). The
  divergence is recorded, not dropped.
- **Hallucination, delusion, agitation, wandering, sundowning** — false-fact
  manufacture or engines the roadmap explicitly defers. `docs/future.md` or never.
- **A persistent distress / affect engine.** `CDR3.md` preserves emotional response —
  "show fear, seek comfort", "appear distressed… when unable to understand" — and
  lists a total loss of emotional response as a behaviour to avoid. So distress is
  *permitted*, not built: the orientation and recognition fragments no longer tell her
  the gaps do not trouble her (an earlier draft did, and that was wrong against the
  ground truth), and let genuine, momentary unease surface in her own voice. What is
  not built is a *sustained* distress or agitation engine — that is the "delirium-like
  fluctuation as the main feature" the spec puts out of scope, and it would be a
  stochastic engine besides.
- **A repetition engine** — still emergent, and at these numbers it should be
  constant: with a two-turn window fading from the first word, she does not recall
  having asked. If the drive shows otherwise, that transcript is where a mechanism
  gets argued for.
- **A language-collapse engine** — trimming her replies, capping sentence length in
  code. The fragment is being tried first because style is the one thing the seam
  demonstrably delivers; see above.
- **CDR 4/5 vocabulary** ("profound", "terminal") — not on the scale this project
  uses, and out of scope entirely.

## The gate, and what actually decides the sprint

Mechanics: `cdr3.yaml`, one rung, one axis, one fragment, and the tests that pin
CDR 3 as a strict rung past CDR 2 (window, thresholds, cue, fade, word-finding,
overrun), the person-only frame, the recognition guard, and the crisp-zero fade.
`make check` green is table stakes; the healthy regression must still prove the layer
switches off to nothing.

The sprint is judged, as all three before it were, on **the adversarial hand-drive
against a live model**, against the CDR 3 success criterion: *does a caregiver
conclude severe dementia within a few exchanges, while still meeting, unmistakably,
the same woman?* Concretely the drive must show: delayed recall 0/3 with a cue that
rescues nothing; the current topic lost within an exchange or two; day, month,
season, place all gone — including at home; at least one honest failure to place the
caregiver, with no invented identity; speech visibly simpler than CDR 2's; a genuine
remote fragment (the wedding, her father) surfacing *without* elaboration; constant
repetition without awareness; no insight; and — still and always — no confabulation
of any kind. The numbers in `cdr3.yaml` are starting values. The drive, not the
suite, is the gate.
