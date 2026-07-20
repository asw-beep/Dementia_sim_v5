"""Phase 3: assessment — a reader of finished sessions, and nothing more.

Everything in this package aggregates what the session log already recorded: the
trace behind every turn, the notes each impairment mechanism appended, the probe
questions the caregiver asked. It computes by rule and renders text. It never calls
a model (an explanation a model wrote would vary between two readings and could be
wrong — the same reason formation may not consult one), never infers a severity
from a transcript (the actual stage is the loaded profile, known by construction),
and never reaches into the simulator to change anything.
"""

from personasim.assessment.anchors import CDR_RUNGS, anchor, rung_of
from personasim.assessment.coach import Feedback, FeedbackKind, coach
from personasim.assessment.ledger import Ledger, build_ledger
from personasim.assessment.probes import ProbeType, classify_probe
from personasim.assessment.report import render_report

__all__ = [
    "CDR_RUNGS",
    "Feedback",
    "FeedbackKind",
    "Ledger",
    "ProbeType",
    "anchor",
    "build_ledger",
    "classify_probe",
    "coach",
    "render_report",
    "rung_of",
]
