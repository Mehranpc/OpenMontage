from __future__ import annotations

import json
from pathlib import Path

from lib import persian_asset_commands as commands
from lib import persian_video_workflow as workflow
from tests.lib.test_issue35_asset_candidate_workspace import _selected_candidate


def test_build_manifest_is_stable_sorted_utf8_and_idempotent(tmp_path: Path) -> None:
    project = tmp_path / "run"
    _selected_candidate(project)

    first = commands.build_manifest(tmp_path, "run")
    manifest_path = project / "artifacts" / "asset_manifest.json"
    report_path = project / "artifacts" / "asset_manifest.check.json"
    manifest_before = manifest_path.read_bytes()
    report_before = report_path.read_bytes()
    manifest_mtime = manifest_path.stat().st_mtime_ns
    report_mtime = report_path.stat().st_mtime_ns

    second = commands.build_manifest(tmp_path, "run")

    assert first["changed"] is True
    assert second["changed"] is False
    assert second["idempotent"] is True
    assert manifest_path.read_bytes() == manifest_before
    assert report_path.read_bytes() == report_before
    assert manifest_path.stat().st_mtime_ns == manifest_mtime
    assert report_path.stat().st_mtime_ns == report_mtime
    assert "این یک جمله نمونه است" in manifest_before.decode("utf-8")
    manifest = json.loads(manifest_before)
    assert manifest["assets"][0]["visual_event_id"] == "event-1"
    assert manifest["assets"][0]["scene_id"] == "beat-1"
    assert manifest["assets"][0]["source_tool"] == "direct_clip_search"
    assert json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8") + b"\n" == manifest_before


def test_build_manifest_applies_explicit_event_and_top_level_overrides(tmp_path: Path) -> None:
    project = tmp_path / "run"
    _selected_candidate(project)
    result = commands.build_manifest(
        tmp_path,
        "run",
        overrides={
            "assets": {
                "event-1": {
                    "fallback_level": "emotional_human",
                    "fallback_reason": "Literal results were exhausted.",
                }
            },
            "metadata": {"review_note": "یادداشت"},
        },
    )
    manifest = json.loads(Path(result["manifestPath"]).read_text(encoding="utf-8"))
    assert manifest["assets"][0]["fallback_level"] == "emotional_human"
    assert manifest["assets"][0]["fallback_reason"] == "Literal results were exhausted."
    assert manifest["metadata"]["review_note"] == "یادداشت"


def test_write_checkpoint_is_idempotent_for_same_manifest_and_metadata(
    tmp_path: Path, monkeypatch,
) -> None:
    project = tmp_path / "run"
    _selected_candidate(project)
    commands.build_manifest(tmp_path, "run")
    stored: dict = {}

    monkeypatch.setattr(commands, "read_checkpoint", lambda *_args, **_kwargs: stored or None)

    def fake_write(pipeline_dir, project_id, stage, status, artifacts, **kwargs):
        stored.update({
            "status": status,
            "artifacts": artifacts,
            "review": kwargs.get("review"),
            "metadata": kwargs.get("metadata"),
            "error": kwargs.get("error"),
        })
        return Path(pipeline_dir) / project_id / "checkpoint_assets.json"

    monkeypatch.setattr(commands, "write_checkpoint", fake_write)
    first = commands.write_assets_checkpoint(tmp_path, "run")
    second = commands.write_assets_checkpoint(tmp_path, "run")
    assert first["changed"] is True
    assert second["changed"] is False
    assert second["idempotent"] is True
    assert stored["status"] == "completed"
    assert stored["metadata"]["manifest_sha256"]


def test_write_checkpoint_records_tool_gap_without_manifest(
    tmp_path: Path, monkeypatch,
) -> None:
    (tmp_path / "run").mkdir()
    observed: dict = {}
    monkeypatch.setattr(commands, "read_checkpoint", lambda *_args, **_kwargs: None)

    def fake_write(_pipeline_dir, _project_id, _stage, status, artifacts, **kwargs):
        observed.update(status=status, artifacts=artifacts, kwargs=kwargs)
        return tmp_path / "run" / "checkpoint_assets.json"

    monkeypatch.setattr(commands, "write_checkpoint", fake_write)
    result = commands.write_assets_checkpoint(
        tmp_path, "run", tool_gap="provider lacks licence metadata"
    )
    assert result["status"] == "failed"
    assert observed["artifacts"] == {}
    assert observed["kwargs"]["metadata"]["tool_gap"] == "provider lacks licence metadata"
    assert observed["kwargs"]["error"] == "provider lacks licence metadata"


def test_front_door_exposes_nested_assets_commands() -> None:
    parser = workflow.build_parser()
    built = parser.parse_args([
        "assets", "build-manifest", "run", "--format", "vertical",
        "--overrides-json", "/tmp/overrides.json",
    ])
    assert built.command == "assets"
    assert built.assets_command == "build-manifest"
    checkpointed = parser.parse_args([
        "assets", "write-checkpoint", "run", "--tool-gap", "missing provider field",
    ])
    assert checkpointed.assets_command == "write-checkpoint"
    assert checkpointed.tool_gap == "missing provider field"
