"""Re-run a real run's recorded commands on the current code (#264).

    python -m scripts.persian_run_replay <exported-project-dir-or.tar[.gz]> [--until N]

The project's `.telemetry/command-events.jsonl` (argv on start edges, exit_code on
finish edges, input bytes under `.telemetry/inputs/`) is replayed in order against
a fresh project built from the export's own `inputs/`: same project id, the
recorded JSON inputs restored byte for byte, and every recorded project path
remapped into the scratch copy. Provider results come from a rehearsal fixture
(`--fixture`, default the first-date recording), so replay never reaches the
network; `--no-media` also skips the browser/ffmpeg render jobs.

The report names the first command whose exit code differs from the recording,
and whether the run now gets further. Exit 0 = every replayed command matched
or improved on the recording; 1 = a command now fails that used to pass.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MODULES = {
    "workflow": "lib.persian_video_workflow",
    "run-kernel": "lib.persian_run_kernel",
    "delivery-quality": "lib.persian_delivery_quality",
}
DEFAULT_FIXTURE = ROOT / "tests" / "fixtures" / "rehearsal" / "first-date"
# Provider work (transcription, stock and music search, downloads) is served
# offline from a rehearsal fixture (#260). Browser/ffmpeg media jobs still run for
# real; skip them with --no-media when only the decision path matters.
_MEDIA = ("run-kernel:run", "run-kernel:start")
_POLLS = {"workflow:alignment-status", "workflow:job-status", "run-kernel:status"}
POLL_STALL_SECONDS = float(os.environ.get("OPENMONTAGE_REPLAY_POLL_STALL_SECONDS") or 10)


def _job_id(stdout: str) -> str:
    try:
        value = json.loads(stdout or "{}")
    except json.JSONDecodeError:
        return ""
    return str(value.get("jobId") or value.get("job_id") or "") if isinstance(value, dict) else ""


#: A command that starts a durable job, and the later commands that name its id as
#: argv[2]. The id derives from a content digest, and replay rewrites project paths
#: inside the job's inputs, so the replayed id differs and later polls must follow it.
_JOB_STARTS = {
    "workflow:alignment-start": {"workflow:alignment-status", "workflow:alignment-commit"},
    "workflow:asset-search": {"run-kernel:status", "workflow:job-status", "workflow:asset-reconcile"},
}


def _next_recorded_job_id(commands: list[dict[str, Any]], index: int, followers: set[str] | None = None) -> str:
    followers = followers or _JOB_STARTS["workflow:alignment-start"]
    for later in commands[index + 1:]:
        if later.get("command") in followers:
            argv = later.get("argv") or []
            return str(argv[2]) if len(argv) > 2 else ""
    return ""


def _started_job_id(stdout: str) -> str:
    """The durable job id a start command reports, whatever key it uses."""
    found = _job_id(stdout)
    if found:
        return found
    try:
        value = json.loads(stdout or "{}")
    except json.JSONDecodeError:
        return ""
    if isinstance(value, dict):
        for key in ("job", "durableJob", "pass"):
            inner = value.get(key)
            if isinstance(inner, dict) and (inner.get("jobId") or inner.get("job_id")):
                return str(inner.get("jobId") or inner.get("job_id"))
    return ""


def _settled(stdout: str) -> bool:
    try:
        value = json.loads(stdout or "{}")
    except json.JSONDecodeError:
        return True
    status = str((value or {}).get("status") or "") if isinstance(value, dict) else ""
    return status not in {"queued", "running", "pending", "starting"}


def recorded_commands(project: Path) -> list[dict[str, Any]]:
    """Pair each recorded start edge with its finish edge's exit code."""
    log = project / ".telemetry" / "command-events.jsonl"
    rows = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines() if line.strip()]
    commands: list[dict[str, Any]] = []
    open_by_name: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        if row.get("edge") == "start":
            item = {"command": row.get("command"), "argv": row.get("argv"),
                    "inputs": row.get("inputs") or {}, "at": row.get("at"), "exit_code": None}
            commands.append(item)
            open_by_name.setdefault(str(row.get("command")), []).append(item)
        elif row.get("edge") == "finish":
            pending = open_by_name.get(str(row.get("command"))) or []
            if pending:
                pending.pop(0)["exit_code"] = row.get("exit_code")
            elif row.get("argv"):
                # bootstrap: the project did not exist at its start edge
                commands.append({"command": row.get("command"), "argv": row.get("argv"), "inputs": {},
                                 "at": row.get("at"), "exit_code": row.get("exit_code")})
    return commands


