from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from lib import persian_edit_workspace as workspace
from lib import persian_preflight as preflight
from lib.persian_edit_workspace import PersianEditWorkspaceError
from lib.persian_hook_quality import HOOK_TIMING_POLICY_VERSION


def _edit(*, recipe: str = "recipe-a", watermark: str = "طریقت", note: str = "") -> dict:
    return {
        "metadata": {"editorNote": note},
        "persian": {
            "format": "vertical",
            "durationSeconds": 6.0,
            "shots": [
                {
                    "id": "shot-1",
                    "startSeconds": 0.0,
                    "endSeconds": 6.0,
                    "transitionIn": "cut",
                    "visualEventId": "event-1",
                    "changeType": "establish",
                    "narrativeRole": "hook",
                    "humanPresence": True,
                    "src": "/tmp/source.mp4",
                    "avoidRegions": [],
                }
            ],
            "moments": [
                {
                    "id": "hook-1",
                    "kind": "hook",
                    "startSeconds": 0.0,
                    "endSeconds": 2.5,
                    "recipe": recipe,
                    "segments": [{"role": "hero", "text": "بازی‌های ویدیویی"}],
                }
            ],
            "typographicBeats": [],
            "captions": [],
            "audio": {},
            "watermark": {"persianText": watermark, "latinText": "Pathway"},
        },
    }


def _layout_issue() -> dict:
    return {"code": "FILM_TYPE_LAYOUT_OVERFLOW", "recoveryClass": "FILM_TYPE_LAYOUT"}


def _stage_layout(project: Path, candidate_id: str, payload: dict, *, parent: str) -> dict:
    return workspace.stage_edit_draft(
        project,
        candidate_id,
        payload,
        parent_attempt_id=parent,
        diagnostic_issue=_layout_issue(),
        strategy="select_curated_typography_recipe",
        changed_fields=["typography.recipe"],
        max_candidates=10,
        revision_cycle=0,
    )


def test_candidate_manifest_is_immutable_parented_and_dependency_aware(tmp_path: Path) -> None:
    project = tmp_path / "project"
    base = workspace.stage_edit_draft(project, "base", _edit(), max_candidates=10)
    child_payload = _edit(recipe="recipe-b")
    child = _stage_layout(project, "layout-1", child_payload, parent="base")

    manifest = workspace.load_convergence_candidate(project, "layout-1")
    assert manifest["candidateId"] == "layout-1"
    assert manifest["parentCandidateId"] == "base"
    assert manifest["baseArtifactSha256"] == base["artifactSha256"]
    assert manifest["artifactSha256"] == child["artifactSha256"]
    assert manifest["recoveryClass"] == "FILM_TYPE_LAYOUT"
    assert manifest["strategy"] == "select_curated_typography_recipe"
    assert manifest["changedFields"] == ["typography.recipe"]
    assert manifest["changedScopes"] == ["typography"]
    assert "typography.recipe" in manifest["mutationSurface"]
    assert manifest["dependencyDigests"]["browser"]
    assert manifest["dependencyDigests"]["retention"]
    assert manifest["disposition"] == "staged"

    with pytest.raises(PersianEditWorkspaceError, match="candidate identity is immutable"):
        workspace.stage_edit_draft(
            project,
            "layout-1",
            child_payload,
            parent_attempt_id="base",
            diagnostic_issue=_layout_issue(),
            strategy="rebalance_measured_line_plan",
            changed_fields=["typography.line_plan"],
            max_candidates=10,
        )


