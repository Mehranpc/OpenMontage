"""Deep execution envelope for durable Persian production phases.

Creative/editorial decisions remain agent-owned. This module owns the deterministic
mechanics that connect one workflow phase attempt to one durable process, its semantic
result, persisted evidence/checkpoint state, and workflow transition outcome.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any, Mapping, Sequence

from lib.json_safe import to_json_safe
from lib.persian_durable_job import durable_command_sha256
from lib import persian_video_workflow as workflow

_ENVELOPE_VERSION = "1.0"
_JOB_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
_CHECKPOINTED_PHASES = frozenset({
    "align_script_timing",
    "plan_scenes_moments",
    "acquire_assets",
    "no_copy_preflight",
})


class PersianRunKernelError(ValueError):
    """Raised when the production execution envelope would become inconsistent."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _validate_job_id(job_id: str) -> str:
    if not _JOB_ID_RE.fullmatch(job_id):
        raise PersianRunKernelError(
            "job_id must be 1-80 ASCII letters/digits plus ._- characters"
        )
    return job_id


def _project_root(state: Mapping[str, Any]) -> Path:
    return Path(str(state["read_allowlist"]["project_root"])).resolve()


def _envelope_path(state: Mapping[str, Any], job_id: str) -> Path:
    return _project_root(state) / ".jobs" / _validate_job_id(job_id) / "execution-envelope.json"


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(
        json.dumps(to_json_safe(dict(payload)), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temp.replace(path)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PersianRunKernelError(f"execution envelope is unreadable: {path}") from exc
    if not isinstance(value, dict):
        raise PersianRunKernelError(f"execution envelope is not a JSON object: {path}")
    return value


def _open_phase_attempt(state: Mapping[str, Any], phase: str) -> int | None:
    telemetry = state.get("phase_telemetry")
    entries = telemetry.get(phase) if isinstance(telemetry, Mapping) else None
    if not isinstance(entries, list) or not entries or not isinstance(entries[-1], Mapping):
        return None
    latest = entries[-1]
    if latest.get("finished_at") or latest.get("outcome") != "running":
        return None
    try:
        return int(latest["attempt"])
    except (KeyError, TypeError, ValueError):
        return None


def _artifact_identity(evidence: Mapping[str, Any]) -> dict[str, Any]:
    """Keep only durable identity fields, not the whole phase evidence payload."""
    identity: dict[str, Any] = {}
    for key, value in evidence.items():
        lower = str(key).lower()
        if lower.endswith("sha256") or lower.endswith("_path"):
            if isinstance(value, (str, int, float, bool)) or value is None:
                identity[str(key)] = value
    return identity


def _job_error_reason(job: Mapping[str, Any]) -> str:
    semantic = job.get("semanticResult")
    if isinstance(semantic, Mapping) and str(semantic.get("error") or "").strip():
        return str(semantic["error"]).strip()
    if str(job.get("semanticError") or "").strip():
        return str(job["semanticError"]).strip()
    return (
        f"durable execution failed: process={job.get('processOutcome')} "
        f"semantic={job.get('semanticOutcome')} exit={job.get('exitCode')}"
    )


def _decorate_job(job: Mapping[str, Any], envelope: Mapping[str, Any]) -> dict[str, Any]:
    execution_outcome = str(
        envelope.get("executionOutcome") or job.get("executionOutcome") or "pending"
    )
    status = str(job.get("status") or "pending")
    if execution_outcome in {"failed", "interrupted"}:
        status = execution_outcome
    return {
        **dict(job),
        "status": status,
        "processOutcome": envelope.get("processOutcome", job.get("processOutcome")),
        "semanticOutcome": envelope.get("semanticOutcome", job.get("semanticOutcome")),
        "executionOutcome": execution_outcome,
        "reportingOutcome": envelope.get("reportingOutcome", job.get("reportingOutcome")),
        "phaseAttempt": envelope["phaseAttempt"],
        "executionEnvelopePath": envelope["path"],
        "executionEnvelope": dict(envelope),
    }


def load_execution_envelope(
    project_id: str,
    job_id: str,
    *,
    pipeline_dir: Path | None = None,
) -> dict[str, Any]:
    state = workflow.load_workflow_state(project_id, pipeline_dir=pipeline_dir)
    return _read_json(_envelope_path(state, job_id))


def start_phase_job(
    project_id: str,
    *,
    job_id: str,
    phase: str,
    argv: Sequence[str],
    idempotence_key: str,
    pipeline_dir: Path | None = None,
    launch: bool = True,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Bind one current workflow attempt to one durable execution exactly once."""
    state = workflow.load_workflow_state(project_id, pipeline_dir=pipeline_dir)
    path = _envelope_path(state, job_id)
    if path.is_file():
        envelope = _read_json(path)
        if str(envelope.get("phase")) != phase:
            raise PersianRunKernelError(
                f"job {job_id!r} is already bound to phase {envelope.get('phase')!r}"
            )
        if str(envelope.get("idempotenceKey")) != idempotence_key:
            raise PersianRunKernelError(
                f"job {job_id!r} is already bound to a different idempotence key"
            )
        requested_command_sha = durable_command_sha256(argv)
        recorded_command_sha = str(envelope.get("commandSha256") or "")
        if recorded_command_sha and recorded_command_sha != requested_command_sha:
            raise PersianRunKernelError(
                f"job {job_id!r} is already bound to a different command"
            )
        return reconcile_phase_job(project_id, job_id, pipeline_dir=pipeline_dir)

    if phase != state.get("next_phase"):
        raise PersianRunKernelError(
            f"cannot start {phase!r}; next phase is {state.get('next_phase')!r}"
        )
    phase_attempt = _open_phase_attempt(state, phase)
    created_attempt = phase_attempt is None
    if created_attempt:
        state = workflow.record_phase_attempt(
            project_id, phase, pipeline_dir=pipeline_dir, now=now
        )
        phase_attempt = int((state.get("attempts") or {})[phase])

    try:
        job = workflow.start_workflow_job(
            project_id,
            job_id=job_id,
            phase=phase,
            argv=argv,
            idempotence_key=idempotence_key,
            pipeline_dir=pipeline_dir,
            launch=launch,
        )
    except Exception as exc:
        if created_attempt:
            try:
                workflow.record_phase_failure(
                    project_id,
                    phase,
                    reason=f"durable job start failed: {exc}",
                    pipeline_dir=pipeline_dir,
                    now=now,
                )
            except Exception:
                pass
        raise

    actual_job_id = str(job.get("jobId") or job_id)
    if actual_job_id != job_id:
        if created_attempt:
            try:
                workflow.record_phase_failure(
                    project_id,
                    phase,
                    reason=(
                        f"idempotence key belongs to durable job {actual_job_id!r}; "
                        f"reuse that job id instead of {job_id!r}"
                    ),
                    pipeline_dir=pipeline_dir,
                    now=now,
                )
            except Exception:
                pass
        raise PersianRunKernelError(
            f"idempotence key belongs to existing durable job {actual_job_id!r}; reuse that job id"
        )

    envelope = {
        "version": _ENVELOPE_VERSION,
        "path": str(path),
        "projectId": project_id,
        "phase": phase,
        "phaseAttempt": int(phase_attempt),
        "jobId": actual_job_id,
        "idempotenceKey": idempotence_key,
        "commandSha256": str(job.get("commandSha256") or durable_command_sha256(argv)),
        "durableStatus": job.get("status"),
        "processOutcome": job.get("processOutcome", "pending"),
        "semanticOutcome": job.get("semanticOutcome", "pending"),
        "executionOutcome": job.get("executionOutcome", "pending"),
        "reportingOutcome": job.get("reportingOutcome", "pending"),
        "artifactOutcome": "pending",
        "artifactIdentity": {},
        "checkpointOutcome": "pending",
        "workflowTransitionOutcome": "pending",
        "workflowTransitionAttempts": 0,
        "nextPhase": phase,
        "durableResultPath": job.get("resultPath"),
        "semanticResultPath": job.get("semanticResultPath"),
        "startedAt": job.get("startedAt") or job.get("createdAt") or _now(),
        "updatedAt": _now(),
    }
    _atomic_json(path, envelope)
    return _decorate_job(job, envelope)


def _close_failed_attempt_if_current(
    project_id: str,
    envelope: Mapping[str, Any],
    job: Mapping[str, Any],
    *,
    pipeline_dir: Path | None,
) -> None:
    state = workflow.load_workflow_state(project_id, pipeline_dir=pipeline_dir)
    phase = str(envelope["phase"])
    if state.get("next_phase") != phase:
        return
    if _open_phase_attempt(state, phase) != int(envelope["phaseAttempt"]):
        return
    workflow.record_phase_failure(
        project_id,
        phase,
        reason=_job_error_reason(job),
        pipeline_dir=pipeline_dir,
    )


def reconcile_phase_job(
    project_id: str,
    job_id: str,
    *,
    pipeline_dir: Path | None = None,
) -> dict[str, Any]:
    """Reconcile durable execution without inferring workflow completion from exit code."""
    envelope = load_execution_envelope(project_id, job_id, pipeline_dir=pipeline_dir)
    job = workflow.reconcile_workflow_job(project_id, job_id, pipeline_dir=pipeline_dir)
    for key in (
        "status",
        "processOutcome",
        "semanticOutcome",
        "executionOutcome",
        "reportingOutcome",
        "semanticResult",
        "semanticError",
        "exitCode",
        "finishedAt",
    ):
        if key in job:
            envelope[{"status": "durableStatus"}.get(key, key)] = job[key]
    envelope["updatedAt"] = _now()

    effective_job = dict(job)
    if (
        job.get("processOutcome") == "succeeded"
        and job.get("semanticOutcome") == "not_reported"
    ):
        envelope["executionOutcome"] = "failed"
        effective_job["executionOutcome"] = "failed"
        effective_job["semanticError"] = (
            "production run kernel requires a semantic result; "
            "process exit code alone is not success"
        )

    if envelope.get("executionOutcome") in {"failed", "interrupted"}:
        _close_failed_attempt_if_current(
            project_id, envelope, effective_job, pipeline_dir=pipeline_dir
        )
        envelope["workflowTransitionOutcome"] = "blocked"
        envelope["workflowTransitionError"] = _job_error_reason(effective_job)

    state = workflow.load_workflow_state(project_id, pipeline_dir=pipeline_dir)
    envelope["nextPhase"] = state.get("next_phase")
    _atomic_json(Path(str(envelope["path"])), envelope)
    return _decorate_job(job, envelope)


def _record_commit_failure(
    envelope: dict[str, Any], evidence: Mapping[str, Any], exc: Exception
) -> None:
    identity = _artifact_identity(evidence)
    envelope["artifactIdentity"] = identity
    envelope["artifactOutcome"] = "unvalidated" if identity else "pending"
    envelope["checkpointOutcome"] = (
        "not_committed" if envelope["phase"] in _CHECKPOINTED_PHASES else "not_applicable"
    )
    envelope["workflowTransitionOutcome"] = "failed"
    envelope["workflowTransitionError"] = str(exc)
    envelope["workflowTransitionAttempts"] = int(
        envelope.get("workflowTransitionAttempts") or 0
    ) + 1
    envelope["updatedAt"] = _now()


def _record_commit_success(
    envelope: dict[str, Any], state: Mapping[str, Any]
) -> None:
    phase = str(envelope["phase"])
    all_evidence = state.get("evidence") if isinstance(state.get("evidence"), Mapping) else {}
    evidence = all_evidence.get(phase) if isinstance(all_evidence, Mapping) else {}
    evidence = evidence if isinstance(evidence, Mapping) else {}
    identity = _artifact_identity(evidence)
    envelope["artifactIdentity"] = identity
    envelope["artifactOutcome"] = "validated" if identity else "not_applicable"
    envelope["checkpointOutcome"] = (
        "validated" if phase in _CHECKPOINTED_PHASES else "not_applicable"
    )
    envelope["workflowTransitionOutcome"] = "succeeded"
    envelope.pop("workflowTransitionError", None)
    envelope["workflowTransitionAttempts"] = int(
        envelope.get("workflowTransitionAttempts") or 0
    ) + 1
    envelope["nextPhase"] = state.get("next_phase")
    envelope["committedAt"] = _now()
    envelope["updatedAt"] = envelope["committedAt"]


def commit_phase_job(
    project_id: str,
    job_id: str,
    *,
    evidence: Mapping[str, Any] | None = None,
    pipeline_dir: Path | None = None,
) -> dict[str, Any]:
    """Advance workflow state from one successful durable execution, idempotently."""
    envelope = load_execution_envelope(project_id, job_id, pipeline_dir=pipeline_dir)
    state = workflow.load_workflow_state(project_id, pipeline_dir=pipeline_dir)
    phase = str(envelope["phase"])

    if envelope.get("workflowTransitionOutcome") == "succeeded":
        return state

    reconcile_phase_job(project_id, job_id, pipeline_dir=pipeline_dir)
    envelope = load_execution_envelope(project_id, job_id, pipeline_dir=pipeline_dir)
    if envelope.get("executionOutcome") != "succeeded":
        raise PersianRunKernelError(
            "workflow commit requires successful semantic execution; "
            f"process={envelope.get('processOutcome')} semantic={envelope.get('semanticOutcome')}"
        )

    if phase in list(state.get("completed_phases") or []):
        _record_commit_success(envelope, state)
        _atomic_json(Path(str(envelope["path"])), envelope)
        return state

    phase_evidence = dict(evidence or {})
    try:
        committed = workflow.complete_phase(
            project_id,
            phase,
            evidence=phase_evidence,
            pipeline_dir=pipeline_dir,
        )
    except Exception as exc:
        _record_commit_failure(envelope, phase_evidence, exc)
        _atomic_json(Path(str(envelope["path"])), envelope)
        raise

    _record_commit_success(envelope, committed)
    _atomic_json(Path(str(envelope["path"])), envelope)
    return committed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="persian-run-kernel")
    sub = parser.add_subparsers(dest="command", required=True)

    start = sub.add_parser("start", help="start one current-phase durable execution")
    start.add_argument("project_id")
    start.add_argument("job_id")
    start.add_argument("--phase", required=True)
    start.add_argument("--idempotence-key", required=True)
    start.add_argument("argv", nargs=argparse.REMAINDER)

    status = sub.add_parser("status", help="reconcile one execution envelope")
    status.add_argument("project_id")
    status.add_argument("job_id")

    commit = sub.add_parser("commit", help="commit one successful execution into workflow state")
    commit.add_argument("project_id")
    commit.add_argument("job_id")
    commit.add_argument("--evidence-json")
    return parser


def _read_evidence(path: str | None) -> dict[str, Any]:
    if path is None:
        return {}
    raw = Path(path).expanduser().resolve()
    try:
        payload = json.loads(raw.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PersianRunKernelError(f"could not read evidence JSON: {raw}") from exc
    if not isinstance(payload, dict):
        raise PersianRunKernelError("evidence JSON must contain one object")
    return payload


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "start":
            command = list(args.argv)
            command = command[1:] if command[:1] == ["--"] else command
            result = start_phase_job(
                args.project_id,
                job_id=args.job_id,
                phase=args.phase,
                argv=command,
                idempotence_key=args.idempotence_key,
            )
        elif args.command == "status":
            result = reconcile_phase_job(args.project_id, args.job_id)
        else:
            result = commit_phase_job(
                args.project_id,
                args.job_id,
                evidence=_read_evidence(args.evidence_json),
            )
    except (PersianRunKernelError, workflow.PersianVideoWorkflowError, OSError, ValueError) as exc:
        parser.error(str(exc))
        return 2
    print(json.dumps(to_json_safe(result), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
