"""#360: acquisition status distinguishes recorded selections from valid ones.

The observed run had twelve recorded selections, five fallback-level disagreements
and one human-presence/subject-continuity failure. Status counted selections, said
"build the manifest", and the manifest audit then refused. Status now evaluates the
recorded evidence with the admission rules, stays read-only, and names the recovery.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from lib import persian_asset_workspace as workspace
from lib.persian_asset_workspace import PersianAssetWorkspaceError
from lib.persian_video_workflow import (
    build_workflow_asset_manifest,
    complete_phase,
    reconcile_scene_plan,
    record_phase_attempt,
    reject_workflow_asset_candidate,
    select_workflow_asset_candidate,
    workflow_status,
    write_workflow_assets_checkpoint,
)
from tests.contracts.test_phase0_contracts import sample_artifact
from tests.lib.test_issue195_scene_plan_duration_gate import (
    BASE, _advance_to_plan_scenes, _bootstrap, _write_checkpoint,
)
from tests.lib.test_issue213_plan_time_moment_feasibility import _beats
from tests.lib.test_issue224_plan_reconcile import _event, _plan, _run_at_acquire
from tests.lib.test_issue35_asset_candidate_workspace import _discovered, _review


def _run_with_plan(tmp_path: Path, beats: list[dict]) -> Path:
    _bootstrap(tmp_path)
    _advance_to_plan_scenes(tmp_path)
    for stage, artifact in (("idea", "brief"), ("script", "script")):
        _write_checkpoint(tmp_path, stage, artifact, sample_artifact(artifact))
    _write_checkpoint(tmp_path, "scene_plan", "scene_plan",
                      {"version": "2.0", "format": "vertical", "subject": "phone", "beats": beats})
    record_phase_attempt("run", "plan_scenes_moments", pipeline_dir=tmp_path, now=BASE)
    complete_phase("run", "plan_scenes_moments", evidence={}, pipeline_dir=tmp_path, now=BASE)
    return tmp_path / "run"


def _candidate(tmp_path: Path, event: str, source_id: str, **review_fields) -> str:
    project = tmp_path / "run"
    plan = _plan(tmp_path)
    beat = next(b for b in plan["beats"] if any(e["id"] == event for e in b["visual_events"]))
    planned = _event(plan, event)
    discovery = workspace.record_discovery_pass(
        project, workspace.asset_workspace_status(project)["discoveryPassCount"],
        [_discovered(project, source_id=source_id, name=f"{source_id}.mp4", slot_id=event,
                     duration=max(12.0, float(planned["duration_seconds"]) + 1.0))],
    )["candidateIds"][0]
    candidate = workspace.stage_asset_candidate(
        project, discovery_id=discovery, visual_event_id=event, semantic_beat_id=beat["id"],
        source_in_seconds=0.0, duration_seconds=4.0, intended_crop={"mode": "full_frame"},
        candidate_rank=1, query=planned["queries"][0], narration_span=planned["narration_span"],
    )["candidateId"]
    review = _review()
    if planned.get("carries_moment"):
        review["frame_review"]["placement_space"] = planned["negative_space"]
    review.update(review_fields)
    workspace.record_candidate_review(project, candidate, review)
    return candidate


def _legacy_select(project: Path, event: str, candidate_id: str) -> None:
    """What admission before #360 allowed: record the selection without plan checks."""
    selections = workspace._read_selections(project)
    record = workspace.load_asset_candidate(project, candidate_id)
    selections[event] = {
        "visualEventId": event, "candidateId": candidate_id,
        "candidateIdentitySha256": record["identitySha256"], "reviewSha256": record["reviewSha256"],
        "rejectedAlternatives": {}, "selectedAt": BASE.isoformat(),
    }
    workspace._write_selections(project, selections)
    record["disposition"] = "selected"
    workspace._atomic_json(workspace._candidate_path(project, candidate_id), record)


def _project_bytes(project: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(project)): path.read_bytes()
        for path in sorted(project.rglob("*"))
        if path.is_file() and ".telemetry" not in path.parts
    }