def test_layout_recovery_classifies_nested_presentation_recipe_as_typography(tmp_path: Path) -> None:
    project = tmp_path / "project"
    base = _edit()
    hook = base["persian"]["moments"][0]
    hook.pop("recipe", None)
    hook["presentation"] = {"recipeId": "editorial-hero-balanced"}
    workspace.stage_edit_draft(project, "base", base, max_candidates=10)

    child = deepcopy(base)
    child["persian"]["moments"][0]["presentation"]["recipeId"] = "editorial-hero-compact"
    staged = workspace.stage_edit_draft(
        project,
        "layout-1",
        child,
        parent_attempt_id="base",
        diagnostic_issue=_layout_issue(),
        strategy="select_curated_typography_recipe",
        changed_fields=["typography.recipe"],
        max_candidates=10,
        revision_cycle=0,
    )

    assert staged["changedScopes"] == ["typography"]
    manifest = workspace.load_convergence_candidate(project, "layout-1")
    assert manifest["changedScopes"] == ["typography"]


def test_asset_selection_recovery_atomically_rebinds_provenance_and_reviewed_regions(tmp_path: Path) -> None:
    project = tmp_path / "project"
    base = _edit()
    shot = base["persian"]["shots"][0]
    shot.pop("src", None)
    shot["source"] = "/tmp/source-a.mp4"
    shot["attribution"] = "Video by A on Pexels"
    shot["avoidRegions"] = [
        {"x": 0.2, "y": 0.3, "w": 0.5, "h": 0.4, "priority": "hard"}
    ]
    workspace.stage_edit_draft(project, "base", base, max_candidates=10)

    child = deepcopy(base)
    child_shot = child["persian"]["shots"][0]
    child_shot["source"] = "/tmp/source-b.mp4"
    child_shot["attribution"] = "Video by B on Pexels"
    child_shot["avoidRegions"] = [
        {"x": 0.3, "y": 0.25, "w": 0.4, "h": 0.3, "priority": "hard"},
        {"x": 0.15, "y": 0.25, "w": 0.7, "h": 0.6, "priority": "soft"},
    ]
    issue = {"code": "ASSET_SELECTION_RETRY", "recoveryClass": "ASSET_SELECTION"}
    staged = workspace.stage_edit_draft(
        project,
        "asset-rebind",
        child,
        parent_attempt_id="base",
        diagnostic_issue=issue,
        strategy="use_authored_alternate_query",
        changed_fields=["assets.selection", "subject_regions.review"],
        max_candidates=10,
        revision_cycle=0,
    )

    assert staged["changedScopes"] == ["assets", "subject_regions"]

    forbidden = deepcopy(child)
    forbidden["persian"]["moments"][0]["segments"][0]["text"] = "کپی تغییر کرده"
    with pytest.raises(PersianEditWorkspaceError, match="mutation surface"):
        workspace.stage_edit_draft(
            project,
            "asset-rebind-copy-change",
            forbidden,
            parent_attempt_id="base",
            diagnostic_issue=issue,
            strategy="use_authored_alternate_query",
            changed_fields=["assets.selection", "subject_regions.review"],
            max_candidates=10,
            revision_cycle=0,
        )


def test_recovery_mutation_surface_rejects_unrelated_edit_changes(tmp_path: Path) -> None:
    project = tmp_path / "project"
    workspace.stage_edit_draft(project, "base", _edit(), max_candidates=10)
    forbidden = _edit(watermark="واترمارک دیگر")

    with pytest.raises(PersianEditWorkspaceError, match="mutation surface"):
        _stage_layout(project, "bad-layout", forbidden, parent="base")

    status = workspace.convergence_status(project)
    assert status["candidateCount"] == 1
    assert status["status"] == "active"


def test_recovery_class_budget_exhaustion_persists_structured_needs_revision(tmp_path: Path) -> None:
    project = tmp_path / "project"
    workspace.stage_edit_draft(project, "base", _edit(), max_candidates=10)
    parent = "base"
    for index in range(3):
        candidate_id = f"layout-{index + 1}"
        _stage_layout(project, candidate_id, _edit(recipe=f"recipe-{index + 1}"), parent=parent)
        parent = candidate_id

    with pytest.raises(PersianEditWorkspaceError, match="candidate budget exhausted"):
        _stage_layout(project, "layout-4", _edit(recipe="recipe-4"), parent=parent)

    status = workspace.convergence_status(project)
    assert status["status"] == "needs_revision"
    unresolved = status["unresolved"]
    assert unresolved["recoveryClass"] == "FILM_TYPE_LAYOUT"
    assert unresolved["attemptsUsed"] == 3
    assert unresolved["maxAttempts"] == 3
    assert unresolved["outcome"] == "needs_human_editorial_revision"
    assert unresolved["unresolvedDiagnostics"][0]["code"] == "FILM_TYPE_LAYOUT_OVERFLOW"


