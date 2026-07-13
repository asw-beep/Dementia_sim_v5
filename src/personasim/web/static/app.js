"use strict";

// The browser holds no persona state. It knows a session id and nothing else —
// every memory decision happens server-side, in the same orchestrator the CLI
// drives. If this file ever starts deciding what she remembers, something has gone
// badly wrong.

const $ = (id) => document.getElementById(id);

const gallery = $("gallery");
const chat = $("chat");
const cards = $("cards");
const messages = $("messages");
const composer = $("composer");
const input = $("input");
const ended = $("ended");

let sessionId = null;
let persona = null;
let busy = false;

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
  composer.classList.remove("hidden");
  setEnabled(true);

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
// there*, not that it is always in the way. A response she cannot account for is a
// bug, and this is where the account lives.
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
  } catch {
    pending.className = "bubble error";
    pending.textContent = "Could not reach the persona.";
  } finally {
    setEnabled(true);
    input.focus();
    messages.scrollTop = messages.scrollHeight;
  }
});

// ---------------------------------------------------------------- end & download

// Downloads the *current* conversation only — not her memory, not her past. The
// transcript carries each turn's trace with it: a record that cannot say why she
// answered as she did is half a record.
function downloadTranscript() {
  const a = document.createElement("a");
  a.href = `/api/session/${sessionId}/transcript`;
  a.download = `transcript-${sessionId.slice(0, 8)}.json`;
  a.click();
}

$("download").addEventListener("click", downloadTranscript);
$("download-ended").addEventListener("click", downloadTranscript);

$("end").addEventListener("click", async () => {
  if (busy) return;
  setEnabled(false);

  const res = await fetch(`/api/session/${sessionId}/end`, { method: "POST" });
  const superseded = res.ok ? (await res.json()).superseded : 0;

  composer.classList.add("hidden");
  ended.classList.remove("hidden");
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
  const stillLive = sessionId && ended.classList.contains("hidden");
  if (stillLive) {
    await fetch(`/api/session/${sessionId}/end`, { method: "POST" }).catch(() => {});
  }
  home();
});
$("back-ended").addEventListener("click", home);

loadPersonas();
