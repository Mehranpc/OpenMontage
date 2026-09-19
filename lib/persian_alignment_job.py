"""Durable alignment execution bound to the Persian production run kernel.

Provider availability is probed before a durable job is launched. The child then
executes the frozen provider plan, writes one digest-bound alignment artifact, and
reports semantic success/failure through OPENMONTAGE_DURABLE_RESULT_PATH. Workflow
advancement consumes that semantic result rather than inferring success from exit code.
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
from lib.persian_alignment_provider import (
    AlignmentProviderError,
    build_alignment_provider_plan,
    execute_alignment_with_fallback,
)
from lib.persian_srt_alignment import build_script_aligned_cues
from tools.tool_registry import registry as default_registry

ALIGNMENT_JOB_VERSION = "1.0"
_SEMANTIC_RESULT_ENV = "OPENMONTAGE_DURABLE_RESULT_PATH"


class AlignmentJobError(RuntimeError):
    """Raised when durable alignment identity or lifecycle truth is inconsistent."""


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
        raise AlignmentJobError(f"{label} must be a lowercase 64-character sha256")
    return text


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AlignmentJobError(f"{label} is unreadable JSON: {path}") from exc
    if not isinstance(value, dict):
        raise AlignmentJobError(f"{label} must contain a JSON object")
    return value


def _selected_candidate(plan: Mapping[str, Any]) -> Mapping[str, Any]:
    selected = str(plan.get("selectedTool") or "")
    for item in list(plan.get("candidates") or []):
        if isinstance(item, Mapping) and str(item.get("tool") or "") == selected:
            return item
    raise AlignmentJobError("provider plan selected tool is missing from candidate evidence")


def _telemetry_category(plan: Mapping[str, Any]) -> str:
    candidate = _selected_candidate(plan)
    return "provider_network_wait" if str(candidate.get("runtime") or "") == "api" else "machine_local_execution"


def _project_inputs(state: Mapping[str, Any]) -> tuple[Path, str, Path | None, str | None]:
    root = Path(str((state.get("read_allowlist") or {}).get("project_root") or "")).resolve()
    input_record = state.get("input") if isinstance(state.get("input"), Mapping) else {}
    narration = input_record.get("narration") if isinstance(input_record, Mapping) else None
    if not isinstance(narration, Mapping):
        raise AlignmentJobError("align_script_timing requires narration input")
    narration_path = Path(str(narration.get("source_path") or "")).resolve()
    if not narration_path.is_file() or not _within(narration_path, root):
        raise AlignmentJobError("narration input must be a current-project file")
    narration_sha = _require_digest(narration.get("sha256"), "narration sha256")
    if _sha(narration_path) != narration_sha:
        raise AlignmentJobError("narration input changed after workflow bootstrap")

    approved = input_record.get("approved_script") if isinstance(input_record, Mapping) else None
    script_path: Path | None = None
    script_sha: str | None = None
    if isinstance(approved, Mapping):
        script_path = Path(str(approved.get("source_path") or "")).resolve()
        if not script_path.is_file() or not _within(script_path, root):
            raise AlignmentJobError("approved script must be a current-project file")
        script_sha = _require_digest(approved.get("sha256"), "approved script sha256")
        if _sha(script_path) != script_sha:
            raise AlignmentJobError("approved script changed after workflow bootstrap")
    return narration_path, narration_sha, script_path, script_sha


def start_alignment_job(
    project_id: str,
    *,
    pipeline_dir: Path | None = None,
    registry=default_registry,
    job_id: str | None = None,
    launch: bool = True,
) -> dict[str, Any]:
    """Probe provider fit first, persist a frozen plan, then launch one durable job."""
    state = workflow.load_workflow_state(project_id, pipeline_dir=pipeline_dir)
    if state.get("next_phase") != "align_script_timing":
        raise AlignmentJobError(
            f"durable alignment is only valid during align_script_timing; next phase is {state.get('next_phase')!r}"
        )
    policy = state.get("alignment_policy") or workflow.alignment_execution_policy(state)
    try:
        plan = build_alignment_provider_plan(policy, registry=registry)
    except AlignmentProviderError as exc:
        raise AlignmentJobError(str(exc)) from exc

    narration_path, narration_sha, script_path, script_sha = _project_inputs(state)
    root = Path(str(state["read_allowlist"]["project_root"])).resolve()
    bundle = {
        "version": ALIGNMENT_JOB_VERSION,
        "projectId": project_id,
        "phase": "align_script_timing",
        "policy": dict(policy),
        "language": "fa",
        "narrationPath": str(narration_path),
        "narrationSha256": narration_sha,
        "approvedScriptPath": str(script_path) if script_path else None,
        "approvedScriptSha256": script_sha,
        "providerPlan": plan,
    }
    payload = _canonical_bytes(bundle)
    plan_sha = hashlib.sha256(payload).hexdigest()
    alignment_dir = root / "artifacts" / "alignment"
    plan_path = alignment_dir / f"provider-plan-{plan_sha}.json"
    if plan_path.exists():
        if plan_path.read_bytes() != payload:
            raise AlignmentJobError("digest-addressed provider plan path contains different bytes")
    else:
        plan_path.parent.mkdir(parents=True, exist_ok=True)
        temp = plan_path.with_name(f".{plan_path.name}.{os.getpid()}.tmp")
        try:
            temp.write_bytes(payload)
            temp.replace(plan_path)
        finally:
            temp.unlink(missing_ok=True)

    result_path = alignment_dir / f"alignment-result-{plan_sha}.json"
    output_dir = root / "artifacts" / "transcription" / plan_sha[:16]
    effective_job_id = job_id or f"alignment-{plan_sha[:16]}"
    idempotence_key = f"alignment-{plan_sha[:32]}"
    argv = [
        sys.executable,
        "-m",
        "lib.persian_alignment_job",
        "_worker",
        "--plan",
        str(plan_path),
        "--plan-sha256",
        plan_sha,
        "--narration",
        str(narration_path),
        "--output-dir",
        str(output_dir),
        "--result",
        str(result_path),
    ]
    if script_path is not None:
        argv.extend(["--approved-script", str(script_path)])

    try:
        started = kernel.start_phase_job(
            project_id,
            job_id=effective_job_id,
            phase="align_script_timing",
            argv=argv,
            idempotence_key=idempotence_key,
            telemetry_category=_telemetry_category(plan),
            pipeline_dir=pipeline_dir,
            launch=launch,
        )
    except kernel.PersianRunKernelError as exc:
        raise AlignmentJobError(str(exc)) from exc
    return {
        **dict(started),
        "providerPlanPath": str(plan_path),
        "providerPlanSha256": plan_sha,
        "alignmentResultPath": str(result_path),
        "selectedTool": plan.get("selectedTool"),
        "selectedProvider": plan.get("selectedProvider"),
        "fallbackReason": plan.get("fallbackReason"),
    }


def _write_semantic_result(payload: Mapping[str, Any]) -> None:
    raw = str(os.environ.get(_SEMANTIC_RESULT_ENV) or "").strip()
    if not raw:
        raise AlignmentJobError(
            f"durable alignment worker requires {_SEMANTIC_RESULT_ENV} from the run kernel"
        )
    _atomic_json(Path(raw).expanduser().resolve(), payload)


def _script_alignment_validator(script_path: Path, script_sha: str):
    text = script_path.read_text(encoding="utf-8")
    if hashlib.sha256(text.encode("utf-8")).hexdigest() != script_sha:
        raise AlignmentJobError("approved script bytes do not match frozen provider plan")
    approved = {
        "text": text,
        "sha256": script_sha,
        "matchPolicy": "exact",
        "maxCps": 21,
    }

    def validate(words: list[dict[str, Any]]) -> None:
        build_script_aligned_cues(approved, words, max_visible_chars=36, id_prefix="caption")

    return validate


def run_alignment_worker(
    *,
    plan_path: Path,
    plan_sha256: str,
    narration_path: Path,
    output_dir: Path,
    result_path: Path,
    approved_script_path: Path | None = None,
    registry=default_registry,
) -> int:
    """Execute a frozen provider plan and report semantic truth to the run kernel."""
    plan_path = plan_path.expanduser().resolve()
    narration_path = narration_path.expanduser().resolve()
    output_dir = output_dir.expanduser().resolve()
    result_path = result_path.expanduser().resolve()
    expected_plan_sha = _require_digest(plan_sha256, "provider plan sha256")
    try:
        if not plan_path.is_file() or _sha(plan_path) != expected_plan_sha:
            raise AlignmentJobError("provider plan sha256 does not match the frozen plan bytes")
        bundle = _read_json(plan_path, "provider plan")
        if str(bundle.get("version") or "") != ALIGNMENT_JOB_VERSION:
            raise AlignmentJobError("provider plan version is unsupported")
        expected_narration = _require_digest(bundle.get("narrationSha256"), "narration sha256")
        if not narration_path.is_file() or _sha(narration_path) != expected_narration:
            raise AlignmentJobError("narration bytes changed after provider planning")
        frozen_narration = str(bundle.get("narrationPath") or "")
        if frozen_narration and narration_path != Path(frozen_narration).expanduser().resolve():
            raise AlignmentJobError("worker narration path differs from frozen provider plan")

        script_sha_raw = bundle.get("approvedScriptSha256")
        validator = None
        if script_sha_raw is not None:
            script_sha = _require_digest(script_sha_raw, "approved script sha256")
            script_path = (
                approved_script_path.expanduser().resolve()
                if approved_script_path is not None
                else Path(str(bundle.get("approvedScriptPath") or "")).expanduser().resolve()
            )
            if not script_path.is_file() or _sha(script_path) != script_sha:
                raise AlignmentJobError("approved script bytes changed after provider planning")
            frozen_script = str(bundle.get("approvedScriptPath") or "")
            if frozen_script and script_path != Path(frozen_script).expanduser().resolve():
                raise AlignmentJobError("worker approved-script path differs from frozen provider plan")
            validator = _script_alignment_validator(script_path, script_sha)

        plan = bundle.get("providerPlan")
        if not isinstance(plan, Mapping):
            raise AlignmentJobError("provider plan bundle is missing providerPlan")
        output_dir.mkdir(parents=True, exist_ok=True)
        data = execute_alignment_with_fallback(
            plan,
            input_path=str(narration_path),
            output_dir=str(output_dir),
            language=str(bundle.get("language") or "fa"),
            initial_prompt=(approved_script_path.read_text(encoding="utf-8") if approved_script_path else None),
            registry=registry,
            validate_word_timings=validator,
        )
        words = list(data.get("word_timestamps") or [])
        if not words:
            raise AlignmentJobError("alignment provider returned no word timings")
        result_payload = {
            **dict(data),
            "alignment_job_version": ALIGNMENT_JOB_VERSION,
            "provider_plan_sha256": expected_plan_sha,
            "narration_sha256": expected_narration,
            "approved_script_sha256": bundle.get("approvedScriptSha256"),
        }
        _atomic_json(result_path, result_payload)
        result_sha = _sha(result_path)
        decision = result_payload.get("provider_decision")
        _write_semantic_result({
            "success": True,
            "data": {
                "alignmentResultPath": str(result_path),
                "alignmentResultSha256": result_sha,
                "providerPlanPath": str(plan_path),
                "providerPlanSha256": expected_plan_sha,
                "wordTimingCount": len(words),
                "selectedProvider": (decision or {}).get("selectedProvider") if isinstance(decision, Mapping) else None,
                "selectedTool": (decision or {}).get("selectedTool") if isinstance(decision, Mapping) else None,
                "selectedModel": (decision or {}).get("selectedModel") if isinstance(decision, Mapping) else None,
            },
        })
        return 0
    except (AlignmentProviderError, AlignmentJobError, OSError, ValueError) as exc:
        result_path.unlink(missing_ok=True)
        _write_semantic_result({
            "success": False,
            "error": str(exc),
            "data": {
                "providerPlanPath": str(plan_path),
                "providerPlanSha256": expected_plan_sha,
            },
        })
        # Semantic failure intentionally exits zero. The production run kernel must
        # consume the semantic result envelope rather than treating exit code as truth.
        return 0
    except Exception as exc:
        result_path.unlink(missing_ok=True)
        _write_semantic_result({
            "success": False,
            "error": f"unexpected alignment worker failure: {exc}",
            "data": {
                "providerPlanPath": str(plan_path),
                "providerPlanSha256": expected_plan_sha,
            },
        })
        return 1


def reconcile_alignment_job(
    project_id: str, job_id: str, *, pipeline_dir: Path | None = None
) -> dict[str, Any]:
    try:
        return kernel.reconcile_phase_job(project_id, job_id, pipeline_dir=pipeline_dir)
    except kernel.PersianRunKernelError as exc:
        raise AlignmentJobError(str(exc)) from exc


def _completion_evidence_from_job(
    state: Mapping[str, Any], job: Mapping[str, Any]
) -> dict[str, Any]:
    if str(job.get("executionOutcome") or "") != "succeeded":
        raise AlignmentJobError("alignment commit requires successful durable semantic execution")
    semantic = job.get("semanticResult")
    if not isinstance(semantic, Mapping) or semantic.get("success") is not True:
        raise AlignmentJobError("alignment durable job lacks a successful semantic result")
    data = semantic.get("data")
    if not isinstance(data, Mapping):
        raise AlignmentJobError("alignment semantic result requires identity data")

    root = Path(str(state["read_allowlist"]["project_root"])).resolve()
    result_path = Path(str(data.get("alignmentResultPath") or "")).expanduser().resolve()
    if not result_path.is_file() or not _within(result_path, root):
        raise AlignmentJobError("alignment result must be a current-project artifact")
    expected_result_sha = _require_digest(data.get("alignmentResultSha256"), "alignment result sha256")
    if _sha(result_path) != expected_result_sha:
        raise AlignmentJobError("alignment result sha256 does not match persisted artifact bytes")

    raw_plan_path = str(data.get("providerPlanPath") or "").strip()
    if not raw_plan_path:
        raise AlignmentJobError("provider plan artifact path is required for alignment commit")
    plan_path = Path(raw_plan_path).expanduser().resolve()
    if not plan_path.is_file() or not _within(plan_path, root):
        raise AlignmentJobError("provider plan artifact must be a current-project file")
    expected_plan_sha = _require_digest(data.get("providerPlanSha256"), "provider plan sha256")
    if _sha(plan_path) != expected_plan_sha:
        raise AlignmentJobError("provider plan sha256 does not match persisted plan bytes")
    plan_bundle = _read_json(plan_path, "provider plan")
    frozen_plan = plan_bundle.get("providerPlan")
    if not isinstance(frozen_plan, Mapping):
        raise AlignmentJobError("provider plan artifact is missing providerPlan evidence")

    result = _read_json(result_path, "alignment result")
    if str(result.get("provider_plan_sha256") or "") != expected_plan_sha:
        raise AlignmentJobError("alignment result is bound to a different provider plan")
    narration_path, narration_sha, script_path, script_sha = _project_inputs(state)
    if str(result.get("narration_sha256") or "") != narration_sha:
        raise AlignmentJobError("alignment result narration identity does not match workflow input")
    if result.get("approved_script_sha256") != script_sha:
        raise AlignmentJobError("alignment result script identity does not match workflow input")
    decision = result.get("provider_decision")
    words = result.get("word_timestamps")
    if not isinstance(decision, Mapping) or not isinstance(words, list) or not words:
        raise AlignmentJobError("alignment result lacks provider decision or word timings")
    for key in ("capability", "mode", "scriptAuthority", "primaryProfile", "selectionPolicy", "candidates"):
        if decision.get(key) != frozen_plan.get(key):
            raise AlignmentJobError(
                f"alignment provider decision drifted from frozen plan field {key!r}"
            )
    evidence = {
        "provider_decision": dict(decision),
        "word_timing_count": len(words),
        "alignment_mode": result.get("alignment_mode") or decision.get("mode"),
        "provider": decision.get("selectedProvider"),
        "provider_tool": decision.get("selectedTool"),
        "model": decision.get("selectedModel"),
        "heavy_recovery_used": bool(decision.get("heavyRecoveryUsed")),
        "alignment_result_path": str(result_path),
        "alignment_result_sha256": expected_result_sha,
        "provider_plan_sha256": expected_plan_sha,
        "provider_plan_path": str(plan_path),
    }
    return evidence


def commit_alignment_job(
    project_id: str, job_id: str, *, pipeline_dir: Path | None = None
) -> dict[str, Any]:
    state = workflow.load_workflow_state(project_id, pipeline_dir=pipeline_dir)
    try:
        job = kernel.reconcile_phase_job(project_id, job_id, pipeline_dir=pipeline_dir)
        evidence = _completion_evidence_from_job(state, job)
        return kernel.commit_phase_job(
            project_id,
            job_id,
            evidence=evidence,
            pipeline_dir=pipeline_dir,
        )
    except kernel.PersianRunKernelError as exc:
        raise AlignmentJobError(str(exc)) from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="persian-alignment-job")
    sub = parser.add_subparsers(dest="command", required=True)
    worker = sub.add_parser("_worker")
    worker.add_argument("--plan", type=Path, required=True)
    worker.add_argument("--plan-sha256", required=True)
    worker.add_argument("--narration", type=Path, required=True)
    worker.add_argument("--output-dir", type=Path, required=True)
    worker.add_argument("--result", type=Path, required=True)
    worker.add_argument("--approved-script", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "_worker":
        return run_alignment_worker(
            plan_path=args.plan,
            plan_sha256=args.plan_sha256,
            narration_path=args.narration,
            output_dir=args.output_dir,
            result_path=args.result,
            approved_script_path=args.approved_script,
        )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
