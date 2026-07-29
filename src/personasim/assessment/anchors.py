"""The CDR's descriptive anchors, loaded from `anchors.yaml`.

The text itself lives in the YAML beside this module, and deliberately not here.
Two reasons, and the second is enforced:

- **It is clinical description, not logic.** A clinician should be able to correct
  the wording of what CDR 2 looks like without opening a Python file — the same
  argument that made severity a YAML profile rather than a branch.
- **The healthy core may not name a stage.** `tests/test_invariants.py` bans the
  vocabulary of impairment everywhere outside `impairment/`, and `assessment/` is
  outside it. Holding the anchors as data keeps that ban whole rather than
  carving an exception into it, which is the sort of exception that never gets
  taken back.

This module is the loader and nothing else. It caches, because the file is static
reference text and reading it per request would be silly.
"""

from __future__ import annotations

from functools import cache
from pathlib import Path
from typing import Any, cast

import yaml

ANCHOR_FILE = Path(__file__).parent / "anchors.yaml"


class AnchorError(Exception):
    """The anchor file is missing, unreadable, or not a possible anchor set."""


@cache
def _loaded() -> dict[str, Any]:
    try:
        raw = yaml.safe_load(ANCHOR_FILE.read_text())
    except OSError as exc:  # pragma: no cover - the file ships with the package
        raise AnchorError(f"cannot read {ANCHOR_FILE}: {exc}") from exc
    except yaml.YAMLError as exc:  # pragma: no cover
        raise AnchorError(f"{ANCHOR_FILE} is not valid YAML: {exc}") from exc
    if not isinstance(raw, dict):  # pragma: no cover
        raise AnchorError(f"{ANCHOR_FILE} must be a mapping")
    return cast(dict[str, Any], raw)


def cdr_rungs() -> tuple[float, ...]:
    """The rungs of the scale, in order. Not a range to be interpolated: 1.5 is
    not a rating a rater may give."""
    return tuple(float(rung) for rung in _loaded()["rungs"])


#: The rungs, as a constant for the many call sites that only ever read them.
CDR_RUNGS: tuple[float, ...] = cdr_rungs()


def domains() -> list[dict[str, str]]:
    """The rateable domains, in worksheet order. The three ADL domains are absent
    on purpose: a conversation cannot show them."""
    return [dict(entry) for entry in _loaded()["domains"]]


def rung_of(profile_name: str) -> float | None:
    """The CDR rung a profile stands at, or None if it is not on the scale."""
    found = _loaded()["profile_rungs"].get(profile_name)
    return None if found is None else float(found)


def anchor(domain: str, rung: float) -> str:
    """The descriptive anchor for one domain at one rung."""
    return str(_loaded()["anchors"][domain][_key(rung)])


def as_payload() -> dict[str, object]:
    """The whole anchor set, shaped for the browser's worksheet."""
    return {
        "rungs": list(CDR_RUNGS),
        "domains": domains(),
        "anchors": _loaded()["anchors"],
    }


def _key(rung: float) -> str:
    """YAML keys are strings, and `1.0` must find the `'1.0'` the file wrote."""
    return f"{float(rung):.1f}"
