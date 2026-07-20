"use strict";

// The browser holds no persona state. It knows a session id and nothing else —
// every memory decision happens server-side, in the same orchestrator the CLI
// drives. If this file ever starts deciding what she remembers, something has gone
// badly wrong.
//
// In assessment mode it additionally holds the *worksheet* — the trainee's
// provisional ratings — which is theirs, not hers, and goes to the server exactly
// once: at commit. The blindness is server-side (blind sessions carry no trace);
// this file merely refrains from asking for what it would not be given.

const $ = (id) => document.getElementById(id);

const gallery = $("gallery");
const chat = $("chat");
const cards = $("cards");
const messages = $("messages");
const composer = $("composer");
const input = $("input");
const ended = $("ended");
const worksheet = $("worksheet");
const reveal = $("reveal");

let sessionId = null;
let persona = null;
let busy = false;
let assessing = false;
let turns = 0;

// The worksheet: the CDR's own vocabulary, restricted to what a conversation can
// show. The three ADL domains are deliberately absent — rating them from a chat
// would train a lie.
const CDR_VALUES = [0, 0.5, 1, 2, 3];
const DOMAINS = [
  ["memory", "Memory"],
  ["orientation", "Orientation"],
  ["judgment", "Judgment", "judgment and problem solving"],
  ["language", "Language", "supporting observation, not a CDR box"],
  ["global", "Global CDR"],
];

// The anchors, condensed from docs/disease_profiles/CDR*.md — the same ground truth
// the profiles were built against. They are here to be read *while* rating, which is
// the whole point: a trainee guessing from feel is not learning the scale. Kept to
// one line each; the doc is the long form.
const ANCHORS = {
  memory: {
    0: "No memory loss, or slight inconsistent forgetfulness.",
    0.5: "Consistent slight forgetfulness; the shape of a recent event survives, its details do not.",
    1: "Moderate loss, worse for recent events; important details go, questions repeat.",
    2: "Recent material is not retained — conversations forgotten soon after, order and timing confused.",
    3: "Only fragments remain; new information is lost almost immediately.",
  },
  orientation: {
    0: "Fully oriented.",
    0.5: "Oriented apart from slight trouble with time — unsure of the date or weekday, and corrects herself.",
    1: "Moderate difficulty with time relationships; still oriented to place during the interview.",
    2: "Wrong about date, weekday and recent timing; usually knows the setting, but not always.",
    3: "Orientation largely lost — time and often place gone; person known only in fragments.",
  },
  judgment: {
    0: "Solves everyday problems well; judgment sound.",
    0.5: "Everyday judgment intact; only long or multi-part questions cost visible effort.",
    1: "Complex problems are difficult and practical planning unreliable; social judgment usually holds.",
    2: "Overwhelmed by planning or sequencing; needs step-by-step prompting, judgment clearly impaired.",
    3: "Cannot compare options or solve problems; dependent on others for nearly every decision.",
  },
  language: {
    0: "Fluent; no word-finding trouble.",
    0.5: "Fluent overall, with an occasional pause or a way round a missing word.",
    1: "Obvious pauses for retrieval and vague wording, still comfortably fluent.",
    2: "Frequent pauses and broad substitutes — “that thing”, “the place”; effort is audible.",
    3: "Short phrases, fillers and broken sentences; even familiar things are hard to name.",
  },
  global: {
    0: "Healthy — nothing impaired to observe.",
    0.5: "Questionable dementia — subtle, and takes a sustained 15–20 minutes to see.",
    1: "Mild dementia — deficits are obvious and interfere with everyday life.",
    2: "Moderate dementia — sustained impairment, clear within a short interview.",
    3: "Severe dementia — the severity is apparent within moments.",
  },
};
let ratings = {};
let armed = false; // two-step commit: first click arms, second commits

// ---------------------------------------------------------------- mode

async function loadMode() {
  try {
    const profile = await fetch("/api/profile").then((r) => r.json());
    assessing = Boolean(profile.assessment);
  } catch {
    assessing = false;
  }
  $("assess-note").classList.toggle("hidden", !assessing);
  $("mode-badge").classList.toggle("hidden", !assessing);
}

