"""#387: under v3_staged the opening hook is the video's first frame.

Owner review of the acceptance-3 render (main d4fc955): the designed hook appeared
0.347s into the video, because the hook moment was anchored like any other moment
(first spoken word minus the 0.25s lead-in). Under v3 the hook must start at 0.0s;
retiming derives that start and keeps the hook's end, and the edit precheck and
compose refuse a v3 opening hook that starts later. v2 is unchanged.
"""
from __future__ import annotations

import copy

import pytest

from lib.persian_moments import audit_moments, build_moments
from lib.persian_scenes import _film_motion
from lib.persian_sync import TimedWord, anchor_moments, audit_sync, retime_moments
from tests.lib.test_issue271_moment_pacing_in_precheck import _edit, _pacing, _words

# The acceptance-3 shape: the first word is spoken at 0.597s -> anchored start 0.347s.
FIRST_WORD = 0.597


def _late_edit(profile: str | None) -> dict:
    edit = _edit(end=12.0)
    persian = edit["persian"]
    persian["moments"][0].update(startSeconds=0.347, endSeconds=4.947)
    persian["audio"]["wordTimings"] = (
        _words("پیام بدی یا صبر کنی", FIRST_WORD)
        + _words("پیام فوری علاقه رو واضح‌تر نشون می‌داد", 8.0)
    )
    if profile:
        persian["pipelineProfile"] = profile
    return edit


@pytest.fixture
def v3(monkeypatch):
    monkeypatch.setenv("OPENMONTAGE_PIPELINE_PROFILE", "v3_staged")


def _moments(edit):
    return build_moments(edit["persian"]["moments"])


def _words_of(edit):
    return TimedWord.from_dicts(edit["persian"]["audio"]["wordTimings"])


def test_anchoring_puts_the_opening_hook_on_frame_zero_only_when_asked():
    edit = _late_edit(None)
    plain = anchor_moments(_moments(edit), _words_of(edit))
    assert plain[0].derived_start == pytest.approx(0.347)
    at_zero = anchor_moments(_moments(edit), _words_of(edit), opening_hook_at_zero=True)
    assert at_zero[0].derived_start == 0.0
    # Later moments keep their narration anchoring.
    assert at_zero[1].derived_start == plain[1].derived_start


def test_retime_starts_the_hook_at_zero_and_keeps_its_end():
    edit = _late_edit(None)
    kwargs = dict(simultaneous_hook_typography=True, film_motion=_film_motion())
    before = retime_moments(_moments(edit), _words_of(edit), **kwargs)[0]
    after = retime_moments(_moments(edit), _words_of(edit), opening_hook_at_zero=True, **kwargs)[0]
    assert after.start_seconds == 0.0
    assert after.end_seconds == pytest.approx(before.end_seconds)


def test_v3_audit_refuses_a_late_opening_hook_and_v2_does_not():
    edit = _late_edit(None)
    late = audit_moments(_moments(edit), duration_seconds=20.0, v2=True, opening_hook_at_zero=True)
    assert any("must start at 0.0s" in problem for problem in late.problems)
    v2 = audit_moments(_moments(edit), duration_seconds=20.0, v2=True)
    assert not any("must start at 0.0s" in problem for problem in v2.problems)
    fixed = copy.deepcopy(edit)
    fixed["persian"]["moments"][0]["startSeconds"] = 0.0
    ok = audit_moments(_moments(fixed), duration_seconds=20.0, v2=True, opening_hook_at_zero=True)
    assert not any("must start at 0.0s" in problem for problem in ok.problems)


def test_a_zero_start_hook_passes_the_sync_audit():
    edit = _late_edit(None)
    edit["persian"]["moments"][0]["startSeconds"] = 0.0
    assert audit_sync(_moments(edit), _words_of(edit), opening_hook_at_zero=True).passed


def test_the_v3_precheck_refuses_a_late_opening_hook(v3):
    found = [d for d in _pacing(_late_edit("v3_staged")) if "must start at 0.0s" in d.message]
    assert found and found[0].message.startswith("m-hook ")


def test_the_v2_precheck_is_unchanged():
    assert not [d for d in _pacing(_late_edit(None)) if "must start at 0.0s" in d.message]
