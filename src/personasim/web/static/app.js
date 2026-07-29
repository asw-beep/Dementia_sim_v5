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
//
// Domains, rungs and anchor text all come from /api/anchors. They were briefly
// written out here as well, which is how a page and a server end up disagreeing
// about what CDR 2 looks like; the coach quotes the same text back after the
// reveal, so there is exactly one copy and the server holds it.
let CDR_VALUES = [];
let DOMAINS = [];
let ANCHORS = {};

async function loadAnchors() {
  const data = await fetch("/api/anchors").then((r) => r.json());
  CDR_VALUES = data.rungs;
  DOMAINS = data.domains.map((d) => [d.key, d.label, d.note]);
  ANCHORS = Object.fromEntries(
    Object.entries(data.anchors).map(([domain, rungs]) => [
      domain,
      Object.fromEntries(Object.entries(rungs).map(([rung, text]) => [Number(rung), text])),
    ]),
  );
}

let ratings = {};
let armed = false; // two-step commit: first click arms, second commits

// ---------------------------------------------------------------- mode

async function loadMode() {
  try {
    const profile = await fetch("/api/profile").then((r) => r.json());
    assessing = Boolean(profile.assessment);
    // Only assessment mode has a worksheet to anchor, and a failure here must not
    // cost the chat: an interview with no anchors is degraded, not broken.
    if (assessing) await loadAnchors();
  } catch {
    assessing = false;
  }
  $("assess-note").classList.toggle("hidden", !assessing);
  $("mode-badge").classList.toggle("hidden", !assessing);

  // The hero says what this session actually is. In assessment mode that is a test
  // with a hidden answer; in plain mode it is a conversation, and promising a CDR
  // rating there would be promising something nobody is scoring.
  // No pronouns in any of it: the cast is a woman and a man, and the gallery is
  // the one screen that speaks about all of them at once.
  $("hero-line").textContent = assessing
    ? "Each patient carries a hidden cognitive state. Conduct the interview and decide their CDR rating from the conversation alone."
    : "Each patient is authored down to the last memory. Talk, then open “why?” on any answer to see what was recalled — and what was not.";
  $("hero-quiet").textContent = assessing
    ? "There is no visible indicator of decline. The conversation is the only instrument you have."
    : "Everything said comes from somewhere. Nothing is invented twice.";
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
      // An <article> holding one real <button>, rather than a button holding the
      // whole card: the CTA has to be the focusable thing, and a button inside a
      // button is invalid. The click listener sits on the article, so a mouse can
      // still hit anywhere and the CTA's click simply bubbles into it.
      const card = document.createElement("article");
      card.className = "card";
      card.innerHTML = `
        <div class="card-top">
          <span class="avatar" aria-hidden="true"></span>
          <div class="card-id">
            <h2></h2>
            <p class="card-sub"></p>
          </div>
        </div>
        <p class="desc"></p>
        <ul class="card-chips"></ul>
        <button class="cta" type="button"></button>`;

      card.querySelector("h2").textContent = p.name;
      card.querySelector(".avatar").textContent = initials(p.name);
      card.querySelector(".card-sub").textContent = summarise(p);
      card.querySelector(".desc").textContent = p.description ?? "";
      card.querySelector(".card-chips").replaceChildren(...chips(p));
      card.querySelector(".cta").textContent = assessing
        ? "Start interview →"
        : "Start conversation →";

      card.addEventListener("click", () => openChat(p));
      return card;
    }),
  );
}

// Initials, for the monogram. Not a portrait and not an emoji face: the card may
// only show what the seed file authored, and nothing authored says what anyone
// looks like.
function initials(name) {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((word) => word[0].toUpperCase())
    .join("");
}

// "Cartographer, retired" → the trade first, then whatever qualifies it. Age and
// trade both come from Identity; nothing here is inferred from her memories.
const trade = (p) => p.occupation.split(",")[0].trim();

