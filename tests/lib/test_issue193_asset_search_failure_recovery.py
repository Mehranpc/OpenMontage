"""#193: the durable asset-search route must close its own handshake on every outcome.

#188 removed a dead end -- a crash between `asset-request` and `asset-result` left
`pending_pass` set, and the phase cannot complete while it is. The durable route moved
that window inside the worker without closing it: a provider failure left the run unable
to complete *or* to re-search. These regressions pin the closure.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from lib import persian_run_kernel as kernel
from lib import persian_video_workflow as workflow
from lib.persian_asset_job import AssetJobError, run_asset_search_job, run_asset_search_worker
from tests.lib.test_issue188_durable_asset_search import (
    _fake_registry,
    _reconcile_until_terminal,
    _request_file,
    _succeeding_child,
)
from tests.lib.test_persian_video_workflow import BASE, _bootstrap_to_assets, _clip_file


def _run_failing_worker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    """Drive the real worker against a provider that refuses."""
    _bootstrap_to_assets(tmp_path)
    clip = _clip_file(tmp_path, 1024)
    request = _request_file(tmp_path)
    semantic_path = tmp_path / "semantic-result.json"
    monkeypatch.setenv("OPENMONTAGE_DURABLE_RESULT_PATH", str(semantic_path))

    run_asset_search_worker(
        project_id="run",
        request_path=request,
        request_sha256=hashlib.sha256(request.read_bytes()).hexdigest(),
        retry_pass=0,
        result_path=tmp_path / "run" / "artifacts" / "acquisition" / "search-pass-0-a0.json",
        pipeline_dir=tmp_path,
        registry=_fake_registry(clip, success=False),
    )
    return json.loads(semantic_path.read_text())


def test_a_failed_pass_is_released_and_the_run_can_search_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The whole point: a provider outage must not latch the phase."""
    semantic = _run_failing_worker(tmp_path, monkeypatch)

    assert semantic["success"] is False
    assert semantic["data"]["passReleased"] is True

    usage = workflow.load_workflow_state("run", pipeline_dir=tmp_path)["asset_usage"]
    assert usage.get("pending_pass") is None, "the failed pass must not stay pending"
    assert usage.get("pending_output_dir") is None
    assert usage.get("pending_limits") is None
    assert [entry["retryPass"] for entry in usage["released_passes"]] == [0]

    # Issuing the same pass again is what a released pass exists to allow. Before the
    # release this raised "still pending result accounting".
    bounded = workflow.bounded_asset_search_request(
        "run", json.loads(_request_file(tmp_path).read_text()), retry_pass=0,
        pipeline_dir=tmp_path, now=BASE,
    )
    assert bounded["clips_per_query"] == 1


