"""Run Persian compose preparation without copying media or writing checkpoints."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import tempfile
from typing import Any
from tools.video.persian_compose_script_aligned import ScriptAlignedPersianCompose
from lib.persian_retention import audit_persian_retention
from lib.persian_captions import caption_band_rect
from lib.persian_srt import PersianCue, audit_cues
from lib.persian_text import split_words
from lib.paths import REPO_ROOT
from lib.persian_edit_contract import (
    PersianEditContractError, collect_persian_edit_diagnostics, validate_persian_edit_contract,
)
from lib.persian_film_type import FilmTypePreflightError


class NoCopyPersianCompose(ScriptAlignedPersianCompose):
    @staticmethod
    def _stage(source: str | Path, staging: Path, name: str) -> str:
        del staging, name
        path = Path(source).expanduser()
        if not path.is_absolute():
            path = (REPO_ROOT / path).resolve()
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
    diversity_min_dwell = float(cfg.get("verticalDiversityMinDwellSeconds") or min_dwell)
    relocations = sum(1 for a, b in zip(slots, slots[1:]) if a.get("zone") != b.get("zone"))
    zones = sorted({str(slot.get("zone")) for slot in slots if slot.get("zone")})
    vertical_bands = sorted({zone.split("-", 1)[0] for zone in zones if "-" in zone})
    long_form = duration >= float(cfg.get("longFormThresholdSeconds") or float("inf"))
    capacity = max(0, int((duration - intro) // min_dwell) - 1) if min_dwell > 0 else 0
    relocation_target = min(int(cfg.get("minLongFormRelocations") or 0), capacity) if long_form else 0
    vertical_band_target = int(cfg.get("minLongFormVerticalBands") or 0) if long_form else 0
    gaps: list[dict[str, float]] = []
    cursor = intro
    for start, end in merged:
        if start > cursor + 1e-9:
            gaps.append({"startSeconds": round(cursor, 3), "endSeconds": round(start, 3)})
        cursor = max(cursor, end)
    if cursor < duration - 1e-9:
        gaps.append({"startSeconds": round(cursor, 3), "endSeconds": round(duration, 3)})
    first_visible = intervals[0][0] if intervals else None
    seen_bands: set[str] = set()
    diversity_exceptions = 0
    dwell_ok = True
    for slot, (start, end) in zip(slots, intervals):
        duration_slot = end - start
        zone = str(slot.get("zone") or "")
        band = zone.split("-", 1)[0] if "-" in zone else zone
        if duration_slot + 1e-9 >= effective_dwell:
            seen_bands.add(band)
            continue
        is_diversity_exception = (
            long_form and diversity_min_dwell > 0
            and duration_slot + 1e-9 >= diversity_min_dwell
            and bool(seen_bands) and band not in seen_bands
        )
        if is_diversity_exception:
            diversity_exceptions += 1
            seen_bands.add(band)
            continue
        dwell_ok = False
        seen_bands.add(band)
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
        "verticalBands": vertical_bands,
        "verticalBandCount": len(vertical_bands),
        "verticalBandTarget": vertical_band_target,
        "verticalBandTargetReached": len(vertical_bands) >= vertical_band_target,
        "firstVisibleSeconds": round(first_visible, 3) if first_visible is not None else None,
        "noEarlyWatermark": first_visible is None or first_visible + 1e-9 >= intro,
        "minDwellSeconds": effective_dwell,
        "verticalDiversityMinDwellSeconds": diversity_min_dwell if long_form else None,
        "diversityDwellExceptionCount": diversity_exceptions,
        "minDwellPassed": dwell_ok,
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
        "watermarkDiagnostics": props.get("watermarkDiagnostics"),
        **({"retentionAudit": retention_audit} if retention_audit is not None else {}),
    }


def preflight_edit_decisions(
    payload: dict[str, Any], *, base_dir: Path | None = None
) -> dict[str, Any]:
    edit = extract_edit_decisions(payload)
    # Contract validation is intentionally first: schema/path/music drift should
    # fail before retention logic or Chromium can turn it into a secondary error.
    validate_persian_edit_contract(edit, base_dir=base_dir)
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



def _artifact_sha256(edit: dict[str, Any]) -> str:
    encoded = json.dumps(edit, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _report(
    *,
    ok: bool,
    edit: dict[str, Any] | None,
    blocking: list[dict[str, Any]],
    warnings: list[Any] | None = None,
    evidence: dict[str, Any] | None = None,
    watermark_diagnostics: dict[str, Any] | None = None,
    next_actions: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "version": 1,
        "ok": ok,
        "status": "pass" if ok else "refused",
        "artifactSha256": _artifact_sha256(edit) if edit is not None else None,
        "blockingIssues": blocking,
        "warnings": list(warnings or []),
        "watermarkDiagnostics": watermark_diagnostics,
        "nextActions": list(next_actions or []),
        "mediaCopies": 0,
        "evidence": evidence or {},
    }


def aggregate_preflight_edit_decisions(
    payload: dict[str, Any], *, base_dir: Path | None = None
) -> dict[str, Any]:
    """Run every cheap gate first, then one browser pass, returning one durable report."""
    root = (base_dir or REPO_ROOT).resolve()
    try:
        edit = extract_edit_decisions(payload)
    except (ValueError, TypeError, KeyError) as exc:
        return _report(
            ok=False, edit=None,
            blocking=[{"code": "INPUT_SHAPE", "message": str(exc), "recoveryClass": "EDIT_ARTIFACT"}],
            next_actions=["Provide an edit_decisions artifact or Persian edit block."],
        )

    contract = collect_persian_edit_diagnostics(edit, base_dir=root)
    if contract:
        issues = [
            {
                "code": item.code,
                "path": item.pointer,
                "message": item.message,
                "recoveryClass": "EDIT_ARTIFACT",
                **({"hint": item.hint} if item.hint else {}),
            }
            for item in contract
        ]
        actions = [item.hint for item in contract if item.hint]
        return _report(ok=False, edit=edit, blocking=issues, next_actions=list(dict.fromkeys(actions)))

    retention = audit_persian_retention(edit["persian"])
    if retention["problems"]:
        return _report(
            ok=False, edit=edit,
            blocking=[
                {"code": "RETENTION_GATE", "message": problem, "recoveryClass": "EDIT_ARTIFACT"}
                for problem in retention["problems"]
            ],
            evidence={"retentionAudit": retention},
            next_actions=["Revise the edit decisions; do not weaken the retention gate."],
        )

    try:
        evidence = preflight_edit_decisions(edit, base_dir=root)
    except FilmTypePreflightError as exc:
        actions = [
            "Use watermarkDiagnostics.topBlockers and suppressionGaps to re-edit timing/placement or footage.",
            "Keep the configured coverage floor and subject-region safety unchanged.",
        ] if exc.diagnostics else ["Resolve the Film Type browser-preflight refusal and retry."]
        return _report(
            ok=False, edit=edit,
            blocking=[{
                "code": exc.code,
                "message": str(exc),
                "recoveryClass": "FILM_TYPE_LAYOUT",
                **({"details": exc.diagnostics} if exc.diagnostics else {}),
            }],
            evidence={"retentionAudit": retention},
            watermark_diagnostics=exc.diagnostics or None,
            next_actions=actions,
        )
    except (OSError, ValueError, TypeError, KeyError) as exc:
        return _report(
            ok=False, edit=edit,
            blocking=[{"code": "PREFLIGHT_RUNTIME", "message": str(exc), "recoveryClass": "PREFLIGHT_RUNTIME"}],
            evidence={"retentionAudit": retention},
            next_actions=["Fix the reported preflight runtime/input failure, then rerun the same draft."],
        )

    return _report(
        ok=True, edit=edit, blocking=[], warnings=evidence.get("warnings") or [], evidence=evidence,
        watermark_diagnostics=evidence.get("watermarkDiagnostics"),
    )


def _atomic_write_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def _default_report_path(input_path: Path) -> Path | None:
    resolved = input_path.expanduser().resolve()
    if resolved.parent.name == "artifacts":
        return resolved.parent.parent / ".preflight" / "preflight_report.json"
    return None


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Persian aggregate geometry/contract preflight with zero media copies")
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        payload = json.loads(args.input.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError) as exc:
        report = _report(
            ok=False, edit=None,
            blocking=[{"code": "INPUT_READ", "message": str(exc), "recoveryClass": "EDIT_ARTIFACT"}],
            next_actions=["Repair the JSON input and retry."],
        )
    else:
        report = aggregate_preflight_edit_decisions(payload, base_dir=REPO_ROOT)
    output = args.output or _default_report_path(args.input)
    if output is not None:
        _atomic_write_report(output, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
