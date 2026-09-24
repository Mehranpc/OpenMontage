from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import pytest

import lib.persian_preflight as preflight
from lib.persian_edit_contract import ContractDiagnostic
from lib.persian_video_workflow import (
    alignment_execution_policy,
    bounded_asset_search_request,
    load_workflow_state,
    record_asset_search_result,
    record_phase_attempt,
    record_phase_failure,
)
from tests.lib.test_persian_preflight_contract import _payload
from tests.lib.test_persian_video_workflow import BASE, _asset_result, _bootstrap_to_assets, _bootstrap


def test_preflight_aggregates_independent_cheap_blockers_before_browser(monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"fixture")
    payload = _payload(str(source))
    monkeypatch.setattr(preflight, "collect_persian_edit_diagnostics", lambda *a, **k: [
        ContractDiagnostic("path.fixture", "/persian/shots/0/source", "technical path issue")
    ])
    monkeypatch.setattr(preflight, "audit_persian_retention", lambda _: {"problems": ["retention issue"]})
    monkeypatch.setattr(preflight, "audit_persian_hook_quality", lambda _: {
        "version": "2.0", "required": True, "problems": ["hook issue"], "advisories": []
    })
    monkeypatch.setattr(preflight, "browser_preflight_edit_decisions", lambda *a, **k: pytest.fail("browser-heavy preflight must not run"))

    report = preflight.aggregate_preflight_edit_decisions(payload, base_dir=tmp_path)
    codes = [item["code"] for item in report["blockingIssues"]]
    assert "path.fixture" in codes
    assert "RETENTION_GATE" in codes
    assert "HOOK_QUALITY_GATE" in codes
    assert report["diagnosticLayers"] == ["contract", "retention", "hook"]


def test_subject_regions_never_create_early_watermark_feasibility_blocker(monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"fixture")
    payload = _payload(str(source))
    payload["persian"]["durationSeconds"] = 20.0
    payload["persian"]["shots"][0]["endSeconds"] = 20.0
    payload["persian"]["shots"][0]["avoidRegions"] = [
        {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0, "startSeconds": 5.0, "endSeconds": 20.0}
    ]
    monkeypatch.setattr(preflight, "audit_persian_retention", lambda _: {"problems": []})
    monkeypatch.setattr(preflight, "audit_persian_hook_quality", lambda _: {"version": "2.0", "required": False, "problems": [], "advisories": []})
    monkeypatch.setattr(preflight, "browser_preflight_edit_decisions", lambda *a, **k: {"ok": True, "watermarkDiagnostics": {"source": "browser"}})

    report = preflight.aggregate_preflight_edit_decisions(payload, base_dir=tmp_path)
    assert report["ok"] is True
    assert not any(item["code"] == "WATERMARK_GLOBAL_FEASIBILITY" for item in report["blockingIssues"])
    assert report["evidence"]["watermarkPolicy"]["subjectGeometryAgnostic"] is True
    assert report["evidence"]["watermarkPolicy"]["collisionInputs"] == ["subtitle", "editorial_text"]


def test_asset_technical_rejects_do_not_consume_semantic_candidate_budget(tmp_path: Path) -> None:
    _bootstrap_to_assets(tmp_path)
    request = bounded_asset_search_request("run", {"max_candidates_total": 4}, retry_pass=0, pipeline_dir=tmp_path, now=BASE)
    result = _asset_result(request, candidates=9, downloaded_bytes=0)
    result.update({"technical_rejects": 8, "semantic_candidates_reviewed": 1})
    state = record_asset_search_result("run", retry_pass=0, result_data=result, pipeline_dir=tmp_path, now=BASE)
    assert state["asset_usage"]["semantic_candidates_reviewed"] == 1
    assert state["asset_usage"]["technical_rejects"] == 8
    second = bounded_asset_search_request("run", {}, retry_pass=1, pipeline_dir=tmp_path, now=BASE)
    assert second["max_candidates_total"] == 15


def test_approved_script_mode_selects_timing_oriented_alignment_policy(tmp_path: Path) -> None:
    state, _ = _bootstrap(tmp_path)
    policy = alignment_execution_policy(state)
    assert policy["mode"] == "timing_oriented"
    assert policy["scriptAuthority"] == "approved_script"
    assert policy["primaryModelClass"] == "smallest_adequate_word_timing"
    assert policy["heavyTranscriptionRecoveryOnly"] is True


def test_phase_failure_closes_running_telemetry_without_advancing_workflow(tmp_path: Path) -> None:
    _bootstrap(tmp_path)
    record_phase_attempt("run", "prepare_inputs", pipeline_dir=tmp_path, now=BASE)
    failed = record_phase_failure(
        "run", "prepare_inputs", reason="external alignment crashed",
        pipeline_dir=tmp_path, now=BASE + timedelta(seconds=7),
    )
    entry = failed["phase_telemetry"]["prepare_inputs"][-1]
    assert entry["outcome"] == "failed"
    assert entry["duration_seconds"] == pytest.approx(7.0)
    assert entry["failure_reason"] == "external alignment crashed"
    assert failed["next_phase"] == "prepare_inputs"
    assert "prepare_inputs" not in failed["completed_phases"]


