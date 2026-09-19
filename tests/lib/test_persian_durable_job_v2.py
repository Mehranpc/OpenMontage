from __future__ import annotations

import json
from pathlib import Path
import sys
import time

import pytest

from lib.paths import REPO_ROOT
from lib.persian_durable_job import load_job, reconcile_job, start_job
from lib.json_safe import to_json_safe
from tools.base_tool import ToolResult


def test_json_safe_normalizes_tool_results_paths_and_sets(tmp_path: Path) -> None:
    result = ToolResult(
        success=True,
        data={"output": tmp_path / "candidate.mp4", "tags": {"render", "final"}},
        artifacts=[str(tmp_path / "candidate.mp4")],
    )
    safe = to_json_safe({"result": result})
    encoded = json.dumps(safe)
    assert "candidate.mp4" in encoded
    assert safe["result"]["success"] is True
    assert sorted(safe["result"]["data"]["tags"]) == ["final", "render"]


def test_start_job_records_canonical_execution_environment(tmp_path: Path) -> None:
    state = start_job(
        tmp_path,
        job_id="env",
        phase="render_final_candidate",
        argv=["python", "-c", "print('ok')"],
        idempotence_key="env-v2",
        launch=False,
    )
    context = state["executionContext"]
    expected_runtime = (tmp_path / ".workspace" / "runtime").resolve()
    assert Path(context["cwd"]).resolve() == expected_runtime
    assert Path(context["workspaceDir"]).resolve() == (tmp_path / ".workspace").resolve()
    assert Path(context["tempDir"]).resolve() == (tmp_path / ".workspace" / "tmp").resolve()
    assert Path(context["interpreter"]).resolve() == Path(sys.executable).resolve()
    assert str(REPO_ROOT.resolve()) in context["pythonPath"].split(":")
    assert state["command"][0] == sys.executable


def test_real_worker_imports_repo_and_persists_separate_outcomes(tmp_path: Path) -> None:
    marker = tmp_path / "context.json"
    code = (
        "import json, os, sys; from pathlib import Path; import lib.paths; "
        f"Path({str(marker)!r}).write_text(json.dumps({{'cwd': os.getcwd(), 'python': sys.executable, 'repo': str(lib.paths.REPO_ROOT)}}))"
    )
    start_job(
        tmp_path,
        job_id="real",
        phase="render_final_candidate",
        argv=["python", "-c", code],
        idempotence_key="real-v2",
    )
    final = None
    for _ in range(80):
        final = reconcile_job(tmp_path, "real")
        execution_terminal = final.get("status") in {"succeeded", "failed", "interrupted"}
        reporting_terminal = final.get("reportingOutcome") in {"succeeded", "failed"}
        if execution_terminal and (final.get("status") == "interrupted" or reporting_terminal):
            break
        time.sleep(0.1)
    assert final is not None and final["status"] == "succeeded"
    assert final["executionOutcome"] == "succeeded"
    assert final["reportingOutcome"] == "succeeded"
    observed = json.loads(marker.read_text())
    assert Path(observed["cwd"]).resolve() == (tmp_path / ".workspace" / "runtime").resolve()
    assert Path(observed["python"]).resolve() == Path(sys.executable).resolve()
    assert Path(observed["repo"]).resolve() == REPO_ROOT.resolve()


def test_reporting_failure_cannot_retroactively_fail_successful_execution(tmp_path: Path, monkeypatch) -> None:
    import lib.persian_durable_job as jobs

    state_path = tmp_path / ".jobs" / "j" / "state.json"
    result_path = state_path.with_name("result.json")
    state_path.parent.mkdir(parents=True)
    state = {
        "version": 2,
        "jobId": "j",
        "phase": "render_final_candidate",
        "status": "running",
        "command": [sys.executable, "-c", "print('ok')"],
    }
    state_path.write_text(json.dumps(state))

    original = jobs._atomic_json
    def fail_result_only(path, value):
        if Path(path) == result_path:
            raise TypeError("ToolResult is not JSON serializable")
        return original(path, value)
    monkeypatch.setattr(jobs, "_atomic_json", fail_result_only)

    jobs._record_finished_execution(state_path, exit_code=0, heartbeat_at="2026-09-15T00:00:00+00:00")
    persisted = load_job(tmp_path, "j")
    assert persisted["status"] == "succeeded"
    assert persisted["executionOutcome"] == "succeeded"
    assert persisted["reportingOutcome"] == "failed"
    assert "JSON serializable" in persisted["reportingError"]
