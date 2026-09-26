"""#180: a moment-phrase change must have an owning recovery surface.

Observed on the L3 acceptance run (``p4-shadow-first-date-first-text-275bc22``):
``m-question`` needed 4.776s but could only ever hold 3.73s, because its anchor
pins its start and the next shot is a single full-frame hard region.

Shortening the phrase was refused by *every* class, and the two refusals are the
whole story:

* ``CAPTION_CONTINUITY`` -- ``changed scopes ['typography']``, allowed
  ``['captions.semantic_handoff', 'captions.cue_grouping']``. Its surface carries
  the ``copy`` scope but not ``typography``.
* ``FILM_TYPE_LAYOUT`` -- refused because its surface carried ``typography`` but
  not ``copy``.

A phrase edit touches both scopes, so the beat had no owner and the run dropped
it. The owner is now a class of its own, because the two obvious widenings are
each wrong: ``CAPTION_CONTINUITY`` is about the caption pipeline, and widening
``FILM_TYPE_LAYOUT`` would break the guarantee pinned by
``test_layout_recovery_can_retime_reveals_but_cannot_rewrite_copy``.
"""

from __future__ import annotations

from lib.persian_edit_workspace import _allowed_scopes
from lib.persian_recovery_policy import _CLASS_POLICIES, recovery_class_for_code


# The scopes a change to `persian.moments[].segments` produces: the moment's
# wording (`copy`) inside a typographic layout (`typography`).
_MOMENT_PHRASE_SCOPES = {"copy", "typography"}


def test_a_moment_phrase_change_has_an_owning_class() -> None:
    """The dedicated class must own both scopes a phrase change touches."""
    allowed = _allowed_scopes(
        _CLASS_POLICIES["EDITORIAL_MOMENT_COPY"]["mutationSurface"]
    )
    missing = _MOMENT_PHRASE_SCOPES - allowed
    assert not missing, (
        "a moment-phrase change would be refused for want of "
        f"{sorted(missing)}; allowed={sorted(allowed)}"
    )


def test_the_class_is_reachable_from_a_diagnostic_code() -> None:
    assert recovery_class_for_code("MOMENT_COPY_FIT") == "EDITORIAL_MOMENT_COPY"


def test_the_class_names_its_repair() -> None:
    strategies = _CLASS_POLICIES["EDITORIAL_MOMENT_COPY"]["strategies"]
    assert "tighten_editorial_moment_wording" in strategies


def test_the_approved_narration_stays_frozen_for_that_class() -> None:
    """Owning a moment's wording must never mean owning the approved words."""
    preserve = _CLASS_POLICIES["EDITORIAL_MOMENT_COPY"]["preserve"]
    assert "approved_script" in preserve
    assert "narration" in preserve


def test_a_layout_recovery_still_cannot_rewrite_copy() -> None:
    """The guarantee that ruled out the cheaper widening must still hold."""
    allowed = _allowed_scopes(_CLASS_POLICIES["FILM_TYPE_LAYOUT"]["mutationSurface"])
    assert "copy" not in allowed


def test_caption_continuity_keeps_its_own_scopes() -> None:
    allowed = _allowed_scopes(
        _CLASS_POLICIES["CAPTION_CONTINUITY"]["mutationSurface"]
    )
    assert {"captions", "copy", "timeline"} <= allowed