def _remap(argv: list[str], old_root: str, new_root: Path, inputs: dict[str, str], store: Path, scratch: Path) -> list[str]:
    """Rewrite project paths and restore each recorded JSON input where it was read.

    An input that lived inside the project goes back to the same relative path in
    the new project (some commands require a current-project file); one outside
    goes to the scratch directory.
    """
    # A recorded path can be absolute (under the old project root) or relative to the
    # repo the agent ran in (`projects/<id>/search-request-0.json`, as on the f418063
    # run); both must land inside the replay project.
    rel_root = "projects/" + Path(old_root).name
    out = []
    for item in argv:
        item = item.replace(old_root, str(new_root))
        flag, sep, value = item.partition("=")
        target = value if sep else flag
        if target == rel_root or target.startswith(rel_root + "/"):
            target = str(new_root) + target[len(rel_root):]
            item = f"{flag}={target}" if sep else target
        out.append(item)
    for index, item in enumerate(out):
        flag, sep, inline = item.partition("=")
        if flag not in inputs:
            continue
        snapshot = store / f"{inputs[flag]}.json"
        if not snapshot.is_file():
            continue
        raw = inline if sep else (out[index + 1] if index + 1 < len(out) else "")
        target = Path(raw) if raw and Path(raw).is_absolute() and str(Path(raw)).startswith(str(new_root)) \
            else scratch / f"{inputs[flag]}.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(snapshot.read_text(encoding="utf-8").replace(old_root, str(new_root)), encoding="utf-8")
        if sep:
            out[index] = f"{flag}={target}"
        elif index + 1 < len(out):
            out[index + 1] = str(target)
    return out


