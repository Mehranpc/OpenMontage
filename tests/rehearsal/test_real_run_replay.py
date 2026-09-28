"""#264 acceptance: a real exported production run replays on the current code.

Fixture: `tests/fixtures/replay/first-date-f418063`, the 2026-09-28 Mac acceptance run
on f418063 (703 recorded command events). It holds the run's JSON state, command log
and recorded inputs, plus its provider recordings (search cache, transcript, word
timings). Every clip, the narration and the music are synthetic stand-ins at the
recorded geometry, frame rate and duration (`scripts/make_replay_fixture.py`); none of
the run's media are in the repository.

Commands 0-238 of that run (bootstrap, alignment, plan, both asset passes, plan
reconciliation, region review, the hook gate, the wall-budget stop and its decision)
must reproduce the recorded exit codes. Command 239 is the edit the run staged
without the opening shot's semantic fields; since #305 it is refused before a
candidate is spent, which is the fix this run exposed.
"""
from __future__ import annotations

from pathlib import Path


from scripts.persian_run_replay import recorded_commands, replay

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "replay" / "first-date-f418063"
MATCHED_PREFIX = 239


def test_the_real_run_replays_through_region_review_and_the_budget_stop(tmp_path, monkeypatch) -> None:
    export = FIXTURE / "export"
    commands = recorded_commands(export)
    assert len(commands) > MATCHED_PREFIX
    assert commands[MATCHED_PREFIX]["command"] == "workflow:edit-stage"

    monkeypatch.setenv("OPENMONTAGE_REPLAY_WORK", str(tmp_path / "replay"))
    report = replay(export, until=MATCHED_PREFIX + 1, fixture=FIXTURE / "providers", media=False)

    assert report["replayed"] == MATCHED_PREFIX + 1
    first = report["first_difference"]
    assert first is not None and first["index"] == MATCHED_PREFIX, first
    assert first["command"] == "workflow:edit-stage"
    assert "shot.opening_semantic_missing" in first["detail"]
