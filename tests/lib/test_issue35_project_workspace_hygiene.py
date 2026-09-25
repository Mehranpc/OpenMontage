from __future__ import annotations

import io
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

import lib.persian_preflight as preflight
from lib.persian_durable_job import start_job
from lib.persian_film_type import prepare_film_type_props
from lib.persian_project_workspace import (
    ProjectWorkspaceError,
    assert_repository_root_unchanged,
    repository_root_snapshot,
    workspace_directory,
    workspace_file,
)
from lib.persian_video_workflow import _bootstrap_inputs, build_parser


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def test_official_workspace_paths_are_classified_and_project_local(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    categories = (
        "temporary_inputs",
        "probes",
        "debug",
        "helpers",
        "cache",
        "generated_evidence",
        "runtime",
        "temp",
    )

    resolved = [workspace_directory(project, category) for category in categories]

    assert len(set(resolved)) == len(categories)
    assert all(_inside(path, project) for path in resolved)
    target = workspace_file(project, "helpers", "diagnostics/inspect.json")
    assert _inside(target, project)
    assert target.parent.is_dir()
    with pytest.raises(ProjectWorkspaceError, match="inside the current project"):
        workspace_file(project, "helpers", "../escape.py")


def test_repository_root_cleanliness_uses_before_after_delta(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "intentional-private.txt").write_text("keep", encoding="utf-8")
    before = repository_root_snapshot(repo)

    assert_repository_root_unchanged(repo, before)
    (repo / "tmp_accidental_script.txt").write_text("leak", encoding="utf-8")

    with pytest.raises(ProjectWorkspaceError, match="repository root gained"):
        assert_repository_root_unchanged(repo, before)


def test_durable_job_declares_project_local_execution_and_temp_roots(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()

    state = start_job(
        project,
        job_id="workspace-job",
        phase="render",
        argv=["python", "-c", "print('ok')"],
        idempotence_key="workspace-job",
        launch=False,
    )

    context = state["executionContext"]
    assert _inside(Path(context["cwd"]), project)
    assert _inside(Path(context["workspaceDir"]), project)
    assert _inside(Path(context["tempDir"]), project)
    assert context["cwd"] != str(Path(__file__).resolve().parents[2])


def test_browser_preflight_scopes_nested_mechanics_to_project_scratch(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    scratch = workspace_directory(project, "probes")
    observed: dict[str, str] = {}

    monkeypatch.setattr(
        preflight.NoCopyPersianCompose,
        "_runtime_persian",
        staticmethod(lambda _edit: {"format": "vertical"}),
    )

    def fake_build(_self, _persian, staging_dir: Path, _run_id: str):
        observed["staging"] = str(staging_dir)
        observed["scratch_env"] = os.environ.get("OPENMONTAGE_SCRATCH_DIR", "")
        return {}, []

    monkeypatch.setattr(preflight.NoCopyPersianCompose, "_build_props", fake_build)
    monkeypatch.setattr(preflight, "summarize", lambda _props, _attrs: {"ok": True})

    result = preflight.browser_preflight_edit_decisions(
        {"persian": {}}, scratch_dir=scratch
    )

    assert result == {"ok": True}
    assert _inside(Path(observed["staging"]), project)
    assert _inside(Path(observed["scratch_env"]), project)


def test_film_type_prepass_uses_supplied_project_scratch(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    scratch = workspace_directory(project, "probes")
    composer = tmp_path / "composer"
    script = composer / "scripts" / "prepare-persian-film-type.mjs"
    script.parent.mkdir(parents=True)
    script.write_text("// fixture", encoding="utf-8")
    observed: list[Path] = []
    props = {
        "design": {"profileVersion": "2.16.0", "resolved": {"layoutVersion": 16}},
        "moments": [],
    }

    def fake_run(argv, **_kwargs):
        source = Path(argv[-2])
        result = Path(argv[-1])
        observed.extend([source, result])
        prepared = dict(props)
        prepared.update(
            {
                "filmType": {"version": 16, "inputHash": "fixture"},
                "watermarkPlanMeasured": True,
                "watermarkPlan": [],
            }
        )
        result.write_text(json.dumps(prepared), encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("lib.persian_film_type.subprocess.run", fake_run)

    prepared = prepare_film_type_props(props, composer, scratch_dir=scratch)

    assert prepared["filmType"]["version"] == 16
    assert observed
    assert all(_inside(path, project) for path in observed)


def test_bootstrap_can_read_approved_script_from_stdin_without_temp_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parser = build_parser()
    args = parser.parse_args(
        ["bootstrap", "--title", "Fixture", "--approved-script-file", "-"]
    )
    monkeypatch.setattr("sys.stdin", io.StringIO("متن تأییدشده"))

    narration, approved_script = _bootstrap_inputs(args)

    assert narration is None
    assert approved_script == "متن تأییدشده"


def test_bounded_recovery_cycle_leaves_the_repository_root_clean(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A public-seam recovery cycle adds no repository-root entry or helper script.

    The bounded Persian workflow replaced ad-hoc helper Python with front-door
    seams; driving a recovery cycle through those seams (edit staging, workspace
    preflight, asset select/replace, send-back) must leave the repository root and
    ``scripts/`` untouched, including no new ``*.py``.
    """
    from lib import persian_asset_workspace as assets
    from lib import persian_edit_workspace as edit_workspace
    from lib import persian_preflight as preflight
    from lib import persian_video_workflow as workflow
    from lib.paths import REPO_ROOT
    from tests.lib.test_issue35_asset_candidate_workspace import _discovered, _review
    from tests.lib.test_issue35_convergence_workspace import _edit
    from tests.lib.test_persian_video_workflow import BASE, _advance_to, _bootstrap

    roots = (REPO_ROOT, REPO_ROOT / "scripts")
    before_entries = {root: repository_root_snapshot(root) for root in roots}
    before_py = {root: frozenset(path.name for path in root.glob("*.py")) for root in roots}

    _bootstrap(tmp_path)
    _advance_to(tmp_path, "no_copy_preflight")
    project = tmp_path / "run"
    hook_text = "بازی‌های ویدیویی"
    workflow.record_hook_selection(
        "run", selected_text=hook_text, hook_family="fixture",
        candidates=[{"text": hook_text}, {"text": "گزینهٔ دوم"}],
        score=8.0, content_match_score=2, evidence_checked=True,
        unsupported_claims_rejected=True,
        rationale="Repository-cleanliness recovery-cycle fixture.",
        pipeline_dir=tmp_path,
    )

    def _draft(attempt_id: str, recipe: str, **kwargs) -> dict:
        payload = _edit(recipe=recipe)
        payload["persian"]["moments"][0]["segments"][0]["text"] = hook_text
        path = project / "artifacts" / f"edit-{attempt_id}.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return workflow.stage_workflow_edit_draft(
            "run", attempt_id, path, pipeline_dir=tmp_path, **kwargs
        )

    base = _draft("base", "recipe-a")
    recovery = _draft(
        "recovery-1", "recipe-b", parent_attempt_id="base",
        diagnostic_code="FILM_TYPE_LAYOUT_OVERFLOW",
        recovery_class="FILM_TYPE_LAYOUT",
        strategy="select_curated_typography_recipe",
        changed_fields=["typography.recipe"],
    )
    assert base["artifactSha256"] != recovery["artifactSha256"]

    def fake_aggregate(
        edit, *, base_dir=None, precomputed_components=None, scratch_dir=None,
        hook_authority=None,
    ):
        return {
            "version": 1, "policyVersion": preflight.PREFLIGHT_POLICY_VERSION,
            "ok": True, "status": "passed",
            "artifactSha256": edit_workspace.artifact_sha256(edit),
            "blockingIssues": [], "recoveryBudgets": {}, "warnings": [],
            "watermarkDiagnostics": None, "nextActions": [],
            "diagnosticLayers": [], "mediaCopies": 0, "evidence": {},
        }

    monkeypatch.setattr(edit_workspace, "aggregate_preflight_edit_decisions", fake_aggregate)
    report = workflow.preflight_workflow_edit_draft("run", "recovery-1", pipeline_dir=tmp_path)
    assert report["ok"] is True

    discovery_id = assets.record_discovery_pass(
        project, 0, [_discovered(project)]
    )["candidateIds"][0]
    first = assets.stage_asset_candidate(
        project, discovery_id=discovery_id, visual_event_id="event-1",
        semantic_beat_id="beat-1", source_in_seconds=0.0, duration_seconds=4.0,
        intended_crop={"mode": "cover", "x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0},
        candidate_rank=1, query="person thinking at desk", narration_span="جملهٔ نمونه",
    )
    assets.record_candidate_review(project, first["candidateId"], _review())
    assets.select_asset_candidate(
        project, "event-1", first["candidateId"], rejected_alternatives={}
    )
    second = assets.stage_asset_candidate(
        project, discovery_id=discovery_id, visual_event_id="event-1",
        semantic_beat_id="beat-1", source_in_seconds=5.0, duration_seconds=4.0,
        intended_crop={"mode": "cover", "x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0},
        candidate_rank=2, query="person thinking at desk", narration_span="جملهٔ نمونه",
    )
    assets.record_candidate_review(project, second["candidateId"], _review())
    replaced = assets.select_asset_candidate(
        project, "event-1", second["candidateId"], replace_existing=True,
        rejected_alternatives={first["candidateId"]: "replaced with a reviewed window"},
    )
    assert replaced["selected"] is True

    rewound = workflow.request_send_back(
        "run", "acquire_assets", reason="user approved a bounded recovery cycle",
        user_directed_revision=True, pipeline_dir=tmp_path, now=BASE,
    )
    assert rewound["status"] == "active"
    assert rewound["next_phase"] == "acquire_assets"

    for root in roots:
        assert_repository_root_unchanged(root, before_entries[root])
        assert frozenset(path.name for path in root.glob("*.py")) == before_py[root]
