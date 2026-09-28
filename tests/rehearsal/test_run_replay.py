"""#264: a recorded run replays on the current code, and replay notices a change.

The rehearsal (#260) is recorded exactly like a production run: argv, JSON input
bytes, checkpoint writes and exit codes. Replaying that recording on unchanged
code reproduces every exit code, including the refusals the run met.
"""
from __future__ import annotations

from pathlib import Path

from scripts.persian_rehearsal import DEFAULT_FIXTURE, PROJECT_ID, Rehearsal
from scripts.persian_run_replay import recorded_commands, replay


def test_recorded_rehearsal_replays_with_identical_outcomes(tmp_path: Path, monkeypatch) -> None:
    result = Rehearsal(DEFAULT_FIXTURE, tmp_path / "run", echo=False).rehearse(until="regions")
    assert result["ok"], result["failure"]
    project = tmp_path / "run" / "projects" / PROJECT_ID
    commands = recorded_commands(project)
    assert commands[0]["command"] == "workflow:bootstrap" and commands[0]["argv"]
    assert any(cmd["command"].startswith("checkpoint:") for cmd in commands)
    refusals = [cmd for cmd in commands if cmd.get("exit_code") not in (0, None)]
    assert refusals, "the recording must include the run's refusals (#262 hook proof, #261 band)"

    monkeypatch.setenv("OPENMONTAGE_REPLAY_WORK", str(tmp_path / "replay"))
    report = replay(project)
    assert report["ok"], report["first_regression"]
    assert report["first_difference"] is None, report["first_difference"]
    assert report["replayed"] == len(commands)
