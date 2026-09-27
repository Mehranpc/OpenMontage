"""Offline full-pipeline rehearsal of the recorded first-date run (#260).

The phases up to the edit precheck need no licensed font and run in every suite. The
browser part (edit preflight onward) needs real Chromium plus the licensed Kahroba font,
so it runs only in the L2 CI job (`OPENMONTAGE_L2_MEDIA_TESTS=1`).
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from scripts.persian_rehearsal import DEFAULT_FIXTURE, Rehearsal

L2 = os.environ.get("OPENMONTAGE_L2_MEDIA_TESTS") == "1"


def _rehearse(tmp_path: Path, until: str) -> dict:
    return Rehearsal(DEFAULT_FIXTURE, tmp_path, echo=False).rehearse(until=until)


def test_recorded_run_reaches_the_edit_phase_offline(tmp_path: Path) -> None:
    result = _rehearse(tmp_path, "regions")
    assert result["ok"], result["failure"]
    assert result["next_phase"] == "no_copy_preflight"
    # The real run needed ~66 min to get here; any regression that re-introduces a
    # late refusal or a slow path shows up in this number.
    assert result["wall_seconds"] < 180


@pytest.mark.skipif(not L2, reason="needs Chromium and the licensed Kahroba font (L2 CI job)")
def test_recorded_run_passes_edit_preflight_with_the_named_remedies(tmp_path: Path) -> None:
    result = _rehearse(tmp_path, "edit")
    assert result["ok"], result["failure"]
    assert result["next_phase"] == "render_opening_candidate"
