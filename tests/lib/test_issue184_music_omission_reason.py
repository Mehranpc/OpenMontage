"""#184: an omitted music bed needs a decision, not a promise.

Observed on the L3 acceptance run (``p4-shadow-first-date-first-text-0b78c56``):
the promoted edit artifact carried

    "Placeholder pending music acquisition; music bed to be attached before promote."

and the film shipped, rendered, and reached ``awaiting_human`` with no music bed
while the manifest calls music required in narrated mode. The gate accepted it
because the check was "is the reason non-empty" -- so a note-to-self passed as a
recorded decision and then described a film that did not exist.

The distinction these tests pin: a film may legitimately be delivered without
music, and may not be delivered with music *promised*.
"""

from __future__ import annotations

import pytest

from lib.persian_music import audit_music


_PLACEHOLDER = (
    "Placeholder pending music acquisition; music bed to be attached before promote."
)
_DECISION = (
    "The film is deliberately narration-only; the pacing carries without a bed."
)


def test_a_placeholder_reason_is_refused() -> None:
    audit = audit_music(track=None, narrated=True, omit_music_reason=_PLACEHOLDER)
    assert audit.problems, "a deferring reason must not pass as a decision"


@pytest.mark.parametrize(
    "reason",
    [
        "TODO: pick a bed",
        "TBD",
        "music to be added later",
        "not yet sourced",
        "will be attached before promote",
    ],
)
def test_deferral_markers_are_refused(reason: str) -> None:
    audit = audit_music(track=None, narrated=True, omit_music_reason=reason)
    assert audit.problems, f"{reason!r} defers rather than decides"


def test_a_real_decision_still_passes_as_an_advisory() -> None:
    audit = audit_music(track=None, narrated=True, omit_music_reason=_DECISION)
    assert not audit.problems
    assert audit.advisories


def test_no_reason_at_all_is_still_refused() -> None:
    audit = audit_music(track=None, narrated=True, omit_music_reason="")
    assert audit.problems
