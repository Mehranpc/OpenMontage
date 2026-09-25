from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from tests.lib.test_issue35_alignment_provider_seam import FakeRegistry, _policy, _tool
from tests.lib.test_persian_video_workflow import _advance_to, _bootstrap
from tools.base_tool import ToolStatus

import lib.persian_alignment_job as alignment_job
import lib.persian_alignment_provider as provider
import lib.persian_video_workflow as workflow


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_alignment_start_probes_and_persists_plan_before_durable_launch(tmp_path, monkeypatch) -> None:
    _bootstrap(tmp_path)
    _advance_to(tmp_path, "align_script_timing")
    primary = _tool("transcriber", "whisperx", ToolStatus.UNAVAILABLE)
    mlx = _tool("mlx_whisper_transcriber", "mlx_whisper")
    registry = FakeRegistry([primary, mlx])
    captured: dict = {}

    def fake_start(project_id: str, **kwargs):
        captured.update({"project_id": project_id, **kwargs})
        return {"status": "queued", "jobId": kwargs["job_id"], "executionOutcome": "pending"}

    monkeypatch.setattr(alignment_job.kernel, "start_phase_job", fake_start)
    result = alignment_job.start_alignment_job(
        "run", pipeline_dir=tmp_path, registry=registry, launch=False
    )

    plan_path = Path(result["providerPlanPath"])
    assert plan_path.is_file()
    bundle = json.loads(plan_path.read_text(encoding="utf-8"))
    assert bundle["providerPlan"]["selectedTool"] == "mlx_whisper_transcriber"
    assert bundle["providerPlan"]["fallbackReason"] == "primary_unavailable:transcriber"
    assert primary.execute_calls in (None, [])
    assert captured["phase"] == "align_script_timing"
    assert captured["telemetry_category"] == "machine_local_execution"
    assert captured["launch"] is False
    assert "--plan-sha256" in captured["argv"]
    assert result["providerPlanSha256"] == _sha(plan_path)


def test_alignment_worker_semantic_failure_can_exit_zero_for_run_kernel_truth(tmp_path, monkeypatch) -> None:
    narration = tmp_path / "narration.wav"
    narration.write_bytes(b"audio")
    result_path = tmp_path / "alignment-result.json"
    semantic_path = tmp_path / "semantic.json"
    primary = _tool("transcriber", "whisperx", lightweight_success=False, heavy_success=False)
    registry = FakeRegistry([primary])
    plan = provider.build_alignment_provider_plan(_policy(), registry=registry)
    bundle = {
        "version": "1.0",
        "providerPlan": plan,
        "narrationSha256": _sha(narration),
        "approvedScriptSha256": None,
    }
    plan_path = tmp_path / "provider-plan.json"
    plan_path.write_text(json.dumps(bundle), encoding="utf-8")
    monkeypatch.setenv("OPENMONTAGE_DURABLE_RESULT_PATH", str(semantic_path))

    code = alignment_job.run_alignment_worker(
        plan_path=plan_path,
        plan_sha256=_sha(plan_path),
        narration_path=narration,
        output_dir=tmp_path / "out",
        result_path=result_path,
        registry=registry,
    )

    assert code == 0
    semantic = json.loads(semantic_path.read_text(encoding="utf-8"))
    assert semantic["success"] is False
    assert "exhausted" in semantic["error"]
    assert not result_path.exists()