def test_global_candidate_budget_is_enforced_by_workspace(tmp_path: Path) -> None:
    project = tmp_path / "project"
    workspace.stage_edit_draft(project, "base", _edit(), max_candidates=2)
    _stage = lambda cid, recipe, parent: workspace.stage_edit_draft(
        project,
        cid,
        _edit(recipe=recipe),
        parent_attempt_id=parent,
        diagnostic_issue=_layout_issue(),
        strategy="select_curated_typography_recipe",
        changed_fields=["typography.recipe"],
        max_candidates=2,
    )
    _stage("layout-1", "recipe-b", "base")
    with pytest.raises(PersianEditWorkspaceError, match="global candidate budget exhausted"):
        _stage("layout-2", "recipe-c", "layout-1")
    assert workspace.convergence_status(project)["unresolved"]["reason"] == "global_candidate_budget_exhausted"


def test_layout_candidate_reuses_unrelated_retention_and_hook_checks(monkeypatch, tmp_path: Path) -> None:
    project = tmp_path / "project"
    calls = {"contract": 0, "retention": 0, "hook": 0, "browser": 0}

    def fake_contract(edit, *, base_dir=None):
        calls["contract"] += 1
        return []

    def fake_retention(persian):
        calls["retention"] += 1
        return {"problems": [], "advisories": [], "marker": calls["retention"]}

    def fake_hook(edit):
        calls["hook"] += 1
        return {
            "problems": [],
            "advisories": [],
            "marker": calls["hook"],
            "timingPolicy": {"version": HOOK_TIMING_POLICY_VERSION},
        }

    def fake_browser(edit, *, base_dir=None, scratch_dir=None):
        calls["browser"] += 1
        return {
            "warnings": [],
            "watermarkDiagnostics": None,
            "browserMarker": calls["browser"],
        }

    monkeypatch.setattr(preflight, "collect_persian_edit_diagnostics", fake_contract)
    monkeypatch.setattr(preflight, "audit_persian_retention", fake_retention)
    monkeypatch.setattr(preflight, "audit_persian_hook_quality", fake_hook)
    monkeypatch.setattr(preflight, "browser_preflight_edit_decisions", fake_browser)

    workspace.stage_edit_draft(project, "base", _edit(), max_candidates=10)
    first = workspace.preflight_edit_draft(project, "base")
    _stage_layout(project, "layout-1", _edit(recipe="recipe-b"), parent="base")
    second = workspace.preflight_edit_draft(project, "layout-1")

    assert first["componentCacheHits"] == {
        "retention": False,
        "hook": False,
        "browser": False,
    }
    assert second["componentCacheHits"]["retention"] is True
    assert second["componentCacheHits"]["hook"] is True
    assert second["componentCacheHits"]["browser"] is False
    assert calls == {"contract": 2, "retention": 1, "hook": 1, "browser": 2}

    manifest = workspace.load_convergence_candidate(project, "layout-1")
    assert manifest["cacheHits"]["retention"] is True
    assert manifest["cacheHits"]["hook"] is True
    assert manifest["disposition"] == "preflight_passed"


