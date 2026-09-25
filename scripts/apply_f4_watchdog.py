from __future__ import annotations

from pathlib import Path


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one anchor, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


workflow = Path("lib/persian_video_workflow.py")
workflow_helper = '''

def enforce_front_door_budget(
    project_id: str,
    *,
    operation: str,
    pipeline_dir: Path | None = None,
    now: datetime | None = None,
    operation_evidence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Persist an actionable stop before admitting more active workflow work."""
    operation_name = str(operation or "").strip()
    if not operation_name:
        raise PersianVideoWorkflowError("front-door budget operation must be non-empty")
    state = load_workflow_state(project_id, pipeline_dir=pipeline_dir)
    phase = str(state.get("next_phase") or "")
    if state.get("status") != "active" or phase not in PHASES:
        return state
    effective_now = now or datetime.now(timezone.utc)
    assert_within_wall_time(state, now=effective_now)
    if not _enforce_phase_boundary_budget(state, phase, now=effective_now):
        return state

    stop = dict(state.get("budget_stop") or {})
    stop.pop("boundary_after_phase", None)
    stop["boundary_before_operation"] = operation_name
    stop["phase"] = phase
    stop["phase_attempt"] = _running_phase_attempt(state, phase)
    stop["open_work_span_ids"] = [
        str(span["span_id"])
        for span in _open_countable_work_spans(state)
        if span.get("span_id")
    ]
    if operation_evidence:
        stop["operation_evidence"] = {
            str(key): value
            for key, value in operation_evidence.items()
            if isinstance(value, (str, int, float, bool)) or value is None
        }
    state["budget_stop"] = stop
    _write_state(_project_root(state), state)
    raise PersianVideoWorkflowError(
        f"{stop.get('reason')}: workflow budget blocks {operation_name!r}; "
        "resume with an explicit budget decision before starting more work"
    )
'''
replace_once(
    workflow,
    "\n\ndef start_explicit_work_span(\n",
    workflow_helper + "\n\ndef start_explicit_work_span(\n",
)

cli_helpers = '''

_BUDGET_GUARD_EXEMPT_COMMANDS = frozenset({
    "bootstrap",
    "status",
    "guard-read",
    "edit-compare",
    "job-status",
    "alignment-status",
    "resume",
    "work-finish",
    "work-abandon",
    "complete",
    "alignment-commit",
    "reconcile-approval",
})


def _cli_operation_name(args: argparse.Namespace) -> str:
    parts = [str(args.command)]
    for attr in ("assets_command", "music_command", "regions_command"):
        value = getattr(args, attr, None)
        if value:
            parts.append(str(value))
    return ":".join(parts)


def _enforce_cli_front_door_budget(args: argparse.Namespace) -> None:
    if str(args.command) in _BUDGET_GUARD_EXEMPT_COMMANDS:
        return
    project_id = getattr(args, "project_id", None)
    if not project_id:
        return
    enforce_front_door_budget(
        str(project_id),
        operation=f"workflow:{_cli_operation_name(args)}",
    )
'''
replace_once(
    workflow,
    "\n\ndef main(argv: Sequence[str] | None = None) -> int:\n",
    cli_helpers + "\n\ndef main(argv: Sequence[str] | None = None) -> int:\n",
)
replace_once(
    workflow,
    '''def main(argv: Sequence[str] | None = None) -> int:\n    args = build_parser().parse_args(argv)\n    try:\n        if args.command == "bootstrap":\n''',
    '''def main(argv: Sequence[str] | None = None) -> int:\n    args = build_parser().parse_args(argv)\n    try:\n        _enforce_cli_front_door_budget(args)\n        if args.command == "bootstrap":\n''',
)

kernel = Path("lib/persian_run_kernel.py")
kernel_helpers = '''

def _idempotence_already_persisted(
    state: Mapping[str, Any], idempotence_key: str
) -> bool:
    index_path = _project_root(state) / ".jobs" / "idempotence.json"
    if not index_path.is_file():
        return False
    try:
        index = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PersianRunKernelError(
            f"durable idempotence index is unreadable: {index_path}"
        ) from exc
    if not isinstance(index, Mapping):
        raise PersianRunKernelError("durable idempotence index must be a JSON object")
    return bool(index.get(idempotence_key))


def _enforce_new_execution_budget(
    state: Mapping[str, Any],
    *,
    project_id: str,
    phase: str,
    job_id: str,
    argv: Sequence[str],
    idempotence_key: str,
    telemetry_category: str,
    pipeline_dir: Path | None,
    now: datetime | None,
) -> dict[str, Any]:
    if _idempotence_already_persisted(state, idempotence_key):
        return dict(state)
    try:
        return workflow.enforce_front_door_budget(
            project_id,
            operation="run-kernel:start",
            pipeline_dir=pipeline_dir,
            now=now,
            operation_evidence={
                "phase": phase,
                "job_id": job_id,
                "idempotence_key": idempotence_key,
                "telemetry_category": telemetry_category,
                "command_sha256": durable_command_sha256(argv),
            },
        )
    except workflow.PersianVideoWorkflowError as exc:
        raise PersianRunKernelError(str(exc)) from exc
'''
replace_once(
    kernel,
    "\n\ndef _artifact_identity(evidence: Mapping[str, Any]) -> dict[str, Any]:\n",
    kernel_helpers + "\n\ndef _artifact_identity(evidence: Mapping[str, Any]) -> dict[str, Any]:\n",
)
replace_once(
    kernel,
    '''    if phase != state.get("next_phase"):\n        raise PersianRunKernelError(\n            f"cannot start {phase!r}; next phase is {state.get('next_phase')!r}"\n        )\n    phase_attempt = _open_phase_attempt(state, phase)\n''',
    '''    if phase != state.get("next_phase"):\n        raise PersianRunKernelError(\n            f"cannot start {phase!r}; next phase is {state.get('next_phase')!r}"\n        )\n    state = _enforce_new_execution_budget(\n        state,\n        project_id=project_id,\n        phase=phase,\n        job_id=job_id,\n        argv=argv,\n        idempotence_key=idempotence_key,\n        telemetry_category=telemetry_category,\n        pipeline_dir=pipeline_dir,\n        now=now,\n    )\n    phase_attempt = _open_phase_attempt(state, phase)\n''',
)

