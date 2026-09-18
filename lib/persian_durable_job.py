"""Durable local subprocess jobs for long Persian-video stages.

Job state lives inside the project, is atomically updated, and can be reconciled
after the controlling chat/terminal disappears. Idempotence keys prevent duplicate
execution of the same logical stage attempt. Execution truth is persisted separately
from best-effort reporting so reporting/serialization cannot erase expensive work.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from lib.json_safe import to_json_safe
from lib.paths import REPO_ROOT

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
_PYTHON_LAUNCHERS = frozenset({"python", "python3", "python.exe", "python3.exe"})
_RESULT_ENV_VAR = "OPENMONTAGE_DURABLE_RESULT_PATH"


class DurableJobError(ValueError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical_env() -> dict[str, str]:
    """Return the deterministic child environment for repo-local durable work."""
    env = dict(os.environ)
    repo = str(REPO_ROOT.resolve())
    existing = str(env.get("PYTHONPATH") or "")
    entries = [item for item in existing.split(os.pathsep) if item]
    entries = [item for item in entries if Path(item).expanduser().resolve() != REPO_ROOT.resolve()]
    env["PYTHONPATH"] = os.pathsep.join([repo, *entries])
    env["PYTHONUNBUFFERED"] = "1"
    return env


def _normalize_command(argv: Sequence[str]) -> list[str]:
    command = list(argv)
    if command and Path(command[0]).name.lower() in _PYTHON_LAUNCHERS:
        command[0] = sys.executable
    return command


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    payload = to_json_safe(dict(value))
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def _validate_id(value: str, label: str) -> str:
    if not _ID_RE.fullmatch(value):
        raise DurableJobError(f"{label} must be 1-80 ASCII letters/digits plus ._- characters")
    return value


def _root(project_dir: Path) -> Path:
    return project_dir.expanduser().resolve() / ".jobs"


def _state_path(project_dir: Path, job_id: str) -> Path:
    return _root(project_dir) / _validate_id(job_id, "job_id") / "state.json"


def _result_path(project_dir: Path, job_id: str) -> Path:
    return _state_path(project_dir, job_id).with_name("result.json")


def _semantic_result_path(project_dir: Path, job_id: str) -> Path:
    return _state_path(project_dir, job_id).with_name("semantic-result.json")


def _log_path(project_dir: Path, job_id: str) -> Path:
    return _state_path(project_dir, job_id).with_name("job.log")


def _index_path(project_dir: Path) -> Path:
    return _root(project_dir) / "idempotence.json"


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DurableJobError(f"job state is unreadable: {path}") from exc
    if not isinstance(value, dict):
        raise DurableJobError(f"job state is not an object: {path}")
    return value


def _command_digest(argv: Sequence[str]) -> str:
    return hashlib.sha256(
        json.dumps(list(argv), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def durable_command_sha256(argv: Sequence[str]) -> str:
    """Return the canonical digest used to bind one durable command identity."""
    return _command_digest(_normalize_command(argv))


def load_job(project_dir: Path, job_id: str) -> dict[str, Any]:
    return _read_json(_state_path(project_dir, job_id))


def start_job(
    project_dir: Path,
    *,
    job_id: str,
    phase: str,
    argv: Sequence[str],
    idempotence_key: str,
    launch: bool = True,
) -> dict[str, Any]:
    """Persist one logical job and detach a heartbeat worker exactly once."""
    if not argv or not all(isinstance(item, str) and item for item in argv):
        raise DurableJobError("argv must contain at least one non-empty string")
    _validate_id(job_id, "job_id")
    _validate_id(phase, "phase")
    _validate_id(idempotence_key, "idempotence_key")
    command = _normalize_command(argv)
    env = _canonical_env()
    root = _root(project_dir)
    root.mkdir(parents=True, exist_ok=True)
    index_path = _index_path(project_dir)
    index = _read_json(index_path) if index_path.exists() else {}
    existing_id = index.get(idempotence_key)
    if existing_id:
        existing = load_job(project_dir, str(existing_id))
        if existing.get("commandSha256") != durable_command_sha256(command):
            raise DurableJobError("idempotence_key already belongs to a different command")
        return {**existing, "idempotentReuse": True}

    state_path = _state_path(project_dir, job_id)
    if state_path.exists():
        raise DurableJobError("job_id already exists; reuse its state or choose a new job_id")
    semantic_result_path = _semantic_result_path(project_dir, job_id)
    state = {
        "version": 2,
        "jobId": job_id,
        "phase": phase,
        "idempotenceKey": idempotence_key,
        "status": "queued",
        "processOutcome": "pending",
        "semanticOutcome": "pending",
        "executionOutcome": "pending",
        "reportingOutcome": "pending",
        "command": command,
        "commandSha256": durable_command_sha256(command),
        "createdAt": _now(),
        "heartbeatAt": None,
        "workerPid": None,
        "resultPath": str(_result_path(project_dir, job_id)),
        "semanticResultPath": str(semantic_result_path),
        "logPath": str(_log_path(project_dir, job_id)),
        "executionContext": {
            "cwd": str(REPO_ROOT.resolve()),
            "interpreter": str(Path(sys.executable).resolve()),
            "pythonPath": env["PYTHONPATH"],
            "semanticResultEnv": _RESULT_ENV_VAR,
        },
    }
    _atomic_json(state_path, state)
    index[idempotence_key] = job_id
    _atomic_json(index_path, index)
    if not launch:
        return state

    log = _log_path(project_dir, job_id)
    log.parent.mkdir(parents=True, exist_ok=True)
    handle = log.open("ab")
    try:
        worker = subprocess.Popen(
            [sys.executable, "-m", "lib.persian_durable_job", "_worker", str(state_path)],
            cwd=REPO_ROOT,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            close_fds=True,
        )
    finally:
        handle.close()
    state["workerPid"] = worker.pid
    state["status"] = "starting"
    state["heartbeatAt"] = _now()
    _atomic_json(state_path, state)
    return state


def _pid_alive(pid: object) -> bool:
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _child_alive_for_job(state: Mapping[str, Any]) -> bool:
    """Return true only while this job's recorded child still appears alive."""
    child_pid = state.get("childPid")
    if not _pid_alive(child_pid):
        return False
    expected_group = state.get("processGroupId")
    if not isinstance(expected_group, int) or expected_group <= 0:
        return True
    try:
        return os.getpgid(int(child_pid)) == expected_group
    except OSError:
        return False