// ---------------------------------------------------------------- gallery

async function loadPersonas() {
  const people = await fetch("/api/personas").then((r) => r.json());

  if (!people.length) {
    $("gallery-empty").classList.remove("hidden");
    return;
  }

  cards.replaceChildren(
    ...people.map((p) => {
      const card = document.createElement("button");
      card.className = "card";
      card.innerHTML = `
        <h2></h2>
        <p class="role"></p>
        <p class="desc"></p>`;
      card.querySelector("h2").textContent = p.name;
      card.querySelector(".role").textContent = `${p.occupation} · ${p.age}`;
      card.querySelector(".desc").textContent = p.description ?? "";
      card.addEventListener("click", () => openChat(p));
      return card;
    }),
  );
}

// ---------------------------------------------------------------- chat

async function openChat(p) {
  persona = p;

  const res = await fetch(`/api/personas/${p.id}/session`, { method: "POST" });
  if (!res.ok) return alert("Could not start a conversation.");
  sessionId = (await res.json()).session_id;

  $("chat-name").textContent = p.name;
  $("chat-sub").textContent = `${p.occupation} · ${p.age}`;
  messages.replaceChildren();
  ended.classList.add("hidden");
  reveal.classList.add("hidden");
  $("chat-body").classList.remove("hidden");
  composer.classList.remove("hidden");
  turns = 0;
  setEnabled(true);

  if (assessing) {
    resetWorksheet();
    worksheet.classList.remove("hidden");
    $("end").textContent = "End interview";
  } else {
    worksheet.classList.add("hidden");
    $("end").textContent = "End conversation";
  }

  gallery.classList.add("hidden");
  chat.classList.remove("hidden");
  input.focus();
}

function bubble(role, text, extra = "") {
  const row = document.createElement("div");
  row.className = `row ${role}`;
  const b = document.createElement("div");
  b.className = `bubble ${extra}`;
  b.textContent = text;
  row.append(b);
  messages.append(row);
  messages.scrollTop = messages.scrollHeight;
  return b;
}

// The memory trace. Folded away by default — the point is that it is *always
// there*, not that it is always in the way. A blind session's replies carry no
// trace at all (the trace is the answer key), so nothing is attached.
function attachWhy(bubbleEl, trace, formed) {
  if (!trace) return;

  const details = document.createElement("details");
  details.className = "why";

  const summary = document.createElement("summary");
  const n = trace.retrieved?.length ?? 0;
  summary.textContent = n ? `why? · ${n} memories` : "why? · nothing recalled";
  details.append(summary);

  const reason = document.createElement("p");
  reason.className = "reason";
  reason.textContent = trace.reason;
  details.append(reason);

  if (n) {
    const list = document.createElement("ul");
    for (const m of trace.retrieved) {
      const li = document.createElement("li");
      const score = document.createElement("span");
      score.className = "score";
      score.textContent = `[${m.score.toFixed(2)}] `;
      li.append(score, document.createTextNode(m.summary));

      if (m.via_relation) {
        const via = document.createElement("span");
        via.className = "via";
        via.textContent = ` ←${m.via_relation}`;
        li.append(via);
      }
      list.append(li);
    }
    details.append(list);
  }

  if (trace.withheld?.length) {
    const list = document.createElement("ul");
    list.className = "withheld";
    for (const m of trace.withheld) {
      const li = document.createElement("li");
      li.textContent = `withheld: ${m.summary} — ${m.reason}`;
      list.append(li);
    }
    details.append(list);
  }

  if (formed?.length) {
    const f = document.createElement("p");
    f.className = "formed";
    f.textContent = `remembered: ${formed.join("; ")}`;
    details.append(f);
  }

  bubbleEl.append(details);
}

function setEnabled(on) {
  busy = !on;
  input.disabled = !on;
  $("send").disabled = !on;
  $("end").disabled = !on;
}

