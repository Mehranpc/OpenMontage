from pathlib import Path


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one anchor, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


kernel = Path("lib/persian_run_kernel.py")
checkpoint_helper = '''

def _enforce_execution_checkpoint(
    project_id: str,
    *,
    operation: str,
    phase: str,
    job_id: str,
    pipeline_dir: Path | None,
) -> None:
    """Stop a live parent at a safe control boundary without discarding its durable child."""
    try:
        state = workflow.enforce_front_door_budget(
            project_id,
            operation=operation,
            pipeline_dir=pipeline_dir,
            operation_evidence={"phase": phase, "job_id": job_id},
        )
    except workflow.PersianVideoWorkflowError as exc:
        raise PersianRunKernelError(str(exc)) from exc
    stop = state.get("budget_stop")
    if (
        state.get("status") == "failed"
        and isinstance(stop, Mapping)
        and stop.get("reason") in {"wall_budget_exceeded", "phase_budget_exceeded"}
    ):
        raise PersianRunKernelError(
            f"{stop.get('reason')}: workflow budget already stopped durable job {job_id!r}; "
            "reconcile/status remains available until an explicit resume decision"
        )
'''
replace_once(
    kernel,
    "\n\ndef _artifact_identity(evidence: Mapping[str, Any]) -> dict[str, Any]:\n",
    checkpoint_helper + "\n\ndef _artifact_identity(evidence: Mapping[str, Any]) -> dict[str, Any]:\n",
)
replace_once(
    kernel,
    '''    result = start_phase_job(\n        project_id,\n        job_id=job_id,\n        phase=phase,\n        argv=argv,\n        idempotence_key=idempotence_key,\n        telemetry_category=telemetry_category,\n        pipeline_dir=pipeline_dir,\n    )\n    deadline = time.monotonic() + timeout\n    while str(result.get("executionOutcome") or "pending") not in {\n        "succeeded", "failed", "interrupted"\n    }:\n        remaining = deadline - time.monotonic()\n        if remaining <= 0:\n            raise PersianRunKernelError(\n                f"durable job {job_id!r} is still running after {timeout:.3f}s; "\n                "the job was preserved. Retry status/commit with the same identity."\n            )\n        time.sleep(min(poll_interval, remaining))\n        result = reconcile_phase_job(project_id, job_id, pipeline_dir=pipeline_dir)\n\n    outcome = str(result.get("executionOutcome") or "pending")\n''',
    '''    result = start_phase_job(\n        project_id,\n        job_id=job_id,\n        phase=phase,\n        argv=argv,\n        idempotence_key=idempotence_key,\n        telemetry_category=telemetry_category,\n        pipeline_dir=pipeline_dir,\n    )\n    _enforce_execution_checkpoint(\n        project_id, operation="run-kernel:after-start", phase=phase, job_id=job_id,\n        pipeline_dir=pipeline_dir,\n    )\n    deadline = time.monotonic() + timeout\n    while str(result.get("executionOutcome") or "pending") not in {\n        "succeeded", "failed", "interrupted"\n    }:\n        _enforce_execution_checkpoint(\n            project_id, operation="run-kernel:wait", phase=phase, job_id=job_id,\n            pipeline_dir=pipeline_dir,\n        )\n        remaining = deadline - time.monotonic()\n        if remaining <= 0:\n            raise PersianRunKernelError(\n                f"durable job {job_id!r} is still running after {timeout:.3f}s; "\n                "the job was preserved. Retry status/commit with the same identity."\n            )\n        time.sleep(min(poll_interval, remaining))\n        result = reconcile_phase_job(project_id, job_id, pipeline_dir=pipeline_dir)\n        _enforce_execution_checkpoint(\n            project_id, operation="run-kernel:after-reconcile", phase=phase, job_id=job_id,\n            pipeline_dir=pipeline_dir,\n        )\n\n    outcome = str(result.get("executionOutcome") or "pending")\n''',
)

workflow = Path("lib/persian_video_workflow.py")
replace_once(
    workflow,
    '''    "edit-compare",\n    "job-status",\n''',
    '''    "edit-compare",\n    "asset-result",\n    "job-status",\n''',
)

skill = Path("skills/persian-video/SKILL.md")
replace_once(
    skill,
    '''command admits new active work, and before a new durable run-kernel execution starts,\nthe same wall/SLO policy is enforced. An overrun persists `status=failed`,\n''',
    '''command admits new active work, before a new durable run-kernel execution starts, and\nat safe checkpoints while a durable child is running, the same wall/SLO policy is\nenforced. An overrun persists `status=failed`,\n''',
)
replace_once(
    skill,
    '''identity, and the blocked operation before new expensive work begins. Existing\nstatus/reconciliation/settlement paths stay usable so durable evidence is not lost.\n''',
    '''identity, and the blocked operation before new expensive work continues. Existing\nstatus/reconciliation paths and external asset-result settlement stay usable so\ndurable evidence is not lost.\n''',
)

test = Path("tests/lib/test_issue138_in_phase_watchdog.py")
text = test.read_text(encoding="utf-8")
text += '''\n\ndef test_run_kernel_rechecks_budget_at_live_child_boundaries(monkeypatch):\n    operations = []\n\n    monkeypatch.setattr(\n        kernel, "start_phase_job",\n        lambda *args, **kwargs: {"executionOutcome": "pending"},\n    )\n    monkeypatch.setattr(\n        kernel, "reconcile_phase_job",\n        lambda *args, **kwargs: {"executionOutcome": "pending"},\n    )\n    monkeypatch.setattr(kernel.time, "sleep", lambda _seconds: None)\n\n    def fake_budget_guard(_project_id, *, operation, **_kwargs):\n        operations.append(operation)\n        if operation == "run-kernel:after-reconcile":\n            raise workflow.PersianVideoWorkflowError(\n                "wall_budget_exceeded: simulated live-child overrun"\n            )\n        return {}\n\n    monkeypatch.setattr(workflow, "enforce_front_door_budget", fake_budget_guard)\n\n    with pytest.raises(kernel.PersianRunKernelError, match="wall_budget_exceeded"):\n        kernel.run_phase_job(\n            "run",\n            job_id="live-child",\n            phase="prepare_inputs",\n            argv=["fixture"],\n            idempotence_key="live-child-v1",\n            poll_interval_seconds=0.001,\n            timeout_seconds=1.0,\n        )\n\n    assert operations == [\n        "run-kernel:after-start",\n        "run-kernel:wait",\n        "run-kernel:after-reconcile",\n    ]\n\n\ndef test_asset_result_remains_available_as_external_settlement(monkeypatch):\n    def fail_if_called(*_args, **_kwargs):\n        raise AssertionError("asset-result must not be blocked before settlement")\n\n    monkeypatch.setattr(workflow, "enforce_front_door_budget", fail_if_called)\n    args = type("Args", (), {"command": "asset-result", "project_id": "run"})()\n    workflow._enforce_cli_front_door_budget(args)\n'''
test.write_text(text, encoding="utf-8")
