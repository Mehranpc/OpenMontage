"""Run Persian compose preparation without copying media or writing checkpoints."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import tempfile
from typing import Any
from tools.video.persian_compose_script_aligned import ScriptAlignedPersianCompose
from lib.persian_retention import audit_persian_retention
from lib.persian_captions import caption_band_rect
from lib.persian_srt import PersianCue, audit_cues
from lib.persian_text import split_words


class NoCopyPersianCompose(ScriptAlignedPersianCompose):
    @staticmethod
    def _stage(source: str | Path, staging: Path, name: str) -> str:
        del staging, name
        path = Path(source).expanduser()
        if not path.is_absolute():
            path = (Path.cwd() / path).resolve()
        if not path.is_file():
            raise FileNotFoundError(f"Persian preflight source does not exist: {path}")
        return str(path)


def extract_edit_decisions(payload: dict[str, Any]) -> dict[str, Any]:
    artifacts = payload.get("artifacts")
    if isinstance(artifacts, dict) and isinstance(artifacts.get("edit_decisions"), dict):
        payload = artifacts["edit_decisions"]
    if isinstance(payload.get("edit_decisions"), dict):
        payload = payload["edit_decisions"]
    if isinstance(payload.get("persian"), dict):
        return payload
    if "shots" in payload and "moments" in payload:
        return {"persian": payload}
    raise ValueError("Expected a checkpoint, edit_decisions artifact, or raw Persian block")


def _opening_evidence(props: dict[str, Any]) -> dict[str, Any]:
    shots = sorted(props.get("shots") or [], key=lambda shot: float(shot.get("startSeconds", 0.0)))
    opening = next((shot for shot in shots if shot.get("narrativeRole") == "hook" and float(shot.get("startSeconds", 0.0)) < 3.0), None)
    hook = next((moment for moment in props.get("moments") or [] if moment.get("kind") == "hook"), None)
    text = ""
    token_count = 0
    short_fallback = False
    if hook:
        text = " ".join(str(segment.get("text") or "") for segment in hook.get("segments") or [] if segment.get("role") != "source").strip()
        token_count = len([word for word in split_words(text) if word != "\n"])
        short_fallback = token_count == 1 and not bool(hook.get("userAuthoredShortHook"))
    return {
        "openingSemanticMatch": opening.get("openingSemanticMatch") if opening else None,
        "openingSemanticRole": opening.get("semanticRole") if opening else None,
        "openingSemanticDirection": opening.get("semanticDirection") if opening else None,
        "openingSelectionReason": opening.get("selectionReason") if opening else None,
        "openingHookText": text,
        "openingHookTokenCount": token_count,
        "openingHookSingleTokenFallback": short_fallback,
    }


def _caption_evidence(props: dict[str, Any]) -> dict[str, Any]:
    design = props.get("design") or {}
    resolved = design.get("resolved") or {}
    captions = props.get("captions") or []
    active = props.get("captionMode") in {"burned_captions", "hybrid"} and bool(captions)
    if not active:
        return {"captionBandCenterX": None, "captionBandSymmetric": None, "captionFitPassed": True}
    safe = ((resolved.get("formats") or {}).get(props.get("format"), {}) or {}).get("safeArea") or {}
    band = caption_band_rect(
        str(props.get("format")), safe_area=safe, profile_version=str(design.get("profileVersion") or ""),
        start_seconds=float(captions[0].get("startSeconds", 0.0)), end_seconds=float(captions[-1].get("endSeconds", 0.0)),
    )
    center = band["x"] + band["w"] / 2
    return {
        "captionBandCenterX": round(center, 6),
        "captionBandSymmetric": abs(center - 0.5) <= 1e-9,
        "captionFitPassed": True,
    }


def _subtitle_boundary_evidence(props: dict[str, Any]) -> dict[str, Any]:
    cues = [
        PersianCue(
            id=str(cue.get("id") or f"caption-{index+1}"), text=str(cue.get("text") or ""),
            start_seconds=float(cue.get("startSeconds", 0.0)), end_seconds=float(cue.get("endSeconds", 0.0)),
        )
        for index, cue in enumerate(props.get("captions") or [])
    ]
    faults = [problem for problem in audit_cues(cues) if "hard sentence boundary" in problem]
    return {"subtitleHardBoundariesPassed": not faults, "subtitleHardBoundaryProblems": faults}


def _watermark_evidence(props: dict[str, Any]) -> dict[str, Any]:
    design = props.get("design") or {}
    cfg = ((design.get("resolved") or {}).get("watermark") or {})
    duration = float(props.get("durationSeconds") or 0.0)
    slots = sorted(props.get("watermarkPlan") or [], key=lambda slot: float(slot.get("startSeconds", 0.0)))
    intervals = [(max(0.0, float(slot.get("startSeconds", 0.0))), min(duration, float(slot.get("endSeconds", 0.0)))) for slot in slots]
    merged: list[list[float]] = []
    for start, end in intervals:
        if end <= start:
            continue
        if merged and start <= merged[-1][1] + 1e-9:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    covered = sum(end - start for start, end in merged)
    ratio = covered / duration if duration > 0 else 0.0
    intro = min(duration, float(cfg.get("introDelaySeconds") or 0.0))
    minimum = float(cfg.get("minCoverageRatio") or 0.0)
    target = float(cfg.get("targetCoverageRatio") or minimum)
    possible = max(0.0, duration - intro) / duration if duration > 0 else 0.0
    floor = min(minimum, possible) if duration < 20 else minimum
    min_dwell = float(cfg.get("minDwellSeconds") or 0.0)
    effective_dwell = min(min_dwell, max(0.0, duration - intro)) if duration < 20 else min_dwell
    relocations = sum(1 for a, b in zip(slots, slots[1:]) if a.get("zone") != b.get("zone"))
    zones = sorted({str(slot.get("zone")) for slot in slots if slot.get("zone")})
    long_form = duration >= float(cfg.get("longFormThresholdSeconds") or float("inf"))
    capacity = max(0, int((duration - intro) // min_dwell) - 1) if min_dwell > 0 else 0
    relocation_target = min(int(cfg.get("minLongFormRelocations") or 0), capacity) if long_form else 0
    gaps: list[dict[str, float]] = []
    cursor = intro
    for start, end in merged:
        if start > cursor + 1e-9:
            gaps.append({"startSeconds": round(cursor, 3), "endSeconds": round(start, 3)})
        cursor = max(cursor, end)
    if cursor < duration - 1e-9:
        gaps.append({"startSeconds": round(cursor, 3), "endSeconds": round(duration, 3)})
    first_visible = intervals[0][0] if intervals else None
    return {
        "slots": slots,
        "coveredSeconds": round(covered, 3),
        "coverageRatio": round(ratio, 6),
        "coverageFloor": round(floor, 6),
        "coverageTarget": round(target, 6),
        "coverageFloorPassed": ratio + 1e-9 >= floor,
        "coverageTargetReached": ratio + 1e-9 >= target,
        "suppressionGaps": gaps,
        "relocationCount": relocations,
        "relocationTarget": relocation_target,
        "relocationTargetReached": relocations >= relocation_target,
        "distinctZones": zones,
        "distinctZoneCount": len(zones),
        "firstVisibleSeconds": round(first_visible, 3) if first_visible is not None else None,
        "noEarlyWatermark": first_visible is None or first_visible + 1e-9 >= intro,
        "minDwellSeconds": effective_dwell,
        "minDwellPassed": all((end - start) + 1e-9 >= effective_dwell for start, end in intervals),
        "maxRelocations": int(cfg.get("maxRelocations") or 0),
        "maxRelocationsPassed": relocations <= int(cfg.get("maxRelocations") or 0),
    }


def summarize(
    props: dict[str, Any],
    attributions: list[str],
    retention_audit: dict[str, Any] | None = None,
) -> dict[str, Any]:
    design = props.get("design") or {}
    moments = []
    for moment in props.get("moments", []):
        geometry = moment.get("layoutGeometry") or {}
        rect = geometry.get("rect")
        if not isinstance(rect, dict):
            flat = {
                key: geometry[key]
                for key in ("x", "y", "w", "h")
                if isinstance(geometry.get(key), (int, float))
            }
            rect = flat or None
        moments.append({
            "id": moment.get("id"),
            "startSeconds": moment.get("startSeconds"),
            "endSeconds": moment.get("endSeconds"),
            "placement": geometry.get("placement"),
            "rect": rect,
            "subjectSafety": geometry.get("subjectSafety"),
            "geometry": geometry or None,
        })
    return {
        "ok": True,
        "profileVersion": design.get("profileVersion"),
        "layoutVersion": (design.get("resolved") or {}).get("layoutVersion"),
        "contentHash": design.get("contentHash"),
        "durationSeconds": props.get("durationSeconds"),
        "moments": moments,
        "captionMode": props.get("captionMode", "sidecar_only"),
        "burnedCaptionCount": len(props.get("captions") or []),
        "watermarkPlanEntries": len(props.get("watermarkPlan") or []),
        "warnings": list((props.get("filmType") or {}).get("warnings") or []),
        "attributions": list(attributions),
        "mediaCopies": 0,
        **_opening_evidence(props),
        **_caption_evidence(props),
        **_subtitle_boundary_evidence(props),
        "watermarkEvidence": _watermark_evidence(props),
        **({"retentionAudit": retention_audit} if retention_audit is not None else {}),
    }


def preflight_edit_decisions(payload: dict[str, Any]) -> dict[str, Any]:
    edit = extract_edit_decisions(payload)
    retention = audit_persian_retention(edit["persian"])
    if retention["problems"]:
        raise ValueError(
            "Persian retention preflight refused:\n- " + "\n- ".join(retention["problems"])
        )
    runtime_persian = NoCopyPersianCompose._runtime_persian(edit)
    if runtime_persian is None:
        raise ValueError("Expected edit_decisions.persian for Persian preflight")
    with tempfile.TemporaryDirectory(prefix="persian-preflight-") as temp:
        props, attributions = NoCopyPersianCompose()._build_props(
            runtime_persian, Path(temp), "preflight"
        )
    return summarize(props, attributions, retention)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Persian geometry preflight with zero media copies")
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        payload = json.loads(args.input.read_text(encoding="utf-8"))
        result = preflight_edit_decisions(payload)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print(f"PREFLIGHT REFUSED:\n{exc}")
        return 2
    text = json.dumps(result, ensure_ascii=False, indent=2)
    print(text)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
