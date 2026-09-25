from __future__ import annotations

import json
from pathlib import Path

import pytest

import lib.persian_edit_workspace as edit_workspace
import lib.persian_geometric_precheck as geometry
import lib.persian_preflight as preflight
from lib.persian_edit_workspace import PersianEditWorkspaceError

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests" / "fixtures" / "persian" / "p4_failed_shadow" / "issue138-v1.json"
METRICS = ROOT / "tests" / "fixtures" / "persian" / "p4_failed_shadow" / "issue138-f1-kahroba-metrics-v1.json"


def _blocker() -> dict:
    return {
        "code": "ASSET_SELECTION_HARD_REGION_COLLISION",
        "message": "provably infeasible F1 geometry",
        "recoveryClass": "ASSET_SELECTION",
        "details": {"stage": "geometric_precheck", "proof": "fixture"},
    }


def _minimal_edit() -> dict:
    return {
        "persian": {
            "format": "vertical",
            "durationSeconds": 10.0,
            "design": {"profile": "film-type", "profileVersion": "2.16.0"},
            "shots": [],
            "moments": [],
            "audio": {},
            "watermark": {"persianText": "طریقت تسلیم", "latinText": "Pathway"},
        }
    }


def test_issue138_f1_fixture_is_provably_infeasible_without_browser() -> None:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    metrics = json.loads(METRICS.read_text(encoding="utf-8"))
    profile = json.loads((ROOT / "styles" / "persian-footage" / "film-type.json").read_text(encoding="utf-8"))
    safe_raw = profile["formats"]["vertical"]["safeArea"]
    safe = {
        "x": safe_raw.get("left", safe_raw["side"]),
        "y": safe_raw["top"],
        "w": 1 - safe_raw.get("left", safe_raw["side"]) - safe_raw.get("right", safe_raw["side"]),
        "h": 1 - safe_raw["top"] - safe_raw["bottom"],
    }
    regions = [
        {key: float(region[key]) for key in ("x", "y", "w", "h")}
        for region in fixture["authority"]["reviewedHardRegions"]["shot-2"][:2]
    ]
    assert geometry.prove_mandatory_strip_infeasible(
        safe_area=safe,
        hard_regions=regions,
        width_fraction=float(metrics["minimumMandatoryTokenWidthPx"]) / 1080.0,
        height_fraction=1.0 / 1920.0,
    )


def test_geometric_report_preserves_f1_blocking_class(monkeypatch: pytest.MonkeyPatch) -> None:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    metrics = json.loads(METRICS.read_text(encoding="utf-8"))
    hard = fixture["authority"]["reviewedHardRegions"]["shot-2"]
    edit = _minimal_edit()
    edit["persian"]["shots"] = [{
        "id": "shot-2", "startSeconds": 5.22, "endSeconds": 13.36,
        "avoidRegions": hard,
    }]
    edit["persian"]["moments"] = [{
        "id": "moment-2", "kind": "statement", "startSeconds": 5.67, "endSeconds": 9.2,
        "segments": [{"role": "hero", "text": "پژوهشگرا آزمایش کردند"}],
    }]
    monkeypatch.setattr(
        geometry,
        "_mandatory_token_width",
        lambda *args, **kwargs: (
            float(metrics["minimumMandatoryTokenWidthPx"]),
            metrics["tokens"][0]["sha256"],
            metrics["fontAssetSha256"],
        ),
    )
    report = geometry.geometric_hard_region_precheck(edit, repo_root=ROOT)
    assert report["status"] == "refused"
    issue = report["blockingIssues"][0]
    assert issue["code"] == "ASSET_SELECTION_HARD_REGION_COLLISION"
    assert issue["details"]["stage"] == "geometric_precheck"
    assert issue["details"]["browserMeasurementRequiredForRejection"] is False


def test_malformed_region_never_contributes_to_reject_proof(monkeypatch: pytest.MonkeyPatch) -> None:
    edit = _minimal_edit()
    edit["persian"]["shots"] = [{
        "id": "shot-bad", "startSeconds": 0.0, "endSeconds": 10.0,
        "avoidRegions": [{
            "x": -1.0, "y": 0.0, "w": 3.0, "h": 1.0,
            "startSeconds": 0.0, "endSeconds": 10.0, "priority": "hard",
        }],
    }]
    edit["persian"]["moments"] = [{
        "id": "moment-bad", "kind": "statement", "startSeconds": 1.0, "endSeconds": 3.0,
        "segments": [{"role": "hero", "text": "نمونه"}],
    }]
    monkeypatch.setattr(
        geometry,
        "_mandatory_token_width",
        lambda *args, **kwargs: (300.0, "a" * 64, "b" * 64),
    )
    report = geometry.geometric_hard_region_precheck(edit, repo_root=ROOT)
    assert report["blockingIssues"] == []
    assert report["status"] == "not_provable"


def test_aggregate_preflight_rejects_geometry_before_browser(monkeypatch: pytest.MonkeyPatch) -> None:
    edit = _minimal_edit()
    monkeypatch.setattr(preflight, "collect_persian_edit_diagnostics", lambda *args, **kwargs: [])
    monkeypatch.setattr(preflight, "audit_persian_retention", lambda *args, **kwargs: {"problems": []})
    monkeypatch.setattr(preflight, "audit_persian_hook_quality", lambda *args, **kwargs: {"problems": [], "timingPolicy": {"version": preflight.HOOK_TIMING_POLICY_VERSION}})
    monkeypatch.setattr(preflight, "render_independent_review_issues", lambda **kwargs: [])
    monkeypatch.setattr(preflight, "geometric_hard_region_precheck", lambda *args, **kwargs: {"status": "refused", "blockingIssues": [_blocker()]})

    def fail_browser(*args, **kwargs):
        raise AssertionError("Chromium/browser preflight must not run after a deterministic F1 rejection")

    monkeypatch.setattr(preflight, "browser_preflight_edit_decisions", fail_browser)
    report = preflight.aggregate_preflight_edit_decisions(edit, base_dir=ROOT)
    assert report["ok"] is False
    assert report["blockingIssues"][0]["code"] == "ASSET_SELECTION_HARD_REGION_COLLISION"
    assert report["blockingIssues"][0]["details"]["stage"] == "geometric_precheck"
    assert report["diagnosticLayers"] == ["geometric_precheck"]


def test_edit_stage_rejects_before_candidate_consumption(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    project = tmp_path / "project"
    monkeypatch.setattr(edit_workspace, "geometric_hard_region_precheck", lambda *args, **kwargs: {"status": "refused", "blockingIssues": [_blocker()]})
    with pytest.raises(PersianEditWorkspaceError, match=r"ASSET_SELECTION_HARD_REGION_COLLISION.*details\.stage=geometric_precheck"):
        edit_workspace.stage_edit_draft(project, "f1-impossible", _minimal_edit())
    assert not (project / ".convergence" / "edit" / "f1-impossible" / "candidate.json").exists()
    assert not (project / ".drafts" / "edit" / "f1-impossible" / "edit_decisions.json").exists()
