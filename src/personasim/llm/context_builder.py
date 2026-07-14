"""Renders retrieved memory into prompt context.

This is where narrative determinism is cashed in. Retrieval already followed the
typed links, so a memory that *explains* another arrives with the relation that
binds them. The builder renders that relation explicitly, nested under the memory
it explains:

    - (2018-11-20) Took in Compass from a shelter
        · this happened because of: Her father died of a stroke that spring

The model is handed the causal bridge. It verbalizes it; it does not build one.
An untyped list of the same two memories would leave the model to guess how they
relate — and to guess differently each session.

The builder is pure: it reads a trace and a memory source and returns messages.
It never calls a model, so it can be tested without one.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from personasim.llm.base import ChatMessage, ChatRole
from personasim.llm.prompts import build_system_prompt
from personasim.models.conversation import Message, Role
from personasim.models.identity import Identity
from personasim.models.memory import (
    EpisodicMemory,
    LinkRelation,
    Memory,
    MemoryId,
    MemoryType,
    RelationshipMemory,
    SemanticMemory,
)
from personasim.models.trace import MemoryTrace, RetrievalIntent, RetrievedMemory
from personasim.retrieval.scope import Scope, scope_of
from personasim.retrieval.source import MemorySource

# How a typed link reads in plain language. The model is given the gloss, not the
# enum, so it verbalizes a relation rather than parroting a field name.
#
# `caused_by` and `led_to` say "a separate event" out loud. Nested under the memory
# they explain, they read as *part of it*: asked about her wedding in 2014, she
# recounted the argument from the birthday in 2011 as though it had happened at the
# altar. Both memories were true and the juxtaposition was a lie. The date was right
# there in the line and the model went straight past it, so the relation has to
# carry the separation itself.
RELATION_PHRASE: dict[LinkRelation, str] = {
    LinkRelation.CAUSED_BY: "this came about because of a separate, earlier event",
    LinkRelation.LED_TO: "this later brought about a separate event",
    LinkRelation.OCCURRED_DURING: "this happened during",
    LinkRelation.INVOLVES: "this involved",
    LinkRelation.CONCERNS: "this concerns",
}

CONNECTION_HEADING = (
    "These are connected to what you recalled above. Each happened on its own, "
    "separate occasion — do not describe one as part of another:"
)

# The bridge, said as a sentence about two events rather than implied by layout.
# `{other}` is the memory being explained.
CONNECTION_SENTENCE: dict[LinkRelation, str] = {
    LinkRelation.CAUSED_BY: '"{other}" came about because of this.',
    LinkRelation.LED_TO: 'This came about because of "{other}".',
    LinkRelation.OCCURRED_DURING: '"{other}" happened during this.',
    LinkRelation.INVOLVES: 'This is who "{other}" involved.',
    LinkRelation.CONCERNS: 'This is what "{other}" is about.',
}

SECTION_HEADING: dict[MemoryType, str] = {
    MemoryType.EPISODIC: "Things you have lived through:",
    MemoryType.SEMANTIC: "Things you know about yourself:",
    MemoryType.RELATIONSHIP: "People in your life:",
}

# A semantic memory whose subject is not `self` is a fact about the caregiver —
# something the persona was *told*, not something she is. Filed under "things you
# know about yourself", "my caregiver lives in Chicago" invites her to move there.
SELF = "self"
TOLD_HEADING = "Things the person you are speaking with has told you about themselves:"

# "Everything" and "in full" are load-bearing. Handed a list it reads as *notes*,
# the model fills what looks like a gap; handed the same list as the boundary of
# what it can recall, it stops at the edge.
PREAMBLE = (
    "Everything you can recall bearing on what was just said, in full.\n"
    "If it is written here, you DO remember it — so answer from it. Do not say it "
    "does not come to mind while it is sitting in front of you. A question that "
    'begins "do you remember…" is still answered from what you remember:'
)

# Said when retrieval found nothing. The model must be told that a blank is the
# correct answer, or it will helpfully produce a biography of its own.
#
# "If you are being asked about your own life" was too soft a hedge: asked what she
# had eaten, the model did not count breakfast as her life, and produced oatmeal
# with raisins — then, challenged on having dined before evening, produced a reason
# for that too. The blank has to be stated as a fact about her, not as a condition
# for her to evaluate.
NO_MEMORY = (
    "Nothing in your memory bears on this. You do not know the answer.\n"
    "That includes today: what you ate, whether you ate, where you have been, what "
    "you did this morning, how you slept. None of it is in your memory, so none of it "
    "is known to you. (The date and the time are the exception — you are told those, "
    "above, and you know them.)\n"
    "Say plainly that it does not come to mind. Do not invent an answer, and do not "
    "produce a plausible one because a blank feels unhelpful — a blank *is* the "
    "answer.\n"
    'Say it as a person would. "I don\'t remember", "it\'s gone", "no, I don\'t think '
    'so" — not "I do not have a memory of being outside today". You are drawing a '
    "blank, not filing a report."
)

# Small talk retrieves nothing by design. Saying "you have no memory of this"
# would make the persona disown a greeting.
NO_RECALL_NEEDED = "Nothing to recall here — this is small talk. Just answer as yourself."


# Retrieval already decided who the question is about — deterministically, from
# pronouns, in `retrieval.scope`. Say so. Left to work it out, the model answered
# "what do I do for a living?" with "I am a cartographer", holding nothing but the
# caregiver's job in the context it had been given: it did not misread the memory,
# it reached past it into identity. Identity is always present and always about her,
# and that is a strong pull. It is cheaper to state the answer to "whose question is
# this?" than to hope the model infers it twice a turn.
SCOPE_NOTE: dict[Scope, str] = {
    Scope.CAREGIVER: (
        "This question is about the person you are speaking with, NOT about you. "
        "Answer from what they have told you, and answer about THEM, in the second "
        'person: "You are a nurse", never "I am a nurse". You are not them, and their '
        "job is not your job. Do not answer with your own life."
    ),
    Scope.SELF: "This question is about you. Answer about yourself.",
    Scope.UNSCOPED: "",
}


def build_memory_context(trace: MemoryTrace, source: MemorySource) -> str:
    """Render one retrieval pass as the memory block of a system prompt."""
    if trace.is_empty:
        blank = NO_RECALL_NEEDED if trace.intent is RetrievalIntent.SMALL_TALK else NO_MEMORY
        return _with_scope(blank, trace)

    memories = _rehydrate(trace, source)
    direct, expansions = _partition(trace, memories)

    if not direct:
        return NO_MEMORY

    roles = _roles(source)
    lines = [PREAMBLE]

    for heading in _sections_in_rank_order(direct, memories):
        lines.append("")
        lines.append(heading)
        lines.extend(
            f"- {_render_direct(item, memories[item.memory_id], roles)}"
            for item in direct
            if _heading_for(memories[item.memory_id]) == heading
        )

    lines.extend(_render_connections(direct, expansions, memories, roles))
    return _with_scope("\n".join(lines), trace)


def _with_scope(context: str, trace: MemoryTrace) -> str:
    """Lead with whose question it is. Retrieval already knows."""
    note = SCOPE_NOTE[scope_of(trace.query)]
    return f"{note}\n\n{context}" if note else context


def _render_connections(
    direct: Sequence[RetrievedMemory],
    expansions: dict[MemoryId, list[RetrievedMemory]],
    memories: dict[MemoryId, Memory],
    roles: dict[str, str],
) -> list[str]:
    """The memories that *explain* the ones asked for, in a section of their own.

    They used to be nested beneath the memory they explained, which is how they
    read: as part of it. Asked about her wedding in 2014, she recounted the argument
    from a birthday in 2011 as though it had happened at the altar — both memories
    true, the juxtaposition a lie. The date sat right there in the line and the model
    went straight past it, and no wording of the label fixed it, because the
    *indentation* was making the claim.

    So they are pulled out and stated as separate occasions, with the connection
    spelled out in a sentence rather than implied by layout. The causal bridge is
    still handed over — that is the whole point of typed links — but it is handed
    over as a relation between two events, not as decoration on one.
    """
    connections = [
        (parent, link)
        for item in direct
        for parent, links in expansions.items()
        if parent == item.memory_id
        for link in links
        if link.via_relation is not None
    ]
    if not connections:
        return []

    lines = ["", CONNECTION_HEADING]
    for parent, link in connections:
        lines.append(f"- {_render(memories[link.memory_id], roles)}")
        lines.append(
            f"    · {CONNECTION_SENTENCE[link.via_relation].format(other=memories[parent].summary)}"
            if link.via_relation is not None
            else ""
        )
    return lines


def _heading_for(memory: Memory) -> str:
    """Which section a memory belongs under — by *subject*, not only by type."""
    if isinstance(memory, SemanticMemory) and memory.subject.casefold() != SELF:
        return TOLD_HEADING
    return SECTION_HEADING[memory.type]


def render_now(when: datetime | None = None) -> str:
    """What day it is, and what time. Told to her, never invented.

    This was improvised for a while, and that was a mistake. "What did you have for
    breakfast?" has no true answer — she did not really eat, so something has to be
    made up. "What day is it?" *does* have a true answer, and the system has known it
    all along. Making her invent a fact that was sitting in `datetime.now()` was
    inventing for the sake of it.

    So it is injected, exactly as identity is: a fact she is handed, not a memory she
    holds and not a sentence she composes. It needs no storage, because a clock is
    right by construction and a stored one would be wrong within the hour.

    A healthy person knows what day it is. Losing that is a *symptom*, which makes
    this the natural seam for Phase 2 to degrade — and it can, without touching a
    memory, because the truth is here rather than in the database.
    """
    now = when or datetime.now()
    return (
        f"Right now it is {now.strftime('%A, %-d %B %Y')}. "
        f"The time is {now.strftime('%-I:%M %p').lower()}.\n"
        "You know this the way anyone knows what day it is. If you are asked, say so "
        "plainly; do not guess, and do not say it does not come to mind.\n"
        "But say it as a person would, not as a clock would. Asked the day, you say "
        '"Monday" — not "it is Monday, the thirteenth of July, two thousand and '
        'twenty-six". Asked the time, you glance and say "just gone five" or "about '
        'half past" — nobody recites the minute unless they are asked for it. Give '
        "the whole date only if the whole date is what was wanted."
    )


def render_speaker(name: str) -> str:
    """Who "I" is, and who "you" is.

    Two people are in this conversation and the persona must never confuse them.
    Without this, asked "what do I do for a living?", she answered "I'm a
    cartographer" — reading the caregiver's "I" as her own while holding the
    caregiver's job in the context she had been handed.

    Note what this does *not* say. Told she was speaking to "your caregiver, the
    person who looks after you", the persona inverted the roles outright: she
    announced "I am your caregiver", gave away her own home as the caregiver's, and
    claimed the caregiver's city as hers. A healthy woman of thirty-eight does not
    have someone who looks after her, and handed that contradiction the model
    resolved it by swapping the two of them. `caregiver` is the right word for the
    domain and the wrong word to put in her mouth. She is simply told who is
    speaking, in terms that do not fight her identity.
    """
    return (
        f"You are speaking with someone. They are the only other person here, and "
        f"your memories call them 'my caregiver'.\n"
        f"In their messages, 'I', 'me' and 'my' always mean THEM — never you. "
        f"'You' and 'your' always mean YOU, {name}.\n"
        f'So "where do I live?" asks what you know about them, and "where do you '
        f'live?" asks about your own home. Never answer one as though it were the '
        f"other, and never speak as if you were them."
    )


def render_cast(source: MemorySource) -> str:
    """Everyone the persona knows, and the assertion that there is no one else.

    Not a retrieval result — the whole cast, on every turn. Who is in your life is
    identity-level knowledge: you do not need reminding that you have a brother in
    order to deny having a sister.

    It earns its place by killing the worst failure this layer has. Asked "how did
    your mother take it when he died?", the persona invented a mother, her silence,
    and her sleeplessness — a question's premise is enough to conjure a person out
    of nothing. It also stops the model reassigning the people it *does* have:
    handed her father's memory beside her wife's family home, it made Robert into
    Maya's father.

    Relationship memory is exhaustive by construction, so "there is no one else" is
    a true statement about the persona, not a convenient lie. It does assume a cast
    small enough to name in full — true of a Phase 1 persona, and worth revisiting
    if one ever grows a hundred acquaintances.
    """
    people = [
        f"{memory.person_name} ({memory.relation})"
        for name in dict.fromkeys(source.person_names())
        for memory in source.find_by_person(name)
        if isinstance(memory, RelationshipMemory)
    ]
    if not people:
        return ""

    # "No one else" is scoped to her *life*, and explicitly excludes the caregiver.
    # Left unqualified it denied the person she was speaking to: told the
    # caregiver's job, she then insisted she had never been told it, because the
    # caregiver was not on the list of people in her life. They are not *in* her
    # life; they are *in the room*.
    return (
        f"The people in your life are: {', '.join(people)}. There is no one else — "
        "besides the person you are speaking with, who is here now. If you are asked about a "
        "relative, a friend, or a colleague who is not on that list, then you do not "
        "have one. Say so about *yourself*, in your own words — 'I don't have a "
        "sister', not 'I don't remember your sister'. A question about your mother "
        "is a question about YOUR family, not about theirs. Do not invent "
        "the person, and do not repeat this instruction back: say it as you would "
        "say it. What you have been told about the person you are speaking with is yours to use."
    )


def build_messages(
    identity: Identity,
    trace: MemoryTrace,
    source: MemorySource,
    user_message: str,
    history: Sequence[Message] = (),
    *,
    now_text: str | None = None,
    voice_notes: str = "",
) -> list[ChatMessage]:
    """The full prompt for one turn: who you are, who you are talking to, what you
    recall, and what was said.

    `history` is the windowed transcript from working memory, and excludes the
    message being answered.

    `now_text` and `voice_notes` are the impairment layer's two hooks into the
    prompt: a replacement for `render_now()` when orientation is degraded, and
    per-turn speech fragments. Both default to nothing, and with the defaults the
    prompt is byte-for-byte the Phase 1 prompt.
    """
    memory_context = build_memory_context(trace, source)
    if voice_notes:
        memory_context = f"{memory_context}\n\n{voice_notes}"

    now_block = now_text if now_text is not None else render_now()
    system = build_system_prompt(
        identity,
        memory_context,
        cast=f"{now_block}\n\n{render_cast(source)}\n\n{render_speaker(identity.name)}".strip(),
    )
    return [
        ChatMessage(role=ChatRole.SYSTEM, content=system),
        *to_chat_messages(history),
        ChatMessage(role=ChatRole.USER, content=user_message),
    ]


def to_chat_messages(history: Sequence[Message]) -> list[ChatMessage]:
    """Map the domain's user/persona turns onto a chat model's user/assistant slots."""
    return [
        ChatMessage(
            role=ChatRole.USER if message.role is Role.USER else ChatRole.ASSISTANT,
            content=message.content,
        )
        for message in history
    ]


def _rehydrate(trace: MemoryTrace, source: MemorySource) -> dict[MemoryId, Memory]:
    """Trace entries carry a summary; rendering wants dates, places, and people."""
    resolved = ((memory_id, source.get(memory_id)) for memory_id in trace.memory_ids)
    return {memory_id: memory for memory_id, memory in resolved if memory is not None}


def _partition(
    trace: MemoryTrace, memories: dict[MemoryId, Memory]
) -> tuple[list[RetrievedMemory], dict[MemoryId, list[RetrievedMemory]]]:
    """Split what was asked for from what came along to explain it.

    An expanded memory is rendered only beneath the memory it explains — never as
    a standalone recollection, because the question never reached for it.
    """
    direct: list[RetrievedMemory] = []
    expansions: dict[MemoryId, list[RetrievedMemory]] = {}

    for item in trace.retrieved:
        if item.memory_id not in memories:
            continue
        parent = item.linked_from
        # An expansion whose parent did not survive rehydration has nothing to
        # hang beneath; render it directly rather than drop a real memory.
        if parent is not None and parent in memories:
            expansions.setdefault(parent, []).append(item)
        else:
            direct.append(item)

    return direct, expansions


def _sections_in_rank_order(
    direct: Sequence[RetrievedMemory], memories: dict[MemoryId, Memory]
) -> list[str]:
    """Lead with the section retrieval ranked highest, not a fixed order."""
    seen: dict[str, None] = {}
    for item in direct:
        seen[_heading_for(memories[item.memory_id])] = None
    return list(seen)


def _render_direct(item: RetrievedMemory, memory: Memory, roles: dict[str, str]) -> str:
    """Render a matched memory at whatever reach a recall gate left it.

    Three states, and the middle one is where very-mild impairment actually lives:

    - **whole** — the memory as authored, with its date, place and people.
    - **hedged** — all of it, but she does not fully trust it. This is what a
      recent memory feels like when it *does* come: the content is right and the
      confidence is not. Without this rung a direct question ("what did you have
      for breakfast?") cues perfectly and is answered perfectly, and the persona
      reads as healthy no matter what the thresholds say.
    - **gist** — the summary with no date, no place, no participants, *and* a
      statement that the specifics are missing. The statement is load-bearing:
      handed a bare summary the model treats the absence as a gap to fill helpfully,
      and fills it.
    """
    if item.detail_withheld:
        return (
            f"{memory.summary} — the shape of it is there, but the particulars "
            "(exactly when, exactly where, who else was there) will not come. Say "
            "the part you have and admit the rest escapes you. Do not reconstruct "
            "it, and do not guess: a blank you own is true, and a plausible detail "
            "is a lie."
        )

    rendered = _render(memory, roles)
    if item.hedged:
        return (
            f"{rendered} — this is right, but it does not come to you cleanly. Say "
            "it as someone half-sure of her own recollection: reach for it, allow "
            "yourself a moment, hedge it ('I think', 'as far as I recall'). Do not "
            "recite it as though it were on a card in front of you."
        )
    return rendered


def _render(memory: Memory, roles: dict[str, str]) -> str:
    match memory:
        case EpisodicMemory():
            return _render_episode(memory, roles)
        case RelationshipMemory():
            return _render_person(memory)
        case _:
            return memory.summary


def _roles(source: MemorySource) -> dict[str, str]:
    """Who each person is *to her*, so a participant list never has to be guessed at.

    Rendered as bare names, "with Maya Okonkwo, Robert Marsh, Tom Marsh" left the
    model to work out whose father Robert was — and asked to describe her wedding it
    got it wrong again, putting Maya's father under the umbrella when Robert is
    Elena's. The relation is data. Handing it over costs a parenthesis.
    """
    return {
        memory.person_name: memory.relation
        for name in dict.fromkeys(source.person_names())
        for memory in source.find_by_person(name)
        if isinstance(memory, RelationshipMemory)
    }


def _render_episode(memory: EpisodicMemory, roles: dict[str, str]) -> str:
    circumstances = [
        text
        for text in (
            memory.occurred_on.isoformat() if memory.occurred_on else None,
            memory.location,
        )
        if text
    ]
    prefix = f"({', '.join(circumstances)}) " if circumstances else ""

    people = [
        f"{person} (your {roles[person]})" if person in roles else person
        for person in memory.participants
    ]
    suffix = f" — with {', '.join(people)}" if people else ""
    return f"{prefix}{memory.summary}{suffix}"


def _render_person(memory: RelationshipMemory) -> str:
    detail = [f"your {memory.relation}", _closeness(memory.closeness)]
    if memory.known_since:
        detail.append(f"known since {memory.known_since.isoformat()}")
    return f"{memory.person_name} — {', '.join(detail)}. {memory.summary}"


def _closeness(value: float) -> str:
    """Closeness is a number to the ranker and a word to the model."""
    if value >= 0.85:
        return "you are very close"
    if value >= 0.6:
        return "you are close"
    if value >= 0.3:
        return "you are on good terms"
    return "you are distant"