skill = Path("skills/persian-video/SKILL.md")
replace_once(
    skill,
    '''`status` is read-only. Its default output is one operational line with the current\nphase, phase elapsed time, wall time versus budget, last written file, and\n`progressing`/`idle` (`idle` means no project write for 15 minutes). Use `--json`\nwhen routing by `next_phase` or inspecting telemetry. At a phase boundary, exceeding\nthe wall budget or 2× the current phase SLO persists `status=failed`,\n`quality_disposition=needs_decision`, the remaining phases, and the exact choices to\ncontinue with more time, continue only to preview, or stop. Never start the next\nphase by bypassing that stop.\n''',
    '''`status` is read-only. Its default output is one operational line with the current\nphase, phase elapsed time, wall time versus budget, last written file, and\n`progressing`/`idle` (`idle` means no project write for 15 minutes). Use `--json`\nwhen routing by `next_phase` or inspecting telemetry. Before a supported front-door\ncommand admits new active work, and before a new durable run-kernel execution starts,\nthe same wall/SLO policy is enforced. An overrun persists `status=failed`,\n`quality_disposition=needs_decision`, stable budget evidence, current phase/work\nidentity, and the blocked operation before new expensive work begins. Existing\nstatus/reconciliation/settlement paths stay usable so durable evidence is not lost.\nPhase completion keeps the same boundary stop policy. Resume only after an explicit\nbudget decision; never bypass the persisted stop.\n''',
)

test = Path("tests/lib/test_issue138_in_phase_watchdog.py")
test.write_text('''from datetime import datetime, timedelta, timezone\nfrom pathlib import Path\nimport sys\n\nimport pytest\n\nfrom lib import persian_run_kernel as kernel\nfrom lib import persian_video_workflow as workflow\nfrom tests.lib.test_persian_video_workflow import BASE, _bootstrap\n\n\ndef test_run_kernel_blocks_new_external_work_after_wall_budget(tmp_path: Path):\n    _bootstrap(tmp_path)\n    marker = tmp_path / "external-work-ran.txt"\n    child = (\n        "from pathlib import Path; "\n        f"Path({str(marker)!r}).write_text('ran', encoding='utf-8')"\n    )\n\n    with pytest.raises(kernel.PersianRunKernelError, match="wall_budget_exceeded"):\n        kernel.start_phase_job(\n            "run",\n            job_id="late-execution",\n            phase="prepare_inputs",\n            argv=[sys.executable, "-c", child],\n            idempotence_key="late-execution-v1",\n            pipeline_dir=tmp_path,\n            now=BASE + timedelta(minutes=46),\n        )\n\n    state = workflow.load_workflow_state("run", pipeline_dir=tmp_path)\n    stop = state["budget_stop"]\n    assert state["status"] == "failed"\n    assert stop["quality_disposition"] == "needs_decision"\n    assert stop["reason"] == "wall_budget_exceeded"\n    assert stop["boundary_before_operation"] == "run-kernel:start"\n    assert stop["phase"] == "prepare_inputs"\n    assert stop["phase_attempt"] is None\n    assert stop["operation_evidence"]["job_id"] == "late-execution"\n    assert int((state.get("attempts") or {}).get("prepare_inputs", 0)) == 0\n    assert not marker.exists()\n    assert not (tmp_path / "run" / ".jobs" / "idempotence.json").exists()\n\n\ndef test_cli_front_door_stops_before_new_work_span(tmp_path: Path, monkeypatch):\n    _bootstrap(tmp_path)\n    state = workflow.load_workflow_state("run", pipeline_dir=tmp_path)\n    state["budget_window_started_at"] = (\n        datetime.now(timezone.utc) - timedelta(minutes=46)\n    ).isoformat()\n    workflow._write_state(tmp_path / "run", state)\n    monkeypatch.setattr(workflow, "PROJECTS_DIR", tmp_path)\n\n    with pytest.raises(SystemExit) as exc_info:\n        workflow.main([\n            "work-start",\n            "run",\n            "--category",\n            "agent_editorial_work",\n            "--name",\n            "late-editorial-work",\n        ])\n    assert exc_info.value.code == 2\n\n    state = workflow.load_workflow_state("run", pipeline_dir=tmp_path)\n    stop = state["budget_stop"]\n    assert state["status"] == "failed"\n    assert stop["reason"] == "wall_budget_exceeded"\n    assert stop["quality_disposition"] == "needs_decision"\n    assert stop["boundary_before_operation"] == "workflow:work-start"\n    assert not any(\n        span.get("kind") == "explicit_work"\n        for span in (state.get("causal_telemetry") or {}).get("spans", [])\n    )\n''', encoding="utf-8")
