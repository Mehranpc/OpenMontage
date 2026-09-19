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
