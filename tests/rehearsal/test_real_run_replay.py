"""#264 acceptance: a real exported production run replays on the current code.

Fixture: `tests/fixtures/replay/first-date-f418063`, the 2026-09-28 Mac acceptance run
on f418063 (703 recorded command events). It holds the run's JSON state, command log
and recorded inputs, plus its provider recordings (search cache, transcript, word
timings). Every clip, the narration and the music are synthetic stand-ins at the
recorded geometry, frame rate and duration (`scripts/make_replay_fixture.py`); none of
the run's media are in the repository.

Without licensed browser measurement, commands 0-143 (bootstrap, alignment, plan and
both asset passes through candidate review) must reproduce the recorded exit codes.
Until #360 the prefix ran to command 239, the edit staged without the opening shot's
semantic fields; #305 keeps that refusal covered in test_opening_semantic_at_precheck,
and the region-review and budget-stop tail in the first-date and budget-stop scenarios.

With licensed Chromium measurement, #341 refuses the crowd carrier at command
143 instead: the free upper band cannot fit its actual copy. Replay must expose
that earlier refusal, not treat the historical successful review as approval.

Without measurement, #360 now refuses command 144: the run selected ev-1, a
typographic carrier, with no reviewed placement_space. The recorded run discovered
that only at command 157 (build-manifest exit 2) after twelve more selections, then
replaced eight of them. Shared admission moves that known blocker to selection.
"""
from __future__ import annotations

from pathlib import Path
import os


from scripts.persian_run_replay import recorded_commands, replay

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "replay" / "first-date-f418063"
MATCHED_PREFIX = 144
LATE_MANIFEST_REFUSAL = 157
MEASURED_PREFIX = 143


def test_the_real_run_replays_through_region_review_and_the_budget_stop(tmp_path, monkeypatch) -> None:
    export = FIXTURE / "export"
    commands = recorded_commands(export)
    measured = os.environ.get("OPENMONTAGE_L2_MEDIA_TESTS") == "1"
    prefix = MEASURED_PREFIX if measured else MATCHED_PREFIX
    expected_command = "workflow:asset-candidate-review" if measured else "workflow:asset-candidate-select"
    # The recorded run's late discovery that admission now pre-empts (#360).
    late = commands[LATE_MANIFEST_REFUSAL]
    assert late["command"] == "workflow:assets:build-manifest" and late["exit_code"] == 2
    assert len(commands) > prefix
    assert commands[prefix]["command"] == expected_command

    monkeypatch.setenv("OPENMONTAGE_REPLAY_WORK", str(tmp_path / "replay"))
    report = replay(export, until=prefix + 1, fixture=FIXTURE / "providers", media=False)

    assert report["replayed"] == prefix + 1
    first = report["first_difference"]
    assert first is not None and first["index"] == prefix, first
    assert first["command"] == expected_command
    assert first["recorded_exit"] == 0 and first["exit"] == 2
    diagnostic = "CARRIER_COPY_UNPLACEABLE" if measured else "[PLACEMENT_SPACE_MISSING] ev-1"
    assert diagnostic in first["detail"]
