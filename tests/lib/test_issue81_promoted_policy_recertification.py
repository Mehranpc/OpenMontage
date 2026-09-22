from __future__ import annotations

from pathlib import Path

import pytest

from lib import persian_edit_workspace as workspace
from lib import persian_preflight as preflight
from lib import persian_video_workflow as workflow
from lib.persian_edit_workspace import PersianEditWorkspaceError
from tests.lib.test_issue35_convergence_workspace import _edit


def _stub_preflight(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(preflight, "collect_persian_edit_diagnostics", lambda edit, *, base_dir=None: [])
    monkeypatch.setattr(
        preflight,
        "audit_persian_retention",
        lambda persian: {"problems": [], "advisories": []},
    )

    def fake_hook(edit, *, hook_authority=None):
        return {
            "version": "2.0",
            "required": True,
            "disposition": "acceptable",
            "problems": [],
            "advisories": [],
            "timingPolicy": {"version": preflight.HOOK_TIMING_POLICY_VERSION},
        }

    monkeypatch.setattr(preflight, "audit_persian_hook_quality", fake_hook)
    monkeypatch.setattr(
        preflight,
        "browser_preflight_edit_decisions",
        lambda edit, *, base_dir=None, scratch_dir=None: {
            "warnings": [],
            "watermarkDiagnostics": None,
        },
    )


def test_promoted_same_digest_can_be_recertified_after_policy_change_without_new_candidate(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _stub_preflight(monkeypatch)
    project = tmp_path / "project"
    payload = _edit()

    workspace.stage_edit_draft(project, "base", payload, max_candidates=1)
    first = workspace.preflight_edit_draft(project, "base")
    workspace.promote_edit_draft(project, "base")
    before = workspace.load_convergence_candidate(project, "base")
    before_hook_digest = before["dependencyDigests"]["hook"]
    before_report_sha = before["preflightReportSha256"]
    canonical_digest = before["artifactSha256"]

    monkeypatch.setattr(workspace, "HOOK_TIMING_POLICY_VERSION", "9.9")
    monkeypatch.setattr(preflight, "HOOK_TIMING_POLICY_VERSION", "9.9")

    with pytest.raises(PersianEditWorkspaceError, match="dependency context changed"):
        workspace.preflight_edit_draft(project, "base")

    second = workspace.preflight_edit_draft(
        project, "base", recertify_promoted=True
    )
    assert second["ok"] is True
    assert second["recertifiedPromotedCandidate"] is True
    assert second["artifactSha256"] == canonical_digest
    assert second["evidence"]["hookQualityAudit"]["timingPolicy"]["version"] == "9.9"

    after = workspace.load_convergence_candidate(project, "base")
    assert after["artifactSha256"] == canonical_digest
    assert after["dependencyDigests"]["hook"] != before_hook_digest
    assert after["preflightReportSha256"] != before_report_sha
    assert after["disposition"] == "preflight_passed"
    history = after["certificationHistory"]
    assert len(history) == 1
    history_path = Path(history[0]["path"])
    assert history_path.is_file()
    assert history[0]["preflightReportSha256"] == before_report_sha

    status = workspace.convergence_status(project)
    assert status["candidateCount"] == 1
    assert status["candidateIds"] == ["base"]

    promoted = workspace.promote_edit_draft(project, "base")
    assert promoted["idempotent"] is True
    assert workspace.load_convergence_candidate(project, "base")["disposition"] == "promoted"


def test_recertification_is_explicit_and_only_for_the_promoted_canonical_digest(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _stub_preflight(monkeypatch)
    project = tmp_path / "project"
    workspace.stage_edit_draft(project, "base", _edit(), max_candidates=1)
    workspace.preflight_edit_draft(project, "base")

    monkeypatch.setattr(workspace, "HOOK_TIMING_POLICY_VERSION", "9.9")
    monkeypatch.setattr(preflight, "HOOK_TIMING_POLICY_VERSION", "9.9")
    with pytest.raises(PersianEditWorkspaceError, match="promoted candidate"):
        workspace.preflight_edit_draft(project, "base", recertify_promoted=True)


def test_front_door_exposes_promoted_policy_recertification_as_an_explicit_opt_in(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    parser = workflow.build_parser()
    parsed = parser.parse_args(
        ["edit-preflight", "run", "base", "--recertify-promoted"]
    )
    assert parsed.recertify_promoted is True

    project = tmp_path / "run"
    state = {
        "project_id": "run",
        "next_phase": "no_copy_preflight",
        "hook_selection": {"mode": "user_supplied"},
        "read_allowlist": {"project_root": str(project)},
    }
    monkeypatch.setattr(workflow, "load_workflow_state", lambda *args, **kwargs: state)
    captured = {}

    def fake_preflight(project_dir, attempt_id, *, hook_authority=None, recertify_promoted=False):
        captured.update(
            project_dir=project_dir,
            attempt_id=attempt_id,
            hook_authority=hook_authority,
            recertify_promoted=recertify_promoted,
        )
        return {"ok": True}

    monkeypatch.setattr(workflow, "preflight_edit_draft", fake_preflight)
    result = workflow.preflight_workflow_edit_draft(
        "run", "base", pipeline_dir=tmp_path, recertify_promoted=True
    )
    assert result == {"ok": True}
    assert captured["attempt_id"] == "base"
    assert captured["recertify_promoted"] is True
