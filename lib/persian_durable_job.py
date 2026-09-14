"""Durable local subprocess jobs for long Persian-video stages.

Job state lives inside the project, is atomically updated, and can be reconciled
after the controlling chat/terminal disappears. Idempotence keys prevent duplicate
execution of the same logical stage attempt.
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

from lib.paths import REPO_ROOT

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")


class DurableJobError(ValueError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(dict(value), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
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
    return hashlib.sha256(json.dumps(list(argv), ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()


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
    _validate_id(job_id, "job_id"); _validate_id(phase, "phase"); _validate_id(idempotence_key, "idempotence_key")
    root = _root(project_dir); root.mkdir(parents=True, exist_ok=True)
    index_path = _index_path(project_dir)
    index = _read_json(index_path) if index_path.exists() else {}
    existing_id = index.get(idempotence_key)
    if existing_id:
        existing = load_job(project_dir, str(existing_id))
        if existing.get("commandSha256") != _command_digest(argv):
            raise DurableJobError("idempotence_key already belongs to a different command")
        return {**existing, "idempotentReuse": True}

    state_path = _state_path(project_dir, job_id)
    if state_path.exists():
        raise DurableJobError("job_id already exists; reuse its state or choose a new job_id")
    state = {
        "version": 1, "jobId": job_id, "phase": phase, "idempotenceKey": idempotence_key,
        "status": "queued", "command": list(argv), "commandSha256": _command_digest(argv),
        "createdAt": _now(), "heartbeatAt": None, "workerPid": None,
        "resultPath": str(_result_path(project_dir, job_id)), "logPath": str(_log_path(project_dir, job_id)),
    }
    _atomic_json(state_path, state)
    index[idempotence_key] = job_id; _atomic_json(index_path, index)
    if not launch:
        return state

    log = _log_path(project_dir, job_id); log.parent.mkdir(parents=True, exist_ok=True)
    handle = log.open("ab")
    try:
        worker = subprocess.Popen(
            [sys.executable, "-m", "lib.persian_durable_job", "_worker", str(state_path)],
            cwd=REPO_ROOT, stdin=subprocess.DEVNULL, stdout=handle, stderr=subprocess.STDOUT,
            start_new_session=True, close_fds=True,
        )
    finally:
        handle.close()
    state["workerPid"] = worker.pid; state["status"] = "starting"; state["heartbeatAt"] = _now()
    _atomic_json(state_path, state)
    return state


def _pid_alive(pid: object) -> bool:
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0); return True
    except OSError:
        return False


def _child_alive_for_job(state: Mapping[str, Any]) -> bool:
    """Return true only while this job's recorded child still appears alive.

    The detached worker is a session/process-group leader. Its child inherits
    that group. Checking the recorded group as well as the PID makes a later PID
    reuse much less likely to be mistaken for the original long-running command.
    Older state without a processGroupId remains conservatively PID-based.
    """
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
    state_path = _state_path(project_dir, job_id); state = _read_json(state_path)
    result_path = _result_path(project_dir, job_id)
    if result_path.exists():
        result = _read_json(result_path)
        state.update({k: result[k] for k in ("status", "exitCode", "finishedAt") if k in result})
        state["heartbeatAt"] = result.get("heartbeatAt", state.get("heartbeatAt"))
        _atomic_json(state_path, state); return state
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
        state["status"] = "interrupted"; state["finishedAt"] = _now()
        state["recoveryAction"] = "Inspect job.log, then retry with a new idempotence key if the stage did not commit its output."
        _atomic_json(state_path, state)
    return state


def _worker(state_path: Path) -> int:
    state = _read_json(state_path)
    result_path = state_path.with_name("result.json"); log_path = state_path.with_name("job.log")
    state["status"] = "running"; state["workerPid"] = os.getpid(); state["startedAt"] = _now(); state["heartbeatAt"] = _now()
    _atomic_json(state_path, state)
    with log_path.open("ab") as log:
        child = subprocess.Popen(state["command"], cwd=REPO_ROOT, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, close_fds=True)
        state["childPid"] = child.pid
        state["processGroupId"] = os.getpgid(child.pid)
        _atomic_json(state_path, state)
        while True:
            code = child.poll()
            state["heartbeatAt"] = _now(); _atomic_json(state_path, state)
            if code is not None:
                break
            time.sleep(1.0)
    status = "succeeded" if code == 0 else "failed"
    result = {"status": status, "exitCode": int(code), "finishedAt": _now(), "heartbeatAt": state["heartbeatAt"]}
    _atomic_json(result_path, result); state.update(result); _atomic_json(state_path, state)
    return int(code)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="persian-durable-job")
    sub = parser.add_subparsers(dest="command", required=True)
    start = sub.add_parser("start"); start.add_argument("project_dir", type=Path); start.add_argument("job_id"); start.add_argument("--phase", required=True); start.add_argument("--idempotence-key", required=True); start.add_argument("argv", nargs=argparse.REMAINDER)
    status = sub.add_parser("status"); status.add_argument("project_dir", type=Path); status.add_argument("job_id")
    worker = sub.add_parser("_worker"); worker.add_argument("state_path", type=Path)
    args = parser.parse_args(argv)
    if args.command == "_worker": return _worker(args.state_path)
    try:
        if args.command == "start":
            command = list(args.argv); command = command[1:] if command[:1] == ["--"] else command
            result = start_job(args.project_dir, job_id=args.job_id, phase=args.phase, argv=command, idempotence_key=args.idempotence_key)
        else: result = reconcile_job(args.project_dir, args.job_id)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2)); return 2
    print(json.dumps({"ok": True, **result}, ensure_ascii=False, indent=2)); return 0


if __name__ == "__main__":
    raise SystemExit(main())