def test_cheap_blocker_never_runs_browser_component(monkeypatch, tmp_path: Path) -> None:
    project = tmp_path / "project"
    browser_calls = 0

    monkeypatch.setattr(
        preflight,
        "collect_persian_edit_diagnostics",
        lambda edit, *, base_dir=None: [
            type("Problem", (), {"code": "EDIT_BAD", "pointer": "/persian", "message": "bad", "hint": None})()
        ],
    )

    def fake_browser(edit, *, base_dir=None, scratch_dir=None):
        nonlocal browser_calls
        browser_calls += 1
        return {"warnings": [], "watermarkDiagnostics": None}

    monkeypatch.setattr(preflight, "browser_preflight_edit_decisions", fake_browser)
    workspace.stage_edit_draft(project, "base", _edit(), max_candidates=10)
    report = workspace.preflight_edit_draft(project, "base")

    assert report["ok"] is False
    assert browser_calls == 0
    assert workspace.load_convergence_candidate(project, "base")["disposition"] == "blocked"


def test_candidate_compare_and_digest_bound_promotion_update_lifecycle(monkeypatch, tmp_path: Path) -> None:
    project = tmp_path / "project"
    monkeypatch.setattr(preflight, "collect_persian_edit_diagnostics", lambda edit, *, base_dir=None: [])
    monkeypatch.setattr(preflight, "audit_persian_retention", lambda persian: {"problems": [], "advisories": []})
    monkeypatch.setattr(preflight, "audit_persian_hook_quality", lambda edit: {"problems": [], "advisories": []})
    monkeypatch.setattr(
        preflight,
        "browser_preflight_edit_decisions",
        lambda edit, *, base_dir=None, scratch_dir=None: {"warnings": [], "watermarkDiagnostics": None},
    )

    workspace.stage_edit_draft(project, "base", _edit(), max_candidates=10)
    _stage_layout(project, "layout-1", _edit(recipe="recipe-b"), parent="base")
    comparison = workspace.compare_edit_candidates(project, "base", "layout-1")
    assert comparison["changedScopes"] == ["typography"]
    assert comparison["leftArtifactSha256"] != comparison["rightArtifactSha256"]

    report = workspace.preflight_edit_draft(project, "layout-1")
    assert report["ok"] is True
    promoted = workspace.promote_edit_draft(project, "layout-1")
    assert promoted["artifactSha256"] == report["artifactSha256"]
    manifest = workspace.load_convergence_candidate(project, "layout-1")
    assert manifest["disposition"] == "promoted"
    assert workspace.convergence_status(project)["promotedCandidateId"] == "layout-1"



def test_front_door_edit_stage_derives_workspace_budget_cycle_and_recovery_metadata(tmp_path: Path, monkeypatch) -> None:
    from lib import persian_video_workflow as workflow

    source = tmp_path / "candidate.json"
    source.write_text("{}", encoding="utf-8")
    project = tmp_path / "run"
    state = {
        "project_id": "run",
        "status": "active",
        "next_phase": "no_copy_preflight",
        "budgets": {"max_revisions_per_stage": 3},
        "user_revision_cycles": 2,
        "hook_selection": {"authority": "test"},
        "read_allowlist": {"project_root": str(project)},
    }
    captured = {}
    monkeypatch.setattr(workflow, "load_workflow_state", lambda *args, **kwargs: state)
    monkeypatch.setattr(workflow, "assert_read_allowed", lambda _state, path: Path(path))
    monkeypatch.setattr(workflow, "_read_json", lambda _path: {"persian": {}})
    monkeypatch.setattr(workflow, "validate_edit_hook_authority", lambda *args, **kwargs: {"valid": True})

    def fake_stage(project_dir, attempt_id, payload, **kwargs):
        captured.update({"project_dir": project_dir, "attempt_id": attempt_id, "payload": payload, **kwargs})
        return {"candidateId": attempt_id, "artifactSha256": "a" * 64}

    monkeypatch.setattr(workflow, "stage_edit_draft", fake_stage)
    result = workflow.stage_workflow_edit_draft(
        "run",
        "layout-1",
        source,
        parent_attempt_id="base",
        diagnostic_code="FILM_TYPE_LAYOUT_OVERFLOW",
        recovery_class="FILM_TYPE_LAYOUT",
        strategy="select_curated_typography_recipe",
        changed_fields=["typography.recipe"],
        pipeline_dir=tmp_path,
    )

    assert captured["parent_attempt_id"] == "base"
    assert captured["diagnostic_issue"] == {
        "code": "FILM_TYPE_LAYOUT_OVERFLOW",
        "recoveryClass": "FILM_TYPE_LAYOUT",
    }
    assert captured["strategy"] == "select_curated_typography_recipe"
    assert captured["changed_fields"] == ["typography.recipe"]
    assert captured["max_candidates"] == 4
    assert captured["revision_cycle"] == 2
    assert result["convergenceBudget"] == {"maxCandidates": 4, "revisionCycle": 2}


