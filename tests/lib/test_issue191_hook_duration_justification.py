"""#191: a hold justification must decide, not defer.

Third instance of the class #184 fixed twice: a recorded reason standing in for the
thing the gate requires. Here the "thing" is a deliberate editorial hold, and any
non-empty string used to waive a *blocking* dead-air problem.
"""
from __future__ import annotations

import pytest

from lib.persian_hook_quality import audit_persian_hook_quality
from tests.lib.test_issue26_production_hardening import _hook_edit

FLAG = "HOOK_TYPOGRAPHIC_DURATION_EXCESS"
# The #184 string, unchanged: it is the note-to-self this class is defined by.
PLACEHOLDER = "Placeholder pending review; hold to be shortened before promote."


def _over_long_hold(justification: str | None = None) -> dict:
    """A 5.0s hold on text whose text-derived budget is well under it."""
    edit = _hook_edit("بازی؟", source_text="بازی؟", anchors=["بازی"])
    edit["persian"]["moments"][0]["endSeconds"] = 5.0
    edit["persian"]["typographicBeats"][0]["endSeconds"] = 5.0
    if justification is not None:
        edit["metadata"]["hookQuality"]["typographicDurationJustification"] = justification
    return edit


def _flagged(edit: dict) -> bool:
    return any(FLAG in problem for problem in audit_persian_hook_quality(edit)["problems"])


def test_a_deferring_justification_does_not_waive_the_dead_air_problem() -> None:
    assert _flagged(_over_long_hold()), "the over-long hold must be refused to begin with"

    assert _flagged(_over_long_hold(PLACEHOLDER)), (
        "a note-to-self must not clear a blocking problem"
    )
    # Every phrase below carries a deferral marker from the shared predicate. The
    # predicate is a fixed marker list and is coarse by design: a deferral phrased
    # outside it still passes, on all three surfaces that use it. That ceiling is
    # recorded on #191, not claimed closed here.
    for deferral in ("TBD", "will be shortened before promote", "to be added later"):
        assert _flagged(_over_long_hold(deferral)), deferral


def test_a_deferring_justification_cannot_flip_the_audit_to_acceptable() -> None:
    """The disposition is what a reviewer reads, so it must not be bought by saying
    something rather than deciding something."""
    audit = audit_persian_hook_quality(_over_long_hold(PLACEHOLDER))

    assert audit["disposition"] != "acceptable"
    assert audit["typographicDuration"]["justified"] is False


def test_a_genuine_editorial_decision_still_waives_the_problem() -> None:
    """The hold may legitimately be deliberate; it may not be promised."""
    audit = audit_persian_hook_quality(
        _over_long_hold("User-directed deliberate hold for an opening title card.")
    )

    assert not _flagged(_over_long_hold("User-directed deliberate hold for an opening title card."))
    assert audit["typographicDuration"]["justified"] is True


def test_an_absent_justification_still_refuses_unchanged() -> None:
    assert _flagged(_over_long_hold(None))


def test_a_hold_inside_its_budget_needs_no_justification_either_way() -> None:
    """The rule only ever concerns an over-budget hold; a deferring string on a legal
    hold is inert, exactly as a genuine one is. This pins that the fix did not turn the
    justification into a required field."""
    edit = _hook_edit("بازی؟", source_text="بازی؟", anchors=["بازی"])
    # 2.0s is inside the 2.4s text-derived floor for this text; the fixture's default
    # 2.9s is already over it.
    edit["persian"]["moments"][0]["endSeconds"] = 2.0
    edit["persian"]["typographicBeats"][0]["endSeconds"] = 2.0
    edit["metadata"]["hookQuality"]["typographicDurationJustification"] = PLACEHOLDER

    audit = audit_persian_hook_quality(edit)

    assert audit["typographicDuration"]["actualSeconds"] == 2.0
    assert not any(FLAG in problem for problem in audit["problems"])
