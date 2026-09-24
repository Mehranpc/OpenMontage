from __future__ import annotations

import copy
from pathlib import Path

import pytest

import lib.persian_preflight as preflight
from lib.persian_edit_workspace import stage_edit_draft
from lib.persian_film_type import FilmTypePreflightError
from lib.persian_recovery_policy import recovery_policy_for_issue
from lib.persian_subject_region_review import (
    SubjectRegionReviewError,
    validate_subject_region_review_evidence,
)


def _edit(source: str = "clip.mp4") -> dict:
    return {
        "version": "1.0",
        "render_runtime": "remotion",
        "renderer_family": "persian-footage",
        "composition_mode": "templated",
        "persian": {
            "format": "vertical",
            "durationSeconds": 12.0,
            "shots": [{
                "id": "shot-1", "source": source,
                "startSeconds": 0.0, "endSeconds": 12.0,
                "attribution": "Video by Test on Pexels",
                "avoidRegions": [],
            }],
            "moments": [{
                "id": "moment-1", "kind": "statement",
                "startSeconds": 1.0, "endSeconds": 5.0,
                "segments": [{"role": "hero", "text": "متن نمونه"}],
            }],
            "typographicBeats": [], "audio": {},
            "watermark": {"persianText": "طریقت تسلیم", "latinText": "Pathway_of_Surrender"},
        },
    }


def _review_evidence() -> dict:
    return {
        "shot_regions": [{
            "shot_id": "shot-1",
            "avoidRegions": [{"x": 0.1, "y": 0.2, "w": 0.6, "h": 0.7}],
            "frame_review": {
                "start": True, "middle": True, "end": True,
                "observed": "Subject/action envelope reviewed across the full selected window.",
            },
        }]
    }


def test_subject_region_recovery_owns_only_subject_regions(tmp_path: Path) -> None:
    plan = recovery_policy_for_issue({
        "code": "SUBJECT_REGION_REVIEW_REQUIRED",
        "recoveryClass": "SUBJECT_REGION_REVIEW",
    })
    assert plan["recoveryClass"] == "SUBJECT_REGION_REVIEW"
    assert plan["strategies"] == ["attach_reviewed_subject_regions"]
    assert plan["mutationSurface"] == ["diagnostic.named_contract_field"]
    for locked in ("hook", "captions", "timeline", "watermark", "typography", "assets", "scenes", "audio_mix", "copy", "unclassified"):
        assert locked in plan["preserve"]
    assert "subject_regions" not in plan["preserve"]

    base = _edit()
    stage_edit_draft(tmp_path, "base", base, max_candidates=3, revision_cycle=1)
    child = copy.deepcopy(base)
    child["persian"]["shots"][0]["avoidRegions"] = _review_evidence()["shot_regions"][0]["avoidRegions"]
    staged = stage_edit_draft(
        tmp_path, "regions", child,
        parent_attempt_id="base",
        diagnostic_issue={"code": "SUBJECT_REGION_REVIEW_REQUIRED", "recoveryClass": "SUBJECT_REGION_REVIEW"},
        recovery_class="SUBJECT_REGION_REVIEW",
        strategy="attach_reviewed_subject_regions",
        changed_fields=["persian.shots[0].avoidRegions"],
        max_candidates=3, revision_cycle=1,
    )
    assert staged["changedScopes"] == ["subject_regions"]


def test_missing_reviewed_regions_are_not_misclassified_as_typography(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"fixture")
    payload = _edit(str(source))

    def refuse(*args, **kwargs):
        raise FilmTypePreflightError(
            "Moment moment-1: Film Type auto placement needs reviewed, screen-space "
            "shot.avoidRegions (including camera motion for the entire dwell). Use [] "
            "only after reviewing a clear shot."
        )

    monkeypatch.setattr(preflight, "browser_preflight_edit_decisions", refuse)
    report = preflight.aggregate_preflight_edit_decisions(payload, base_dir=tmp_path)
    issue = report["blockingIssues"][0]
    assert issue["code"] == "SUBJECT_REGION_REVIEW_REQUIRED"
    assert issue["recoveryClass"] == "SUBJECT_REGION_REVIEW"
    plan = issue["recoveryPlan"]
    assert plan["strategies"] == ["attach_reviewed_subject_regions"]
    assert "subject_regions" not in plan["preserve"]


