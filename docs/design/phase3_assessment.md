# Phase 3 — assessment mode: training a caregiver's eye through blind interview

The first *consumer* of the simulator, and the reason it was built: **a caregiver
interviews a patient without knowing her stage, rates her while they talk, commits to
a CDR, and only then learns the truth — with the evidence they used, missed, or never
elicited laid out beside their answer.** Repeated with a different hidden stage each
time — including, deliberately, a healthy one — this is diagnosis practice through
pure conversation.

This document supersedes the first Phase 3 scope: same foundations (the evidence
ledger, the no-LLM invariant, the honesty boundary), sharpened into a training loop.

## What real practice says

The design is not invented from taste; it mirrors how CDR raters are actually made:

- **The CDR is a semi-structured interview scored against descriptive anchors.** The
  Washington University Knight ADRC — the instrument's home — certifies raters by
  having them rate gold-standard interview cases blind and comparing their ratings
  against the established scores (the Brief Training & Reliability Protocol). Our
  loop is that protocol with one upgrade: the trainee *conducts* the interview
  rather than watching a video of one, so the skill of *eliciting* evidence is
  trained alongside the skill of reading it.
- **Simulation training works when it is deliberate practice**: repeated, varied
  cases with immediate, structured, evidence-linked feedback — consistently more
  effective than didactic teaching for clinical reasoning. Every design choice below
  serves that loop: vary the case (the draw), make the trainee commit (the
  worksheet), close the loop at once (the reveal), make the feedback specific (the
  coach), allow re-study (review mode).
- **False positives are a trained-away error.** A rater who only ever sees disease
  learns to find it everywhere. Healthy is therefore a first-class case in the draw,
  not a control afterthought — exactly the user's requirement, and the reason
  `healthy.yaml` was kept reachable from the first day of Phase 2.

## What we already have, and where it leaks

Everything the loop needs to *explain* already exists: every turn persists its full
trace (withheld memories with arithmetic, fade/overrun/word-finding/orientation notes
under four stable prefixes); severities are ordered data in five YAML files; the
`CDR*.md` specs are fixed anchor text; the 15-probe comparison script is a validated
probe bank; the web UI already runs profiled sessions.

What does not exist is **blindness**. Today the truth leaks from five places, and 3B
must seal each:

1. `/api/profile` returns the loaded profile's label.
2. Every message sent to the browser carries its trace (`Exchange.trace`) — the
   `why?` panel names withheld memories and reasons. **The trace is the answer key.**
3. The transcript download includes those traces.
4. `./run start` / `./run status` and the server log print the profile label.
5. Structurally: `SessionStore` fixes one profile per *server* at construction. A
   blind draw must happen per *session*, or every interview in a sitting has the
   same answer.

Blindness is a UI contract, not a security boundary: an operator with the database
or the CLI can always look. That is fine — the trainee is asked not to cheat
themselves, same as any self-administered practice — but it is stated, not implied.

## The loop

**1. The draw.** Opening an assessment session draws a hidden profile — uniform over
`{healthy, cdr05, cdr1, cdr2, cdr3}`. The draw is *genuinely random, on purpose*:
the hash-not-roll invariant exists so an impaired session replays identically, and
that reasoning protects `impairment/` — the draw's one job is to be unguessable, so
`assessment/` uses a real RNG and the ban stays scoped where its reason lives. The
drawn label is written to storage for the reveal and appears nowhere else: not in
the API, not in the log, not in `./run status` (which shows `assessment (hidden)`).
Weights are data and may later be tuned (e.g. oversampling the hard 0 / 0.5 / 1
boundaries); uniform is the starting value.

**2. The interview.** Pure conversation, as today. Two optional supports, both
static data: an **interview guide** — a probe checklist distilled from the CDR's
semi-structured shape and our validated probe bank (orientation to time and place, a
three-word delayed recall, a multi-part instruction, recent episodic questions,
remote biography, word-finding observation) — and the **anchor text** from
`CDR*.md`, the same descriptive anchors a WU rater sees. Training wheels, not rails:
the guide suggests, never enforces.

**3. The worksheet.** Alongside the chat, the trainee rates as they go — provisional,
adjustable at any time, in the CDR's own vocabulary (0 / 0.5 / 1 / 2 / 3) — but only
for what a conversation can show: **memory**, **orientation**, **judgment** (as far
as the overrun expresses it), plus **language** as a supporting observation, and one
**global** rating. The three ADL domains are not on the worksheet; a conversation
cannot show them, and pretending otherwise would train a lie. (For the same reason
the Washington University global-scoring algorithm is not computed — it needs all
six domains. The global here is the trainee's holistic judgment, which is the skill
being trained.)

**4. The commitment.** Ending the conversation locks the transcript; submitting the
worksheet locks the rating. Only then does anything reveal. A prediction that can be
revised after a peek is not a prediction — the WU protocol has the same property.

**5. The reveal.** The actual stage, the trainee's rating beside it, per domain, and
the evidence ledger (Sprint 3A) underneath: what the session actually showed, each
line naming its turn.

**6. The coach — "what you missed".** Three kinds of feedback, all computed by rule,
none by a model:

