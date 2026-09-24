"""Deterministic subject-region sheet and proposal tooling for Persian production."""
from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any
from uuid import uuid4

from lib.persian_assets import scene_asset_requirements
from lib.persian_dependency_cache import (
    asset_visual_dependency_digest, scene_geometry_dependency_digest,
)
from lib.persian_subject_region_review import (
    SubjectRegionReviewError,
    validate_subject_region_review_evidence,
)


REGION_COMMAND_VERSION = "1.1"
GRID_COLUMNS = 10
GRID_ROWS = 10
FRAME_POSITIONS = ("start", "middle", "end")
FRAME_EDGE_SECONDS = 0.30
FRAME_SCALE_WIDTH = 540
FRAME_FILTER = (
    f"scale={FRAME_SCALE_WIDTH}:-2,"
    "drawgrid=w=iw/10:h=ih/10:t=2:c=red@0.7"
)
SHEET_DIR = Path("artifacts") / "subject-region-sheets"
INDEX_NAME = "index.json"
PROPOSAL_NAME = "proposal.json"
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


class PersianRegionCommandError(ValueError):
    """Raised when deterministic region tooling cannot complete safely."""


def _stable_text(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _digest(value: object) -> str:
    return hashlib.sha256(_stable_text(value).encode("utf-8")).hexdigest()


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PersianRegionCommandError(f"could not read {label}: {path}") from exc
    if not isinstance(value, dict):
        raise PersianRegionCommandError(f"{label} must be a JSON object: {path}")
    return value


def _read_optional_object(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _atomic_stable_json(path: Path, value: Mapping[str, Any]) -> bool:
    rendered = _stable_text(dict(value))
    if path.is_file():
        try:
            if path.read_text(encoding="utf-8") == rendered:
                return False
        except OSError:
            pass
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(rendered, encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return True


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _project_dir(pipeline_dir: Path, project_id: str) -> Path:
    root = Path(pipeline_dir).expanduser().resolve()
    project = (root / str(project_id)).resolve()
    if not _is_within(project, root) or not project.is_dir():
        raise PersianRegionCommandError(f"project does not exist: {project}")
    return project


def _number(value: object, *, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PersianRegionCommandError(f"{label} must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise PersianRegionCommandError(f"{label} must be a finite number")
    return result


def _positive_duration(value: object, *, label: str) -> float:
    result = _number(value, label=label)
    if result <= 0:
        raise PersianRegionCommandError(f"{label} must be > 0")
    return result


def _scene_beats(scene_plan: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    beats = scene_plan.get("beats")
    if beats is None:
        metadata = scene_plan.get("metadata")
        beats = metadata.get("beats") if isinstance(metadata, Mapping) else None
    if not isinstance(beats, list) or not beats:
        raise PersianRegionCommandError("scene plan requires non-empty beats")
    if not all(isinstance(beat, Mapping) for beat in beats):
        raise PersianRegionCommandError("scene plan beats must be objects")
    return list(beats)


def _timeline_units(scene_plan: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Return footage units in canonical scene order with absolute timeline intervals."""
    units: list[dict[str, Any]] = []
    cursor = 0.0
    for beat_index, beat in enumerate(_scene_beats(scene_plan)):
        beat_id = str(beat.get("id") or "").strip()
        if not beat_id:
            raise PersianRegionCommandError(f"scene beat[{beat_index}] requires an id")
        beat_duration = _positive_duration(
            beat.get("duration_seconds"), label=f"scene beat {beat_id} duration_seconds"
        )
        if beat.get("typographic"):
            cursor += beat_duration
            continue
        events = beat.get("visual_events")
        if isinstance(events, list) and events:
            event_cursor = cursor
            total = 0.0
            for event_index, event in enumerate(events):
                if not isinstance(event, Mapping):
                    raise PersianRegionCommandError(
                        f"scene beat {beat_id} visual_event[{event_index}] must be an object"
                    )
                event_id = str(event.get("id") or "").strip()
                if not event_id:
                    raise PersianRegionCommandError(
                        f"scene beat {beat_id} visual_event[{event_index}] requires an id"
                    )
                duration = _positive_duration(
                    event.get("duration_seconds"),
                    label=f"visual event {event_id} duration_seconds",
                )
                units.append({
                    "beatId": beat_id,
                    "visualEventId": event_id,
                    "durationSeconds": round(duration, 6),
                    "timelineStartSeconds": round(event_cursor, 6),
                    "timelineEndSeconds": round(event_cursor + duration, 6),
                })
                event_cursor += duration
                total += duration
            if abs(total - beat_duration) > 0.05:
                raise PersianRegionCommandError(
                    f"scene beat {beat_id} visual event durations do not match beat duration"
                )
        else:
            units.append({
                "beatId": beat_id,
                "visualEventId": None,
                "durationSeconds": round(beat_duration, 6),
                "timelineStartSeconds": round(cursor, 6),
                "timelineEndSeconds": round(cursor + beat_duration, 6),
            })
        cursor += beat_duration

    canonical = scene_asset_requirements(dict(scene_plan))[0]
    canonical_keys = [
        (str(row.get("beat_id") or ""), str(row.get("visual_event_id") or ""))
        for row in canonical
    ]
    timeline_keys = [
        (str(row["beatId"]), str(row.get("visualEventId") or "")) for row in units
    ]
    if canonical_keys != timeline_keys:
        raise PersianRegionCommandError(
            "scene-plan footage order disagrees with canonical asset requirements"
        )
    return units


def _asset_path(project: Path, raw_path: object, *, label: str) -> Path:
    value = str(raw_path or "").strip()
    if not value:
        raise PersianRegionCommandError(f"{label} path is missing")
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        candidate = project / candidate
    resolved = candidate.resolve()
    if not _is_within(resolved, project):
        raise PersianRegionCommandError(f"{label} path must stay inside the project")
    if not resolved.is_file():
        raise PersianRegionCommandError(f"{label} video is missing: {resolved}")
    return resolved


def _frame_times(start: float, end: float) -> list[float]:
    window = end - start
    if window <= 0:
        raise PersianRegionCommandError("source window must satisfy start < end")
    edge = min(FRAME_EDGE_SECONDS, window / 4.0)
    return [
        round(start + edge, 6),
        round((start + end) / 2.0, 6),
        round(end - edge, 6),
    ]


def _frame_intervals(
    frame_times: Sequence[float],
    *,
    source_start: float,
    source_end: float,
    timeline_start: float,
    timeline_end: float,
) -> list[tuple[float, float]]:
    window = source_end - source_start
    duration = timeline_end - timeline_start
    ratios = [(value - source_start) / window for value in frame_times]
    boundaries = [0.0, (ratios[0] + ratios[1]) / 2.0, (ratios[1] + ratios[2]) / 2.0, 1.0]
    return [
        (
            round(timeline_start + duration * boundaries[index], 6),
            round(timeline_start + duration * boundaries[index + 1], 6),
        )
        for index in range(3)
    ]


def _relative(path: Path, project: Path) -> str:
    return path.relative_to(project).as_posix()


def _valid_png(path: Path) -> bool:
    try:
        if not path.is_file() or path.stat().st_size <= len(_PNG_SIGNATURE):
            return False
        with path.open("rb") as handle:
            return handle.read(len(_PNG_SIGNATURE)) == _PNG_SIGNATURE
    except OSError:
        return False


def _cached_png_ok(path: Path, expected_sha256: str | None) -> bool:
    return bool(expected_sha256) and _valid_png(path) and _hash_file(path) == expected_sha256


def _render_png(destination: Path, args: Sequence[str], *, ffmpeg_bin: str) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.stem}.{uuid4().hex}.tmp.png")
    command = [ffmpeg_bin, "-v", "error", "-y", *[str(item) for item in args], str(temporary)]
    try:
        subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if not _valid_png(temporary):
            raise PersianRegionCommandError(
                f"ffmpeg did not produce a valid PNG for {destination.name}"
            )
        os.replace(temporary, destination)
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.decode("utf-8", errors="replace").strip() if isinstance(exc.stderr, bytes) else str(exc.stderr or "").strip()
        detail = f": {stderr}" if stderr else ""
        raise PersianRegionCommandError(
            f"ffmpeg failed while building {destination.name}{detail}"
        ) from exc
    except OSError as exc:
        raise PersianRegionCommandError(
            f"ffmpeg could not run while building {destination.name}: {exc}"
        ) from exc
    finally:
        temporary.unlink(missing_ok=True)


def _copy_png_atomic(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.stem}.{uuid4().hex}.tmp.png")
    try:
        shutil.copyfile(source, temporary)
        if not _valid_png(temporary):
            raise PersianRegionCommandError(f"could not build valid PNG {destination.name}")
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def _existing_output_digests(index: Mapping[str, Any] | None) -> dict[str, str]:
    result: dict[str, str] = {}
    if not isinstance(index, Mapping):
        return result
    shots = index.get("shots")
    if isinstance(shots, list):
        for shot in shots:
            if not isinstance(shot, Mapping):
                continue
            frames = shot.get("frames")
            if isinstance(frames, list):
                for frame in frames:
                    if isinstance(frame, Mapping):
                        path = str(frame.get("path") or "")
                        digest = str(frame.get("sha256") or "")
                        if path and digest:
                            result[path] = digest
            sheet = shot.get("sheet")
            if isinstance(sheet, Mapping):
                path = str(sheet.get("path") or "")
                digest = str(sheet.get("sha256") or "")
                if path and digest:
                    result[path] = digest
    groups = index.get("groups")
    if isinstance(groups, list):
        for group in groups:
            if isinstance(group, Mapping):
                path = str(group.get("path") or "")
                digest = str(group.get("sha256") or "")
                if path and digest:
                    result[path] = digest
    return result


def _records_by_id(index: Mapping[str, Any] | None, key: str, id_key: str) -> dict[str, Mapping[str, Any]]:
    if not isinstance(index, Mapping):
        return {}
    values = index.get(key)
    if not isinstance(values, list):
        return {}
    result: dict[str, Mapping[str, Any]] = {}
    for value in values:
        if not isinstance(value, Mapping):
            continue
        record_id = str(value.get(id_key) or "")
        if record_id:
            result[record_id] = value
    return result


def _shot_cache_identity_from_plan(shot: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "shotId": shot["shotId"],
        "beatId": shot["beatId"],
        "visualEventId": shot["visualEventId"],
        "sourceId": shot["sourceId"],
        "sourcePath": shot["sourcePath"],
        "sourceWindow": shot["sourceWindow"],
        "sourceDurationSeconds": shot["sourceDurationSeconds"],
        "frameSize": {"width": shot["width"], "height": shot["height"]},
        "timeline": shot["timeline"],
        "frames": [
            {
                "position": position,
                "sourceSeconds": shot["frameTimes"][index],
                "timelineStartSeconds": shot["frameIntervals"][index][0],
                "timelineEndSeconds": shot["frameIntervals"][index][1],
            }
            for index, position in enumerate(FRAME_POSITIONS)
        ],
    }


def _shot_cache_identity_from_record(shot: Mapping[str, Any]) -> dict[str, Any]:
    frames = shot.get("frames")
    normalized_frames: list[dict[str, Any]] = []
    if isinstance(frames, list):
        for frame in frames:
            if not isinstance(frame, Mapping):
                continue
            normalized_frames.append({
                "position": frame.get("position"),
                "sourceSeconds": frame.get("sourceSeconds"),
                "timelineStartSeconds": frame.get("timelineStartSeconds"),
                "timelineEndSeconds": frame.get("timelineEndSeconds"),
            })
    return {
        "shotId": shot.get("shotId"),
        "beatId": shot.get("beatId"),
        "visualEventId": shot.get("visualEventId"),
        "sourceId": shot.get("sourceId"),
        "sourcePath": shot.get("sourcePath"),
        "sourceWindow": shot.get("sourceWindow"),
        "sourceDurationSeconds": shot.get("sourceDurationSeconds"),
        "frameSize": shot.get("frameSize"),
        "timeline": shot.get("timeline"),
        "frames": normalized_frames,
    }


def _shot_cache_matches(existing: Mapping[str, Any] | None, shot: Mapping[str, Any]) -> bool:
    return bool(
        isinstance(existing, Mapping)
        and _shot_cache_identity_from_record(existing) == _shot_cache_identity_from_plan(shot)
    )


def _record_output_digests(record: Mapping[str, Any] | None) -> dict[str, str]:
    if not isinstance(record, Mapping):
        return {}
    result: dict[str, str] = {}
    frames = record.get("frames")
    if isinstance(frames, list):
        for frame in frames:
            if isinstance(frame, Mapping):
                path = str(frame.get("path") or "")
                digest = str(frame.get("sha256") or "")
                if path and digest:
                    result[path] = digest
    sheet = record.get("sheet")
    if isinstance(sheet, Mapping):
        path = str(sheet.get("path") or "")
        digest = str(sheet.get("sha256") or "")
        if path and digest:
            result[path] = digest
    return result


def _recipe_cache_compatible(index: Mapping[str, Any] | None, recipe: Mapping[str, Any]) -> bool:
    return bool(
        isinstance(index, Mapping)
        and index.get("version") == "1.0"
        and index.get("commandVersion") == REGION_COMMAND_VERSION
        and index.get("grid") == {"columns": GRID_COLUMNS, "rows": GRID_ROWS}
        and index.get("recipe") == recipe
    )


def _group_cache_digest(
    existing_group: Mapping[str, Any] | None,
    members: Sequence[Mapping[str, Any]],
    existing_shots: Mapping[str, Mapping[str, Any]],
) -> str | None:
    if not isinstance(existing_group, Mapping):
        return None
    shot_ids = [str(member.get("shotId") or "") for member in members]
    if existing_group.get("shotIds") != shot_ids:
        return None
    for member in members:
        shot_id = str(member.get("shotId") or "")
        previous = existing_shots.get(shot_id)
        if not isinstance(previous, Mapping):
            return None
        current_sheet = member.get("sheet")
        previous_sheet = previous.get("sheet")
        if not isinstance(current_sheet, Mapping) or not isinstance(previous_sheet, Mapping):
            return None
        if current_sheet.get("sha256") != previous_sheet.get("sha256"):
            return None
    digest = str(existing_group.get("sha256") or "")
    return digest or None


def _build_recipe() -> dict[str, Any]:
    return {
        "commandVersion": REGION_COMMAND_VERSION,
        "framePositions": list(FRAME_POSITIONS),
        "edgeSeconds": FRAME_EDGE_SECONDS,
        "scaleWidth": FRAME_SCALE_WIDTH,
        "frameFilter": FRAME_FILTER,
        "shotSheetFilter": "[0][1][2]hstack=inputs=3[out]",
        "groupFilter": "[0][1]vstack=inputs=2[out]",
        "groupSize": 2,
    }


def _index_fingerprint(
    input_record: Mapping[str, Any], shots: Sequence[Mapping[str, Any]]
) -> str:
    dependency_inputs = {
        key: input_record.get(key)
        for key in (
            "assetManifestPath", "assetVisualDependencySha256",
            "scenePlanPath", "sceneGeometryDependencySha256",
        )
    }
    return _digest({
        "inputs": dependency_inputs,
        "recipe": _build_recipe(),
        "shots": [
            {
                "beatId": shot["beatId"],
                "visualEventId": shot["visualEventId"],
                "sourcePath": shot["sourcePath"],
                "sourceWindow": shot["sourceWindow"],
                "timeline": shot["timeline"],
            }
            for shot in shots
        ],
    })


def _same_float(left: object, right: object) -> bool:
    try:
        return abs(float(left) - float(right)) <= 1e-6
    except (TypeError, ValueError):
        return False


def _build_shot_plan(project: Path, manifest: Mapping[str, Any], scene_plan: Mapping[str, Any]) -> list[dict[str, Any]]:
    assets = manifest.get("assets")
    if not isinstance(assets, list) or not assets:
        raise PersianRegionCommandError("asset manifest requires non-empty assets")
    rows = [row for row in assets if isinstance(row, Mapping)]
    by_event: dict[str, list[Mapping[str, Any]]] = {}
    by_beat: dict[str, list[Mapping[str, Any]]] = {}
    for row in rows:
        event_id = str(row.get("visual_event_id") or "").strip()
        beat_id = str(row.get("beat_id") or row.get("scene_id") or "").strip()
        if event_id:
            by_event.setdefault(event_id, []).append(row)
        if beat_id:
            by_beat.setdefault(beat_id, []).append(row)

    plan: list[dict[str, Any]] = []
    for index, unit in enumerate(_timeline_units(scene_plan), 1):
        event_id = str(unit.get("visualEventId") or "")
        beat_id = str(unit["beatId"])
        matches = by_event.get(event_id, []) if event_id else by_beat.get(beat_id, [])
        label = event_id or beat_id
        if len(matches) != 1:
            raise PersianRegionCommandError(
                f"{label}: expected exactly one canonical asset, got {len(matches)}"
            )
        row = matches[0]
        source_start = _number(
            row.get("source_in_seconds"), label=f"{label} source_in_seconds"
        )
        source_end = _number(
            row.get("source_window_end_seconds"),
            label=f"{label} source_window_end_seconds",
        )
        source_duration = _positive_duration(
            row.get("duration_seconds"), label=f"{label} duration_seconds"
        )
        if source_start < 0 or source_end <= source_start or source_end > source_duration + 1e-6:
            raise PersianRegionCommandError(
                f"{label}: selected source window must satisfy 0 <= start < end <= duration"
            )
        source = _asset_path(project, row.get("path"), label=label)
        frame_times = _frame_times(source_start, source_end)
        intervals = _frame_intervals(
            frame_times,
            source_start=source_start,
            source_end=source_end,
            timeline_start=float(unit["timelineStartSeconds"]),
            timeline_end=float(unit["timelineEndSeconds"]),
        )
        plan.append({
            "ordinal": index,
            "shotId": f"shot-{index}",
            "fileStem": f"shot-{index:03d}",
            "beatId": beat_id,
            "visualEventId": event_id or None,
            "sourceId": str(row.get("source_id") or ""),
            "source": source,
            "sourcePath": _relative(source, project),
            "sourceWindow": [round(source_start, 6), round(source_end, 6)],
            "sourceDurationSeconds": round(source_duration, 6),
            "frameTimes": frame_times,
            "frameIntervals": intervals,
            "timeline": {
                "startSeconds": round(float(unit["timelineStartSeconds"]), 6),
                "endSeconds": round(float(unit["timelineEndSeconds"]), 6),
            },
            "width": int(row.get("width") or 0),
            "height": int(row.get("height") or 0),
        })
    if len(plan) != len(rows):
        expected = {
            str(row.get("visualEventId") or row.get("beatId") or "") for row in plan
        }
        extra = sorted(
            str(row.get("visual_event_id") or row.get("beat_id") or row.get("scene_id") or "")
            for row in rows
            if str(row.get("visual_event_id") or row.get("beat_id") or row.get("scene_id") or "") not in expected
        )
        raise PersianRegionCommandError(
            "asset manifest contains entries not present in the scene plan"
            + (f": {', '.join(extra)}" if extra else "")
        )
    return plan


def build_sheets(
    pipeline_dir: Path,
    project_id: str,
    *,
    ffmpeg_bin: str = "ffmpeg",
) -> dict[str, Any]:
    """Build cached 10x10 start/middle/end subject-region review sheets."""
    project = _project_dir(Path(pipeline_dir), project_id)
    manifest_path = project / "artifacts" / "asset_manifest.json"
    scene_path = project / "artifacts" / "scene_plan.json"
    manifest = _read_object(manifest_path, label="asset manifest")
    scene_plan = _read_object(scene_path, label="scene plan")
    shots = _build_shot_plan(project, manifest, scene_plan)

    input_record = {
        "assetManifestPath": _relative(manifest_path, project),
        "assetManifestSha256": _hash_file(manifest_path),
        "assetVisualDependencySha256": asset_visual_dependency_digest(manifest),
        "scenePlanPath": _relative(scene_path, project),
        "scenePlanSha256": _hash_file(scene_path),
        "sceneGeometryDependencySha256": scene_geometry_dependency_digest(scene_plan),
    }
    recipe = _build_recipe()
    fingerprint = _index_fingerprint(input_record, shots)

    output_root = project / SHEET_DIR
    index_path = output_root / INDEX_NAME
    existing = _read_optional_object(index_path)
    cache_same = bool(existing and existing.get("fingerprint") == fingerprint)
    expected_digests = _existing_output_digests(existing) if cache_same else {}
    recipe_cache_compatible = _recipe_cache_compatible(existing, recipe)
    existing_shots = _records_by_id(existing, "shots", "shotId")
    existing_groups = _records_by_id(existing, "groups", "groupId")
    rebuilt: list[str] = []
    shot_records: list[dict[str, Any]] = []

    for shot in shots:
        previous_shot = existing_shots.get(str(shot["shotId"]))
        shot_expected = expected_digests if cache_same else (
            _record_output_digests(previous_shot)
            if recipe_cache_compatible and _shot_cache_matches(previous_shot, shot)
            else {}
        )
        frame_records: list[dict[str, Any]] = []
        frame_paths: list[Path] = []
        for frame_index, position in enumerate(FRAME_POSITIONS):
            destination = output_root / f"{shot['fileStem']}-{position}.png"
            relative = _relative(destination, project)
            if not _cached_png_ok(destination, shot_expected.get(relative)):
                _render_png(
                    destination,
                    [
                        "-ss", f"{shot['frameTimes'][frame_index]:.6f}",
                        "-i", str(shot["source"]),
                        "-frames:v", "1",
                        "-vf", FRAME_FILTER,
                    ],
                    ffmpeg_bin=ffmpeg_bin,
                )
                rebuilt.append(relative)
            frame_paths.append(destination)
            interval = shot["frameIntervals"][frame_index]
            frame_records.append({
                "position": position,
                "sourceSeconds": shot["frameTimes"][frame_index],
                "timelineStartSeconds": interval[0],
                "timelineEndSeconds": interval[1],
                "path": relative,
                "sha256": _hash_file(destination),
            })

        sheet_path = output_root / f"{shot['fileStem']}-sheet.png"
        sheet_relative = _relative(sheet_path, project)
        if not _cached_png_ok(sheet_path, shot_expected.get(sheet_relative)):
            _render_png(
                sheet_path,
                [
                    "-i", str(frame_paths[0]),
                    "-i", str(frame_paths[1]),
                    "-i", str(frame_paths[2]),
                    "-filter_complex", "[0][1][2]hstack=inputs=3[out]",
                    "-map", "[out]",
                ],
                ffmpeg_bin=ffmpeg_bin,
            )
            rebuilt.append(sheet_relative)
        shot_records.append({
            "shotId": shot["shotId"],
            "beatId": shot["beatId"],
            "visualEventId": shot["visualEventId"],
            "sourceId": shot["sourceId"],
            "sourcePath": shot["sourcePath"],
            "sourceWindow": shot["sourceWindow"],
            "sourceDurationSeconds": shot["sourceDurationSeconds"],
            "frameSize": {"width": shot["width"], "height": shot["height"]},
            "timeline": shot["timeline"],
            "frames": frame_records,
            "sheet": {"path": sheet_relative, "sha256": _hash_file(sheet_path)},
        })

    groups: list[dict[str, Any]] = []
    for group_index in range(0, len(shot_records), 2):
        members = shot_records[group_index:group_index + 2]
        group_path = output_root / f"group-{group_index // 2 + 1:03d}-grid.png"
        group_relative = _relative(group_path, project)
        group_id = f"group-{group_index // 2 + 1}"
        group_expected = expected_digests.get(group_relative) if cache_same else None
        if group_expected is None and recipe_cache_compatible:
            group_expected = _group_cache_digest(
                existing_groups.get(group_id), members, existing_shots
            )
        if not _cached_png_ok(group_path, group_expected):
            first = project / members[0]["sheet"]["path"]
            if len(members) == 2:
                second = project / members[1]["sheet"]["path"]
                _render_png(
                    group_path,
                    [
                        "-i", str(first),
                        "-i", str(second),
                        "-filter_complex", "[0][1]vstack=inputs=2[out]",
                        "-map", "[out]",
                    ],
                    ffmpeg_bin=ffmpeg_bin,
                )
            else:
                _copy_png_atomic(first, group_path)
            rebuilt.append(group_relative)
        groups.append({
            "groupId": group_id,
            "shotIds": [str(member["shotId"]) for member in members],
            "path": group_relative,
            "sha256": _hash_file(group_path),
        })

    index = {
        "version": "1.0",
        "commandVersion": REGION_COMMAND_VERSION,
        "fingerprint": fingerprint,
        "inputs": input_record,
        "grid": {"columns": GRID_COLUMNS, "rows": GRID_ROWS},
        "recipe": recipe,
        "shots": shot_records,
        "groups": groups,
    }
    index_changed = _atomic_stable_json(index_path, index)
    changed = bool(rebuilt) or index_changed
    return {
        "indexPath": str(index_path),
        "fingerprint": fingerprint,
        "shotCount": len(shot_records),
        "rebuiltOutputs": rebuilt,
        "changed": changed,
        "idempotent": not changed,
    }


def _input_dependencies_match(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    keys = (
        "assetManifestPath", "assetVisualDependencySha256",
        "scenePlanPath", "sceneGeometryDependencySha256",
    )
    return all(left.get(key) == right.get(key) for key in keys)


def _validate_sheet_index(
    project: Path,
    index: Mapping[str, Any],
    *,
    manifest: Mapping[str, Any],
    scene_plan: Mapping[str, Any],
    input_record: Mapping[str, Any],
) -> list[dict[str, Any]]:
    canonical = _build_shot_plan(project, manifest, scene_plan)
    fail = "subject-region sheet index is corrupt or incompatible; run regions build-sheets again"
    if (
        index.get("version") != "1.0"
        or index.get("commandVersion") != REGION_COMMAND_VERSION
        or index.get("grid") != {"columns": GRID_COLUMNS, "rows": GRID_ROWS}
        or not isinstance(index.get("inputs"), Mapping)
        or not _input_dependencies_match(index.get("inputs"), input_record)
        or index.get("fingerprint") != _index_fingerprint(input_record, canonical)
    ):
        raise PersianRegionCommandError(fail)

    indexed_shots = index.get("shots")
    if not isinstance(indexed_shots, list) or len(indexed_shots) != len(canonical):
        raise PersianRegionCommandError(fail)

    for expected, indexed in zip(canonical, indexed_shots):
        if not isinstance(indexed, Mapping):
            raise PersianRegionCommandError(fail)
        for key in ("shotId", "beatId", "visualEventId", "sourceId", "sourcePath", "sourceWindow", "timeline"):
            if indexed.get(key) != expected.get(key):
                raise PersianRegionCommandError(fail)
        if not _same_float(indexed.get("sourceDurationSeconds"), expected.get("sourceDurationSeconds")):
            raise PersianRegionCommandError(fail)

        indexed_frames = indexed.get("frames")
        if not isinstance(indexed_frames, list) or len(indexed_frames) != len(FRAME_POSITIONS):
            raise PersianRegionCommandError(fail)
        for frame_index, position in enumerate(FRAME_POSITIONS):
            frame = indexed_frames[frame_index]
            if not isinstance(frame, Mapping):
                raise PersianRegionCommandError(fail)
            interval = expected["frameIntervals"][frame_index]
            expected_path = (SHEET_DIR / f"{expected['fileStem']}-{position}.png").as_posix()
            if (
                frame.get("position") != position
                or not _same_float(frame.get("sourceSeconds"), expected["frameTimes"][frame_index])
                or not _same_float(frame.get("timelineStartSeconds"), interval[0])
                or not _same_float(frame.get("timelineEndSeconds"), interval[1])
                or frame.get("path") != expected_path
            ):
                raise PersianRegionCommandError(fail)
            digest = str(frame.get("sha256") or "")
            if not _cached_png_ok(project / expected_path, digest):
                raise PersianRegionCommandError(
                    "subject-region review output is missing or corrupt; run regions build-sheets again"
                )

        expected_sheet_path = (SHEET_DIR / f"{expected['fileStem']}-sheet.png").as_posix()
        sheet = indexed.get("sheet")
        if not isinstance(sheet, Mapping) or sheet.get("path") != expected_sheet_path:
            raise PersianRegionCommandError(fail)
        if not _cached_png_ok(project / expected_sheet_path, str(sheet.get("sha256") or "")):
            raise PersianRegionCommandError(
                "subject-region review output is missing or corrupt; run regions build-sheets again"
            )

    groups = index.get("groups")
    expected_group_count = (len(canonical) + 1) // 2
    if not isinstance(groups, list) or len(groups) != expected_group_count:
        raise PersianRegionCommandError(fail)
    for group_index, group in enumerate(groups):
        if not isinstance(group, Mapping):
            raise PersianRegionCommandError(fail)
        members = canonical[group_index * 2:group_index * 2 + 2]
        expected_path = (SHEET_DIR / f"group-{group_index + 1:03d}-grid.png").as_posix()
        if (
            group.get("groupId") != f"group-{group_index + 1}"
            or group.get("shotIds") != [str(member["shotId"]) for member in members]
            or group.get("path") != expected_path
        ):
            raise PersianRegionCommandError(fail)
        if not _cached_png_ok(project / expected_path, str(group.get("sha256") or "")):
            raise PersianRegionCommandError(
                "subject-region review output is missing or corrupt; run regions build-sheets again"
            )
    return canonical


def _grid_region(raw: object, *, label: str) -> dict[str, float]:
    if not isinstance(raw, Mapping):
        raise PersianRegionCommandError(f"{label}.grid must be an object")
    values: dict[str, int] = {}
    for key in ("x1", "y1", "x2", "y2"):
        value = raw.get(key)
        if isinstance(value, bool) or not isinstance(value, int):
            raise PersianRegionCommandError(f"{label}.grid.{key} must be an integer")
        values[key] = value
    if not (
        0 <= values["x1"] < values["x2"] <= GRID_COLUMNS
        and 0 <= values["y1"] < values["y2"] <= GRID_ROWS
    ):
        raise PersianRegionCommandError(
            f"{label}.grid must satisfy 0 <= x1 < x2 <= 10 and 0 <= y1 < y2 <= 10"
        )
    return {
        "x": round(values["x1"] / GRID_COLUMNS, 6),
        "y": round(values["y1"] / GRID_ROWS, 6),
        "w": round((values["x2"] - values["x1"]) / GRID_COLUMNS, 6),
        "h": round((values["y2"] - values["y1"]) / GRID_ROWS, 6),
    }


def _annotation_regions(raw_frame: Mapping[str, Any], *, label: str) -> list[dict[str, Any]]:
    if raw_frame.get("clear") is True:
        if any(key in raw_frame for key in ("grid", "priority", "regions")):
            raise PersianRegionCommandError(
                f"{label} clear frame cannot also declare grid/priority/regions"
            )
        return []
    raw_regions = raw_frame.get("regions")
    if raw_regions is None:
        raw_regions = [{"priority": raw_frame.get("priority"), "grid": raw_frame.get("grid")}]
    if not isinstance(raw_regions, list) or not raw_regions:
        raise PersianRegionCommandError(f"{label}.regions must be non-empty or set clear=true")
    result: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_regions):
        if not isinstance(raw, Mapping):
            raise PersianRegionCommandError(f"{label}.regions[{index}] must be an object")
        priority = str(raw.get("priority") or "").strip()
        if priority not in {"hard", "soft"}:
            raise PersianRegionCommandError(
                f"{label}.regions[{index}].priority must be 'hard' or 'soft'"
            )
        result.append({
            **_grid_region(raw.get("grid"), label=f"{label}.regions[{index}]"),
            "priority": priority,
        })
    return result


def _merge_timed_regions(regions: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[float, float, float, float, str], list[tuple[float, float]]] = {}
    for raw in regions:
        key = (
            float(raw["x"]), float(raw["y"]), float(raw["w"]), float(raw["h"]),
            str(raw["priority"]),
        )
        grouped.setdefault(key, []).append(
            (float(raw["startSeconds"]), float(raw["endSeconds"]))
        )
    merged: list[dict[str, Any]] = []
    for key, intervals in grouped.items():
        intervals.sort()
        compact: list[list[float]] = []
        for start, end in intervals:
            if compact and abs(compact[-1][1] - start) <= 1e-6:
                compact[-1][1] = end
            else:
                compact.append([start, end])
        x, y, w, h, priority = key
        for start, end in compact:
            merged.append({
                "x": x, "y": y, "w": w, "h": h, "priority": priority,
                "startSeconds": round(start, 6), "endSeconds": round(end, 6),
            })
    merged.sort(key=lambda row: (
        row["startSeconds"], row["endSeconds"], row["priority"],
        row["x"], row["y"], row["w"], row["h"],
    ))
    return merged


def propose_regions(
    pipeline_dir: Path,
    project_id: str,
    annotations: Mapping[str, Any],
) -> dict[str, Any]:
    """Convert reviewed 10x10 annotations into a non-final subject-region proposal."""
    project = _project_dir(Path(pipeline_dir), project_id)
    output_root = project / SHEET_DIR
    index_path = output_root / INDEX_NAME
    index = _read_object(index_path, label="subject-region sheet index")
    inputs = index.get("inputs")
    if not isinstance(inputs, Mapping):
        raise PersianRegionCommandError("subject-region sheet index has no input binding")
    manifest_path = project / "artifacts" / "asset_manifest.json"
    scene_path = project / "artifacts" / "scene_plan.json"
    manifest = _read_object(manifest_path, label="asset manifest")
    scene_plan = _read_object(scene_path, label="scene plan")
    input_record = {
        "assetManifestPath": _relative(manifest_path, project),
        "assetManifestSha256": _hash_file(manifest_path),
        "assetVisualDependencySha256": asset_visual_dependency_digest(manifest),
        "scenePlanPath": _relative(scene_path, project),
        "scenePlanSha256": _hash_file(scene_path),
        "sceneGeometryDependencySha256": scene_geometry_dependency_digest(scene_plan),
    }
    if not _input_dependencies_match(inputs, input_record):
        raise PersianRegionCommandError(
            "subject-region sheet index is stale; run regions build-sheets again"
        )
    canonical_shots = _validate_sheet_index(
        project, index, manifest=manifest, scene_plan=scene_plan, input_record=input_record
    )
    raw_shots = annotations.get("shots") if isinstance(annotations, Mapping) else None
    if not isinstance(raw_shots, list) or not raw_shots:
        raise PersianRegionCommandError("region annotations require non-empty shots")

    by_id: dict[str, Mapping[str, Any]] = {}
    for position, raw in enumerate(raw_shots):
        if not isinstance(raw, Mapping):
            raise PersianRegionCommandError(f"annotations.shots[{position}] must be an object")
        shot_id = str(raw.get("shot_id") or "").strip()
        if not shot_id:
            raise PersianRegionCommandError(f"annotations.shots[{position}].shot_id is required")
        if shot_id in by_id:
            raise PersianRegionCommandError(f"duplicate annotated shot id: {shot_id}")
        by_id[shot_id] = raw

    expected_ids = [str(shot["shotId"]) for shot in canonical_shots]
    missing = [shot_id for shot_id in expected_ids if shot_id not in by_id]
    unexpected = sorted(set(by_id) - set(expected_ids))
    if missing:
        raise PersianRegionCommandError(
            "missing annotated shot ids: " + ", ".join(missing)
        )
    if unexpected:
        raise PersianRegionCommandError(
            "unexpected annotated shot ids: " + ", ".join(unexpected)
        )

    proposed_rows: list[dict[str, Any]] = []
    for shot in canonical_shots:
        shot_id = str(shot["shotId"])
        annotation = by_id[shot_id]
        observed = str(annotation.get("observed") or "").strip()
        if not observed:
            raise PersianRegionCommandError(f"{shot_id}.observed must be non-empty")
        raw_frames = annotation.get("frames")
        if not isinstance(raw_frames, list):
            raise PersianRegionCommandError(f"{shot_id}.frames must be an array")
        annotation_frames: dict[str, Mapping[str, Any]] = {}
        for raw in raw_frames:
            if not isinstance(raw, Mapping):
                raise PersianRegionCommandError(f"{shot_id}.frames entries must be objects")
            position = str(raw.get("position") or "").strip()
            if position not in FRAME_POSITIONS:
                raise PersianRegionCommandError(
                    f"{shot_id}.frames position must be start, middle, or end"
                )
            if position in annotation_frames:
                raise PersianRegionCommandError(
                    f"{shot_id} has duplicate frame annotation for {position}"
                )
            annotation_frames[position] = raw
        missing_positions = [pos for pos in FRAME_POSITIONS if pos not in annotation_frames]
        if missing_positions:
            raise PersianRegionCommandError(
                f"{shot_id} missing frame annotations: {', '.join(missing_positions)}"
            )

        timed: list[dict[str, Any]] = []
        for frame_index, position in enumerate(FRAME_POSITIONS):
            start, end = shot["frameIntervals"][frame_index]
            for region in _annotation_regions(
                annotation_frames[position], label=f"{shot_id}.{position}"
            ):
                timed.append({**region, "startSeconds": start, "endSeconds": end})

        proposed_rows.append({
            "shot_id": shot_id,
            "avoidRegions": _merge_timed_regions(timed),
            "frame_review": {
                "start": True,
                "middle": True,
                "end": True,
                "observed": observed,
            },
        })

    evidence = {"shot_regions": proposed_rows}
    try:
        normalized = validate_subject_region_review_evidence(
            evidence, expected_shot_ids=expected_ids
        )
    except SubjectRegionReviewError as exc:
        raise PersianRegionCommandError(str(exc)) from exc

    proposal = {
        "version": "1.0",
        "status": "proposed",
        "confirmationRequired": True,
        "source": {
            "indexPath": _relative(index_path, project),
            "indexFingerprint": str(index.get("fingerprint") or ""),
            "annotationsSha256": _digest(dict(annotations)),
        },
        "proposedEvidence": normalized,
    }
    proposal_path = output_root / PROPOSAL_NAME
    changed = _atomic_stable_json(proposal_path, proposal)
    return {
        "proposalPath": str(proposal_path),
        "status": "proposed",
        "confirmationRequired": True,
        "shotCount": len(proposed_rows),
        "changed": changed,
        "idempotent": not changed,
    }


__all__ = [
    "PersianRegionCommandError",
    "build_sheets",
    "propose_regions",
]
