"""Actionable contract checks for Persian edit artifacts.

This module sits before compose/browser preparation. It intentionally does not
repair inputs or weaken render gates: it turns contract drift into deterministic
JSON-pointer diagnostics while the author still has enough context to fix the edit.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

import jsonschema

from lib.paths import REPO_ROOT
from lib.persian_music import (
    MUSIC_AUDIBILITY_FLOOR_LUFS,
    derive_loudness_aware_mix,
    evaluate_music_separation,
    measure_integrated_loudness,
)
from schemas.artifacts import load_schema


@dataclass(frozen=True)
class ContractDiagnostic:
    code: str
    pointer: str
    message: str
    hint: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {key: value for key, value in asdict(self).items() if value is not None}


class PersianEditContractError(ValueError):
    """Raised when an edit artifact violates the executable Persian contract."""

    def __init__(self, diagnostics: Iterable[ContractDiagnostic]):
        self.diagnostics = tuple(diagnostics)
        body = "\n".join(
            f"- {item.pointer}: {item.message}"
            + (f" Hint: {item.hint}" if item.hint else "")
            for item in self.diagnostics
        )
        super().__init__("Persian edit contract refused:\n" + body)


_ALIAS_HINTS = {
    "width": ("w", "avoid-region rectangles use normalized x/y/w/h"),
    "height": ("h", "avoid-region rectangles use normalized x/y/w/h"),
    "start": ("startSeconds", "time-scoped regions use absolute timeline seconds"),
    "end": ("endSeconds", "time-scoped regions use absolute timeline seconds"),
}


def _pointer(parts: Iterable[Any]) -> str:
    encoded = [str(part).replace("~", "~0").replace("/", "~1") for part in parts]
    return "/" + "/".join(encoded) if encoded else "/"


def _persian_schema() -> dict[str, Any]:
    return load_schema("edit_decisions")["properties"]["persian"]


def _schema_diagnostics(edit: dict[str, Any]) -> list[ContractDiagnostic]:
    full = any(
        key in edit
        for key in ("version", "cuts", "render_runtime", "renderer_family", "composition_mode")
    )
    schema = load_schema("edit_decisions") if full else _persian_schema()
    instance: Any = edit if full else edit.get("persian")
    base = [] if full else ["persian"]
    if not isinstance(instance, dict):
        return [ContractDiagnostic("schema.type", "/persian", "must be an object")]

    validator = jsonschema.Draft202012Validator(schema)
    diagnostics: list[ContractDiagnostic] = []
    for error in sorted(validator.iter_errors(instance), key=lambda item: list(item.absolute_path)):
        path = base + list(error.absolute_path)
        hint = None
        if error.validator == "additionalProperties":
            container = error.instance if isinstance(error.instance, dict) else {}
            allowed = set((error.schema.get("properties") or {}).keys())
            unexpected = [key for key in container if key not in allowed]
            if len(unexpected) == 1:
                bad = unexpected[0]
                path = path + [bad]
                replacement = _ALIAS_HINTS.get(bad)
                if replacement:
                    hint = f"use {replacement[0]!r}; {replacement[1]}"
        diagnostics.append(
            ContractDiagnostic(
                code=f"schema.{error.validator}",
                pointer=_pointer(path),
                message=error.message,
                hint=hint,
            )
        )
    return diagnostics


def _region_diagnostics(persian: dict[str, Any]) -> list[ContractDiagnostic]:
    diagnostics: list[ContractDiagnostic] = []
    for shot_index, shot in enumerate(persian.get("shots") or []):
        if not isinstance(shot, dict):
            continue
        shot_start = shot.get("startSeconds")
        shot_end = shot.get("endSeconds")
        for region_index, region in enumerate(shot.get("avoidRegions") or []):
            if not isinstance(region, dict):
                continue
            prefix = ["persian", "shots", shot_index, "avoidRegions", region_index]
            for stale, (replacement, explanation) in _ALIAS_HINTS.items():
                if stale in region:
                    diagnostics.append(
                        ContractDiagnostic(
                            "region.alias",
                            _pointer(prefix + [stale]),
                            f"{stale!r} is not part of the avoid-region contract",
                            f"use {replacement!r}; {explanation}",
                        )
                    )
            start = region.get("startSeconds", shot_start)
            end = region.get("endSeconds", shot_end)
            if not isinstance(start, (int, float)) or not isinstance(end, (int, float)):
                continue
            if end <= start:
                diagnostics.append(
                    ContractDiagnostic(
                        "region.time_order",
                        _pointer(prefix),
                        f"region interval {start}-{end}s is empty or reversed",
                        "endSeconds must be greater than startSeconds",
                    )
                )
            if isinstance(shot_start, (int, float)) and start < shot_start:
                diagnostics.append(
                    ContractDiagnostic(
                        "region.before_shot",
                        _pointer(prefix + ["startSeconds"]),
                        f"{start}s is before shot start {shot_start}s",
                        "region times are absolute and must stay within the owning shot",
                    )
                )
            if isinstance(shot_end, (int, float)) and end > shot_end:
                diagnostics.append(
                    ContractDiagnostic(
                        "region.after_shot",
                        _pointer(prefix + ["endSeconds"]),
                        f"{end}s is after shot end {shot_end}s",
                        "region times are absolute and must stay within the owning shot",
                    )
                )
    return diagnostics


def _shot_source_window_diagnostics(persian: dict[str, Any]) -> list[ContractDiagnostic]:
    """Refuse visibly repeated source time, while allowing distinct windows of one clip."""
    diagnostics: list[ContractDiagnostic] = []
    by_source: dict[str, list[tuple[int, str, float, float]]] = {}
    for index, shot in enumerate(persian.get("shots") or []):
        if not isinstance(shot, dict) or not shot.get("source"):
            continue
        try:
            timeline_start = float(shot.get("startSeconds", 0.0))
            timeline_end = float(shot.get("endSeconds", 0.0))
            source_start = float(shot.get("sourceInSeconds") or 0.0)
        except (TypeError, ValueError):
            continue
        duration = timeline_end - timeline_start
        if duration <= 0:
            continue
        source_end = source_start + duration
        source = str(shot["source"])
        shot_id = str(shot.get("id") or f"shot-{index}")
        for _prior_index, prior_id, prior_start, prior_end in by_source.get(source, []):
            overlap = min(source_end, prior_end) - max(source_start, prior_start)
            if overlap > 0.10:
                diagnostics.append(
                    ContractDiagnostic(
                        "shot.duplicate_source_window",
                        _pointer(["persian", "shots", index, "source"]),
                        f"{shot_id!r} reuses {overlap:.2f}s of source time already shown by {prior_id!r}",
                        "use the scene's own reviewed asset or a non-overlapping source window; repeated visible footage is not an acceptable default",
                    )
                )
        by_source.setdefault(source, []).append((index, shot_id, source_start, source_end))
    return diagnostics


def _resolved_media_paths(
    persian: dict[str, Any], *, base_dir: Path | None
) -> tuple[Path, Path] | None:
    if base_dir is None:
        return None
    audio = persian.get("audio") if isinstance(persian.get("audio"), dict) else {}
    track = persian.get("musicTrack") if isinstance(persian.get("musicTrack"), dict) else None
    if not track or not track.get("path") or not audio.get("narration"):
        return None
    root = base_dir.expanduser().resolve()
    music_raw = Path(str(track["path"])).expanduser()
    narration_raw = Path(str(audio["narration"])).expanduser()
    music_path = music_raw.resolve() if music_raw.is_absolute() else (root / music_raw).resolve()
    narration_path = (
        narration_raw.resolve()
        if narration_raw.is_absolute()
        else (root / narration_raw).resolve()
    )
    if not music_path.is_file() or not narration_path.is_file():
        return None
    return narration_path, music_path


def inspect_persian_audio_mix(
    edit: dict[str, Any], *, base_dir: Path | None = None
) -> dict[str, Any] | None:
    """Return versioned measured/derived mix evidence for production preflight."""
    persian = edit.get("persian")
    if not isinstance(persian, dict):
        return None
    paths = _resolved_media_paths(persian, base_dir=base_dir)
    if paths is None:
        return None
    narration_path, music_path = paths
    narration_lufs = measure_integrated_loudness(narration_path)
    music_lufs = measure_integrated_loudness(music_path)
    audio = persian.get("audio") if isinstance(persian.get("audio"), dict) else {}
    if audio.get("musicDuckVolume") is not None:
        try:
            authored_gain = float(audio["musicDuckVolume"])
        except (TypeError, ValueError):
            return None
        result = evaluate_music_separation(
            narration_lufs=narration_lufs,
            music_lufs=music_lufs,
            music_gain=authored_gain,
        )
        result["gainSource"] = "authored_legacy_override"
        return result
    result = derive_loudness_aware_mix(
        narration_lufs=narration_lufs,
        music_lufs=music_lufs,
    )
    result["gainSource"] = "derived_loudness_policy"
    return result


def _music_diagnostics(
    persian: dict[str, Any], *, base_dir: Path | None = None
) -> list[ContractDiagnostic]:
    diagnostics: list[ContractDiagnostic] = []
    audio = persian.get("audio") if isinstance(persian.get("audio"), dict) else {}
    if persian.get("musicTrack") and audio.get("music"):
        diagnostics.append(
            ContractDiagnostic(
                "music.duplicate_owner",
                "/persian/musicTrack",
                "music is declared both as persian.musicTrack and persian.audio.music",
                "use persian.musicTrack as the canonical licensed record; compose derives audio.music from its path",
            )
        )
    if audio.get("musicTrack") is not None:
        diagnostics.append(
            ContractDiagnostic(
                "music.stale_location",
                "/persian/audio/musicTrack",
                "musicTrack is nested under audio, which is not the executable contract",
                "move the complete record to /persian/musicTrack",
            )
        )
    if isinstance(persian.get("musicTrack"), dict) and "acknowledgeUnknownMusicRisk" in persian["musicTrack"]:
        diagnostics.append(
            ContractDiagnostic(
                "music.stale_ack_location",
                "/persian/musicTrack/acknowledgeUnknownMusicRisk",
                "acknowledgeUnknownMusicRisk is not part of the musicTrack record",
                "move it to /persian/acknowledgeUnknownMusicRisk",
            )
        )

    paths = _resolved_media_paths(persian, base_dir=base_dir)
    track = persian.get("musicTrack") if isinstance(persian.get("musicTrack"), dict) else None
    if track and base_dir is not None and track.get("path"):
        root = base_dir.expanduser().resolve()
        music_raw = Path(str(track["path"])).expanduser()
        music_path = music_raw.resolve() if music_raw.is_absolute() else (root / music_raw).resolve()
        if music_path.is_file():
            try:
                music_lufs = measure_integrated_loudness(music_path)
            except RuntimeError as exc:
                diagnostics.append(
                    ContractDiagnostic(
                        "music.loudness_unmeasurable",
                        "/persian/musicTrack/path",
                        str(exc),
                        "repair or replace the music file; production preflight must verify audible signal",
                    )
                )
            else:
                if music_lufs < MUSIC_AUDIBILITY_FLOOR_LUFS:
                    diagnostics.append(
                        ContractDiagnostic(
                            "music.near_silent",
                            "/persian/musicTrack/path",
                            f"music integrated loudness is {music_lufs:.1f} LUFS, below the {MUSIC_AUDIBILITY_FLOOR_LUFS:.1f} LUFS audibility floor",
                            "normalize or replace the bed before preflight; presence of an almost-silent audio file does not satisfy the music requirement",
                        )
                    )

    if paths is not None:
        narration_path, _music_path = paths
        try:
            mix = inspect_persian_audio_mix({"persian": persian}, base_dir=base_dir)
        except RuntimeError as exc:
            diagnostics.append(
                ContractDiagnostic(
                    "music.mix_unmeasurable",
                    "/persian/audio/narration",
                    str(exc),
                    "repair the narration/music input; production preflight must verify the speech/music balance",
                )
            )
        else:
            if mix is not None and mix.get("gainSource") == "authored_legacy_override" and not mix.get("passed"):
                reason = str(mix.get("reason") or "")
                code = "music.mix_too_loud" if reason == "music_too_loud" else "music.mix_too_quiet"
                relation = "below" if reason == "music_too_loud" else "above"
                boundary = mix["minSeparationLu"] if reason == "music_too_loud" else mix["maxSeparationLu"]
                diagnostics.append(
                    ContractDiagnostic(
                        code,
                        "/persian/audio/musicDuckVolume",
                        f"authored speech-time music gain predicts a {mix['predictedSeparationLu']:.1f} LU gap, {relation} the {boundary:.1f} LU policy boundary",
                        "remove the fixed musicDuckVolume and let the versioned loudness policy derive speech-time gain from measured narration/music LUFS",
                    )
                )
    return diagnostics


def _path_diagnostics(
    persian: dict[str, Any], *, base_dir: Path | None
) -> list[ContractDiagnostic]:
    if base_dir is None:
        return []
    root = base_dir.expanduser().resolve()
    diagnostics: list[ContractDiagnostic] = []
    candidates: list[tuple[list[Any], Any]] = []
    for index, shot in enumerate(persian.get("shots") or []):
        if isinstance(shot, dict):
            candidates.append((["persian", "shots", index, "source"], shot.get("source")))
    audio = persian.get("audio") if isinstance(persian.get("audio"), dict) else {}
    candidates.append((["persian", "audio", "narration"], audio.get("narration")))
    track = persian.get("musicTrack") if isinstance(persian.get("musicTrack"), dict) else {}
    candidates.append((["persian", "musicTrack", "path"], track.get("path")))

    for pointer_parts, raw in candidates:
        if raw in (None, ""):
            continue
        path = Path(str(raw)).expanduser()
        resolved = path.resolve() if path.is_absolute() else (root / path).resolve()
        if not resolved.is_file():
            diagnostics.append(
                ContractDiagnostic(
                    "path.missing",
                    _pointer(pointer_parts),
                    f"media path does not exist: {resolved}",
                    "use an existing file path before browser preparation; preflight never downloads or invents assets",
                )
            )
    return diagnostics


def collect_persian_edit_diagnostics(
    edit: dict[str, Any], *, base_dir: Path | None = None
) -> list[ContractDiagnostic]:
    """Return all contract defects that can be established without a browser."""
    diagnostics = _schema_diagnostics(edit)
    persian = edit.get("persian")
    if isinstance(persian, dict):
        diagnostics.extend(_region_diagnostics(persian))
        diagnostics.extend(_shot_source_window_diagnostics(persian))
        diagnostics.extend(_music_diagnostics(persian, base_dir=base_dir))
        diagnostics.extend(_path_diagnostics(persian, base_dir=base_dir))

    deduped: list[ContractDiagnostic] = []
    seen: set[tuple[str, str, str]] = set()
    for item in diagnostics:
        key = (item.code, item.pointer, item.message)
        if key not in seen:
            seen.add(key)
            deduped.append(item)
    return deduped


def validate_persian_edit_contract(
    edit: dict[str, Any], *, base_dir: Path | None = None
) -> None:
    diagnostics = collect_persian_edit_diagnostics(edit, base_dir=base_dir)
    if diagnostics:
        raise PersianEditContractError(diagnostics)