- **Discriminating evidence** (rated ≠ actual): for each domain, the turns whose
  recorded behaviour separates the two stages. The profiles are ordered data, so the
  diff is mechanical: *"You rated memory CDR 0.5. At turn 6 the three-word list came
  back 0 of 3 with no response to cueing — at 0.5 the expected pattern is 2 of 3, or
  1 with a cue. See also turn 9, where breakfast was withheld outright."* Phrased
  from the profile numbers and the spec anchors; every claim carries a turn number.
- **Coverage** — the feedback only an *active* interview can get, and the most
  valuable: what was never elicited. The ledger knows which probe types the session
  contains; if orientation was never probed, the coach says so: *"Nothing in this
  transcript could separate 0.5 from 1 on orientation — the day was never asked."*
  Missed diagnoses are more often failures of elicitation than of reading, and this
  trains exactly that.
- **Confirming evidence** (rated = actual): the turns that carried the signal, so a
  right answer consolidates instead of just passing.

**7. Review mode.** After the reveal, the trace panel unlocks over the finished
transcript: the trainee re-reads the interview with the answer key visible, each
reply's `why?` now showing what was withheld and why. All the data already exists;
this is the cheapest high-value feature in the phase.

**8. The record.** Each assessment is stored — session, actual stage, the committed
worksheet — and a plain history lists them: date, actual, rated, hit or miss, per
domain. That is the whole record. **No grades, no percentage scores, no
certification, no leaderboard**: the WU protocol certifies raters; we train them.
The history is a mirror, not a mark — a trainee who keeps calling healthy patients
CDR 0.5 will see the column of misses themselves.

## What stays true from the first scope

- **The reveal is a replay, not a judgment.** `assessment/` never imports
  `personasim.llm` (invariant test, same reason as formation) — a model-written
  explanation would vary between readings and could be wrong.
- **The system never diagnoses.** The actual CDR is the drawn profile, known by
  construction — never inferred from the transcript. A severity inferrer would be a
  second scorer to tune the simulator against.
- **The honesty boundary.** Three domains evidenced; three named as unobservable in
  conversation; language as supporting evidence.
- **Trace notes stay prefix-tagged strings**, vocabulary pinned by test on both the
  emitting and parsing sides.

## The sprints

**3A — the evidence ledger** (unchanged foundation, one addition). `persona assess
<session-id>`: the deterministic per-domain report — recall fates split remote vs
recent, orientation withholdings, overruns, word-finding cadence, every line naming
its turn, the profile's intended numbers beside the observed behaviour. *Addition:*
the ledger also classifies **probe coverage** — which probe types the interview
contains and which are absent — because the coach's coverage feedback and the
discriminating diff both read from it. CLI only; drives before tests, as ever.

**3B — the blind loop.** The per-session draw (the `SessionStore` change), the five
leaks sealed, the worksheet with anchors and the optional guide, commit, and the
reveal showing actual + rating + raw ledger. The assessments table (additive — a new
table, no change to any existing schema, keeping the Phase 1 promise). Exit: a blind
end-to-end interview in the browser; the trace panel demonstrably absent in blind
mode and intact outside it; a healthy draw indistinguishable in the UI from an
impaired one until reveal.

**3C — the coach.** The discriminating-evidence diff, coverage feedback, confirming
evidence, review mode, and the history list. Exit — the phase's one success
criterion: **a trainee who rates wrongly can point, after the reveal, to the
specific turns they misread or the probes they never asked — in the transcript's own
words.** Judged by hand-driven blind sessions at every stage including healthy, with
the misses examined.

## Not in Phase 3 — do not build these

- **LLM-generated feedback or summaries**, however fluent — the invariant, again.
- **Severity inference from transcripts** — the anti-goal.
- **Grades, scores, certification, leaderboards** — history only.
- **Adaptive difficulty / spaced repetition over the draw** — `docs/future.md`; the
  weights are data, so it needs no architecture when it earns its place.
- **An informant-interview mode** — the only honest route to the three ADL domains
  (a clinician rates those from a collateral source, and a second simulated voice
  could someday provide one) — `docs/future.md`, explicitly, so the idea is kept
  without being built.
- **Random persona generation** — Phase 4. The draw varies the *profile* over the
  one authored persona; varying the *person* is a different, larger thing.
- **New symptoms, mechanisms, or profile fields** — a gap a drive exposes is a
  Phase 2 amendment argued with a transcript, never a Phase 3 feature.

## Open decisions (recommendations made; say so if they should go the other way)

1. **Prediction storage: a new `assessments` table** (session id, actual profile,
   per-domain + global rating, committed-at) rather than a sidecar file — it is
   relational data about a session, and the table is purely additive.
2. **Worksheet granularity: three domains + language + global**, per the honesty
   boundary. A global-only worksheet would be simpler but trains less and starves
   the coach of its per-domain diff.
3. **Draw weights: uniform to start**, held as data. Revisit after real trainees
   miss in a pattern.
4. **Short interviews: warn, don't block.** Committing after three turns gets
   *"little evidence has been gathered — commit anyway?"*; a hard minimum would
   train turn-counting, not interviewing.
