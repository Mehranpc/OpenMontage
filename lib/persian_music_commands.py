"""Cached, idempotent music search/fetch commands for Persian production."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from pathlib import Path
from typing import Any, Callable, Mapping
from uuid import uuid4

from lib.persian_music import audit_music, build_music_track
from tools.audio.freesound_music import FreesoundMusic
from tools.audio.pixabay_music import PixabayMusic
from tools.base_tool import BaseTool, ToolStatus

_ALLOWED_PROVIDERS = {"freesound_music", "pixabay_music"}


class PersianMusicCommandError(ValueError):
    """Raised when cached music acquisition cannot complete safely."""


def _stable_text(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"



def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_json(path: Path, value: Mapping[str, Any]) -> bool:
    rendered = _stable_text(dict(value))
    if path.is_file() and path.read_text(encoding="utf-8") == rendered:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    temporary.write_text(rendered, encoding="utf-8")
    os.replace(temporary, path)
    return True


def _read_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PersianMusicCommandError(f"could not read {label}: {path}") from exc
    if not isinstance(value, dict):
        raise PersianMusicCommandError(f"{label} must be a JSON object: {path}")
    return value


def _project(pipeline_dir: Path, project_id: str) -> Path:
    project = (Path(pipeline_dir) / project_id).expanduser().resolve()
    if not project.is_dir():
        raise PersianMusicCommandError(f"project does not exist: {project}")
    return project


def _factory(provider: str) -> BaseTool:
    return PixabayMusic() if provider == "pixabay_music" else FreesoundMusic()


def _search_id(request: Mapping[str, Any]) -> str:
    payload = json.dumps(dict(request), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"music-{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:24]}"


def search_music(
    pipeline_dir: Path,
    project_id: str,
    request: Mapping[str, Any],
    *,
    tool_factory: Callable[[str], BaseTool] = _factory,
) -> dict[str, Any]:
    """Run one provider request once and persist its downloaded bytes in a cache."""
    project = _project(pipeline_dir, project_id)
    normalized = {str(key): value for key, value in request.items()}
    provider = str(normalized.pop("provider", "")).strip()
    if "output_path" in normalized:
        raise PersianMusicCommandError(
            "music search output_path is command-owned; use assets music fetch to choose a destination"
        )
    if provider not in _ALLOWED_PROVIDERS:
        raise PersianMusicCommandError(
            "music provider must be freesound_music or pixabay_music"
        )
    query = str(normalized.get("query") or "").strip()
    if not query:
        raise PersianMusicCommandError("music search requires a non-empty query")
    normalized["query"] = query
    identity = {"provider": provider, **normalized}
    search_id = _search_id(identity)
    root = project / ".asset-workspace" / "music"
    record_path = root / "searches" / f"{search_id}.json"
    cache_path = root / "cache" / f"{search_id}.mp3"

    if record_path.is_file():
        record = _read_object(record_path, label="music search cache")
        if (
            record.get("request") == identity
            and cache_path.is_file()
            and record.get("audioSha256") == _sha256_file(cache_path)
        ):
            return {**record, "idempotent": True, "changed": False}
        raise PersianMusicCommandError(
            f"music search cache is incomplete or corrupt: {search_id}"
        )

    tool = tool_factory(provider)
    if tool.get_status() != ToolStatus.AVAILABLE:
        raise PersianMusicCommandError(f"music provider is unavailable: {provider}")
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    inputs = dict(normalized)
    inputs["output_path"] = str(cache_path)
    try:
        result = tool.execute(inputs)
    except Exception as exc:
        cache_path.unlink(missing_ok=True)
        raise PersianMusicCommandError(f"{provider} music search failed: {exc}") from exc
    if not result.success:
        cache_path.unlink(missing_ok=True)
        raise PersianMusicCommandError(result.error or f"{provider} music search failed")
    if not cache_path.is_file() or cache_path.stat().st_size <= 0:
        raise PersianMusicCommandError("music provider reported success without audio bytes")

    record = {
        "version": "1.0",
        "searchId": search_id,
        "request": identity,
        "provider": provider,
        "cachedPath": str(cache_path),
        "audioSha256": _sha256_file(cache_path),
        "sizeBytes": cache_path.stat().st_size,
        "result": dict(result.data),
    }
    _atomic_json(record_path, record)
    return {**record, "idempotent": False, "changed": True}


def _destination(project: Path, raw: str | Path) -> Path:
    candidate = Path(raw).expanduser()
    path = candidate.resolve() if candidate.is_absolute() else (project / candidate).resolve()
    try:
        path.relative_to(project)
    except ValueError as exc:
        raise PersianMusicCommandError(
            f"music output must stay inside its project: {path}"
        ) from exc
    return path


def fetch_music(
    pipeline_dir: Path,
    project_id: str,
    search_id: str,
    metadata: Mapping[str, Any],
    *,
    output_path: str | Path = "assets/music/bed.mp3",
) -> dict[str, Any]:
    """Promote cached bytes and persist an audited canonical music-track record."""
    project = _project(pipeline_dir, project_id)
    if re.fullmatch(r"music-[0-9a-f]{24}", str(search_id)) is None:
        raise PersianMusicCommandError("invalid music search id")
    root = project / ".asset-workspace" / "music"
    record = _read_object(
        root / "searches" / f"{search_id}.json", label="music search cache"
    )
    if record.get("searchId") != search_id:
        raise PersianMusicCommandError("music search cache identity does not match")
    cache_path = Path(str(record.get("cachedPath") or "")).expanduser().resolve()
    try:
        cache_path.relative_to(root.resolve())
    except ValueError as exc:
        raise PersianMusicCommandError("cached music path escaped the project cache") from exc
    expected_sha = str(record.get("audioSha256") or "")
    if not cache_path.is_file() or _sha256_file(cache_path) != expected_sha:
        raise PersianMusicCommandError("cached music bytes are missing or changed")

    destination = _destination(project, output_path)
    raw_track = dict(metadata)
    raw_track["path"] = str(destination)
    raw_track["source"] = str(record.get("provider") or "")
    result_data = record.get("result") if isinstance(record.get("result"), Mapping) else {}
    if not str(raw_track.get("attribution") or "").strip():
        title = str(result_data.get("track_title") or result_data.get("name") or "").strip()
        artist = str(result_data.get("artist") or "").strip()
        raw_track["attribution"] = " — ".join(part for part in (title, artist) if part)
    try:
        track = build_music_track(raw_track)
        audit = audit_music(
            track=track,
            narrated=True,
            acknowledge_unknown_risk=bool(raw_track.get("acknowledgeUnknownRisk")),
        )
    except ValueError as exc:
        raise PersianMusicCommandError(str(exc)) from exc
    if not audit.passed:
        raise PersianMusicCommandError("music audit failed: " + " | ".join(audit.problems))

    changed_audio = not destination.is_file() or _sha256_file(destination) != expected_sha
    if changed_audio:
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(f".{destination.name}.{uuid4().hex}.tmp")
        shutil.copyfile(cache_path, temporary)
        os.replace(temporary, destination)

    track_path = project / "artifacts" / "music_track.json"
    track_record = track.to_dict()
    changed_record = _atomic_json(track_path, track_record)
    return {
        "searchId": search_id,
        "audioPath": str(destination),
        "audioSha256": expected_sha,
        "trackPath": str(track_path),
        "track": track_record,
        "changed": changed_audio or changed_record,
        "idempotent": not changed_audio and not changed_record,
    }


__all__ = [
    "PersianMusicCommandError",
    "fetch_music",
    "search_music",
]
