"""Actionable contract checks for Persian edit artifacts.

This module sits before compose/browser preparation.  It intentionally does not
repair inputs or weaken any render gate: it turns contract drift into deterministic
JSON-pointer diagnostics while the author still has enough context to fix the edit.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Iterable

import jsonschema

from schemas.artifacts import load_schema
from lib.paths import REPO_ROOT


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
            # jsonschema's message contains the unexpected property name, but its
            # path stops at the containing object. Recover common stale aliases so
            # callers get a copy/pasteable fix instead of an opaque schema dump.
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


def _music_diagnostics(persian: dict[str, Any]) -> list[ContractDiagnostic]:
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
    return diagnostics


def _path_diagnostics(persian: dict[str, Any], *, base_dir: Path | None) -> list[ContractDiagnostic]:
    # Pure contract validation may be used without filesystem context. Production
    # preflight always passes REPO_ROOT, making authored relative paths repository-
    # relative and independent of the caller's cwd. Absolute paths stay readable.
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
        diagnostics.extend(_music_diagnostics(persian))
        diagnostics.extend(_path_diagnostics(persian, base_dir=base_dir))

    # Alias errors can be reported by both the strict schema and semantic pass;
    # keep one stable diagnostic per code/pointer/message tuple.
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