def test_alignment_worker_persists_digest_bound_success_result(tmp_path, monkeypatch) -> None:
    narration = tmp_path / "narration.wav"
    narration.write_bytes(b"audio")
    script = tmp_path / "approved_script.txt"
    script.write_text("سلام دنیا", encoding="utf-8")
    result_path = tmp_path / "alignment-result.json"
    semantic_path = tmp_path / "semantic.json"
    timing_tool = _tool("transcriber", "whisperx")

    def valid_timing_execute(inputs):
        from tools.base_tool import ToolResult
        if timing_tool.execute_calls is None:
            timing_tool.execute_calls = []
        timing_tool.execute_calls.append(dict(inputs))
        return ToolResult(
            success=True,
            duration_seconds=0.25,
            data={
                "provider": "whisperx",
                "word_timestamps": [
                    {"word": "سلام", "start": 0.0, "end": 0.8},
                    {"word": "دنیا", "start": 0.8, "end": 1.6},
                ],
            },
        )

    timing_tool.execute = valid_timing_execute
    registry = FakeRegistry([timing_tool])
    plan = provider.build_alignment_provider_plan(_policy(), registry=registry)
    bundle = {
        "version": "1.0",
        "providerPlan": plan,
        "narrationSha256": _sha(narration),
        "approvedScriptSha256": _sha(script),
    }
    plan_path = tmp_path / "provider-plan.json"
    plan_path.write_text(json.dumps(bundle), encoding="utf-8")
    monkeypatch.setenv("OPENMONTAGE_DURABLE_RESULT_PATH", str(semantic_path))

    code = alignment_job.run_alignment_worker(
        plan_path=plan_path,
        plan_sha256=_sha(plan_path),
        narration_path=narration,
        output_dir=tmp_path / "out",
        result_path=result_path,
        approved_script_path=script,
        registry=registry,
    )

    assert code == 0
    semantic = json.loads(semantic_path.read_text(encoding="utf-8"))
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert semantic["success"] is True
    assert semantic["data"]["alignmentResultSha256"] == _sha(result_path)
    assert semantic["data"]["providerPlanSha256"] == _sha(plan_path)
    assert result["provider_decision"]["semanticOutcome"] == "succeeded"
    assert len(result["word_timestamps"]) == 2


def test_alignment_commit_derives_phase_evidence_from_semantic_result(tmp_path, monkeypatch) -> None:
    _bootstrap(tmp_path)
    state = _advance_to(tmp_path, "align_script_timing")
    project = Path(state["read_allowlist"]["project_root"])
    registry = FakeRegistry([_tool("transcriber", "whisperx")])
    plan = provider.build_alignment_provider_plan(state["alignment_policy"], registry=registry)
    alignment = provider.execute_alignment_with_fallback(
        plan,
        input_path=str(project / "inputs" / "narration.wav"),
        output_dir=str(project / "artifacts" / "transcription"),
        registry=registry,
    )
    alignment.update({
        "provider_plan_sha256": "PLACEHOLDER",
        "narration_sha256": state["input"]["narration"]["sha256"],
        "approved_script_sha256": state["input"]["approved_script"]["sha256"],
    })
    plan_bundle = {
        "version": "1.0",
        "providerPlan": plan,
        "narrationSha256": state["input"]["narration"]["sha256"],
        "approvedScriptSha256": state["input"]["approved_script"]["sha256"],
    }
    plan_path = project / "artifacts" / "alignment" / "provider-plan.json"
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.write_text(json.dumps(plan_bundle), encoding="utf-8")
    plan_sha = _sha(plan_path)
    alignment["provider_plan_sha256"] = plan_sha
    result_path = project / "artifacts" / "alignment" / "alignment-result.json"
    result_path.write_text(json.dumps(alignment), encoding="utf-8")
    semantic_data = {
        "alignmentResultPath": str(result_path),
        "alignmentResultSha256": _sha(result_path),
        "providerPlanPath": str(plan_path),
        "providerPlanSha256": plan_sha,
    }
    monkeypatch.setattr(
        alignment_job.kernel,
        "reconcile_phase_job",
        lambda *a, **k: {
            "executionOutcome": "succeeded",
            "semanticOutcome": "succeeded",
            "semanticResult": {"success": True, "data": semantic_data},
        },
    )
    captured: dict = {}

    def fake_commit(project_id: str, job_id: str, **kwargs):
        captured.update(kwargs["evidence"])
        return {"next_phase": "plan_scenes_moments"}

    monkeypatch.setattr(alignment_job.kernel, "commit_phase_job", fake_commit)
    committed = alignment_job.commit_alignment_job("run", "alignment-job", pipeline_dir=tmp_path)

    assert committed["next_phase"] == "plan_scenes_moments"
    assert captured["provider"] == "whisperx"
    assert captured["provider_tool"] == "transcriber"
    assert captured["word_timing_count"] == 2
    assert captured["alignment_result_sha256"] == _sha(result_path)


