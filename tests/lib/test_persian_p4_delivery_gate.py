import hashlib
import json
from copy import deepcopy
from pathlib import Path

import jsonschema
import pytest

from lib.checkpoint import (
    CheckpointValidationError,
    _validate_persian_delivery_gate,
    init_project,
    write_checkpoint,
)
from schemas.artifacts import validate_artifact


def _candidate(tmp_path: Path) -> tuple[Path, str]:
    path = tmp_path / "run" / "renders" / "candidate.mp4"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"candidate")
    return path, hashlib.sha256(b"candidate").hexdigest()


def _render(path: Path, digest: str) -> dict:
    return {
        "version": "1.0",
        "outputs": [{
            "path": str(path), "format": "mp4", "resolution": "1080x1920",
            "duration_seconds": 10, "sha256": digest,
        }],
        "delivery_status": "final_candidate",
        "human_visual_approval": False,
        "persian_text_verified": False,
    }


def _review(path: Path, digest: str) -> dict:
    return {
        "version": "1.0", "output_path": str(path), "output_sha256": digest,
        "status": "pass",
        "checks": {
            "technical_probe": {}, "visual_spotcheck": {}, "audio_spotcheck": {},
            "promise_preservation": {}, "subtitle_check": {},
        },
    }


def _quality(path: Path, digest: str) -> dict:
    return {
        "version": "1.0", "policy_version": "p4-delivery-v1",
        "policy_mode": "enforced", "generated_at": "2026-09-24T08:00:00Z",
        "output_path": str(path), "output_sha256": digest,
        "technical_disposition": "pass", "delivery_disposition": "deliver",
        "blockers": [], "stale_refs": [], "missing_checks": [],
        "time_and_cost_summary": {
            "workflow_wall_seconds": 120.0, "unattributed_wall_seconds": 2.0,
            "causal_coverage_percent": 98.333, "total_cost_usd": 1.25,
        },
    }


def _enforced_project(tmp_path: Path, monkeypatch) -> tuple[Path, str]:
    monkeypatch.setenv("OPENMONTAGE_PERSIAN_DELIVERY_GATE_MODE", "enforced")
    init_project("run", title="Run", pipeline_type="persian-footage", pipeline_dir=tmp_path)
    return _candidate(tmp_path)


def _write_candidate(tmp_path: Path, artifacts: dict) -> None:
    write_checkpoint(
        tmp_path, "run", "compose", "awaiting_human", artifacts,
        pipeline_type="persian-footage",
    )


def test_quality_report_schema_is_strict(tmp_path: Path) -> None:
    path, digest = _candidate(tmp_path)
    payload = _quality(path, digest)
    validate_artifact("quality_report", payload)
    payload["unexpected"] = True
    with pytest.raises(jsonschema.ValidationError):
        validate_artifact("quality_report", payload)


def test_new_run_pins_shadow_or_explicit_enforced_policy(tmp_path: Path, monkeypatch) -> None:
    init_project("shadow", title="Shadow", pipeline_type="persian-footage", pipeline_dir=tmp_path)
    shadow = json.loads((tmp_path / "shadow" / "project.json").read_text())
    assert shadow["delivery_gate_policy"] == {"version": "p4-delivery-v1", "mode": "shadow"}

    monkeypatch.setenv("OPENMONTAGE_PERSIAN_DELIVERY_GATE_MODE", "enforced")
    init_project("enforced", title="Enforced", pipeline_type="persian-footage", pipeline_dir=tmp_path)
    enforced = json.loads((tmp_path / "enforced" / "project.json").read_text())
    assert enforced["delivery_gate_policy"] == {"version": "p4-delivery-v1", "mode": "enforced"}


def test_legacy_marker_is_not_retroactively_enforced(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path / "run"
    project.mkdir()
    (project / "project.json").write_text(json.dumps({
        "version": "1.0", "project_id": "run", "title": "Legacy",
        "pipeline_type": "persian-footage",
    }))
    monkeypatch.setenv("OPENMONTAGE_PERSIAN_DELIVERY_GATE_MODE", "enforced")
    init_project("run", title="Legacy", pipeline_type="persian-footage", pipeline_dir=tmp_path)
    marker = json.loads((project / "project.json").read_text())
    assert "delivery_gate_policy" not in marker


def test_enforced_delivery_requires_quality_and_final_review(tmp_path: Path, monkeypatch) -> None:
    path, digest = _enforced_project(tmp_path, monkeypatch)
    with pytest.raises(CheckpointValidationError, match="requires quality_report"):
        _write_candidate(tmp_path, {"render_report": _render(path, digest)})


def test_enforced_delivery_rejects_open_evidence_gaps(tmp_path: Path, monkeypatch) -> None:
    path, digest = _enforced_project(tmp_path, monkeypatch)
    base = {
        "render_report": _render(path, digest),
        "final_review": _review(path, digest),
        "quality_report": _quality(path, digest),
    }
    for field in ("blockers", "stale_refs", "missing_checks"):
        artifacts = deepcopy(base)
        artifacts["quality_report"][field] = [f"open-{field}"]
        with pytest.raises(CheckpointValidationError, match="unresolved blockers"):
            _write_candidate(tmp_path, artifacts)


def test_enforced_delivery_rejects_stale_review_identity(tmp_path: Path, monkeypatch) -> None:
    path, digest = _enforced_project(tmp_path, monkeypatch)
    artifacts = {
        "render_report": _render(path, digest),
        "final_review": _review(path, "b" * 64),
        "quality_report": _quality(path, digest),
    }
    with pytest.raises(CheckpointValidationError, match="final_review is stale"):
        _write_candidate(tmp_path, artifacts)


def test_enforced_delivery_accepts_exact_green_evidence(tmp_path: Path, monkeypatch) -> None:
    path, digest = _enforced_project(tmp_path, monkeypatch)
    artifacts = {
        "render_report": _render(path, digest),
        "final_review": _review(path, digest),
        "quality_report": _quality(path, digest),
    }
    marker = json.loads((tmp_path / "run" / "project.json").read_text())
    _validate_persian_delivery_gate(
        tmp_path, "run", "compose", "awaiting_human", artifacts, marker
    )
    assert artifacts["quality_report"]["delivery_disposition"] == "deliver"
