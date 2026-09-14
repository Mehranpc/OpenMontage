from __future__ import annotations
import json
from pathlib import Path
import pytest
from lib.persian_edit_workspace import (
    PersianEditWorkspaceError, artifact_sha256, promote_edit_draft, stage_edit_draft,
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