def test_alignment_commit_rejects_tampered_result_before_workflow_commit(tmp_path, monkeypatch) -> None:
    _bootstrap(tmp_path)
    state = _advance_to(tmp_path, "align_script_timing")
    project = Path(state["read_allowlist"]["project_root"])
    result_path = project / "artifacts" / "alignment" / "alignment-result.json"
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        alignment_job.kernel,
        "reconcile_phase_job",
        lambda *a, **k: {
            "executionOutcome": "succeeded",
            "semanticOutcome": "succeeded",
            "semanticResult": {
                "success": True,
                "data": {
                    "alignmentResultPath": str(result_path),
                    "alignmentResultSha256": "0" * 64,
                    "providerPlanSha256": "a" * 64,
                },
            },
        },
    )
    monkeypatch.setattr(
        alignment_job.kernel,
        "commit_phase_job",
        lambda *a, **k: pytest.fail("tampered alignment result must not commit"),
    )
    with pytest.raises(alignment_job.AlignmentJobError, match="sha256"):
        alignment_job.commit_alignment_job("run", "alignment-job", pipeline_dir=tmp_path)


def test_workflow_parser_exposes_durable_alignment_lifecycle() -> None:
    parser = workflow.build_parser()
    assert parser.parse_args(["alignment-start", "run"]).command == "alignment-start"
    assert parser.parse_args(["alignment-status", "run", "job"]).command == "alignment-status"
    assert parser.parse_args(["alignment-commit", "run", "job"]).command == "alignment-commit"


def test_alignment_start_normalizes_run_kernel_start_failure(tmp_path, monkeypatch) -> None:
    _bootstrap(tmp_path)
    _advance_to(tmp_path, "align_script_timing")
    registry = FakeRegistry([_tool("transcriber", "whisperx")])

    def fail_start(*args, **kwargs):
        raise alignment_job.kernel.PersianRunKernelError("durable start refused")

    monkeypatch.setattr(alignment_job.kernel, "start_phase_job", fail_start)
    with pytest.raises(alignment_job.AlignmentJobError, match="durable start refused"):
        alignment_job.start_alignment_job(
            "run", pipeline_dir=tmp_path, registry=registry, launch=False
        )


def test_alignment_commit_requires_digest_bound_provider_plan_artifact(tmp_path, monkeypatch) -> None:
    _bootstrap(tmp_path)
    state = _advance_to(tmp_path, "align_script_timing")
    project = Path(state["read_allowlist"]["project_root"])
    result_path = project / "artifacts" / "alignment" / "alignment-result.json"
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        alignment_job.kernel,
        "reconcile_phase_job",
        lambda *a, **k: {
            "executionOutcome": "succeeded",
            "semanticOutcome": "succeeded",
            "semanticResult": {
                "success": True,
                "data": {
                    "alignmentResultPath": str(result_path),
                    "alignmentResultSha256": _sha(result_path),
                    "providerPlanSha256": "a" * 64,
                },
            },
        },
    )
    with pytest.raises(alignment_job.AlignmentJobError, match="provider plan"):
        alignment_job.commit_alignment_job("run", "alignment-job", pipeline_dir=tmp_path)


def test_alignment_worker_persists_heavy_recovery_reason(tmp_path, monkeypatch) -> None:
    """A lightweight-recovery run persists its recovery reason, not just its success."""
    narration = tmp_path / "narration.wav"
    narration.write_bytes(b"audio")
    result_path = tmp_path / "alignment-result.json"
    semantic_path = tmp_path / "semantic.json"
    primary = _tool("transcriber", "whisperx", lightweight_success=False, heavy_success=True)
    registry = FakeRegistry([primary])
    plan = provider.build_alignment_provider_plan(_policy(), registry=registry)
    bundle = {
        "version": "1.0",
        "providerPlan": plan,
        "narrationSha256": _sha(narration),
        "approvedScriptSha256": None,
    }
    plan_path = tmp_path / "provider-plan.json"
    plan_path.write_text(json.dumps(bundle), encoding="utf-8")
    monkeypatch.setenv("OPENMONTAGE_DURABLE_RESULT_PATH", str(semantic_path))

    code = alignment_job.run_alignment_worker(
        plan_path=plan_path,
        plan_sha256=_sha(plan_path),
        narration_path=narration,
        output_dir=tmp_path / "out",
        result_path=result_path,
        registry=registry,
    )

    assert code == 0
    decision = json.loads(result_path.read_text(encoding="utf-8"))["provider_decision"]
    assert decision["heavyRecoveryUsed"] is True
    assert decision["recoveryReason"] == "lightweight_providers_exhausted"