def reconcile_job(project_dir: Path, job_id: str) -> dict[str, Any]:
    state_path = _state_path(project_dir, job_id)
    state = _read_json(state_path)
    result_path = _result_path(project_dir, job_id)
    if result_path.exists():
        result = _read_json(result_path)
        state.update(
            {
                key: result[key]
                for key in (
                    "status",
                    "exitCode",
                    "finishedAt",
                    "processOutcome",
                    "semanticOutcome",
                    "semanticResult",
                    "semanticError",
                    "executionOutcome",
                    "reportingOutcome",
                )
                if key in result
            }
        )
        state["heartbeatAt"] = result.get("heartbeatAt", state.get("heartbeatAt"))
        _atomic_json(state_path, state)
        return state
    active = {"queued", "starting", "running", "orphaned_running"}
    if state.get("status") in active and not _pid_alive(state.get("workerPid")):
        if _child_alive_for_job(state):
            state["status"] = "orphaned_running"
            state["recoveryAction"] = (
                "Worker exited but the recorded child process is still running; do not retry "
                "or reuse this phase with a new idempotence key until reconciliation sees it exit."
            )
            _atomic_json(state_path, state)
            return state
        state["status"] = "interrupted"
        state["processOutcome"] = "interrupted"
        if state.get("semanticOutcome") in {None, "pending", "running"}:
            state["semanticOutcome"] = "not_reported"
        state["executionOutcome"] = "interrupted"
        state["finishedAt"] = _now()
        state["recoveryAction"] = (
            "Inspect job.log, then retry with a new idempotence key if the stage did not commit its output."
        )
        _atomic_json(state_path, state)
    return state


def _read_semantic_result(state_path: Path, state: Mapping[str, Any]) -> tuple[str, dict[str, Any] | None, str | None]:
    raw_path = str(state.get("semanticResultPath") or "").strip()
    path = Path(raw_path) if raw_path else state_path.with_name("semantic-result.json")
    if not path.is_file():
        return "not_reported", None, None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return "invalid", None, f"semantic result is unreadable JSON: {exc}"
    if not isinstance(payload, dict):
        return "invalid", None, "semantic result must be a JSON object"
    success = payload.get("success")
    if not isinstance(success, bool):
        return "invalid", to_json_safe(payload), "semantic result requires boolean success"
    return ("succeeded" if success else "failed"), to_json_safe(payload), None


