"""#264: the command log records enough to replay a run.

The first-date export had 483 command events with names only: no arguments, no
inputs, no outcome. A replay can re-run commands only if the log records the
exact argv, the bytes of each JSON file handed in, and the exit code.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from lib import persian_video_workflow as workflow
from lib.persian_workflow_telemetry import command_events_path
from tests.lib.test_persian_video_workflow import _bootstrap


def _events(root: Path) -> list[dict]:
    return [json.loads(line) for line in command_events_path(root).read_text(encoding="utf-8").splitlines()]


def test_start_records_argv_and_input_snapshot_finish_records_exit(tmp_path: Path, monkeypatch) -> None:
    _bootstrap(tmp_path)
    monkeypatch.setattr(workflow, "PROJECTS_DIR", tmp_path)
    root = tmp_path / "run"
    evidence = root / ".workspace" / "e.json"
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text('{"attempt_id": "base"}', encoding="utf-8")
    argv = ["complete", "run", "--phase", "no_copy_preflight", "--evidence-json", str(evidence)]
    code = workflow.run_recorded_cli("run", "workflow:complete", argv, lambda: 3)
    assert code == 3
    evidence.write_text('{"attempt_id": "changed later"}', encoding="utf-8")
    start, finish = _events(root)[-2:]
    assert start["edge"] == "start" and start["argv"] == argv
    digest = start["inputs"]["--evidence-json"]
    stored = root / ".telemetry" / "inputs" / f"{digest}.json"
    # The bytes the command actually read, not the file's later contents.
    assert stored.read_text(encoding="utf-8") == '{"attempt_id": "base"}'
    assert digest == hashlib.sha256(stored.read_bytes()).hexdigest()
    assert finish["edge"] == "finish" and finish["exit_code"] == 3 and "argv" not in finish


def test_a_refusal_records_its_exit_code(tmp_path: Path, monkeypatch) -> None:
    _bootstrap(tmp_path)
    monkeypatch.setattr(workflow, "PROJECTS_DIR", tmp_path)

    def refuse():
        raise SystemExit(2)

    try:
        workflow.run_recorded_cli("run", "workflow:complete", ["complete", "run"], refuse)
    except SystemExit:
        pass
    assert _events(tmp_path / "run")[-1]["exit_code"] == 2


def test_every_json_file_flag_is_snapshotted() -> None:
    """A file flag missing from the list silently breaks replay of that command."""
    import re

    sources = "".join(Path(f"lib/{name}.py").read_text(encoding="utf-8") for name in (
        "persian_video_workflow", "persian_run_kernel", "persian_delivery_quality"))
    flags = set(re.findall(r'add_argument\(\s*"(--[a-z-]*json)"', sources))
    flags |= set(re.findall(r'add_argument\(\s*"(--[a-z-]+)"[^)]*metavar="PATH"', sources))
    flags -= {"--narration", "--approved-script-file"}  # bootstrap inputs, copied into the project
    assert flags <= set(workflow._REPLAY_INPUT_FLAGS), sorted(flags - set(workflow._REPLAY_INPUT_FLAGS))