composer.addEventListener("submit", async (event) => {
  event.preventDefault();
  const text = input.value.trim();
  if (!text || busy) return;

  bubble("user", text);
  input.value = "";
  setEnabled(false);

  const pending = bubble("persona", "…", "thinking");

  try {
    const res = await fetch(`/api/session/${sessionId}/message`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    });

    if (!res.ok) {
      const detail = (await res.json().catch(() => ({}))).detail ?? "Something went wrong.";
      pending.className = "bubble error";
      pending.textContent = detail;
      return;
    }

    const reply = await res.json();
    pending.className = "bubble";
    pending.textContent = reply.content;
    attachWhy(pending, reply.trace, reply.formed);
    turns += 1;
    refreshCommit();
  } catch {
    pending.className = "bubble error";
    pending.textContent = "Could not reach the persona.";
  } finally {
    setEnabled(true);
    input.focus();
    messages.scrollTop = messages.scrollHeight;
  }
});

// ---------------------------------------------------------------- worksheet

function resetWorksheet() {
  ratings = Object.fromEntries(DOMAINS.map(([key]) => [key, null]));
  armed = false;

  const rows = DOMAINS.map(([key, label, note]) => {
    const row = document.createElement("div");
    row.className = `ws-row${key === "global" ? " global" : ""}`;

    const name = document.createElement("span");
    name.className = "ws-label";
    name.textContent = label;
    if (note) {
      const aside = document.createElement("span");
      aside.className = "ws-note";
      aside.textContent = note;
      name.append(aside);
    }
    row.append(name);

    // The anchor for whatever the trainee is currently pointing at: the hovered
    // chip if there is one, the chosen rating otherwise. Hover reads the scale
    // without committing to it, which is how you compare two adjacent stages.
    const anchor = document.createElement("p");
    anchor.className = "ws-anchor";
    const showAnchor = (value) => {
      const shown = value === undefined ? ratings[key] : value;
      anchor.textContent = shown === null ? "" : ANCHORS[key][shown];
      anchor.classList.toggle("preview", value !== undefined && value !== ratings[key]);
    };

    const chips = document.createElement("div");
    chips.className = "chips";
    for (const value of CDR_VALUES) {
      const chip = document.createElement("button");
      chip.type = "button";
      chip.className = "chip";
      chip.textContent = String(value);
      chip.title = ANCHORS[key][value];
      chip.addEventListener("mouseenter", () => showAnchor(value));
      chip.addEventListener("focus", () => showAnchor(value));
      chip.addEventListener("click", () => {
        ratings[key] = ratings[key] === value ? null : value;
        for (const c of chips.children) c.classList.remove("on");
        if (ratings[key] !== null) chip.classList.add("on");
        showAnchor();
        armed = false;
        refreshCommit();
      });
      chips.append(chip);
    }
    chips.addEventListener("mouseleave", () => showAnchor());
    row.append(chips, anchor);
    return row;
  });

  $("ws-rows").replaceChildren(...rows);
  refreshCommit();
}

function refreshCommit() {
  const commit = $("commit");
  const hint = $("commit-hint");
  const ready = ratings.global !== null;

  commit.disabled = !ready;
  commit.textContent = armed ? "Click again to commit — this reveals the truth" : "Commit rating";
  commit.classList.toggle("armed", armed);

  if (!ready) {
    hint.textContent = "A global CDR is required; domains are optional.";
  } else if (turns < 8 && !armed) {
    hint.textContent = `Only ${turns} exchange${turns === 1 ? "" : "s"} so far — little evidence has been gathered.`;
  } else {
    hint.textContent = "";
  }
}

$("commit").addEventListener("click", async () => {
  if (ratings.global === null) return;
  if (!armed) {
    armed = true;
    refreshCommit();
    return;
  }

  $("commit").disabled = true;
  const res = await fetch(`/api/session/${sessionId}/commit`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(ratings),
  });
  if (!res.ok) {
    const detail = (await res.json().catch(() => ({}))).detail ?? "Could not commit.";
    $("commit-hint").textContent = detail;
    $("commit").disabled = false;
    armed = false;
    return;
  }

  showReveal(await res.json());
});