def _record_finished_execution(
    state_path: Path, *, exit_code: int, heartbeat_at: str | None = None
) -> dict[str, Any]:
    """Persist process and semantic execution truth first; reporting may fail later."""
    state = _read_json(state_path)
    result_path = state_path.with_name("result.json")
    process_outcome = "succeeded" if int(exit_code) == 0 else "failed"
    semantic_outcome, semantic_result, semantic_error = _read_semantic_result(state_path, state)
    execution_succeeded = process_outcome == "succeeded" and semantic_outcome in {
        "succeeded",
        "not_reported",
    }
    status = "succeeded" if execution_succeeded else "failed"
    finished: dict[str, Any] = {
        "status": status,
        "processOutcome": process_outcome,
        "semanticOutcome": semantic_outcome,
        "executionOutcome": status,
        "exitCode": int(exit_code),
        "finishedAt": _now(),
        "heartbeatAt": heartbeat_at or state.get("heartbeatAt") or _now(),
    }
    if semantic_result is not None:
        finished["semanticResult"] = semantic_result
    if semantic_error:
        finished["semanticError"] = semantic_error
    state.update(finished)
    state["reportingOutcome"] = "pending"
    _atomic_json(state_path, state)

    try:
        report = {**finished, "reportingOutcome": "succeeded"}
        _atomic_json(result_path, report)
    except Exception as exc:
        state["reportingOutcome"] = "failed"
        state["reportingError"] = str(exc)
        _atomic_json(state_path, state)
        return state

    state["reportingOutcome"] = "succeeded"
    state.pop("reportingError", None)
    _atomic_json(state_path, state)
    return state


def _worker(state_path: Path) -> int:
    state = _read_json(state_path)
    log_path = state_path.with_name("job.log")
    semantic_result_path = Path(
        str(state.get("semanticResultPath") or state_path.with_name("semantic-result.json"))
    )
    semantic_result_path.unlink(missing_ok=True)
    state["status"] = "running"
    state["processOutcome"] = "running"
    state["semanticOutcome"] = "pending"
    state["executionOutcome"] = "running"
    state["workerPid"] = os.getpid()
    state["startedAt"] = _now()
    state["heartbeatAt"] = _now()
    _atomic_json(state_path, state)
    child_env = _canonical_env()
    child_env[_RESULT_ENV_VAR] = str(semantic_result_path)
    with log_path.open("ab") as log:
        child = subprocess.Popen(
            state["command"],
            cwd=REPO_ROOT,
            env=child_env,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            close_fds=True,
        )
        state["childPid"] = child.pid
        state["processGroupId"] = os.getpgid(child.pid)
        _atomic_json(state_path, state)
        while True:
            code = child.poll()
            state["heartbeatAt"] = _now()
            _atomic_json(state_path, state)
            if code is not None:
                break
            time.sleep(1.0)
    _record_finished_execution(
        state_path,
        exit_code=int(code),
        heartbeat_at=str(state.get("heartbeatAt") or _now()),
    )
    return int(code)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="persian-durable-job")
    sub = parser.add_subparsers(dest="command", required=True)
    start = sub.add_parser("start")
    start.add_argument("project_dir", type=Path)
    start.add_argument("job_id")
    start.add_argument("--phase", required=True)
    start.add_argument("--idempotence-key", required=True)
    start.add_argument("argv", nargs=argparse.REMAINDER)
    status = sub.add_parser("status")
    status.add_argument("project_dir", type=Path)
    status.add_argument("job_id")
    worker = sub.add_parser("_worker")
    worker.add_argument("state_path", type=Path)
    args = parser.parse_args(argv)
    if args.command == "_worker":
        return _worker(args.state_path)
    try:
        if args.command == "start":
            command = list(args.argv)
            command = command[1:] if command[:1] == ["--"] else command
            result = start_job(
                args.project_dir,
                job_id=args.job_id,
                phase=args.phase,
                argv=command,
                idempotence_key=args.idempotence_key,
            )
        else:
            result = reconcile_job(args.project_dir, args.job_id)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print(json.dumps(to_json_safe({"ok": False, "error": str(exc)}), ensure_ascii=False, indent=2))
        return 2
    print(json.dumps(to_json_safe({"ok": True, **result}), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