def test_measured_hard_collision_routes_to_asset_reselection_without_copy_change(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"fixture")
    payload = _edit(str(source))

    def refuse(*args, **kwargs):
        raise FilmTypePreflightError(
            "Moment moment-1: hard regions blocked otherwise fitting candidates",
            code="ASSET_SELECTION_HARD_REGION_COLLISION",
            diagnostics={"momentId": "moment-1", "shotIds": ["shot-1"]},
        )

    monkeypatch.setattr(preflight, "browser_preflight_edit_decisions", refuse)
    report = preflight.aggregate_preflight_edit_decisions(payload, base_dir=tmp_path)
    issue = report["blockingIssues"][0]
    assert issue["code"] == "ASSET_SELECTION_HARD_REGION_COLLISION"
    assert issue["details"] == {"momentId": "moment-1", "shotIds": ["shot-1"]}
    assert issue["recoveryClass"] == "ASSET_SELECTION"
    assert "copy" in issue["recoveryPlan"]["preserve"]
    assert issue["recoveryPlan"]["strategies"][0] == "reuse_reviewed_non_overlapping_source_window"
    action = " ".join(report["nextActions"])
    assert "first reuse a reviewed alternate crop/window" in action
    assert "only for named shots whose existing reviewed options are exhausted" in action


def test_plain_layout_failure_stays_layout_recovery(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"fixture")

    def refuse(*args, **kwargs):
        raise FilmTypePreflightError("Moment moment-1: no curated measured candidate fits")

    monkeypatch.setattr(preflight, "browser_preflight_edit_decisions", refuse)
    report = preflight.aggregate_preflight_edit_decisions(_edit(str(source)), base_dir=tmp_path)
    issue = report["blockingIssues"][0]
    assert issue["recoveryClass"] == "FILM_TYPE_LAYOUT"


def test_subject_region_evidence_validator_is_fail_closed_and_complete() -> None:
    with pytest.raises(SubjectRegionReviewError, match="shot_regions"):
        validate_subject_region_review_evidence({}, expected_shot_ids=["shot-1"])

    normalized = validate_subject_region_review_evidence(
        _review_evidence(), expected_shot_ids=["shot-1"]
    )
    assert normalized["shot_regions"][0]["shot_id"] == "shot-1"
    assert normalized["shot_regions"][0]["avoidRegions"][0] == {
        "x": 0.1, "y": 0.2, "w": 0.6, "h": 0.7
    }


def test_subject_region_evidence_validator_requires_every_expected_shot() -> None:
    with pytest.raises(SubjectRegionReviewError, match="missing reviewed shot ids"):
        validate_subject_region_review_evidence(
            _review_evidence(), expected_shot_ids=["shot-1", "shot-2"]
        )


def test_subject_region_priority_round_trips_and_rejects_unknown_values() -> None:
    evidence = _review_evidence()
    evidence["shot_regions"][0]["avoidRegions"][0]["priority"] = "soft"
    normalized = validate_subject_region_review_evidence(evidence, expected_shot_ids=["shot-1"])
    assert normalized["shot_regions"][0]["avoidRegions"][0]["priority"] == "soft"

    evidence["shot_regions"][0]["avoidRegions"][0]["priority"] = "medium"
    with pytest.raises(SubjectRegionReviewError, match="priority"):
        validate_subject_region_review_evidence(evidence, expected_shot_ids=["shot-1"])


def test_legacy_subject_region_priority_remains_implicit_hard() -> None:
    normalized = validate_subject_region_review_evidence(
        _review_evidence(), expected_shot_ids=["shot-1"]
    )
    region = normalized["shot_regions"][0]["avoidRegions"][0]
    assert "priority" not in region