// ---------------------------------------------------------------- the reveal

const fmtCDR = (v) =>
  v === null || v === undefined ? "—" : v === 0 ? "CDR 0 (healthy)" : `CDR ${v}`;

function showReveal(outcome) {
  $("chat-body").classList.add("hidden");

  $("reveal-actual").textContent = outcome.actual.label;
  $("reveal-yours").textContent = fmtCDR(outcome.ratings.global);

  // A plain hit-or-miss on the global. The per-domain coaching is Sprint 3C;
  // until then the evidence ledger below is the explanation.
  const verdict = $("reveal-verdict");
  verdict.textContent = labelMatches(outcome.actual.name, outcome.ratings.global) ? "match" : "miss";
  verdict.className = `verdict ${verdict.textContent}`;

  const rows = DOMAINS.filter(([key]) => key !== "global").map(([key, label]) => {
    const row = document.createElement("div");
    row.className = "reveal-domain";
    row.innerHTML = `<span class="ws-label"></span><span class="val"></span>`;
    row.querySelector(".ws-label").textContent = label;
    row.querySelector(".val").textContent = fmtCDR(outcome.ratings[key]);
    return row;
  });
  $("reveal-domains").replaceChildren(...rows);

  $("reveal-report").textContent = outcome.report;
  reveal.classList.remove("hidden");
  reveal.scrollTop = 0;
}

// The profile names are healthy, cdr05, cdr1, cdr2, cdr3; the rating is a number.
function labelMatches(name, rating) {
  const map = { healthy: 0, cdr05: 0.5, cdr1: 1, cdr2: 2, cdr3: 3 };
  return map[name] === rating;
}

// ---------------------------------------------------------------- end & download

// Downloads the *current* conversation only — not her memory, not her past. In a
// blind session the turns carry no trace (the trace is the answer key); otherwise
// each turn's trace goes with it, because a record that cannot say why she
// answered as she did is half a record.
function downloadTranscript() {
  const a = document.createElement("a");
  a.href = `/api/session/${sessionId}/transcript`;
  a.download = `transcript-${sessionId.slice(0, 8)}.json`;
  a.click();
}

$("download").addEventListener("click", downloadTranscript);
$("download-ended").addEventListener("click", downloadTranscript);
$("download-reveal").addEventListener("click", downloadTranscript);

$("end").addEventListener("click", async () => {
  if (busy) return;
  setEnabled(false);

  const res = await fetch(`/api/session/${sessionId}/end`, { method: "POST" });
  const superseded = res.ok ? (await res.json()).superseded : 0;

  composer.classList.add("hidden");

  if (assessing) {
    // The interview is over; the rating is not. The worksheet stays live and the
    // commit is what moves things forward.
    ended.classList.remove("hidden");
    ended.querySelector("span").textContent = "Interview ended — commit your rating when ready.";
    ended.querySelector("#download-ended").classList.add("hidden");
    ended.querySelector("#back-ended").classList.add("hidden");
    return;
  }

  ended.classList.remove("hidden");
  ended.querySelector("#download-ended").classList.remove("hidden");
  ended.querySelector("#back-ended").classList.remove("hidden");
  ended.querySelector("span").textContent =
    superseded > 0
      ? `Conversation ended. ${superseded} memories were consolidated.`
      : "Conversation ended.";
});

const home = () => {
  sessionId = null;
  persona = null;
  chat.classList.add("hidden");
  gallery.classList.remove("hidden");
};

$("back").addEventListener("click", async () => {
  // Leaving is ending. Working memory does not survive a session, and a session
  // nobody closes is one the log never sees the end of. If the banner is showing,
  // it has already been ended.
  const stillLive = sessionId && ended.classList.contains("hidden") && reveal.classList.contains("hidden");
  if (stillLive) {
    await fetch(`/api/session/${sessionId}/end`, { method: "POST" }).catch(() => {});
  }
  home();
});
$("back-ended").addEventListener("click", home);
$("reveal-back").addEventListener("click", home);

loadMode().then(loadPersonas);
