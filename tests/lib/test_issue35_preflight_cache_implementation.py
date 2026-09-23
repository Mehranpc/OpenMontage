from __future__ import annotations

from pathlib import Path

from lib import persian_edit_workspace as workspace


def _edit() -> dict:
    return {
        "persian": {
            "format": "vertical",
            "durationSeconds": 6.0,
            "shots": [],
            "moments": [],
            "typographicBeats": [],
            "captions": [],
            "audio": {},
        }
    }


def _passing_report(edit: dict, marker: int) -> dict:
    return {
        "version": 1,
        "policyVersion": workspace.PREFLIGHT_POLICY_VERSION,
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
        "evidence": {"marker": marker},
    }


def test_full_report_cache_is_invalidated_when_dependency_digest_changes(
    monkeypatch, tmp_path: Path
) -> None:
    project = tmp_path / "project"
    calls = 0
    browser_revision = "browser-a"

    def fake_dependencies(_edit_payload):
        return {
            "retention": "retention-stable",
            "hook": "hook-stable",
            "browser": browser_revision,
        }

    def fake_aggregate(edit, *, base_dir=None, precomputed_components=None, scratch_dir=None):
        nonlocal calls
        calls += 1
        return _passing_report(edit, calls)

    monkeypatch.setattr(workspace, "_dependency_digests", fake_dependencies)
    monkeypatch.setattr(workspace, "aggregate_preflight_edit_decisions", fake_aggregate)

    workspace.stage_edit_draft(project, "first", _edit(), max_candidates=10)
    first = workspace.preflight_edit_draft(project, "first")
    assert first["cacheHit"] is False
    assert calls == 1

    browser_revision = "browser-b"
    workspace.stage_edit_draft(project, "second", _edit(), max_candidates=10)
    second = workspace.preflight_edit_draft(project, "second")

    assert second["cacheHit"] is False
    assert second["dependencyDigests"]["browser"] == "browser-b"
    assert second["evidence"]["marker"] == 2
    assert calls == 2


def test_browser_dependency_digest_contains_implementation_identity() -> None:
    digests = workspace._dependency_digests(_edit())
    identity = workspace._component_implementation_digests()

    assert set(identity) == {"retention", "hook", "browser"}
    assert "lib/persian_sync.py" in workspace._COMPONENT_IMPLEMENTATION_PATHS["browser"]
    assert all(len(value) == 64 for value in identity.values())
    assert all(value for value in identity.values())
    assert digests["browser"] != workspace._stable_digest(
        {
            "policyVersion": workspace.PREFLIGHT_POLICY_VERSION,
            "version": "browser-v1",
            "deps": _edit()["persian"],
        }
    )
