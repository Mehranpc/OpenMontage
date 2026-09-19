from __future__ import annotations

import copy
from pathlib import Path

import pytest

import lib.persian_preflight as preflight
import lib.persian_video_workflow as workflow
from lib.persian_edit_workspace import stage_edit_draft
from lib.persian_film_type import FilmTypePreflightError
from lib.persian_recovery_policy import recovery_policy_for_issue
from lib.persian_video_workflow import (
    PHASES,
    PersianVideoWorkflowError,
    bootstrap_persian_video,
    complete_phase,
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
                "avoidRegions": [],
            }],
            "moments": [{
                "id": "moment-1", "kind": "statement",
                "startSeconds": 1.0, "endSeconds": 5.0,
                "segments": [{"role": "hero", "text": "متن نمونه"}],
            }],
            "typographicBeats": [], "captions": [], "audio": {},
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
    assert plan["mutationSurface"] == ["subject_regions"]
    assert "typography" in plan["preserve"]
    assert "assets" in plan["preserve"]

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
    assert staged["candidate"]["changedScopes"] == ["subject_regions"]


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
    assert report["recoveryPlans"]["SUBJECT_REGION_REVIEW"]["mutationSurface"] == ["subject_regions"]


def test_review_subject_regions_phase_requires_valid_per_shot_geometry(tmp_path: Path) -> None:
    state = bootstrap_persian_video(
        title="Run", approved_script="متن تأییدشده", project_id="run",
        pipeline_dir=tmp_path, backlot_opener=lambda _: 0,
    )
    state["completed_phases"] = list(PHASES[:7])
    state["next_phase"] = "review_subject_regions"
    state.setdefault("attempts", {})["review_subject_regions"] = 1
    workflow._write_state(tmp_path / "run", state)

    with pytest.raises(PersianVideoWorkflowError, match="shot_regions"):
        complete_phase("run", "review_subject_regions", evidence={}, pipeline_dir=tmp_path)

    completed = complete_phase(
        "run", "review_subject_regions", evidence=_review_evidence(), pipeline_dir=tmp_path
    )
    assert completed["next_phase"] == "no_copy_preflight"
    stored = completed["evidence"]["review_subject_regions"]["shot_regions"]
    assert stored[0]["shot_id"] == "shot-1"
    assert stored[0]["avoidRegions"][0] == {"x": 0.1, "y": 0.2, "w": 0.6, "h": 0.7}
