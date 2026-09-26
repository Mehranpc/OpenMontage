"""Durable acquisition provider pass bound to the Persian production run kernel.

The search/download pass used to run **inside an agent turn**, by calling
``direct_clip_search`` inline. Two things followed from that: the largest block of
unattended wall time in a run was charged to no causal category at all, and a crash
between ``asset-request`` and ``asset-result`` left ``asset_usage.pending_pass`` set —
a state the phase cannot complete from, with the provider search possibly already
paid for.

Here the same three steps run as one durable, measured execution:

    bounded_asset_search_request -> direct_clip_search -> record_asset_search_result

The budget clamp, the accounting, and the ceiling validations are unchanged: they
remain owned by ``lib.persian_video_workflow``, and this module does no arithmetic of
its own.

The pass deliberately does **not** own the workflow transition. Candidate staging,
review, rejection, selection, manifest and checkpoint are agent judgement, so
``complete --phase acquire_assets`` is still what advances the phase and its existing
workspace-binding validation still decides whether it may (#188).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence

from lib import persian_run_kernel as kernel
from lib import persian_video_workflow as workflow
from tools.tool_registry import registry as default_registry

ASSET_JOB_VERSION = "1.0"
SEARCH_TOOL = "direct_clip_search"
_PHASE = "acquire_assets"
_SEMANTIC_RESULT_ENV = "OPENMONTAGE_DURABLE_RESULT_PATH"


class AssetJobError(workflow.PersianVideoWorkflowError):
    """Raised when durable acquisition identity or lifecycle truth is inconsistent.

    Derives from the front door's own error so every `asset-search` failure exits
    through the same clean `parser.error` contract as the other commands instead of a
    traceback. The import cannot run the other way -- this module reads the workflow
    module -- so this is the direction that works without a cycle (#193).
    """


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_bytes(value: Mapping[str, Any]) -> bytes:
    return (json.dumps(dict(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temp.write_bytes(_canonical_bytes(value))
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)


def _within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _require_digest(value: object, label: str) -> str:
    text = str(value or "").strip().lower()
    if len(text) != 64 or any(ch not in "0123456789abcdef" for ch in text):
        raise AssetJobError(f"{label} must be a lowercase 64-character sha256")
    return text


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AssetJobError(f"{label} is unreadable JSON: {path}") from exc
    if not isinstance(value, dict):
        raise AssetJobError(f"{label} must contain a JSON object")
    return value


def _project_root(state: Mapping[str, Any]) -> Path:
    root = str((state.get("read_allowlist") or {}).get("project_root") or "").strip()
    if not root:
        raise AssetJobError("workflow state has no project root")
    return Path(root).resolve()


def run_asset_search_job(
    project_id: str,
    *,
    request_path: Path,
    retry_pass: int,
    attempt: int = 0,
    pipeline_dir: Path | None = None,
    job_id: str | None = None,
    registry=default_registry,
    timeout_seconds: float = 1800.0,
    launch: bool = True,
    now=None,
) -> dict[str, Any]:
    """Run one bounded provider pass as a durable, measured execution.

    ``launch=False`` starts the job and returns without waiting, for callers that must
    stay asynchronous; the same identity is then reconciled with
    ``persian_run_kernel status <project> <job-id>``.

    ``attempt`` exists because idempotence protects against *duplicate success*, not
    against retrying a *failure*: a released pass (see
    ``workflow.release_asset_search_pass``) is re-issued under the next attempt, where
    the same (pass, request bytes) identity would otherwise reconcile the failed
    envelope forever (#193).
    """
    state = workflow.load_workflow_state(project_id, pipeline_dir=pipeline_dir)
    if state.get("next_phase") != _PHASE:
        raise AssetJobError(
            f"durable asset search is only valid during {_PHASE}; "
            f"next phase is {state.get('next_phase')!r}"
        )
    root = _project_root(state)
    request = request_path.expanduser().resolve()
    if not request.is_file() or not _within(request, root):
        raise AssetJobError("asset request must be a current-project file")
    request_sha = _sha(request)
    # Parsed here as well as in the worker so a malformed request fails before a
    # durable identity is minted for it.
    _read_json(request, "asset request")

    policy = workflow.asset_search_policy()
    if retry_pass < 0 or retry_pass > int(policy["max_retry_passes"]):
        raise AssetJobError(
            f"asset retry pass {retry_pass} exceeds max {policy['max_retry_passes']}"
        )

    attempt = int(attempt)
    if attempt < 0:
        raise AssetJobError("asset search attempt must not be negative")
    result_path = (
        root / "artifacts" / "acquisition"
        / f"search-pass-{retry_pass}-{request_sha[:16]}-a{attempt}.json"
    )
    effective_job_id = job_id or f"asset-search-{retry_pass}-{request_sha[:16]}-a{attempt}"
    # The logical identity of the pass is (retry pass, exact request bytes, attempt): the
    # same pass resumed after a crash reconciles instead of re-issuing the search, a
    # changed request is a different search rather than a re-run of this one, and a
    # released failed pass is retried under the next attempt.
    idempotence_key = f"asset-search-{retry_pass}-{request_sha[:32]}-a{attempt}"
    argv = [
        sys.executable,
        "-m",
        "lib.persian_asset_job",
        "_worker",
        "--project",
        project_id,
        "--pipeline-dir",
        str(Path(pipeline_dir).expanduser().resolve()) if pipeline_dir else str(workflow.PROJECTS_DIR),
        "--request",
        str(request),
        "--request-sha256",
        request_sha,
        "--retry-pass",
        str(retry_pass),
        "--result",
        str(result_path),
    ]
    try:
        if launch:
            return {
                **dict(
                    kernel.run_phase_job(
                        project_id,
                        job_id=effective_job_id,
                        phase=_PHASE,
                        argv=argv,
                        idempotence_key=idempotence_key,
                        telemetry_category="provider_network_wait",
                        timeout_seconds=timeout_seconds,
                        owns_transition=False,
                        pipeline_dir=pipeline_dir,
                        now=now,
                    )
                ),
                "assetRequestPath": str(request),
                "assetRequestSha256": request_sha,
                "assetSearchResultPath": str(result_path),
            }
        return {
            **dict(
                kernel.start_phase_job(
                    project_id,
                    job_id=effective_job_id,
                    phase=_PHASE,
                    argv=argv,
                    idempotence_key=idempotence_key,
                    telemetry_category="provider_network_wait",
                    owns_transition=False,
                    pipeline_dir=pipeline_dir,
                    now=now,
                )
            ),
            "assetRequestPath": str(request),
            "assetRequestSha256": request_sha,
            "assetSearchResultPath": str(result_path),
        }
    except kernel.PersianRunKernelError as exc:
        raise AssetJobError(
            _failure_detail(project_id, effective_job_id, exc, pipeline_dir)
        ) from exc


def _failure_detail(
    project_id: str,
    job_id: str,
    exc: Exception,
    pipeline_dir: Path | None,
) -> str:
    """Append the job's semantic error, which is where the real reason lives.

    The kernel's own message is generic ("finished with execution outcome 'failed'"), so
    without this the provider's reason -- the only thing that says what to do next --
    would be reachable only by inspecting the envelope by hand (#193).
    """
    try:
        envelope = kernel.load_execution_envelope(
            project_id, job_id, pipeline_dir=pipeline_dir
        )
    except (kernel.PersianRunKernelError, OSError, ValueError, KeyError):
        return str(exc)
    # A reported `success: false` carries its reason inside the semantic result;
    # `semanticError` is reserved for a result that could not be read at all.
    semantic = envelope.get("semanticResult")
    detail = str(semantic.get("error") or "").strip() if isinstance(semantic, Mapping) else ""
    if not detail:
        detail = str(envelope.get("semanticError") or "").strip()
    return f"{exc} — {detail}" if detail else str(exc)


def _write_semantic_result(payload: Mapping[str, Any]) -> None:
    raw = str(os.environ.get(_SEMANTIC_RESULT_ENV) or "").strip()
    if not raw:
        raise AssetJobError(
            f"durable asset worker requires {_SEMANTIC_RESULT_ENV} from the run kernel"
        )
    _atomic_json(Path(raw).expanduser().resolve(), payload)


def _tool_data(result: Any) -> Mapping[str, Any]:
    data = getattr(result, "data", None)
    if getattr(result, "success", False) is not True or not isinstance(data, Mapping):
        error = str(getattr(result, "error", "") or "the search tool reported no result")
        raise AssetJobError(f"{SEARCH_TOOL} failed: {error}")
    return data


def run_asset_search_worker(
    *,
    project_id: str,
    request_path: Path,
    request_sha256: str,
    retry_pass: int,
    result_path: Path,
    pipeline_dir: Path | None = None,
    registry=default_registry,
) -> int:
    """Execute one frozen, bounded provider pass and report semantic truth."""
    request_path = request_path.expanduser().resolve()
    result_path = result_path.expanduser().resolve()
    expected_sha = _require_digest(request_sha256, "asset request sha256")
    issued = False
    try:
        state = workflow.load_workflow_state(project_id, pipeline_dir=pipeline_dir)
        root = _project_root(state)
        if not _within(request_path, root):
            raise AssetJobError("asset request must be a current-project file")
        if not request_path.is_file() or _sha(request_path) != expected_sha:
            raise AssetJobError(
                "asset request bytes changed after the durable pass was started"
            )
        request = _read_json(request_path, "asset request")

        bounded = workflow.bounded_asset_search_request(
            project_id, request, retry_pass=retry_pass, pipeline_dir=pipeline_dir
        )
        # From here the pass exists in workflow state and must be closed on every
        # outcome -- settling it on success, releasing it on failure -- or the run is
        # left unable to complete or re-search (#193).
        issued = True
        tool = registry.get(SEARCH_TOOL)
        data = dict(_tool_data(tool.execute(bounded)))
        # Accounting stays where it already lives: this only settles the pass the
        # request opened, and it is what clears `pending_pass` so the phase can finish.
        workflow.record_asset_search_result(
            project_id, retry_pass=retry_pass, result_data=data, pipeline_dir=pipeline_dir
        )

        payload = {
            **data,
            "asset_job_version": ASSET_JOB_VERSION,
            "retry_pass": retry_pass,
            "asset_request_sha256": expected_sha,
        }
        _atomic_json(result_path, payload)
        _write_semantic_result({
            "success": True,
            "data": {
                "retryPass": retry_pass,
                "assetRequestPath": str(request_path),
                "assetRequestSha256": expected_sha,
                "assetSearchResultPath": str(result_path),
                "assetSearchResultSha256": _sha(result_path),
                "candidatesConsidered": int(data.get("candidates_considered") or 0),
                "bytesDownloaded": int(data.get("bytes_downloaded") or 0),
                "outputDir": str(data.get("output_dir") or ""),
            },
        })
        return 0
    except (AssetJobError, workflow.PersianVideoWorkflowError, OSError, ValueError) as exc:
        return _fail_worker(
            exc, project_id=project_id, retry_pass=retry_pass, expected_sha=expected_sha,
            result_path=result_path, issued=issued, pipeline_dir=pipeline_dir, exit_code=0,
        )
    except Exception as exc:
        return _fail_worker(
            exc, project_id=project_id, retry_pass=retry_pass, expected_sha=expected_sha,
            result_path=result_path, issued=issued, pipeline_dir=pipeline_dir, exit_code=1,
        )


def _fail_worker(
    exc: Exception,
    *,
    project_id: str,
    retry_pass: int,
    expected_sha: str,
    result_path: Path,
    issued: bool,
    pipeline_dir: Path | None,
    exit_code: int,
) -> int:
    """Report semantic failure and release the pass this execution issued.

    The pass is released, not settled: a provider outage did not discover anything, so
    recording it as a completed pass would spend the retry budget on a failure and put
    invented counters into the download ceiling.
    """
    result_path.unlink(missing_ok=True)
    error = str(exc) if exit_code == 0 else f"unexpected asset search worker failure: {exc}"
    released = False
    if issued:
        try:
            workflow.release_asset_search_pass(
                project_id, retry_pass=retry_pass, reason=error, pipeline_dir=pipeline_dir
            )
            released = True
        except (workflow.PersianVideoWorkflowError, OSError, ValueError):
            # Best effort: reporting the failure matters more than the release, and the
            # operator still has `asset-search-release` for a worker that died outright.
            released = False
    _write_semantic_result({
        "success": False,
        "error": error,
        "data": {
            "retryPass": retry_pass,
            "assetRequestSha256": expected_sha,
            "passReleased": released,
        },
    })
    # Semantic failure intentionally exits zero for a handled failure. The production run
    # kernel must consume the semantic result envelope rather than treating exit code as
    # truth.
    return exit_code


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="persian-asset-job")
    sub = parser.add_subparsers(dest="command", required=True)
    worker = sub.add_parser("_worker")
    worker.add_argument("--project", required=True)
    worker.add_argument("--pipeline-dir", type=Path)
    worker.add_argument("--request", type=Path, required=True)
    worker.add_argument("--request-sha256", required=True)
    worker.add_argument("--retry-pass", type=int, required=True)
    worker.add_argument("--result", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "_worker":
        return run_asset_search_worker(
            project_id=args.project,
            request_path=args.request,
            request_sha256=args.request_sha256,
            retry_pass=args.retry_pass,
            result_path=args.result,
            pipeline_dir=args.pipeline_dir,
        )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