def test_a_released_pass_does_not_spend_the_retry_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Release means "did not complete", not "completed with nothing". A provider
    outage must not consume the pass a genuine retry needs."""
    _run_failing_worker(tmp_path, monkeypatch)

    usage = workflow.load_workflow_state("run", pipeline_dir=tmp_path)["asset_usage"]
    assert usage.get("completed_passes", []) == []
    # The outage is not recorded as a discovery of nothing, and no counters are invented.
    assert "bytes_downloaded" not in usage or usage.get("bytes_downloaded") in (None, 0)


def test_a_released_pass_is_retried_under_a_fresh_durable_identity(tmp_path: Path) -> None:
    """Idempotence protects against duplicate success, not against retrying a failure."""
    _bootstrap_to_assets(tmp_path)
    request = _request_file(tmp_path)

    first = run_asset_search_job(
        "run", request_path=request, retry_pass=0, attempt=0,
        pipeline_dir=tmp_path, launch=False, now=BASE,
    )
    retry = run_asset_search_job(
        "run", request_path=request, retry_pass=0, attempt=1,
        pipeline_dir=tmp_path, launch=False, now=BASE,
    )
    again = run_asset_search_job(
        "run", request_path=request, retry_pass=0, attempt=1,
        pipeline_dir=tmp_path, launch=False, now=BASE,
    )

    assert retry["jobId"] != first["jobId"]
    assert retry["idempotenceKey"] != first["idempotenceKey"]
    # The same attempt is still one logical operation.
    assert again["jobId"] == retry["jobId"]


def test_commit_refuses_a_measured_only_job(tmp_path: Path) -> None:
    """The invariant held on `run` but not on `commit`: an operator could advance the
    phase from a job whose entire purpose is to be measured."""
    _bootstrap_to_assets(tmp_path)
    kernel.start_phase_job(
        "run",
        job_id="measured-only",
        phase="acquire_assets",
        argv=[__import__("sys").executable, "-c", _succeeding_child({"success": True, "data": {}})],
        idempotence_key="measured-only-key",
        telemetry_category="provider_network_wait",
        owns_transition=False,
        pipeline_dir=tmp_path,
        now=BASE,
    )
    assert _reconcile_until_terminal(tmp_path, "measured-only")["executionOutcome"] == "succeeded"

    with pytest.raises(kernel.PersianRunKernelError, match="measured-only"):
        kernel.commit_phase_job("run", "measured-only", evidence={}, pipeline_dir=tmp_path)

    assert workflow.load_workflow_state("run", pipeline_dir=tmp_path)["next_phase"] == "acquire_assets"


def test_a_failed_job_surfaces_the_provider_reason(tmp_path: Path) -> None:
    """The kernel's own message is generic; the reason the operator needs lives in the
    job's semantic result."""
    _bootstrap_to_assets(tmp_path)
    request = _request_file(tmp_path)
    # Complete pass 0, so the worker's very first step refuses for a real, specific reason.
    workflow.bounded_asset_search_request(
        "run", json.loads(request.read_text()), retry_pass=0, pipeline_dir=tmp_path, now=BASE
    )
    workflow.record_asset_search_result(
        "run",
        retry_pass=0,
        result_data={
            "output_dir": str((tmp_path / "run" / "assets").resolve()),
            "resolved_sources": ["pexels", "pixabay_video"],
            "max_candidates_total": 16,
            "max_bytes_per_clip": 96 * 1024 * 1024,
            "max_total_download_bytes": 512 * 1024 * 1024,
            "candidates_considered": 0,
            "bytes_downloaded": 0,
            "clips": [],
        },
        pipeline_dir=tmp_path,
        now=BASE,
    )

    with pytest.raises(AssetJobError, match="already recorded"):
        run_asset_search_job(
            "run", request_path=request, retry_pass=0, pipeline_dir=tmp_path, now=BASE
        )

    # No pass was issued by that execution, so nothing was released either.
    usage = workflow.load_workflow_state("run", pipeline_dir=tmp_path)["asset_usage"]
    assert usage.get("pending_pass") is None
    assert usage.get("released_passes") is None


def test_a_worker_that_died_has_an_operator_release(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A killed worker cannot release its own pass, so the operator needs a command.

    The wall-budget guard is deliberately NOT patched here: the fixture's clock is in the
    past, so the run reads as over-budget, and releasing a latched pass is exactly the
    thing that must still work from that state. A release the budget stop could block
    would recreate the dead end it exists to close.
    """
    _bootstrap_to_assets(tmp_path)
    request = _request_file(tmp_path)
    workflow.bounded_asset_search_request(
        "run", json.loads(request.read_text()), retry_pass=0, pipeline_dir=tmp_path, now=BASE
    )
    monkeypatch.setattr(workflow, "PROJECTS_DIR", tmp_path)

    workflow.main(["asset-search-release", "run", "--retry-pass", "0", "--reason", "worker killed"])

    usage = workflow.load_workflow_state("run", pipeline_dir=tmp_path)["asset_usage"]
    assert usage.get("pending_pass") is None
    assert usage.get("completed_passes", []) == []
    assert usage["released_passes"][0]["reason"] == "worker killed"


def test_a_job_error_exits_through_the_front_door_contract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """Every `asset-search` failure must use the same clean exit-2 contract as the other
    commands, not escape as an uncaught traceback."""
    _bootstrap_to_assets(tmp_path)
    monkeypatch.setattr(workflow, "PROJECTS_DIR", tmp_path)
    # The fixture's clock is in the past, so the real-now wall guard would stop the CLI
    # before the error contract under test. This test is about the contract, not the guard.
    monkeypatch.setattr(workflow, "_enforce_cli_front_door_budget", lambda args: None)
    outside = tmp_path.parent / "outside-request.json"
    outside.write_text(json.dumps({"queries": [{"query": "x", "slot_id": "b1-e1"}]}))

    with pytest.raises(SystemExit) as exit_info:
        workflow.main(
            ["asset-search", "run", "--retry-pass", "0", "--request", str(outside)]
        )

    assert exit_info.value.code == 2
    assert "current-project file" in capsys.readouterr().err
