from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from lib import persian_region_commands as commands
from lib import persian_video_workflow as workflow
from lib.persian_subject_region_review import (
    SubjectRegionReviewError,
    validate_subject_region_review_evidence,
)

PNG = b"\x89PNG\r\n\x1a\n"


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def _project(tmp_path: Path) -> Path:
    project = tmp_path / "run"
    assets = project / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    clip1 = assets / "one.mp4"
    clip2 = assets / "two.mp4"
    clip1.write_bytes(b"video-one")
    clip2.write_bytes(b"video-two")
    scene = {
        "version": "2.0",
        "beats": [
            {
                "id": "beat-1",
                "duration_seconds": 4.0,
                "typographic": False,
                "visual_events": [{"id": "event-1", "duration_seconds": 4.0}],
            },
            {"id": "beat-type", "duration_seconds": 2.0, "typographic": True},
            {
                "id": "beat-2",
                "duration_seconds": 3.0,
                "typographic": False,
                "visual_events": [{"id": "event-2", "duration_seconds": 3.0}],
            },
        ],
    }
    manifest = {
        "assets": [
            {
                "visual_event_id": "event-2",
                "beat_id": "beat-2",
                "path": str(clip2),
                "source_id": "src-2",
                "source_in_seconds": 2.0,
                "source_window_end_seconds": 2.2,
                "duration_seconds": 10.0,
                "width": 1080,
                "height": 1920,
            },
            {
                "visual_event_id": "event-1",
                "beat_id": "beat-1",
                "path": str(clip1),
                "source_id": "src-1",
                "source_in_seconds": 1.0,
                "source_window_end_seconds": 5.0,
                "duration_seconds": 10.0,
                "width": 1080,
                "height": 1920,
            },
        ]
    }
    _write_json(project / "artifacts" / "scene_plan.json", scene)
    _write_json(project / "artifacts" / "asset_manifest.json", manifest)
    return project


