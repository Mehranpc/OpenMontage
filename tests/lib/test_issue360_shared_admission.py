"""#360: selection admission and the manifest audit apply one requirement policy.

A clip lacking required human presence or subject continuity used to become selected
and was refused only when the whole manifest was audited. Admission now runs the
audit's own event-local rules on the row the build would produce, aggregates every
blocker already provable, and writes nothing when it refuses. Completion-only rules
(every planned event covered) still wait for the manifest.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from lib import persian_asset_commands as commands
from lib import persian_asset_workspace as workspace
from lib import persian_video_workflow as workflow
from lib.persian_asset_workspace import AssetAdmissionRefused, PersianAssetWorkspaceError
from lib.persian_assets import ASSET_RULE_CLASSES, audit_asset_manifest
from tests.lib.test_issue35_asset_candidate_workspace import _discovered, _review
from tests.lib.test_issue35_semantic_scene_plan_checkpoint import _event

NARRATION = "این یک جمله نمونه است"
QUERY = "person thinking at desk"


def _plan(project: Path, **overrides: dict) -> dict:
    """Two planned events on one beat; ``overrides`` maps event id -> field changes."""
    events = []
    for event_id in ("event-a", "event-b"):
        event = {**_event(event_id, 4.0), "narration_span": NARRATION, "queries": [QUERY]}
        event.update(overrides.get(event_id.replace("-", "_"), {}))
        events.append(event)
    plan = {"version": "2.0", "format": "vertical", "subject": "sample",
            "target_duration_seconds": 8.0,
            "beats": [{"id": "beat-1", "intent_fa": "نمونه", "script_line_fa": NARRATION,
                       "duration_seconds": 8.0, "typographic": False, "visual_events": events}]}
    project.mkdir(parents=True, exist_ok=True)
    (project / "checkpoint_scene_plan.json").write_text(json.dumps({
        "stage": "scene_plan", "status": "completed", "artifacts": {"scene_plan": plan},
    }, ensure_ascii=False), encoding="utf-8")
    return plan


def _candidate(project: Path, event: str, source_id: str, *, start: float = 0.0, rank: int = 1, **review) -> str:
    discovery = workspace.record_discovery_pass(
        project, workspace.asset_workspace_status(project)["discoveryPassCount"],
        [_discovered(project, source_id=source_id, name=f"{source_id}.mp4", slot_id=event)],
    )["candidateIds"][0]
    staged = workspace.stage_asset_candidate(
        project, discovery_id=discovery, visual_event_id=event, semantic_beat_id="beat-1",
        source_in_seconds=start, duration_seconds=4.0,
        intended_crop={"mode": "cover", "x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0},
        candidate_rank=rank, query=QUERY, narration_span=NARRATION,
    )
    body = _review()
    body.update(review)
    workspace.record_candidate_review(project, staged["candidateId"], body)
    return staged["candidateId"]


def _durable_bytes(project: Path) -> dict[str, bytes]:
    root = project / ".asset-workspace"
    snapshot = {str(path.relative_to(project)): path.read_bytes() for path in sorted(root.rglob("*.json"))}
    assert snapshot, "atomicity must inspect the durable candidate workspace"
    return snapshot


def _select(project: Path, event: str, candidate: str, **kwargs):
    return workspace.select_asset_candidate(project, event, candidate, rejected_alternatives={}, **kwargs)


@pytest.mark.parametrize(("field", "code"), [
    ("human_presence", "HUMAN_PRESENCE_MISSING"),
    ("shows_subject", "SUBJECT_CONTINUITY_LOST"),
])
def test_required_presence_is_refused_at_selection_with_the_audit_reason(
    tmp_path: Path, field: str, code: str,
) -> None:
    project = tmp_path / "run"
    plan = _plan(project)
    candidate = _candidate(project, "event-a", "absent", **{field: False})
    before = _durable_bytes(project)

    with pytest.raises(AssetAdmissionRefused) as refused:
        _select(project, "event-a", candidate)

    assert _durable_bytes(project) == before
    assert workspace.asset_workspace_status(project)["selectedCount"] == 0
    [diagnostic] = refused.value.diagnostics
    assert diagnostic["code"] == code
    assert (diagnostic["expected"], diagnostic["observed"]) == (True, False)
    assert diagnostic["visualEventId"] == "event-a" and diagnostic["candidateId"] == candidate
    # The same failure the manifest audit reports for the row the build would write.
    row = workspace._manifest_row(workspace.load_asset_candidate(project, candidate))
    assert diagnostic["message"] in audit_asset_manifest({"assets": [row]}, plan)


def test_all_known_blockers_are_returned_together_and_repeat_identically(tmp_path: Path) -> None:
    project = tmp_path / "run"
    _plan(project)
    candidate = _candidate(
        project, "event-a", "bad", human_presence=False, shows_subject=False,
        staged_stock_risk="high", geometry_review={"crop_safe": False, "observed": "cut"},
    )
    first = second = None
    with pytest.raises(AssetAdmissionRefused) as first:
        _select(project, "event-a", candidate)
    with pytest.raises(AssetAdmissionRefused) as second:
        _select(project, "event-a", candidate)
    codes = [item["code"] for item in first.value.diagnostics]
    assert set(codes) == {"CROP_UNSAFE", "HUMAN_PRESENCE_MISSING", "STAGED_RISK_HIGH", "SUBJECT_CONTINUITY_LOST"}
    assert codes == sorted(codes)
    assert first.value.diagnostics == second.value.diagnostics
    assert "nothing was written" in str(first.value)
    human = next(item for item in first.value.diagnostics if item["code"] == "HUMAN_PRESENCE_MISSING")
    # Human presence is never reconciled away to fit a clip.
    assert "reconcile_plan" not in human["recovery"]


def test_reviewed_fallback_disagreement_is_refused_and_a_match_builds(tmp_path: Path) -> None:
    project = tmp_path / "run"
    _plan(project, event_b={"fallback_level": "adjacent_metaphor"})
    literal_claimed = _candidate(project, "event-a", "metaphor", fallback_level="adjacent_metaphor",
                                 fallback_reason="no literal footage exists")
    with pytest.raises(AssetAdmissionRefused) as refused:
        _select(project, "event-a", literal_claimed)
    [diagnostic] = refused.value.diagnostics
    assert diagnostic["code"] == "FALLBACK_MISMATCH"
    assert (diagnostic["expected"], diagnostic["observed"]) == ("exact_literal", "adjacent_metaphor")

    literal = _candidate(project, "event-a", "literal", start=0.0, rank=2)
    metaphor = _candidate(project, "event-b", "crowd", fallback_level="adjacent_metaphor",
                          fallback_reason="a crowd under an open sky is the closest honest read")
    workspace.select_asset_candidate(project, "event-a", literal,
                                     rejected_alternatives={literal_claimed: "claims a metaphor"})
    assert _select(project, "event-b", metaphor)["declarationsRequired"] == []

    built = commands.build_manifest(project.parent, project.name)
    rows = {row["visual_event_id"]: row for row in json.loads(Path(built["manifestPath"]).read_text())["assets"]}
    assert rows["event-b"]["fallback_level"] == "adjacent_metaphor"
    assert rows["event-a"]["fallback_level"] == "exact_literal"
    with pytest.raises(PersianAssetWorkspaceError, match="cannot replace reviewed fallback_level"):
        workspace.build_asset_manifest_from_workspace(
            project, overrides={"assets": {"event-b": {"fallback_level": "abstract"}}}
        )


def test_unreviewed_fallback_is_a_declaration_the_build_must_make(tmp_path: Path) -> None:
    project = tmp_path / "run"
    _plan(project, event_a={"fallback_level": "emotional_human"})
    candidate = _candidate(project, "event-a", "legacy-shape")
    result = _select(project, "event-a", candidate)
    [declaration] = result["declarationsRequired"]
    assert declaration["ruleClass"] == "manifest_declaration"
    assert declaration["code"] == "FALLBACK_UNDECLARED"
    assert (declaration["expected"], declaration["observed"]) == ("emotional_human", None)
    assert declaration["recovery"] == ["declare_at_manifest_build", "reconcile_plan"]


def test_partial_selection_is_admitted_but_completion_still_requires_every_event(tmp_path: Path) -> None:
    project = tmp_path / "run"
    _plan(project)
    selected = _select(project, "event-a", _candidate(project, "event-a", "only"))
    assert selected["selected"] is True
    # The build's exact_literal default already satisfies a literal plan.
    assert selected["declarationsRequired"] == []
    with pytest.raises(commands.PersianAssetCommandError, match="event-b: no asset"):
        commands.build_manifest(project.parent, project.name)
    assert set(ASSET_RULE_CLASSES) == {"event_local", "current_set", "manifest_declaration", "completion"}


def test_current_set_overlap_refuses_before_full_coverage_and_distinct_windows_stay_legal(tmp_path: Path) -> None:
    project = tmp_path / "run"
    _plan(project)
    discovery = workspace.record_discovery_pass(
        project, 0, [_discovered(project, source_id="long", name="long.mp4", duration=20.0, slot_id="event-a")]
    )["candidateIds"][0]

    def staged(event: str, start: float) -> str:
        item = workspace.stage_asset_candidate(
            project, discovery_id=discovery, visual_event_id=event, semantic_beat_id="beat-1",
            source_in_seconds=start, duration_seconds=4.0, intended_crop={"mode": "full_frame"},
            candidate_rank=1, query=QUERY, narration_span=NARRATION,
        )["candidateId"]
        workspace.record_candidate_review(project, item, _review())
        return item

    _select(project, "event-a", staged("event-a", 0.0))
    overlapping = staged("event-b", 2.0)
    with pytest.raises(AssetAdmissionRefused) as refused:
        _select(project, "event-b", overlapping)
    assert [item["code"] for item in refused.value.diagnostics] == ["SOURCE_WINDOW_OVERLAP"]
    assert refused.value.diagnostics[0]["ruleClass"] == "current_set"
    distinct = workspace.select_asset_candidate(
        project, "event-b", staged("event-b", 8.0),
        rejected_alternatives={overlapping: "overlaps event-a's window"},
    )
    assert distinct["selected"] is True


def test_refused_replacement_and_idempotent_reselection_write_nothing(tmp_path: Path) -> None:
    project = tmp_path / "run"
    _plan(project)
    good = _candidate(project, "event-a", "good")
    _select(project, "event-a", good)
    bad = _candidate(project, "event-a", "bad", human_presence=False, rank=2)
    before = _durable_bytes(project)
    with pytest.raises(AssetAdmissionRefused, match="HUMAN_PRESENCE_MISSING"):
        workspace.select_asset_candidate(project, "event-a", bad, replace_existing=True,
                                         rejected_alternatives={good: "try the other"})
    assert _durable_bytes(project) == before
    assert workspace.load_asset_candidate(project, good)["disposition"] == "selected"

    # A legacy selection the plan no longer admits is not a clean idempotent no-op.
    _plan(project, event_a={"human_presence": True, "shows_subject": True, "queries": ["another query"]})
    with pytest.raises(AssetAdmissionRefused, match="QUERY_NOT_AUTHORED"):
        workspace.select_asset_candidate(project, "event-a", good, rejected_alternatives={bad: "no human"})
    assert _durable_bytes(project) == before


def test_missing_or_malformed_plan_and_unplanned_events_fail_closed(tmp_path: Path) -> None:
    project = tmp_path / "run"
    project.mkdir()
    candidate = _candidate(project, "event-a", "noplan")
    with pytest.raises(AssetAdmissionRefused, match="PLAN_MISSING"):
        _select(project, "event-a", candidate)
    artifact = project / "artifacts" / "scene_plan.json"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text("{not json", encoding="utf-8")
    with pytest.raises(AssetAdmissionRefused, match="PLAN_INVALID"):
        _select(project, "event-a", candidate)
    artifact.unlink()
    _plan(project)
    stray = _candidate(project, "event-z", "stray")
    with pytest.raises(AssetAdmissionRefused, match="EVENT_NOT_IN_PLAN"):
        _select(project, "event-z", stray)
    assert workspace.asset_workspace_status(project)["selectedCount"] == 0


def test_front_door_prints_machine_readable_refusal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    from tests.lib.test_issue224_plan_reconcile import _event as planned_event, _plan as run_plan, _run_at_acquire

    _run_at_acquire(tmp_path)
    monkeypatch.setattr(workflow, "PROJECTS_DIR", tmp_path)
    # The fixture's clock is historical; the wall budget is not what this test is about.
    monkeypatch.setattr(workflow, "_enforce_cli_front_door_budget", lambda args: None)
    project = tmp_path / "run"
    planned = planned_event(run_plan(tmp_path), "event-0")
    discovery = workspace.record_discovery_pass(
        project, 0, [_discovered(project, source_id="cli", name="cli.mp4", slot_id="event-0")]
    )["candidateIds"][0]
    candidate = workspace.stage_asset_candidate(
        project, discovery_id=discovery, visual_event_id="event-0", semantic_beat_id="beat-0",
        source_in_seconds=0.0, duration_seconds=4.0, intended_crop={"mode": "full_frame"},
        candidate_rank=1, query=planned["queries"][0], narration_span=planned["narration_span"],
    )["candidateId"]
    review = _review()
    review["shows_subject"] = False  # the plan needs the phone in frame
    if planned.get("carries_moment"):
        review["frame_review"]["placement_space"] = planned["negative_space"]
    workspace.record_candidate_review(project, candidate, review)

    with pytest.raises(SystemExit) as exited:
        workflow.main(["asset-candidate-select", "run", "event-0", candidate])
    assert exited.value.code == 2
    captured = capsys.readouterr()
    assert "{" in captured.out, captured.err
    payload = json.loads(captured.out[captured.out.index("{"):])
    assert payload["refused"] is True
    assert [item["code"] for item in payload["diagnostics"]] == ["SUBJECT_CONTINUITY_LOST"]
    assert "SUBJECT_CONTINUITY_LOST" in captured.err
    assert workspace.asset_workspace_status(project)["selectedCount"] == 0


@pytest.mark.parametrize(("field", "value", "code"), [
    ("opening_semantic_match", False, "HOOK_OPENING_MATCH"),
    ("semantic_role", "different_role", "HOOK_SEMANTIC_ROLE"),
    ("semantic_direction", "different_direction", "HOOK_SEMANTIC_DIRECTION"),
])
def test_recorded_opening_failure_is_refused_before_selection(
    tmp_path: Path, field: str, value: object, code: str,
) -> None:
    project = tmp_path / "run"
    _plan(project, event_a={"narrative_role": "hook", "semantic_role": "human_anchor",
                           "semantic_direction": "toward_subject"})
    review = {"opening_semantic_match": True, "semantic_role": "human_anchor",
              "semantic_direction": "toward_subject", field: value}
    candidate = _candidate(project, "event-a", "opening", **review)
    before = _durable_bytes(project)
    with pytest.raises(AssetAdmissionRefused) as refused:
        _select(project, "event-a", candidate)
    assert code in [item["code"] for item in refused.value.diagnostics]
    assert _durable_bytes(project) == before


def test_recorded_opening_evidence_is_preserved_and_cannot_be_overridden(tmp_path: Path) -> None:
    project = tmp_path / "run"
    _plan(project, event_a={"narrative_role": "hook", "semantic_role": "human_anchor",
                           "semantic_direction": "toward_subject"})
    evidence = {"opening_semantic_match": True, "semantic_role": "human_anchor",
                "semantic_direction": "toward_subject"}
    candidate = _candidate(project, "event-a", "opening", **evidence)
    assert _select(project, "event-a", candidate)["declarationsRequired"] == []
    manifest = workspace.build_asset_manifest_from_workspace(project)
    row = manifest["assets"][0]
    for field, value in evidence.items():
        assert row[field] == value
        changed = False if field == "opening_semantic_match" else "different"
        with pytest.raises(PersianAssetWorkspaceError, match="cannot replace reviewed"):
            workspace.build_asset_manifest_from_workspace(
                project, overrides={"assets": {"event-a": {field: changed}}},
            )
        tampered = json.loads(json.dumps(manifest))
        tampered["assets"][0][field] = changed
        with pytest.raises(PersianAssetWorkspaceError, match="persisted candidate review"):
            workspace.validate_asset_manifest_against_workspace(project, tampered)


@pytest.mark.parametrize(("field", "value"), [
    ("opening_semantic_match", "yes"), ("semantic_role", " "), ("semantic_direction", ""),
])
def test_malformed_opening_evidence_is_refused_at_review(tmp_path: Path, field: str, value: object) -> None:
    project = tmp_path / "run"
    _plan(project, event_a={"narrative_role": "hook", "semantic_role": "human_anchor",
                           "semantic_direction": "toward_subject"})
    with pytest.raises(PersianAssetWorkspaceError, match=field):
        _candidate(project, "event-a", "opening", **{field: value})


def test_legacy_review_without_opening_evidence_still_needs_declarations(tmp_path: Path) -> None:
    project = tmp_path / "run"
    _plan(project, event_a={"narrative_role": "hook", "semantic_role": "human_anchor",
                           "semantic_direction": "toward_subject"})
    candidate = _candidate(project, "event-a", "opening")
    required = {item["field"] for item in _select(project, "event-a", candidate)["declarationsRequired"]}
    assert required == {"opening_semantic_match", "semantic_role", "semantic_direction"}