def _legacy_twelve(tmp_path: Path) -> tuple[Path, list[str], str]:
    beats = _beats(*[(5.0, None)] * 12)
    events = [beat["visual_events"][0] for beat in beats]
    fallback_events = [event["id"] for event in events[:5]]
    human_event = events[5]["id"]
    for event in events:
        if event["id"] in fallback_events:
            event["fallback_level"] = "adjacent_metaphor"
        if event["id"] == human_event:
            event["human_presence"] = True
    project = _run_with_plan(tmp_path, beats)
    for index, event in enumerate(events):
        fields: dict = {}
        if event["id"] in fallback_events:
            # Legacy review admission kept any extra key; these recorded a literal read.
            fields = {"fallback_level": "exact_literal"}
        if event["id"] == human_event:
            fields = {"human_presence": False, "shows_subject": False}
        _legacy_select(project, event["id"], _candidate(tmp_path, event["id"], f"src-{index}", **fields))
    return project, fallback_events, human_event


def test_twelve_recorded_selections_are_not_twelve_valid_ones(tmp_path: Path) -> None:
    project, fallback_events, human_event = _legacy_twelve(tmp_path)
    before = _project_bytes(project)

    first = workflow_status("run", pipeline_dir=tmp_path, now=BASE)["acquisition"]
    again = workflow_status("run", pipeline_dir=tmp_path, now=BASE)["acquisition"]

    assert _project_bytes(project) == before  # read-only; no plan artifact materialised
    assert not (project / "artifacts" / "scene_plan.json").exists()
    assert first == again
    assert first["unresolvedEvents"] == []  # established meaning: events with no selection
    assert first["recordedSelectionCount"] == 12
    assert first["validSelectionCount"] == 6
    assert first["invalidEvents"] == sorted([*fallback_events, human_event])
    readiness = first["readiness"]
    assert readiness["disposition"] == "invalid_selections"
    human_codes = {item["code"] for item in readiness["diagnostics"][human_event]}
    assert human_codes == {"HUMAN_PRESENCE_MISSING", "SUBJECT_CONTINUITY_LOST"}
    for event in fallback_events:
        [item] = readiness["diagnostics"][event]
        assert item["code"] == "FALLBACK_MISMATCH"
        assert (item["expected"], item["observed"]) == ("adjacent_metaphor", "exact_literal")
    step = first["nextStep"]
    assert "build the manifest and complete" not in step
    assert "Do not build the manifest yet" in step and "not a user decision" in step


def test_rejecting_an_invalid_selection_reopens_its_event_and_a_valid_alternate_repairs_it(
    tmp_path: Path,
) -> None:
    project = _run_with_plan(tmp_path, _beats((4.0, None), (56.0, None)))
    good = _candidate(tmp_path, "event-1", "good")
    select_workflow_asset_candidate("run", "event-1", good, rejected_alternatives={}, pipeline_dir=tmp_path)
    bad = _candidate(tmp_path, "event-0", "bad", shows_subject=False)
    _legacy_select(project, "event-0", bad)
    alternate = _candidate(tmp_path, "event-0", "alternate")
    passes = workspace.asset_workspace_status(project)["discoveryPassCount"]
    reviews = {cid: workspace.load_asset_candidate(project, cid)["reviewSha256"] for cid in (good, bad, alternate)}

    with pytest.raises(PersianAssetWorkspaceError, match="must be replaced before rejection"):
        reject_workflow_asset_candidate("run", good, category="editorial", reason="x", pipeline_dir=tmp_path)
    rejected = reject_workflow_asset_candidate(
        "run", bad, category="semantic", reason="the phone never appears", pipeline_dir=tmp_path,
    )
    assert rejected["rejection"]["releasedSelections"] == ["event-0"]
    assert rejected["rejection"]["admissionCodes"] == ["SUBJECT_CONTINUITY_LOST"]
    acquisition = workflow_status("run", pipeline_dir=tmp_path, now=BASE)["acquisition"]
    assert acquisition["unresolvedEvents"] == ["event-0"]
    assert acquisition["invalidEvents"] == [] and acquisition["validSelectionCount"] == 1

    select_workflow_asset_candidate("run", "event-0", alternate, rejected_alternatives={}, pipeline_dir=tmp_path)
    ready = workflow_status("run", pipeline_dir=tmp_path, now=BASE)["acquisition"]
    assert ready["readiness"]["disposition"] == "ready_for_manifest"
    assert ready["validSelectionCount"] == ready["recordedSelectionCount"] == 2
    assert build_workflow_asset_manifest("run", pipeline_dir=tmp_path)["assetCount"] == 2
    assert write_workflow_assets_checkpoint("run", pipeline_dir=tmp_path)["status"] == "completed"
    # No new discovery, and no review was rewritten.
    assert workspace.asset_workspace_status(project)["discoveryPassCount"] == passes
    assert {cid: workspace.load_asset_candidate(project, cid)["reviewSha256"] for cid in reviews} == reviews