def replay(export: Path, *, until: int | None = None, fixture: Path = DEFAULT_FIXTURE,
           media: bool = True) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="om-replay-") as tmp:
        work = Path(os.environ.get("OPENMONTAGE_REPLAY_WORK") or tmp)
        work.mkdir(parents=True, exist_ok=True)
        source = export
        if export.is_file():
            with tarfile.open(export) as archive:
                archive.extractall(work / "export", filter="data")
            found = next((p.parent for p in (work / "export").rglob("persian-video-workflow.json")), None)
            if found is None:
                raise SystemExit(f"no persian-video-workflow.json in {export}")
            source = found
        state = json.loads((source / "persian-video-workflow.json").read_text(encoding="utf-8"))
        project_id = str(state.get("project_id"))
        old_root = str((state.get("read_allowlist") or {}).get("project_root") or "")
        projects = work / "projects"
        project = projects / project_id
        commands = recorded_commands(source)
        if not any(cmd.get("argv") for cmd in commands):
            return {"ok": False, "reason": "this export's command log has no recorded argv; it predates #264"}
        user_inputs = work / "user-inputs"
        user_inputs.mkdir(parents=True)
        for name in ("narration.mp3", "narration.wav", "narration.m4a", "approved_script.txt"):
            if (source / "inputs" / name).is_file():
                shutil.copyfile(source / "inputs" / name, user_inputs / name)
        scratch = work / "inputs"
        scratch.mkdir()
        env = dict(os.environ, OPENMONTAGE_PROJECTS_DIR=str(projects),
                   OPENMONTAGE_REHEARSAL_FIXTURE=str(fixture),
                   PYTHONPATH=str(ROOT) + os.pathsep + os.environ.get("PYTHONPATH", ""))
        results: list[dict[str, Any]] = []
        job_ids: dict[str, str] = {}
        first_regression = None
        for index, cmd in enumerate(commands[:until]):
            name = str(cmd.get("command") or "")
            argv = cmd.get("argv")
            if not argv or (not media and name.startswith(_MEDIA)):
                results.append({"index": index, "command": name, "skipped": True})
                continue
            if name == "workflow:bootstrap":
                # The user's files lived outside the project; use the export's copies.
                staged = {p.name: p for p in user_inputs.iterdir()}
                source_names = {"narration": None, "script": None}
                for staged_name in staged:
                    source_names["script" if staged_name.endswith(".txt") else "narration"] = staged[staged_name]
                fixed = []
                for pos, item in enumerate(argv):
                    prev = argv[pos - 1] if pos else ""
                    if prev == "--narration" and source_names["narration"]:
                        item = str(source_names["narration"])
                    elif prev == "--approved-script-file" and item != "-" and source_names["script"]:
                        item = str(source_names["script"])
                    fixed.append(item)
                argv = fixed
            if name.startswith("checkpoint:"):
                snapshot = source / ".telemetry" / "inputs" / f"{(cmd.get('inputs') or {}).get('--checkpoint')}.json"
                payload = json.loads(snapshot.read_text(encoding="utf-8").replace(old_root, str(project)))
                code = (
                    "import json,sys; from pathlib import Path; from lib.checkpoint import write_checkpoint;"
                    "p=json.loads(Path(sys.argv[3]).read_text(encoding='utf-8'));"
                    "write_checkpoint(Path(sys.argv[1]), sys.argv[2], p['stage'], p['status'], p['artifacts'],"
                    " **{k: v for k, v in p['options'].items() if v is not None})"
                )
                staged = scratch / f"checkpoint-{index}.json"
                staged.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
                done = subprocess.run([sys.executable, "-c", code, str(projects), project_id, str(staged)],
                                      cwd=ROOT, env=env, capture_output=True, text=True, timeout=1500)
                row = {"index": index, "command": name, "recorded_exit": 0, "exit": done.returncode}
                if done.returncode != 0:
                    row.update(differs=True, detail=(done.stderr or done.stdout).strip()[-1500:])
                    first_regression = first_regression or row
                results.append(row)
                continue
            module = MODULES.get(name.split(":", 1)[0])
            if module is None:
                results.append({"index": index, "command": name, "skipped": True})
                continue
            call = _remap(list(argv), old_root, project, dict(cmd.get("inputs") or {}),
                          source / ".telemetry" / "inputs", scratch) if old_root else list(argv)
            # Durable job ids derive from content digests, so a replayed job can get
            # a new id; later commands naming the recorded id follow the new one.
            call = [job_ids.get(item, item) for item in call]
            done = subprocess.run([sys.executable, "-m", module, *call], cwd=ROOT, env=env,
                                  capture_output=True, text=True, timeout=1500)
            if name in _POLLS:
                # The original agent polled a durable job until it settled; wall time
                # differs here, so poll until the job reaches the recorded outcome. A
                # poll whose answer stops changing will never reach it (a job the
                # replay skipped, or one that settled differently), so it gives up
                # after POLL_STALL_SECONDS of identical answers instead of spinning
                # through 600 subprocesses per recorded poll.
                deadline = time.monotonic() + POLL_STALL_SECONDS
                last = (done.returncode, done.stdout)
                while not (done.returncode == cmd.get("exit_code") and _settled(done.stdout)):
                    if time.monotonic() > deadline:
                        break
                    time.sleep(0.25)
                    done = subprocess.run([sys.executable, "-m", module, *call], cwd=ROOT, env=env,
                                          capture_output=True, text=True, timeout=1500)
                    if (done.returncode, done.stdout) != last:
                        last = (done.returncode, done.stdout)
                        deadline = time.monotonic() + POLL_STALL_SECONDS
            if name in _JOB_STARTS and done.returncode == 0:
                new_id = _started_job_id(done.stdout)
                old_id = _next_recorded_job_id(commands, index, _JOB_STARTS[name])
                if new_id and old_id and new_id != old_id and new_id.split("-")[0] == old_id.split("-")[0]:
                    job_ids[old_id] = new_id
            recorded = cmd.get("exit_code")
            row = {"index": index, "command": name, "recorded_exit": recorded, "exit": done.returncode}
            if recorded is not None and done.returncode != recorded:
                row["differs"] = True
                row["detail"] = (done.stderr or done.stdout).strip()[-1500:]
                if recorded == 0 and first_regression is None:
                    first_regression = row
            results.append(row)
            if os.environ.get("OPENMONTAGE_REPLAY_ECHO"):
                print(f"[{index}] {name} recorded={row.get('recorded_exit')} now={row.get('exit')}", file=sys.stderr, flush=True)
        differs = [row for row in results if row.get("differs")]
        return {
            "ok": first_regression is None,
            "project_id": project_id,
            "replayed": sum(1 for row in results if not row.get("skipped")),
            "skipped": sum(1 for row in results if row.get("skipped")),
            "first_difference": differs[0] if differs else None,
            "first_regression": first_regression,
            "now_passes": [row for row in differs if row["recorded_exit"] not in (0, None) and row["exit"] == 0],
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="persian-run-replay", description=__doc__.splitlines()[0])
    parser.add_argument("export", type=Path)
    parser.add_argument("--until", type=int, default=None, help="replay only the first N commands")
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE,
                        help="rehearsal fixture serving the run's recorded provider results")
    parser.add_argument("--no-media", action="store_true", help="skip browser/ffmpeg media jobs")
    args = parser.parse_args(argv)
    report = replay(args.export.expanduser().resolve(), until=args.until,
                    fixture=args.fixture.expanduser().resolve(), media=not args.no_media)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