def _fake_ffmpeg(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    calls: list[list[str]] = []

    def fake_run(argv, **kwargs):
        args = [str(item) for item in argv]
        calls.append(args)
        output = Path(args[-1])
        output.parent.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256("\0".join(args[:-1]).encode("utf-8"))
        for index, arg in enumerate(args[:-1]):
            if index > 0 and args[index - 1] == "-i":
                source = Path(arg)
                if source.is_file():
                    digest.update(source.read_bytes())
        output.write_bytes(PNG + digest.digest())
        return subprocess.CompletedProcess(args, 0, stdout=b"", stderr=b"")

    monkeypatch.setattr(commands.subprocess, "run", fake_run)
    return calls


def _annotations() -> dict:
    return {
        "shots": [
            {
                "shot_id": "shot-1",
                "observed": "سوژه در سه قاب بررسی شد.",
                "frames": [
                    {
                        "position": "start",
                        "priority": "hard",
                        "grid": {"x1": 1, "y1": 2, "x2": 7, "y2": 8},
                    },
                    {
                        "position": "middle",
                        "priority": "hard",
                        "grid": {"x1": 2, "y1": 2, "x2": 8, "y2": 8},
                    },
                    {"position": "end", "clear": True},
                ],
            },
            {
                "shot_id": "shot-2",
                "observed": "قاب کوتاه با سوژه ثابت بررسی شد.",
                "frames": [
                    {
                        "position": "start",
                        "priority": "hard",
                        "grid": {"x1": 0, "y1": 1, "x2": 5, "y2": 9},
                    },
                    {
                        "position": "middle",
                        "regions": [
                            {
                                "priority": "hard",
                                "grid": {"x1": 0, "y1": 1, "x2": 5, "y2": 9},
                            },
                            {
                                "priority": "soft",
                                "grid": {"x1": 6, "y1": 2, "x2": 10, "y2": 8},
                            },
                        ],
                    },
                    {
                        "position": "end",
                        "priority": "hard",
                        "grid": {"x1": 0, "y1": 1, "x2": 5, "y2": 9},
                    },
                ],
            },
        ]
    }


def test_build_sheets_uses_scene_order_absolute_timeline_and_exact_grid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _project(tmp_path)
    calls = _fake_ffmpeg(monkeypatch)

    result = commands.build_sheets(tmp_path, "run")
    index = json.loads(Path(result["indexPath"]).read_text(encoding="utf-8"))

    assert [row["visualEventId"] for row in index["shots"]] == ["event-1", "event-2"]
    assert [row["shotId"] for row in index["shots"]] == ["shot-1", "shot-2"]
    assert index["shots"][0]["timeline"] == {"startSeconds": 0.0, "endSeconds": 4.0}
    assert index["shots"][1]["timeline"] == {"startSeconds": 6.0, "endSeconds": 9.0}
    assert [row["sourceSeconds"] for row in index["shots"][0]["frames"]] == [1.3, 3.0, 4.7]
    assert [row["sourceSeconds"] for row in index["shots"][1]["frames"]] == [2.05, 2.1, 2.15]
    assert index["grid"] == {"columns": 10, "rows": 10}
    assert any("drawgrid=w=iw/10:h=ih/10" in " ".join(call) for call in calls)
    assert len(calls) == 9


def test_build_sheets_is_idempotent_and_cache_hit_runs_no_ffmpeg(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(tmp_path)
    calls = _fake_ffmpeg(monkeypatch)
    first = commands.build_sheets(tmp_path, "run")
    outputs = [Path(first["indexPath"])] + list((project / "artifacts" / "subject-region-sheets").glob("*.png"))
    mtimes = {path: path.stat().st_mtime_ns for path in outputs}
    before = len(calls)

    second = commands.build_sheets(tmp_path, "run")

    assert second["changed"] is False
    assert second["idempotent"] is True
    assert second["rebuiltOutputs"] == []
    assert len(calls) == before
    assert {path: path.stat().st_mtime_ns for path in outputs} == mtimes

def test_build_sheets_rebuilds_only_changed_shot_and_dependent_group(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(tmp_path)
    calls = _fake_ffmpeg(monkeypatch)
    commands.build_sheets(tmp_path, "run")
    output_root = project / "artifacts" / "subject-region-sheets"
    shot1_outputs = sorted(output_root.glob("shot-001-*.png"))
    shot1_mtimes = {path: path.stat().st_mtime_ns for path in shot1_outputs}
    before_calls = len(calls)

    manifest_path = project / "artifacts" / "asset_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    event2 = next(row for row in manifest["assets"] if row["visual_event_id"] == "event-2")
    event2["source_id"] = "src-2-replacement"
    event2["source_in_seconds"] = 3.0
    event2["source_window_end_seconds"] = 3.2
    _write_json(manifest_path, manifest)

    rebuilt = commands.build_sheets(tmp_path, "run")

    assert len(calls) == before_calls + 5
    assert rebuilt["rebuiltOutputs"] == [
        "artifacts/subject-region-sheets/shot-002-start.png",
        "artifacts/subject-region-sheets/shot-002-middle.png",
        "artifacts/subject-region-sheets/shot-002-end.png",
        "artifacts/subject-region-sheets/shot-002-sheet.png",
        "artifacts/subject-region-sheets/group-001-grid.png",
    ]
    assert {path: path.stat().st_mtime_ns for path in shot1_outputs} == shot1_mtimes


def test_build_sheets_repairs_only_corrupt_cached_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(tmp_path)
    calls = _fake_ffmpeg(monkeypatch)
    commands.build_sheets(tmp_path, "run")
    before = len(calls)
    corrupt = project / "artifacts" / "subject-region-sheets" / "shot-001-start.png"
    corrupt.write_bytes(b"corrupt")

    repaired = commands.build_sheets(tmp_path, "run")

    assert len(calls) == before + 1
    assert repaired["rebuiltOutputs"] == ["artifacts/subject-region-sheets/shot-001-start.png"]
    assert corrupt.read_bytes().startswith(PNG)


def test_build_sheets_rejects_path_escape_and_symlink_escape(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(tmp_path)
    _fake_ffmpeg(monkeypatch)
    manifest_path = project / "artifacts" / "asset_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["assets"][0]["path"] = "../outside.mp4"
    _write_json(manifest_path, manifest)
    with pytest.raises(commands.PersianRegionCommandError, match="inside the project"):
        commands.build_sheets(tmp_path, "run")

    project = _project(tmp_path)
    outside = tmp_path / "outside.mp4"
    outside.write_bytes(b"outside")
    escape = project / "assets" / "escape.mp4"
    escape.symlink_to(outside)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["assets"][0]["path"] = str(escape)
    _write_json(manifest_path, manifest)
    with pytest.raises(commands.PersianRegionCommandError, match="inside the project"):
        commands.build_sheets(tmp_path, "run")


def test_build_sheets_rejects_manifest_scene_mismatch_and_ffmpeg_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(tmp_path)
    manifest_path = project / "artifacts" / "asset_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["assets"][0]["visual_event_id"] = "wrong-event"
    _write_json(manifest_path, manifest)
    with pytest.raises(commands.PersianRegionCommandError, match="event-2"):
        commands.build_sheets(tmp_path, "run")

    project = _project(tmp_path)

    def fail(argv, **kwargs):
        raise subprocess.CalledProcessError(1, argv, stderr=b"decode failed")

    monkeypatch.setattr(commands.subprocess, "run", fail)
    with pytest.raises(commands.PersianRegionCommandError, match="ffmpeg"):
        commands.build_sheets(tmp_path, "run")


def test_build_sheets_maps_missing_ffmpeg_to_command_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _project(tmp_path)

    def missing(_argv, **_kwargs):
        raise FileNotFoundError("ffmpeg not found")

    monkeypatch.setattr(commands.subprocess, "run", missing)
    with pytest.raises(commands.PersianRegionCommandError, match="ffmpeg could not run"):
        commands.build_sheets(tmp_path, "run")


def test_propose_converts_grid_to_normalized_regions_and_remains_nonfinal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(tmp_path)
    _fake_ffmpeg(monkeypatch)
    commands.build_sheets(tmp_path, "run")

    result = commands.propose_regions(tmp_path, "run", _annotations())
    proposal_path = Path(result["proposalPath"])
    proposal = json.loads(proposal_path.read_text(encoding="utf-8"))

    assert proposal["status"] == "proposed"
    assert proposal["confirmationRequired"] is True
    assert "shot_regions" not in proposal
    evidence = proposal["proposedEvidence"]
    first = evidence["shot_regions"][0]
    assert first["avoidRegions"][0] == {
        "x": 0.1,
        "y": 0.2,
        "w": 0.6,
        "h": 0.6,
        "priority": "hard",
        "startSeconds": 0.0,
        "endSeconds": 1.15,
    }
    second = evidence["shot_regions"][1]
    hard = [r for r in second["avoidRegions"] if r["priority"] == "hard"]
    assert hard == [{
        "x": 0.0,
        "y": 0.1,
        "w": 0.5,
        "h": 0.8,
        "priority": "hard",
        "startSeconds": 6.0,
        "endSeconds": 9.0,
    }]
    with pytest.raises(SubjectRegionReviewError, match="shot_regions"):
        validate_subject_region_review_evidence(proposal, expected_shot_ids=["shot-1", "shot-2"])
    normalized = validate_subject_region_review_evidence(
        evidence, expected_shot_ids=["shot-1", "shot-2"]
    )
    assert len(normalized["shot_regions"]) == 2
    raw = proposal_path.read_bytes()
    assert "سوژه در سه قاب بررسی شد." in raw.decode("utf-8")
    assert json.dumps(proposal, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8") + b"\n" == raw


def test_propose_is_idempotent_and_requires_complete_valid_annotations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _project(tmp_path)
    _fake_ffmpeg(monkeypatch)
    commands.build_sheets(tmp_path, "run")
    first = commands.propose_regions(tmp_path, "run", _annotations())
    path = Path(first["proposalPath"])
    mtime = path.stat().st_mtime_ns
    second = commands.propose_regions(tmp_path, "run", _annotations())
    assert second["changed"] is False
    assert second["idempotent"] is True
    assert path.stat().st_mtime_ns == mtime

    missing = _annotations()
    missing["shots"] = missing["shots"][:1]
    with pytest.raises(commands.PersianRegionCommandError, match="missing annotated shot ids"):
        commands.propose_regions(tmp_path, "run", missing)

    invalid = _annotations()
    invalid["shots"][0]["frames"][0]["priority"] = "medium"
    with pytest.raises(commands.PersianRegionCommandError, match="priority"):
        commands.propose_regions(tmp_path, "run", invalid)


def test_propose_rejects_stale_sheet_index(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = _project(tmp_path)
    _fake_ffmpeg(monkeypatch)
    commands.build_sheets(tmp_path, "run")
    scene_path = project / "artifacts" / "scene_plan.json"
    scene = json.loads(scene_path.read_text(encoding="utf-8"))
    scene["subject"] = "changed"
    _write_json(scene_path, scene)
    with pytest.raises(commands.PersianRegionCommandError, match="stale"):
        commands.propose_regions(tmp_path, "run", _annotations())


def test_propose_rejects_tampered_index_and_corrupt_review_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(tmp_path)
    _fake_ffmpeg(monkeypatch)
    commands.build_sheets(tmp_path, "run")
    index_path = project / "artifacts" / "subject-region-sheets" / "index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    index["shots"][0]["frames"][0]["timelineEndSeconds"] = 99.0
    _write_json(index_path, index)

    with pytest.raises(commands.PersianRegionCommandError, match="index is corrupt or incompatible"):
        commands.propose_regions(tmp_path, "run", _annotations())

    commands.build_sheets(tmp_path, "run")
    frame_path = project / "artifacts" / "subject-region-sheets" / "shot-001-start.png"
    frame_path.write_bytes(b"corrupt")
    with pytest.raises(commands.PersianRegionCommandError, match="review output is missing or corrupt"):
        commands.propose_regions(tmp_path, "run", _annotations())


def test_front_door_exposes_regions_commands_and_returns_exit_2_on_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    parser = workflow.build_parser()
    built = parser.parse_args(["regions", "build-sheets", "run"])
    assert built.command == "regions"
    assert built.regions_command == "build-sheets"
    proposed = parser.parse_args(["regions", "propose", "run", "--json", "/tmp/regions.json"])
    assert proposed.regions_command == "propose"
    assert proposed.json == "/tmp/regions.json"

    monkeypatch.setattr(workflow, "PROJECTS_DIR", tmp_path)
    with pytest.raises(SystemExit) as exc:
        workflow.main(["regions", "build-sheets", "missing"])
    assert exc.value.code == 2


def test_music_only_manifest_change_preserves_subject_region_png_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(tmp_path)
    calls = _fake_ffmpeg(monkeypatch)
    first = commands.build_sheets(tmp_path, "run")
    pngs = sorted((project / "artifacts" / "subject-region-sheets").glob("*.png"))
    mtimes = {path: path.stat().st_mtime_ns for path in pngs}
    before_calls = len(calls)

    manifest_path = project / "artifacts" / "asset_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["musicTrack"] = {
        "path": "assets/music/bed.mp3",
        "provider": "pixabay",
        "license": {"name": "Pixabay Content License"},
    }
    _write_json(manifest_path, manifest)

    second = commands.build_sheets(tmp_path, "run")

    assert second["fingerprint"] == first["fingerprint"]
    assert second["rebuiltOutputs"] == []
    assert len(calls) == before_calls
    assert {path: path.stat().st_mtime_ns for path in pngs} == mtimes
