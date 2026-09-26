"""#188: the acquisition provider pass runs as a durable, measured execution.

Provider wait used to be charged inside an agent turn, and a crash between
``asset-request`` and ``asset-result`` left ``pending_pass`` set -- a state the phase
cannot complete from, with the search possibly already paid for. The pass now has one
durable identity, and it deliberately does not own the phase's workflow transition.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys
import time
from types import SimpleNamespace

import pytest

from lib import persian_run_kernel as kernel
from lib import persian_video_workflow as workflow
from lib.persian_asset_job import AssetJobError, run_asset_search_job, run_asset_search_worker
from tests.lib.test_persian_video_workflow import (
    BASE,
    _asset_result,
    _bootstrap_to_assets,
    _clip_file,
)


def _succeeding_child(payload: dict) -> str:
    return (
        "import json,os; from pathlib import Path; "
        f"Path(os.environ['OPENMONTAGE_DURABLE_RESULT_PATH']).write_text(json.dumps({payload!r}))"
    )


def _reconcile_until_terminal(tmp_path: Path, job_id: str) -> dict:
    for _ in range(100):
        result = kernel.reconcile_phase_job("run", job_id, pipeline_dir=tmp_path, now=BASE)
        if result["status"] in {"succeeded", "failed", "interrupted"}:
            return result
        time.sleep(0.05)
    raise AssertionError("durable job never reached a terminal state")


def _run_measured_job(tmp_path: Path, job_id: str) -> dict:
    kernel.start_phase_job(
        "run",
        job_id=job_id,
        phase="acquire_assets",
        argv=[sys.executable, "-c", _succeeding_child({"success": True, "data": {"retryPass": 0}})],
        idempotence_key=f"key-{job_id}",
        telemetry_category="provider_network_wait",
        owns_transition=False,
        pipeline_dir=tmp_path,
        now=BASE,
    )
    return _reconcile_until_terminal(tmp_path, job_id)


def test_a_measured_only_job_is_counted_without_advancing_its_phase(tmp_path: Path) -> None:
    _bootstrap_to_assets(tmp_path)

    result = _run_measured_job(tmp_path, "measured-search")

    assert result["executionOutcome"] == "succeeded"
    envelope = kernel.load_execution_envelope("run", "measured-search", pipeline_dir=tmp_path)
    assert envelope["transitionMode"] == "measured_only"
    # Neither claim would be true: the job did not advance a phase, and it is not
    # still waiting to.
    assert envelope["workflowTransitionOutcome"] == "not_applicable"
    assert workflow.load_workflow_state("run", pipeline_dir=tmp_path)["next_phase"] == "acquire_assets"
    spans = workflow.load_workflow_state("run", pipeline_dir=tmp_path)["causal_telemetry"]["spans"]
    assert any(
        span.get("span_id") == "job:measured-search" and span.get("finished_at")
        for span in spans
    )


def test_a_default_job_still_owns_its_transition(tmp_path: Path) -> None:
    """The default is unchanged: callers that do not ask for measured-only keep
    owning the workflow transition."""
    _bootstrap_to_assets(tmp_path)

    kernel.start_phase_job(
        "run",
        job_id="owning-job",
        phase="acquire_assets",
        argv=[sys.executable, "-c", _succeeding_child({"success": True, "data": {}})],
        idempotence_key="owning-key",
        pipeline_dir=tmp_path,
        now=BASE,
    )
    _reconcile_until_terminal(tmp_path, "owning-job")

    envelope = kernel.load_execution_envelope("run", "owning-job", pipeline_dir=tmp_path)
    assert envelope["transitionMode"] == "workflow"
    assert envelope["workflowTransitionOutcome"] != "not_applicable"


def _request_file(tmp_path: Path, retry_pass: int = 0) -> Path:
    path = tmp_path / "run" / f"search-request-{retry_pass}.json"
    path.write_text(json.dumps({"queries": [{"query": "coffee pour", "slot_id": "b1-e1"}]}))
    return path


def _fake_registry(clip: dict, *, success: bool = True, calls: list | None = None):
    def execute(bounded):
        if calls is not None:
            calls.append(dict(bounded))
        if not success:
            return SimpleNamespace(success=False, data=None, error="provider unavailable")
        return SimpleNamespace(
            success=True,
            data=_asset_result(bounded, candidates=1, downloaded_bytes=clip["file_size_bytes"], clips=[clip]),
            error=None,
        )

    return SimpleNamespace(get=lambda name: SimpleNamespace(execute=execute))


def test_the_worker_accounts_the_pass_and_reports_semantic_truth(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import hashlib

    _bootstrap_to_assets(tmp_path)
    clip = _clip_file(tmp_path, 1024)
    request = _request_file(tmp_path)
    request_sha = hashlib.sha256(request.read_bytes()).hexdigest()
    result_path = tmp_path / "run" / "artifacts" / "acquisition" / "search-pass-0.json"
    semantic_path = tmp_path / "semantic-result.json"
    monkeypatch.setenv("OPENMONTAGE_DURABLE_RESULT_PATH", str(semantic_path))

    calls: list = []
    exit_code = run_asset_search_worker(
        project_id="run",
        request_path=request,
        request_sha256=request_sha,
        retry_pass=0,
        result_path=result_path,
        pipeline_dir=tmp_path,
        registry=_fake_registry(clip, calls=calls),
    )

    assert exit_code == 0
    assert len(calls) == 1, "the pass must search exactly once"
    semantic = json.loads(semantic_path.read_text())
    assert semantic["success"] is True
    assert semantic["data"]["assetRequestSha256"] == request_sha
    assert semantic["data"]["candidatesConsidered"] == 1
    assert result_path.is_file()

    state = workflow.load_workflow_state("run", pipeline_dir=tmp_path)
    usage = state["asset_usage"]
    assert usage.get("pending_pass") is None, "the pass must be settled, not left pending"
    assert usage["completed_passes"] == [0]
    # The issued request is fully closed, which is the state the phase can complete
    # from -- `pending_pass` is exactly what `_complete_phase_impl` refuses.
    assert usage.get("pending_limits") is None
    assert usage.get("pending_output_dir") is None


def test_a_request_changed_after_the_pass_started_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import hashlib

    _bootstrap_to_assets(tmp_path)
    clip = _clip_file(tmp_path, 1024)
    request = _request_file(tmp_path)
    original_sha = hashlib.sha256(request.read_bytes()).hexdigest()
    semantic_path = tmp_path / "semantic-result.json"
    monkeypatch.setenv("OPENMONTAGE_DURABLE_RESULT_PATH", str(semantic_path))

    request.write_text(json.dumps({"queries": [{"query": "something else", "slot_id": "b1-e1"}]}))
    calls: list = []
    run_asset_search_worker(
        project_id="run",
        request_path=request,
        request_sha256=original_sha,
        retry_pass=0,
        result_path=tmp_path / "run" / "artifacts" / "acquisition" / "search-pass-0.json",
        pipeline_dir=tmp_path,
        registry=_fake_registry(clip, calls=calls),
    )

    assert calls == [], "a request whose bytes changed must not be searched"
    assert json.loads(semantic_path.read_text())["success"] is False


def test_a_failed_search_is_reported_and_leaves_the_pass_recoverable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """This name used to promise more than the body checked: it asserted only that the
    failure was reported, while the pass stayed pending and the run stayed stuck. The
    recoverability it claims is asserted here now (#193)."""
    import hashlib

    _bootstrap_to_assets(tmp_path)
    clip = _clip_file(tmp_path, 1024)
    request = _request_file(tmp_path)
    semantic_path = tmp_path / "semantic-result.json"
    monkeypatch.setenv("OPENMONTAGE_DURABLE_RESULT_PATH", str(semantic_path))

    exit_code = run_asset_search_worker(
        project_id="run",
        request_path=request,
        request_sha256=hashlib.sha256(request.read_bytes()).hexdigest(),
        retry_pass=0,
        result_path=tmp_path / "run" / "artifacts" / "acquisition" / "search-pass-0.json",
        pipeline_dir=tmp_path,
        registry=_fake_registry(clip, success=False),
    )

    # Semantic failure exits zero on purpose: the kernel reads the envelope, not the
    # exit code.
    assert exit_code == 0
    assert json.loads(semantic_path.read_text())["success"] is False
    # ...and "recoverable" means the pass is released, not left latched.
    usage = workflow.load_workflow_state("run", pipeline_dir=tmp_path)["asset_usage"]
    assert usage.get("pending_pass") is None


def test_the_job_binds_one_pass_to_one_provider_bound_identity(tmp_path: Path) -> None:
    _bootstrap_to_assets(tmp_path)
    request = _request_file(tmp_path)

    started = run_asset_search_job(
        "run", request_path=request, retry_pass=0, pipeline_dir=tmp_path, launch=False, now=BASE
    )
    envelope = kernel.load_execution_envelope("run", started["jobId"], pipeline_dir=tmp_path)

    assert envelope["telemetryCategory"] == "provider_network_wait"
    assert envelope["transitionMode"] == "measured_only"
    assert envelope["phase"] == "acquire_assets"
    # The same (pass, request bytes) resumes the same logical search instead of paying
    # for a second one.
    again = run_asset_search_job(
        "run", request_path=request, retry_pass=0, pipeline_dir=tmp_path, launch=False, now=BASE
    )
    assert again["jobId"] == started["jobId"]
    assert again["idempotenceKey"] == started["idempotenceKey"]


def test_a_request_outside_the_project_is_refused(tmp_path: Path) -> None:
    _bootstrap_to_assets(tmp_path)
    outside = tmp_path.parent / "outside-request.json"
    outside.write_text(json.dumps({"queries": [{"query": "coffee pour", "slot_id": "b1-e1"}]}))

    with pytest.raises(AssetJobError, match="current-project file"):
        run_asset_search_job(
            "run", request_path=outside, retry_pass=0, pipeline_dir=tmp_path, launch=False, now=BASE
        )


def test_the_job_refuses_a_retry_pass_beyond_the_workflow_budget(tmp_path: Path) -> None:
    _bootstrap_to_assets(tmp_path)
    request = _request_file(tmp_path)

    with pytest.raises(AssetJobError, match="exceeds max"):
        run_asset_search_job(
            "run", request_path=request, retry_pass=2, pipeline_dir=tmp_path, launch=False, now=BASE
        )