def test_front_door_parser_exposes_recovery_candidate_metadata_and_compare_command() -> None:
    from lib import persian_video_workflow as workflow

    parser = workflow.build_parser()
    staged = parser.parse_args([
        "edit-stage", "run", "layout-1", "--json", "/tmp/edit.json",
        "--parent", "base",
        "--diagnostic-code", "FILM_TYPE_LAYOUT_OVERFLOW",
        "--recovery-class", "FILM_TYPE_LAYOUT",
        "--strategy", "select_curated_typography_recipe",
        "--changed-field", "typography.recipe",
    ])
    assert staged.parent_attempt_id == "base"
    assert staged.diagnostic_code == "FILM_TYPE_LAYOUT_OVERFLOW"
    assert staged.recovery_class == "FILM_TYPE_LAYOUT"
    assert staged.changed_fields == ["typography.recipe"]

    compared = parser.parse_args(["edit-compare", "run", "base", "layout-1"])
    assert compared.command == "edit-compare"
    assert compared.left_attempt_id == "base"
    assert compared.right_attempt_id == "layout-1"


def test_workflow_status_surfaces_convergence_workspace_without_file_probing(tmp_path: Path, monkeypatch) -> None:
    from lib import persian_video_workflow as workflow

    project = tmp_path / "run"
    state = {
        "project_id": "run",
        "status": "active",
        "next_phase": "no_copy_preflight",
        "input": {},
        "completed_phases": [],
        "attempts": {},
        "send_backs": 0,
        "recovery_attempts": {},
        "asset_usage": {},
        "alignment_policy": {},
        "read_allowlist": {"project_root": str(project)},
    }
    monkeypatch.setattr(workflow, "load_workflow_state", lambda *args, **kwargs: state)
    monkeypatch.setattr(workflow, "phase_time_accounting", lambda _state: {})
    monkeypatch.setattr(
        workflow,
        "convergence_status",
        lambda project_dir, **_kwargs: {
            "status": "active",
            "candidateCount": 2,
            "candidateIds": ["base", "layout-1"],
            "promotedCandidateId": None,
            "unresolved": None,
        },
    )
    status = workflow.workflow_status("run", pipeline_dir=tmp_path)
    assert status["convergence"]["candidateCount"] == 2
    assert status["convergence"]["candidateIds"] == ["base", "layout-1"]



def test_full_report_cache_hit_does_not_fabricate_component_cache_hits(monkeypatch, tmp_path: Path) -> None:
    project = tmp_path / "project"
    calls = 0

    def fake_aggregate(edit, *, base_dir=None, precomputed_components=None, scratch_dir=None):
        nonlocal calls
        calls += 1
        return {
            "version": 1,
            "policyVersion": preflight.PREFLIGHT_POLICY_VERSION,
            "ok": True,
            "status": "pass",
            "artifactSha256": workspace.artifact_sha256(edit),
            "blockingIssues": [],
            "recoveryBudgets": {},
            "warnings": [],
            "watermarkDiagnostics": None,
            "nextActions": [],
            "diagnosticLayers": [],
            "mediaCopies": 0,
            "evidence": {},
        }

    monkeypatch.setattr(workspace, "aggregate_preflight_edit_decisions", fake_aggregate)
    workspace.stage_edit_draft(project, "base", _edit(), max_candidates=10)
    first = workspace.preflight_edit_draft(project, "base")
    workspace.stage_edit_draft(project, "same-edit", _edit(), max_candidates=10)
    second = workspace.preflight_edit_draft(project, "same-edit")

    assert calls == 1
    assert first["cacheHit"] is False
    assert second["cacheHit"] is True
    assert second["componentCacheHits"] == {
        "retention": False,
        "hook": False,
        "browser": False,
    }
    manifest = workspace.load_convergence_candidate(project, "same-edit")
    assert manifest["cacheHits"]["fullReport"] is True
    assert manifest["cacheHits"]["browser"] is False