const summarise = (p) => `${p.age} · ${trade(p)}`;

function chips(p) {
  const qualifiers = p.occupation
    .split(",")
    .slice(1)
    .map((part) => part.trim())
    .filter(Boolean)
    .map((part) => part[0].toUpperCase() + part.slice(1));

  return [`${p.age} years`, trade(p), ...qualifiers].map((text) => {
    const chip = document.createElement("li");
    chip.className = "card-chip";
    chip.textContent = text;
    return chip;
  });
}

// ---------------------------------------------------------------- chat

async function openChat(p) {
  persona = p;

  const res = await fetch(`/api/personas/${p.id}/session`, { method: "POST" });
  if (!res.ok) return alert("Could not start a conversation.");
  sessionId = (await res.json()).session_id;

  $("chat-name").textContent = p.name;
  $("chat-sub").textContent = `${p.occupation}  ${p.age} yrs`;
  messages.replaceChildren();
  ended.classList.add("hidden");
  reveal.classList.add("hidden");
  $("chat-body").classList.remove("hidden");
  composer.classList.remove("hidden");
  turns = 0;
  setEnabled(true);
  $("end").classList.remove("hidden");

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

// `into` is the live chat by default; review mode passes its own pane so the same
// bubble and the same why-panel render the finished interview.
function bubble(role, text, extra = "", into = messages) {
  const row = document.createElement("div");
  row.className = `row ${role}`;
  const b = document.createElement("div");
  b.className = `bubble ${extra}`;
  b.textContent = text;
  row.append(b);
  into.append(row);
  if (into === messages) messages.scrollTop = messages.scrollHeight;
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
    hint.textContent = "An overall CDR is required; domains are optional.";
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
  v === null || v === undefined ? "—" : `CDR ${v}`;

// The profile names are healthy, cdr05, cdr1, cdr2, cdr3 — the display should be
// exactly one of CDR 0, CDR 0.5, CDR 1, CDR 2, CDR 3, never the fuller prose the
// profile's own label carries (that's for the report, not the card).
const ACTUAL_DISPLAY = { healthy: "CDR 0", cdr05: "CDR 0.5", cdr1: "CDR 1", cdr2: "CDR 2", cdr3: "CDR 3" };
const fmtActual = (name) => ACTUAL_DISPLAY[name] ?? name;

function showReveal(outcome) {
  $("chat-body").classList.add("hidden");
  // The interview is over and cannot be resumed; offering to end it again is an
  // invitation to a 404.
  $("end").classList.add("hidden");

  $("reveal-actual").textContent = fmtActual(outcome.actual.name);
  $("reveal-yours").textContent = fmtCDR(outcome.ratings.global);

  const verdict = $("reveal-verdict");
  verdict.textContent = labelMatches(outcome.actual.name, outcome.ratings.global) ? "match" : "miss";
  verdict.className = `verdict ${verdict.textContent}`;

  // Per domain: what you said, and — from the coach — what she actually was, so
  // the row itself shows where the reading went wrong before any prose is read.
  const byDomain = Object.fromEntries((outcome.coach ?? []).map((r) => [r.domain, r]));
  const rows = DOMAINS.filter(([key]) => key !== "global").map(([key, label]) => {
    const reading = byDomain[key];
    const row = document.createElement("div");
    row.className = `reveal-domain${reading?.missed ? " missed" : ""}`;
    row.innerHTML =
      `<span class="ws-label"></span><span class="val"></span><span class="was"></span>`;
    row.querySelector(".ws-label").textContent = label;
    row.querySelector(".val").textContent = fmtCDR(outcome.ratings[key]);
    row.querySelector(".was").textContent = reading?.missed
      ? `she was ${fmtCDR(reading.actual)}`
      : "";
    return row;
  });
  $("reveal-domains").replaceChildren(...rows);

  showCoach(outcome.coach ?? []);
  $("reveal-report").textContent = outcome.report;
  reveal.classList.remove("hidden");
  reveal.scrollTop = 0;
}

// The coach: one card per domain, ordered so what you got wrong is read first.
// Evidence lines (indented by the coach, each naming its turns) are set apart from
// the prose — they are the part a trainee is meant to be able to point at.
const KIND_TITLE = {
  discriminating: "Misread",
  coverage: "Never asked",
  confirming: "Read correctly",
};

function showCoach(readings) {
  const order = { discriminating: 0, coverage: 1, confirming: 2 };
  const cards = [...readings]
    .sort((a, b) => order[a.kind] - order[b.kind])
    .map((reading) => {
      const card = document.createElement("section");
      card.className = `coach-card ${reading.kind}`;

      const head = document.createElement("h3");
      head.innerHTML = `<span class="tag"></span><span class="dom"></span>`;
      head.querySelector(".tag").textContent = KIND_TITLE[reading.kind] ?? reading.kind;
      head.querySelector(".dom").textContent = reading.domain;
      card.append(head);

      for (const line of reading.lines) {
        const p = document.createElement("p");
        p.className = line.startsWith("  ") ? "coach-evidence" : "coach-line";
        p.textContent = line.trim();
        card.append(p);
      }
      return card;
    });

  $("coach").replaceChildren(...cards);
  $("coach").classList.toggle("hidden", cards.length === 0);
}

// ---------------------------------------------------------------- history

// Committed interviews only — an abandoned draw is not an interview. Ordered
// newest first, and deliberately without a total: the CDR protocol certifies
// raters, this trains them.
async function loadHistory() {
  if (!assessing) return;
  const rows = await fetch("/api/assessments")
    .then((r) => r.json())
    .catch(() => []);

  $("history").classList.toggle("hidden", rows.length === 0);
  if (!rows.length) return;

  const cells = rows.map((row) => {
    const tr = document.createElement("tr");
    tr.className = row.hit ? "hit" : "miss";
    const when = new Date(row.at).toLocaleDateString(undefined, {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
    const r = row.ratings ?? {};
    for (const text of [
      when,
      fmtActual(row.actual.name),
      fmtCDR(r.global),
      fmtCDR(r.memory),
      fmtCDR(r.orientation),
      fmtCDR(r.judgment),
      fmtCDR(r.language),
    ]) {
      const td = document.createElement("td");
      td.textContent = text;
      tr.append(td);
    }
    const verdict = document.createElement("td");
    verdict.className = "verdict-cell";
    verdict.textContent = row.hit ? "match" : "miss";
    tr.append(verdict);
    return tr;
  });
  $("history-rows").replaceChildren(...cells);
}

// ---------------------------------------------------------------- review mode

// The finished interview, re-read with the answer key visible. The traces come
// from the session log rather than the page's own transcript: a blind session's
// exchanges never carried one, and this is the record that always did.
$("review").addEventListener("click", async () => {
  const res = await fetch(`/api/session/${sessionId}/review`);
  if (!res.ok) return;
  const data = await res.json();

  $("review-actual").textContent = fmtActual(data.actual.name);
  const pane = $("review-turns");
  pane.replaceChildren();
  for (const turn of data.turns) {
    bubble("user", turn.user, "", pane);
    attachWhy(bubble("persona", turn.persona, "", pane), turn.trace, []);
  }

  reveal.classList.add("hidden");
  $("review-view").classList.remove("hidden");
  $("review-view").scrollTop = 0;
});

$("review-back").addEventListener("click", () => {
  $("review-view").classList.add("hidden");
  reveal.classList.remove("hidden");
});

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
  reveal.classList.add("hidden");
  $("review-view").classList.add("hidden");
  gallery.classList.remove("hidden");
  // The interview just finished is the newest row, so the history is refreshed on
  // the way back rather than only at startup.
  loadHistory();
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

loadMode().then(loadPersonas).then(loadHistory);
