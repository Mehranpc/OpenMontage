"""#264 acceptance: a real exported production run replays on the current code.

Fixture: `tests/fixtures/replay/first-date-f418063`, the 2026-09-28 Mac acceptance run
on f418063 (703 recorded command events). It holds the run's JSON state, command log
and recorded inputs, plus its provider recordings (search cache, transcript, word
timings). Every clip, the narration and the music are synthetic stand-ins at the
recorded geometry, frame rate and duration (`scripts/make_replay_fixture.py`); none of
the run's media are in the repository.

Without licensed browser measurement, commands 0-238 (bootstrap, alignment, plan, both asset passes, plan
reconciliation, region review, the hook gate, the wall-budget stop and its decision)
must reproduce the recorded exit codes. Command 239 is the edit the run staged
without the opening shot's semantic fields; since #305 it is refused before a
candidate is spent, which is the fix this run exposed.

With licensed Chromium measurement, #341 refuses the crowd carrier at command
143 instead: the free upper band cannot fit its actual copy. Replay must expose
that earlier refusal, not treat the historical successful review as approval.
"""
from __future__ import annotations

from pathlib import Path
import os


from scripts.persian_run_replay import recorded_commands, replay

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "replay" / "first-date-f418063"
MATCHED_PREFIX = 239
MEASURED_PREFIX = 143


def test_the_real_run_replays_through_region_review_and_the_budget_stop(tmp_path, monkeypatch) -> None:
    export = FIXTURE / "export"
    commands = recorded_commands(export)
    measured = os.environ.get("OPENMONTAGE_L2_MEDIA_TESTS") == "1"
    prefix = MEASURED_PREFIX if measured else MATCHED_PREFIX
    expected_command = "workflow:asset-candidate-review" if measured else "workflow:edit-stage"
    assert len(commands) > prefix
    assert commands[prefix]["command"] == expected_command

    monkeypatch.setenv("OPENMONTAGE_REPLAY_WORK", str(tmp_path / "replay"))
    report = replay(export, until=prefix + 1, fixture=FIXTURE / "providers", media=False)

    assert report["replayed"] == prefix + 1
    first = report["first_difference"]
    assert first is not None and first["index"] == prefix, first
    assert first["command"] == expected_command
    assert first["recorded_exit"] == 0 and first["exit"] == 2
    diagnostic = "CARRIER_COPY_UNPLACEABLE" if measured else "shot.opening_semantic_missing"
    assert diagnostic in first["detail"]
