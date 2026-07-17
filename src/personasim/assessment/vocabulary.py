"""The note vocabulary: the contract between the impairment layer and this reader.

Impairment mechanisms explain themselves by appending short notes to
`trace.reason`, each under a stable prefix. Those notes are strings, not
structured fields — a deliberate decision (see `docs/design/phase3_assessment.md`):
four stable prefixes did not justify touching a Phase 1 model. The price of that
decision is paid here, once: this module is the only place the phrases are known,
and a test pins both sides — the emitters produce these shapes, this parser reads
them — so a reworded note breaks loudly instead of silently orphaning the ledger.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

#: `trace.reason` is the base retrieval reason plus appended notes, joined "; ".
_SEPARATOR = "; "

#: The fade and the overrun share a prefix — both are working-memory events — and
#: are told apart by their content, pinned below.
WORKING_MEMORY_PREFIX = "working memory: "
WORD_FINDING_PREFIX = "word-finding: "
ORIENTATION_PREFIX = "orientation: "

#: Inside the working-memory prefix: the transcript fade ("2 earlier exchanges
#: fading, 9 words slipped") versus the long-question overrun ("a 5-part question
#: overran; kept only the last 1"). Note the overrun itself contains "; " — the
#: parser below re-joins what the split broke.
_FADE_MARK = " slipped"
_OVERRUN_MARK = " overran"

#: The recall gate's summary counts, appended to the reason by `_rebuilt`.
_RECALL_SUMMARY = re.compile(r"^\d+ (out of reach|in outline only|recalled but unsure)$")


class NoteKind(StrEnum):
    FADE = "fade"
    OVERRUN = "overrun"
    WORD_FINDING = "word_finding"
    ORIENTATION = "orientation"
    RECALL_SUMMARY = "recall_summary"


@dataclass(frozen=True)
class Note:
    kind: NoteKind
    text: str


def notes_of(reason: str) -> list[Note]:
    """Every mechanism note in a trace's reason, in order.

    The base retrieval reason also uses "; " internally, so parts are matched by
    prefix, never by position. An overrun note is itself split by the separator
    ("…overran; kept only the last 1") and is re-joined with its continuation.
    """
    notes: list[Note] = []
    parts = reason.split(_SEPARATOR)
    index = 0
    while index < len(parts):
        part = parts[index]
        if part.startswith(WORKING_MEMORY_PREFIX):
            body = part.removeprefix(WORKING_MEMORY_PREFIX)
            if _OVERRUN_MARK in body and index + 1 < len(parts):
                index += 1
                body = f"{body}{_SEPARATOR}{parts[index]}"
                notes.append(Note(NoteKind.OVERRUN, body))
            elif body.endswith(_FADE_MARK):
                notes.append(Note(NoteKind.FADE, body))
        elif part.startswith(WORD_FINDING_PREFIX):
            notes.append(Note(NoteKind.WORD_FINDING, part.removeprefix(WORD_FINDING_PREFIX)))
        elif part.startswith(ORIENTATION_PREFIX):
            notes.append(Note(NoteKind.ORIENTATION, part.removeprefix(ORIENTATION_PREFIX)))
        elif _RECALL_SUMMARY.match(part):
            notes.append(Note(NoteKind.RECALL_SUMMARY, part))
        index += 1
    return notes


class WithheldKind(StrEnum):
    """Why a found memory was kept out of reach — read off its recorded reason."""

    RECENT_RECALL = "recent_recall"  # the recall gate: poorly laid down, out of reach
    PLACE = "place"  # the place gate: she cannot say where she is
    EXPANSION = "expansion"  # followed a memory that itself did not come to mind
    OTHER = "other"


#: The reason phrases the gates write into `WithheldMemory.reason`, pinned.
_WITHHELD_RECENT = "recent ("
_WITHHELD_PLACE = "disoriented to place"
_WITHHELD_EXPANSION = "connected to a memory that did not come to mind"


def withheld_kind(reason: str) -> WithheldKind:
    if reason.startswith(_WITHHELD_RECENT):
        return WithheldKind.RECENT_RECALL
    if reason.startswith(_WITHHELD_PLACE):
        return WithheldKind.PLACE
    if reason.startswith(_WITHHELD_EXPANSION):
        return WithheldKind.EXPANSION
    return WithheldKind.OTHER
