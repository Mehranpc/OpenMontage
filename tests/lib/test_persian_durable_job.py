from __future__ import annotations
import json, sys, time
from pathlib import Path
import pytest
from lib.persian_durable_job import DurableJobError, reconcile_job, start_job


def test_idempotence_key_reuses_same_logical_job(tmp_path: Path) -> None:
    argv = [sys.executable, "-c", "print('ok')"]
    first = start_job(tmp_path, job_id="j1", phase="preflight", argv=argv, idempotence_key="same", launch=False)
    second = start_job(tmp_path, job_id="j2", phase="preflight", argv=argv, idempotence_key="same", launch=False)
    assert first["jobId"] == second["jobId"] == "j1"
    assert second["idempotentReuse"] is True


def test_idempotence_key_refuses_different_command(tmp_path: Path) -> None:
    start_job(tmp_path, job_id="j1", phase="preflight", argv=["echo", "one"], idempotence_key="same", launch=False)
    with pytest.raises(DurableJobError, match="different command"):
        start_job(tmp_path, job_id="j2", phase="preflight", argv=["echo", "two"], idempotence_key="same", launch=False)


def test_reconcile_marks_dead_unfinished_worker_interrupted(tmp_path: Path) -> None:
    start_job(tmp_path, job_id="j1", phase="render", argv=["echo", "ok"], idempotence_key="render1", launch=False)
    path = tmp_path / ".jobs" / "j1" / "state.json"
    state = json.loads(path.read_text()); state.update({"status": "running", "workerPid": 99999999}); path.write_text(json.dumps(state))
    reconciled = reconcile_job(tmp_path, "j1")
    assert reconciled["status"] == "interrupted"
    assert "Inspect job.log" in reconciled["recoveryAction"]



def test_reconcile_keeps_live_orphan_child_running(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    start_job(tmp_path, job_id="j1", phase="render", argv=["echo", "ok"], idempotence_key="render1", launch=False)
    path = tmp_path / ".jobs" / "j1" / "state.json"
    state = json.loads(path.read_text())
    state.update({"status": "running", "workerPid": 99999999, "childPid": 4242, "processGroupId": 777})
    path.write_text(json.dumps(state))

    monkeypatch.setattr("lib.persian_durable_job._pid_alive", lambda pid: pid == 4242)
    monkeypatch.setattr("lib.persian_durable_job.os.getpgid", lambda pid: 777)
    reconciled = reconcile_job(tmp_path, "j1")
    assert reconciled["status"] == "orphaned_running"
    assert "do not retry" in reconciled["recoveryAction"]
    assert "finishedAt" not in reconciled


def test_reconcile_marks_orphan_interrupted_after_child_exits(tmp_path: Path) -> None:
    start_job(tmp_path, job_id="j1", phase="render", argv=["echo", "ok"], idempotence_key="render1", launch=False)
    path = tmp_path / ".jobs" / "j1" / "state.json"
    state = json.loads(path.read_text())
    state.update({"status": "orphaned_running", "workerPid": 99999999, "childPid": 99999998})
    path.write_text(json.dumps(state))
    reconciled = reconcile_job(tmp_path, "j1")
    assert reconciled["status"] == "interrupted"
    assert reconciled["finishedAt"]

def test_detached_worker_finishes_and_persists_result(tmp_path: Path) -> None:
    marker = tmp_path / "done.txt"
    start_job(
        tmp_path, job_id="j1", phase="preflight",
        argv=[sys.executable, "-c", f"from pathlib import Path; Path({str(marker)!r}).write_text('ok')"],
        idempotence_key="run1",
    )
    final = None
    for _ in range(40):
        final = reconcile_job(tmp_path, "j1")
        if final["status"] in {"succeeded", "failed", "interrupted"}: break
        time.sleep(0.1)
    assert final is not None and final["status"] == "succeeded"
    assert final["exitCode"] == 0 and marker.read_text() == "ok"
