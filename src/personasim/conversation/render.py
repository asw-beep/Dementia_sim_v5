"""Rendering a memory trace for a human.

The trace is the answer to "why did she say that". It is a data structure first —
`persona trace` is sequenced before the web panel precisely so the trace is forced
into a readable form while it is still honest, rather than being reshaped around a
UI component.

This module formats. It decides nothing.
"""

from __future__ import annotations

from collections.abc import Sequence

from personasim.models.conversation import Turn
from personasim.models.trace import MemoryTrace, RetrievedMemory

# A replayed trace shows the memories *as they read at the time*. Summaries can be
# rewritten since — `persona seed --force` exists precisely so they can be — so a
# replay may quote text that no longer exists anywhere. That is correct for a log
# and misleading for a memory browser, and the difference has to be said out loud.
HISTORICAL_NOTE = (
    "This is a record of what was retrieved at the time, not a view of memory now. "
    "Summaries edited since (`persona seed --force`) still read here as they read then."
)


def render_session(turns: Sequence[Turn], *, session_id: str) -> str:
    """A whole session, replayed: what was said, what was answered, and why.

    The `why` is the point. A response the persona cannot account for is a bug, and
    until this existed the account was locked in a JSON column nobody read.
    """
    if not turns:
        return f"session {session_id}: no turns recorded."

    lines = [f"session {session_id} — {len(turns)} turns", HISTORICAL_NOTE, ""]

    for number, turn in enumerate(turns, start=1):
        lines.append(f"[{number}] you> {turn.user_message.content}")
        lines.append(f"    her> {turn.persona_message.content}")
        lines.append("")
        lines.append(render_trace(turn.trace, indent="    "))
        lines.append("")

    return "\n".join(lines)


def render_trace(trace: MemoryTrace, *, indent: str = "  ") -> str:
    """One retrieval pass, as a human reads it."""
    lines = [f"{indent}{trace.reason}"]

    if trace.is_empty:
        lines.append(f"{indent}  (nothing retrieved — she is speaking from identity alone)")
        return "\n".join(lines)

    for memory in trace.retrieved:
        lines.append(f"{indent}  {_render_memory(memory)}")

    return "\n".join(lines)


def _render_memory(memory: RetrievedMemory) -> str:
    """Score, type, summary — and, for an expanded memory, the relation that
    dragged it in. A memory the question never asked for is the interesting one:
    it is there to explain, and the trace should say so."""
    head = f"[{memory.score:.2f}] {memory.memory_type.value[:4]}  {memory.summary}"

    if memory.was_expanded and memory.via_relation is not None:
        return f"{head}   <-{memory.via_relation.value}-"

    if memory.matched_keywords:
        return f"{head}   on {memory.matched_keywords}"

    return head
