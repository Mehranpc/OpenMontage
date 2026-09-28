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


def test_repo_relative_project_paths_land_in_the_replay_project(tmp_path: Path) -> None:
    """The f418063 run passed `--request projects/<id>/search-request-0.json`; replay
    left it relative to its own cwd, so asset-search failed at the first search."""
    from scripts.persian_run_replay import _remap

    old = "/Users/someone/OpenMontage/projects/first-date-message-timing"
    new = tmp_path / "projects" / "first-date-message-timing"
    argv = ["asset-search", "first-date-message-timing", "--request",
            "projects/first-date-message-timing/search-request-0.json", f"--out={old}/x.json"]
    out = _remap(argv, old, new, {}, tmp_path / "store", tmp_path / "scratch")
    assert out[3] == str(new / "search-request-0.json")
    assert out[4] == f"--out={new}/x.json"
    assert out[1] == "first-date-message-timing"  # the project id itself is not a path


def test_a_poll_that_never_changes_gives_up(tmp_path: Path, monkeypatch) -> None:
    """A recorded poll whose replayed answer never reaches the recorded outcome (a
    skipped job) spun through thousands of subprocesses; it now stops after the
    stall window."""
    import scripts.persian_run_replay as mod

    assert mod.POLL_STALL_SECONDS <= 30


def test_a_budget_decision_replays_against_an_aged_window(tmp_path: Path) -> None:
    """The recorded run decided after a real wall-budget stop; replay runs in seconds,
    so it ages the window and persists the same stop before the decision."""
    import json

    from scripts.persian_run_replay import _age_budget_window
    from tests.lib.test_persian_video_workflow import _bootstrap_to_assets

    _bootstrap_to_assets(tmp_path)
    project = tmp_path / "run"
    _age_budget_window(project)
    state = json.loads((project / "persian-video-workflow.json").read_text(encoding="utf-8"))
    assert state["budget_stop"]["reason"] == "wall_budget_exceeded"
