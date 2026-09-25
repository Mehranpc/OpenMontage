from __future__ import annotations

import hashlib
from pathlib import Path

import lib.persian_edit_workspace as edit_workspace
import lib.persian_video_workflow as workflow
from tests.fixture_support.p4_failed_shadow import load_issue138_fixture
from tests.lib.test_persian_video_workflow import (
    _advance_to,
    _bootstrap,
    _cutless_persian_edit,
)


def _tree_snapshot(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_issue138_edit_probe_matches_official_context_and_is_read_only(
    tmp_path: Path, monkeypatch,
) -> None:
    _bootstrap(tmp_path)
    _advance_to(tmp_path, "no_copy_preflight")
    project = tmp_path / "run"
    fixture = load_issue138_fixture()
    authority = dict(fixture["authority"]["hookSelection"])

    state = workflow.load_workflow_state("run", pipeline_dir=tmp_path)
    state["hook_selection"] = authority
    workflow._write_state(project, state)

    edit = _cutless_persian_edit("issue138-f2")
    edit_workspace.stage_edit_draft(
        project, "f2-context", edit, hook_authority=authority
    )

    seen_authority: list[dict] = []

    def canonical_oracle(payload, **kwargs):
        seen_authority.append(dict(kwargs.get("hook_authority") or {}))
        return {
            "status": "pass",
            "ok": True,
            "artifactSha256": edit_workspace.artifact_sha256(payload),
            "blockingIssues": [],
            "warnings": [],
            "evidence": {},
            "watermarkDiagnostics": None,
            "nextActions": [],
            "diagnosticLayers": [],
            "policyVersion": edit_workspace.PREFLIGHT_POLICY_VERSION,
        }

    monkeypatch.setattr(
        edit_workspace, "aggregate_preflight_edit_decisions", canonical_oracle
    )

    before = _tree_snapshot(project)
    probe = workflow.probe_workflow_edit_draft(
        "run", "f2-context", pipeline_dir=tmp_path
    )
    after = _tree_snapshot(project)
    assert after == before
    assert probe["readOnly"] is True
    assert probe["durableSideEffects"] is False

    official = workflow.preflight_workflow_edit_draft(
        "run", "f2-context", pipeline_dir=tmp_path
    )
    assert probe["blockingIssues"] == official["blockingIssues"]
    assert probe["artifactSha256"] == official["artifactSha256"]
    assert probe["workflowAuthorityContext"] == official["workflowAuthorityContext"]
    assert seen_authority == [authority, authority]

    context = probe["workflowAuthorityContext"]
    assert context["hookAuthority"] == {
        "mode": "user_supplied",
        "authoritative": True,
        "sha256": fixture["authority"]["hookSelection"]["sha256"],
    }
    assert context["policyPin"]["filmTypeProfileVersion"] == "2.16.0"


def test_parser_exposes_supported_read_only_edit_probe() -> None:
    args = workflow.build_parser().parse_args(["edit-probe", "run", "f2-context"])
    assert args.command == "edit-probe"
    assert args.project_id == "run"
    assert args.attempt_id == "f2-context"