def test_alignment_commit_normalizes_provider_fallback_reason_into_workflow_evidence(
    tmp_path, monkeypatch
) -> None:
    """The commit path records the fallback reason in canonical workflow evidence."""
    from tests.lib.test_persian_video_workflow import BASE

    _bootstrap(tmp_path)
    state = _advance_to(tmp_path, "align_script_timing")
    workflow.record_phase_attempt(
        "run", "align_script_timing", pipeline_dir=tmp_path, now=BASE
    )
    project = Path(state["read_allowlist"]["project_root"])
    registry = FakeRegistry([
        _tool("transcriber", "whisperx", ToolStatus.UNAVAILABLE),
        _tool("mlx_whisper_transcriber", "mlx_whisper"),
    ])
    plan = provider.build_alignment_provider_plan(state["alignment_policy"], registry=registry)
    alignment = provider.execute_alignment_with_fallback(
        plan,
        input_path=str(project / "inputs" / "narration.wav"),
        output_dir=str(project / "artifacts" / "transcription"),
        registry=registry,
    )
    assert alignment["provider_decision"]["fallbackReason"] == "primary_unavailable:transcriber"
    alignment.update({
        "provider_plan_sha256": "PLACEHOLDER",
        "narration_sha256": state["input"]["narration"]["sha256"],
        "approved_script_sha256": state["input"]["approved_script"]["sha256"],
    })
    plan_bundle = {
        "version": "1.0",
        "providerPlan": plan,
        "narrationSha256": state["input"]["narration"]["sha256"],
        "approvedScriptSha256": state["input"]["approved_script"]["sha256"],
    }
    plan_path = project / "artifacts" / "alignment" / "provider-plan.json"
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.write_text(json.dumps(plan_bundle), encoding="utf-8")
    plan_sha = _sha(plan_path)
    alignment["provider_plan_sha256"] = plan_sha
    result_path = project / "artifacts" / "alignment" / "alignment-result.json"
    result_path.write_text(json.dumps(alignment), encoding="utf-8")
    semantic_data = {
        "alignmentResultPath": str(result_path),
        "alignmentResultSha256": _sha(result_path),
        "providerPlanPath": str(plan_path),
        "providerPlanSha256": plan_sha,
    }
    monkeypatch.setattr(
        alignment_job.kernel,
        "reconcile_phase_job",
        lambda *a, **k: {
            "executionOutcome": "succeeded",
            "semanticOutcome": "succeeded",
            "semanticResult": {"success": True, "data": semantic_data},
        },
    )
    # align_script_timing is checkpoint-backed; the completed script checkpoint is a
    # separate concern from the fallback-evidence normalization under test here.
    monkeypatch.setattr(
        workflow, "read_checkpoint",
        lambda *a, **k: {"status": "completed", "artifacts": {"script": {}}},
    )
    captured: dict = {}

    def real_commit(project_id: str, job_id: str, *, evidence=None, pipeline_dir=None, now=None):
        committed = workflow.complete_phase(
            project_id, "align_script_timing", evidence=evidence,
            pipeline_dir=pipeline_dir, now=BASE,
        )
        captured["provider_fallback_reason"] = committed["evidence"]["align_script_timing"][
            "provider_fallback_reason"
        ]
        return committed

    monkeypatch.setattr(alignment_job.kernel, "commit_phase_job", real_commit)
    committed = alignment_job.commit_alignment_job("run", "alignment-job", pipeline_dir=tmp_path)

    assert committed["next_phase"] == "plan_scenes_moments"
    assert captured["provider_fallback_reason"] == "primary_unavailable:transcriber"