def test_a_plan_change_invalidates_readiness_derived_from_the_old_plan(tmp_path: Path) -> None:
    _run_at_acquire(tmp_path)
    for event in ("event-0", "event-1", "event-2"):
        select_workflow_asset_candidate(
            "run", event, _candidate(tmp_path, event, f"s-{event}"), rejected_alternatives={},
            pipeline_dir=tmp_path,
        )
    before = workflow_status("run", pipeline_dir=tmp_path, now=BASE)["acquisition"]["readiness"]
    assert before["disposition"] == "ready_for_manifest"

    reconcile_scene_plan(
        "run", [{"visual_event_id": "event-1", "set": {"negative_space": "centre_band"}}],
        reason="test a changed declaration", pipeline_dir=tmp_path, now=BASE,
    )
    after = workflow_status("run", pipeline_dir=tmp_path, now=BASE)["acquisition"]["readiness"]
    assert after["inputsSha256"] != before["inputsSha256"]
    assert after["disposition"] == "invalid_selections"
    assert [item["code"] for item in after["diagnostics"]["event-1"]] == ["PLACEMENT_SPACE_MISMATCH"]


def test_an_unreadable_plan_is_never_a_clean_readiness(tmp_path: Path) -> None:
    project = _run_at_acquire(tmp_path)
    select_workflow_asset_candidate(
        "run", "event-0", _candidate(tmp_path, "event-0", "only"), rejected_alternatives={},
        pipeline_dir=tmp_path,
    )
    (project / "checkpoint_scene_plan.json").write_text("{torn", encoding="utf-8")
    acquisition = workflow_status("run", pipeline_dir=tmp_path, now=BASE)["acquisition"]
    assert acquisition["readiness"]["disposition"] == "plan_unavailable"
    assert acquisition["readiness"]["planProblem"]["code"] == "PLAN_INVALID"
    assert "cannot be built" in acquisition["nextStep"]
    assert json.loads(json.dumps(acquisition)) == acquisition


@pytest.mark.parametrize("dependency", ["selection_binding", "identity", "review", "context"])
def test_readiness_binds_the_ledger_and_actual_immutable_evidence(
    tmp_path: Path, dependency: str,
) -> None:
    _run_at_acquire(tmp_path)
    project = tmp_path / "run"
    event = next(iter(_plan(tmp_path)["beats"][0]["visual_events"]))["id"]
    candidate_id = _candidate(tmp_path, event, "bound-evidence")
    select_workflow_asset_candidate(
        "run", event, candidate_id, rejected_alternatives={}, pipeline_dir=tmp_path,
    )
    before = workspace.selection_readiness(project)
    if dependency == "selection_binding":
        selections = workspace._read_selections(project)
        selections[event]["reviewSha256"] = "0" * 64
        workspace._write_selections(project, selections)
    else:
        candidate = workspace.load_asset_candidate(project, candidate_id)
        if dependency == "identity":
            candidate["identity"]["sourceWindow"]["startSeconds"] += 0.25
            candidate["identity"]["sourceWindow"]["endSeconds"] += 0.25
        elif dependency == "review":
            candidate["review"]["shows_subject"] = not candidate["review"]["shows_subject"]
        else:
            candidate["context"]["query"] = "changed without a new immutable review"
        # Model a torn/legacy record: claimed hashes were not refreshed.
        workspace._atomic_json(workspace._candidate_path(project, candidate_id), candidate)
    durable = _project_bytes(project)
    after = workspace.selection_readiness(project)
    assert after["inputsSha256"] != before["inputsSha256"]
    assert event in after["staleEvents"]
    assert after["validSelectionCount"] == 0
    assert _project_bytes(project) == durable