def test_phase_telemetry_distinguishes_editorial_and_external_execution(tmp_path: Path) -> None:
    _bootstrap(tmp_path)
    started = record_phase_attempt("run", "prepare_inputs", pipeline_dir=tmp_path, now=BASE)
    entry = started["phase_telemetry"]["prepare_inputs"][-1]
    assert entry["execution_class"] == "editorial"
    # Synthetic external timing record proves accounting is separated rather than merged.
    started["phase_telemetry"]["render_final_candidate"] = [{
        "started_at": BASE.isoformat(),
        "finished_at": (BASE + timedelta(seconds=122)).isoformat(),
        "duration_seconds": 122.0,
        "execution_class": "external_durable",
        "outcome": "succeeded",
    }]
    import lib.persian_video_workflow as workflow
    workflow._write_state(tmp_path / "run", started)
    status = load_workflow_state("run", pipeline_dir=tmp_path)
    accounting = workflow.phase_time_accounting(status)
    assert accounting["external_durable_seconds"] == pytest.approx(122.0)
    assert accounting["active_editorial_seconds"] == pytest.approx(0.0)


def test_preflight_cli_is_compact_but_persists_full_report(tmp_path: Path, monkeypatch, capsys) -> None:
    source = tmp_path / "edit.json"
    output = tmp_path / "full-preflight.json"
    source.write_text(json.dumps(_payload("missing.mp4")), encoding="utf-8")
    code = preflight.main([str(source), "--output", str(output)])
    assert code == 2
    stdout = json.loads(capsys.readouterr().out)
    assert stdout["status"] == "refused"
    assert stdout["reportPath"] == str(output.resolve())
    assert "blockingIssues" not in stdout
    assert stdout["blockingCount"] >= 1
    full = json.loads(output.read_text(encoding="utf-8"))
    assert full["blockingIssues"]
    assert len(stdout["reportSha256"]) == 64


def test_validation_ladder_is_ordered_cheap_before_expensive_render() -> None:
    from tools.video.persian_compose import persian_validation_ladder

    ladder = persian_validation_ladder()
    assert [stage["id"] for stage in ladder["stages"]] == [
        "schema_authority",
        "timing_paths_assets",
        "layout_geometry_subject_regions",
        "font_persian_text_preflight",
        "opening_render",
        "full_render",
        "mastering",
        "final_review",
    ]
    assert [stage["renderRequired"] for stage in ladder["stages"]] == [
        False, False, False, False, True, True, True, True,
    ]


def test_render_independent_retention_rule_is_shared_by_preflight_and_final_review(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from lib import persian_video_workflow as workflow
    from tools.video.persian_compose import render_independent_review_issues

    retention = {"problems": ["retention issue"]}
    shared = render_independent_review_issues(retention_audit=retention)
    assert shared == [{
        "code": "RETENTION_GATE",
        "domain": "retention",
        "message": "retention issue",
    }]

    source = tmp_path / "clip.mp4"
    source.write_bytes(b"fixture")
    payload = _payload(str(source))
    monkeypatch.setattr(preflight, "collect_persian_edit_diagnostics", lambda *a, **k: [])
    monkeypatch.setattr(preflight, "audit_persian_retention", lambda _: retention)
    monkeypatch.setattr(preflight, "audit_persian_hook_quality", lambda _: {
        "version": "2.0", "required": False, "problems": [], "advisories": []
    })
    monkeypatch.setattr(
        preflight, "browser_preflight_edit_decisions",
        lambda *a, **k: pytest.fail("render/browser-heavy preflight must not run"),
    )

    report = preflight.aggregate_preflight_edit_decisions(payload, base_dir=tmp_path)
    assert report["ok"] is False
    assert report["blockingIssues"][0]["code"] == "RETENTION_GATE"
    assert report["evidence"]["validationLadder"]["version"] == "1.0"
    assert report["evidence"]["validationLadder"]["stages"][3]["id"] == "font_persian_text_preflight"

    render_report = {
        "retention_audit": retention,
        "post_render_motion_qa": {"passed": True, "failRuns": []},
        "silent_watch_audit": {
            "main_point_understood": True,
            "hook_direction_understood": True,
            "conclusion_understood": True,
            "notes": ["understood"],
        },
        "cut_rhythm": "acceptable",
        "caption_readability": "acceptable",
        "strongest_scene": "scene-a",
        "weakest_scene": "scene-b",
        "hook_strength": "acceptable",
        "resolution_strength": "acceptable",
    }
    with pytest.raises(workflow.PersianVideoWorkflowError, match="RETENTION_GATE"):
        workflow._render_report_review_fields(render_report)


def test_required_hook_rule_is_shared_and_fail_closed_on_weak_disposition() -> None:
    from tools.video.persian_compose import render_independent_review_issues

    issues = render_independent_review_issues(hook_quality_audit={
        "version": "2.0",
        "required": True,
        "disposition": "weak",
        "problems": [],
    })
    assert issues == [{
        "code": "HOOK_QUALITY_GATE",
        "domain": "hook_quality",
        "message": "required hook-quality disposition must be acceptable or strong",
    }]