def test_promotion_rejects_preflight_report_changed_after_candidate_binding(monkeypatch, tmp_path: Path) -> None:
    project = tmp_path / "project"
    monkeypatch.setattr(preflight, "collect_persian_edit_diagnostics", lambda edit, *, base_dir=None: [])
    monkeypatch.setattr(preflight, "audit_persian_retention", lambda persian: {"problems": [], "advisories": []})
    monkeypatch.setattr(preflight, "audit_persian_hook_quality", lambda edit: {"problems": [], "advisories": []})
    monkeypatch.setattr(
        preflight,
        "browser_preflight_edit_decisions",
        lambda edit, *, base_dir=None, scratch_dir=None: {"warnings": [], "watermarkDiagnostics": None},
    )

    workspace.stage_edit_draft(project, "base", _edit(), max_candidates=10)
    report = workspace.preflight_edit_draft(project, "base")
    assert report["ok"] is True
    report_path = project / ".preflight" / "edit" / "base" / "preflight_report.json"
    raw = __import__("json").loads(report_path.read_text(encoding="utf-8"))
    raw["warnings"] = ["tampered after preflight"]
    report_path.write_text(__import__("json").dumps(raw, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(PersianEditWorkspaceError, match="preflight report changed"):
        workspace.promote_edit_draft(project, "base")


def test_layout_recovery_rejects_unclassified_render_affecting_changes(tmp_path: Path) -> None:
    project = tmp_path / "project"
    workspace.stage_edit_draft(project, "base", _edit(), max_candidates=10)
    forbidden = deepcopy(_edit())
    forbidden["persian"]["format"] = "square"

    with pytest.raises(PersianEditWorkspaceError, match="mutation surface"):
        _stage_layout(project, "bad-format", forbidden, parent="base")



def test_front_door_rejects_second_root_candidate_in_same_revision_cycle(tmp_path: Path, monkeypatch) -> None:
    from lib import persian_video_workflow as workflow

    source = tmp_path / "candidate.json"
    source.write_text("{}", encoding="utf-8")
    project = tmp_path / "run"
    state = {
        "project_id": "run",
        "status": "active",
        "next_phase": "no_copy_preflight",
        "budgets": {"max_revisions_per_stage": 3},
        "user_revision_cycles": 0,
        "hook_selection": {"authority": "test"},
        "read_allowlist": {"project_root": str(project)},
    }
    monkeypatch.setattr(workflow, "load_workflow_state", lambda *args, **kwargs: state)
    monkeypatch.setattr(workflow, "assert_read_allowed", lambda _state, path: Path(path))
    monkeypatch.setattr(workflow, "_read_json", lambda _path: {"persian": {}})
    monkeypatch.setattr(workflow, "validate_edit_hook_authority", lambda *args, **kwargs: {"valid": True})
    monkeypatch.setattr(
        workflow,
        "convergence_status",
        lambda _project, **_kwargs: {
            "status": "active",
            "candidateCount": 1,
            "candidateIds": ["base"],
            "promotedCandidateId": None,
            "unresolved": None,
        },
    )

    with pytest.raises(workflow.PersianVideoWorkflowError, match="base convergence candidate already exists"):
        workflow.stage_workflow_edit_draft(
            "run", "second-root", source, pipeline_dir=tmp_path
        )


def test_sibling_candidate_continuity_is_measured_against_its_parent(tmp_path: Path) -> None:
    project = tmp_path / "project"
    base = _edit()
    workspace.stage_edit_draft(project, "base", base, max_candidates=10)

    first_child = deepcopy(base)
    first_child["persian"]["moments"].append({
        "id": "child-only-moment",
        "kind": "statement",
        "startSeconds": 3.0,
        "endSeconds": 4.0,
        "segments": [{"role": "hero", "text": "فقط در شاخه اول"}],
    })
    workspace.stage_edit_draft(
        project, "child-a", first_child, parent_attempt_id="base", max_candidates=10
    )

    sibling = workspace.stage_edit_draft(
        project, "child-b", deepcopy(base), parent_attempt_id="base", max_candidates=10
    )
    assert sibling["removedEditorialMomentIds"] == []
    assert sibling["editorialMomentIds"] == ["hook-1"]



def test_cached_retention_blocker_remains_blocking_without_browser_rerun(monkeypatch, tmp_path: Path) -> None:
    project = tmp_path / "project"
    calls = {"retention": 0, "browser": 0}

    monkeypatch.setattr(preflight, "collect_persian_edit_diagnostics", lambda edit, *, base_dir=None: [])

    def fake_retention(persian):
        calls["retention"] += 1
        return {"problems": ["cached retention blocker"], "advisories": [], "marker": 1}

    def fake_browser(edit, *, base_dir=None, scratch_dir=None):
        calls["browser"] += 1
        return {"warnings": [], "watermarkDiagnostics": None}

    monkeypatch.setattr(preflight, "audit_persian_retention", fake_retention)
    monkeypatch.setattr(preflight, "audit_persian_hook_quality", lambda edit: {"problems": [], "advisories": []})
    monkeypatch.setattr(preflight, "browser_preflight_edit_decisions", fake_browser)

    workspace.stage_edit_draft(project, "base", _edit(), max_candidates=10)
    first = workspace.preflight_edit_draft(project, "base")
    assert first["ok"] is False
    assert first["blockingIssues"][0]["code"] == "RETENTION_GATE"

    workspace.stage_edit_draft(
        project,
        "child",
        _edit(recipe="recipe-b"),
        parent_attempt_id="base",
        max_candidates=10,
    )
    second = workspace.preflight_edit_draft(project, "child")

    assert second["ok"] is False
    assert second["componentCacheHits"]["retention"] is True
    assert second["blockingIssues"][0]["code"] == "RETENTION_GATE"
    assert second["evidence"]["retentionAudit"]["marker"] == 1
    assert calls == {"retention": 1, "browser": 0}



def test_workflow_status_scopes_convergence_to_current_revision_cycle(tmp_path: Path, monkeypatch) -> None:
    from lib import persian_video_workflow as workflow

    project = tmp_path / "run"
    state = {
        "project_id": "run",
        "status": "active",
        "next_phase": "no_copy_preflight",
        "user_revision_cycles": 3,
        "input": {},
        "completed_phases": [],
        "attempts": {},
        "send_backs": 0,
        "recovery_attempts": {},
        "asset_usage": {},
        "alignment_policy": {},
        "read_allowlist": {"project_root": str(project)},
    }
    observed = {}
    monkeypatch.setattr(workflow, "load_workflow_state", lambda *args, **kwargs: state)
    monkeypatch.setattr(workflow, "phase_time_accounting", lambda _state: {})

    def fake_convergence_status(project_dir, *, revision_cycle=None):
        observed["project_dir"] = project_dir
        observed["revision_cycle"] = revision_cycle
        return {
            "status": "active",
            "revisionCycle": revision_cycle,
            "candidateCount": 0,
            "candidateIds": [],
            "promotedCandidateId": None,
            "unresolved": None,
        }

    monkeypatch.setattr(workflow, "convergence_status", fake_convergence_status)
    status = workflow.workflow_status("run", pipeline_dir=tmp_path)
    assert observed["revision_cycle"] == 3
    assert status["convergence"]["revisionCycle"] == 3
