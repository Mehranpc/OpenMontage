from __future__ import annotations
import json
from pathlib import Path
import pytest
from lib.persian_edit_workspace import (
    PersianEditWorkspaceError, _dependency_digests, artifact_sha256, load_promotable_edit_draft,
    preflight_edit_draft, promote_edit_draft, stage_edit_draft,
)


def _edit(tag: str = "one") -> dict:
    return {"persian": {"format": "vertical", "durationSeconds": 1.0, "shots": [], "moments": [], "audio": {}, "watermark": {"persianText": tag, "latinText": "Pathway"}}}


def _write_report(project: Path, attempt: str, edit: dict, ok: bool, *, digest: str | None = None) -> None:
    path = project / ".preflight" / "edit" / attempt / "preflight_report.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"ok": ok, "artifactSha256": digest or artifact_sha256(edit)}), encoding="utf-8")


def test_failed_probe_never_overwrites_canonical(tmp_path: Path) -> None:
    project = tmp_path / "project"; canonical = project / "artifacts" / "edit_decisions.json"
    canonical.parent.mkdir(parents=True); canonical.write_text(json.dumps(_edit("old")), encoding="utf-8")
    new = _edit("new"); stage_edit_draft(project, "a1", new); _write_report(project, "a1", new, False)
    with pytest.raises(PersianEditWorkspaceError, match="did not pass"):
        promote_edit_draft(project, "a1")
    assert json.loads(canonical.read_text())["persian"]["watermark"]["persianText"] == "old"


def test_promotion_is_digest_bound_atomic_and_idempotent(tmp_path: Path) -> None:
    project = tmp_path / "project"; new = _edit("new")
    staged = stage_edit_draft(project, "a1", new); _write_report(project, "a1", new, True)
    first = promote_edit_draft(project, "a1")
    second = promote_edit_draft(project, "a1")
    assert first["promoted"] is True and second["idempotent"] is True
    canonical = json.loads((project / "artifacts" / "edit_decisions.json").read_text())
    assert artifact_sha256(canonical) == staged["artifactSha256"]


def test_digest_mismatch_blocks_promotion(tmp_path: Path) -> None:
    project = tmp_path / "project"; edit = _edit()
    stage_edit_draft(project, "a1", edit); _write_report(project, "a1", edit, True, digest="0" * 64)
    with pytest.raises(PersianEditWorkspaceError, match="digest differs"):
        promote_edit_draft(project, "a1")


def test_attempt_id_is_immutable_for_different_bytes(tmp_path: Path) -> None:
    project = tmp_path / "project"; stage_edit_draft(project, "a1", _edit("one"))
    with pytest.raises(PersianEditWorkspaceError, match="different edit bytes"):
        stage_edit_draft(project, "a1", _edit("two"))


def test_hook_dependency_digest_is_authority_aware() -> None:
    edit = _edit()
    automatic = {"mode": "automatic", "authoritative": False, "sha256": "a" * 64}
    user = {"mode": "user_supplied", "authoritative": True, "sha256": "b" * 64}
    auto_deps = _dependency_digests(edit, hook_authority=automatic)
    user_deps = _dependency_digests(edit, hook_authority=user)
    assert auto_deps["hook"] != user_deps["hook"]
    assert auto_deps["retention"] == user_deps["retention"]
    assert auto_deps["browser"] == user_deps["browser"]


def test_promotion_refuses_when_hook_authority_context_changed(tmp_path: Path) -> None:
    project = tmp_path / "project"
    edit = _edit("new")
    first = {"mode": "user_supplied", "authoritative": True, "sha256": "a" * 64}
    changed = {"mode": "user_supplied", "authoritative": True, "sha256": "b" * 64}
    stage_edit_draft(project, "a1", edit, hook_authority=first)
    report = project / ".preflight" / "edit" / "a1" / "preflight_report.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps({
        "ok": True,
        "artifactSha256": artifact_sha256(edit),
        "dependencyDigests": _dependency_digests(edit, hook_authority=first),
    }), encoding="utf-8")
    with pytest.raises(PersianEditWorkspaceError, match="dependency context changed"):
        load_promotable_edit_draft(project, "a1", hook_authority=changed)


def test_preflight_refuses_when_hook_authority_changed_after_staging(tmp_path: Path) -> None:
    project = tmp_path / "project"
    edit = _edit("new")
    first = {"mode": "user_supplied", "authoritative": True, "sha256": "a" * 64}
    changed = {"mode": "user_supplied", "authoritative": True, "sha256": "b" * 64}
    stage_edit_draft(project, "a2", edit, hook_authority=first)
    with pytest.raises(PersianEditWorkspaceError, match="staged dependency context changed"):
        preflight_edit_draft(project, "a2", hook_authority=changed)
