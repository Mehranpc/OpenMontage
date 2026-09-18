from __future__ import annotations

import json
from pathlib import Path
import time

import pytest

from lib import persian_run_kernel as kernel
from lib import persian_video_workflow as workflow


def _fresh_project(tmp_path: Path, *, with_narration: bool = False) -> Path:
    projects_root = tmp_path / "projects"
    narration_path = None
    if with_narration:
        narration = tmp_path / "narration.wav"
        narration.write_bytes(b"not-real-audio-but-stable-input-bytes")
        narration_path = str(narration)
    workflow.bootstrap_persian_video(
        title="execution truth",
        narration_path=narration_path,
        approved_script="متن تأییدشده برای آزمون",
        project_id="run",
        pipeline_dir=projects_root,
        backlot_opener=lambda _project_id: 0,
    )
    return projects_root


def _semantic_child(*, success: bool, error: str | None = None) -> str:
    payload = {"success": success}
    if error is not None:
        payload["error"] = error
    return (
        "import json, os; from pathlib import Path; "
        "path = Path(os.environ['OPENMONTAGE_DURABLE_RESULT_PATH']); "
        f"path.write_text(json.dumps({payload!r}))"
    )


def _wait_for_job(projects_root: Path, job_id: str) -> dict:
    terminal = {"succeeded", "failed", "interrupted"}
    result = kernel.reconcile_phase_job("run", job_id, pipeline_dir=projects_root)
    for _ in range(100):
        if result.get("status") in terminal:
            return result
        time.sleep(0.05)
        result = kernel.reconcile_phase_job("run", job_id, pipeline_dir=projects_root)
    return result


def _prepare_inputs_evidence(projects_root: Path) -> dict[str, str]:
    state = workflow.load_workflow_state("run", pipeline_dir=projects_root)
    return {
        "authoritative_script_sha256": state["input"]["approved_script"]["sha256"],
        "narration_sha256": state["input"]["narration"]["sha256"],
    }


def test_front_door_zero_exit_does_not_hide_failed_semantic_result(tmp_path: Path) -> None:
    projects_root = _fresh_project(tmp_path)
    kernel.start_phase_job(
        "run",
        job_id="semantic-failure",
        phase="prepare_inputs",
        argv=["python", "-c", _semantic_child(success=False, error="provider unavailable")],
        idempotence_key="semantic-failure-v1",
        pipeline_dir=projects_root,
    )

    final = _wait_for_job(projects_root, "semantic-failure")
    assert final["status"] == "failed"
    assert final["processOutcome"] == "succeeded"
    assert final["semanticOutcome"] == "failed"
    assert final["executionOutcome"] == "failed"
    assert final["semanticResult"]["success"] is False
    assert final["semanticResult"]["error"] == "provider unavailable"


def test_front_door_binds_durable_job_to_one_phase_attempt(tmp_path: Path) -> None:
    projects_root = _fresh_project(tmp_path)
    started = kernel.start_phase_job(
        "run",
        job_id="bound-failure",
        phase="prepare_inputs",
        argv=["python", "-c", _semantic_child(success=False, error="bad timing")],
        idempotence_key="bound-failure-v1",
        pipeline_dir=projects_root,
    )
    assert started["phaseAttempt"] == 1

    _wait_for_job(projects_root, "bound-failure")
    state = workflow.load_workflow_state("run", pipeline_dir=projects_root)
    envelope = kernel.load_execution_envelope("run", "bound-failure", pipeline_dir=projects_root)
    assert envelope["phase"] == "prepare_inputs"
    assert envelope["phaseAttempt"] == 1
    assert envelope["processOutcome"] == "succeeded"
    assert envelope["semanticOutcome"] == "failed"
    assert envelope["executionOutcome"] == "failed"
    assert state["phase_telemetry"]["prepare_inputs"][-1]["outcome"] == "failed"
    assert state["next_phase"] == "prepare_inputs"


def test_successful_job_advances_only_through_digest_bound_commit(tmp_path: Path) -> None:
    projects_root = _fresh_project(tmp_path, with_narration=True)
    kernel.start_phase_job(
        "run",
        job_id="prepare-success",
        phase="prepare_inputs",
        argv=["python", "-c", _semantic_child(success=True)],
        idempotence_key="prepare-success-v1",
        pipeline_dir=projects_root,
    )
    final = _wait_for_job(projects_root, "prepare-success")
    assert final["executionOutcome"] == "succeeded"
    assert workflow.load_workflow_state("run", pipeline_dir=projects_root)["next_phase"] == "prepare_inputs"

    evidence = _prepare_inputs_evidence(projects_root)
    committed = kernel.commit_phase_job(
        "run", "prepare-success", evidence=evidence, pipeline_dir=projects_root
    )
    assert committed["next_phase"] == "align_script_timing"
    envelope = kernel.load_execution_envelope("run", "prepare-success", pipeline_dir=projects_root)
    assert envelope["workflowTransitionOutcome"] == "succeeded"
    assert envelope["checkpointOutcome"] == "not_applicable"
    assert envelope["artifactIdentity"]["authoritative_script_sha256"] == evidence["authoritative_script_sha256"]
    assert envelope["artifactIdentity"]["narration_sha256"] == evidence["narration_sha256"]

    repeated = kernel.commit_phase_job(
        "run", "prepare-success", evidence=evidence, pipeline_dir=projects_root
    )
    assert repeated["next_phase"] == "align_script_timing"
    assert kernel.load_execution_envelope(
        "run", "prepare-success", pipeline_dir=projects_root
    )["workflowTransitionOutcome"] == "succeeded"


def test_failed_commit_preserves_successful_execution_for_retry(tmp_path: Path) -> None:
    projects_root = _fresh_project(tmp_path, with_narration=True)
    kernel.start_phase_job(
        "run",
        job_id="recoverable-commit",
        phase="prepare_inputs",
        argv=["python", "-c", _semantic_child(success=True)],
        idempotence_key="recoverable-commit-v1",
        pipeline_dir=projects_root,
    )
    _wait_for_job(projects_root, "recoverable-commit")

    with pytest.raises(workflow.PersianVideoWorkflowError, match="authoritative_script_sha256"):
        kernel.commit_phase_job(
            "run", "recoverable-commit", evidence={}, pipeline_dir=projects_root
        )

    after_failure = workflow.load_workflow_state("run", pipeline_dir=projects_root)
    envelope = kernel.load_execution_envelope(
        "run", "recoverable-commit", pipeline_dir=projects_root
    )
    assert envelope["executionOutcome"] == "succeeded"
    assert envelope["workflowTransitionOutcome"] == "failed"
    assert after_failure["next_phase"] == "prepare_inputs"

    recovered = kernel.commit_phase_job(
        "run",
        "recoverable-commit",
        evidence=_prepare_inputs_evidence(projects_root),
        pipeline_dir=projects_root,
    )
    assert recovered["next_phase"] == "align_script_timing"
    assert kernel.load_execution_envelope(
        "run", "recoverable-commit", pipeline_dir=projects_root
    )["workflowTransitionOutcome"] == "succeeded"
