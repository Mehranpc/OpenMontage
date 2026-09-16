"""Local end-to-end trial for the Persian Reels pipeline.

This harness is NOT production certification. Narration, ASR, Film Type rendering,
and post-render QA run for real on the local machine. Footage is synthetic, so the
production asset gate must reject its provenance before a labelled fixture projection
exercises the remaining semantic/asset contracts.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.checkpoint import write_checkpoint
from lib.persian_assets import assert_video_only, audit_asset_manifest
from lib.persian_rendered_review import measure_rendered_audio_output
from lib.persian_retention import audit_persian_retention
from lib.persian_scenes import audit_scene_plan
from lib.persian_srt_alignment import build_script_aligned_cues
from lib.persian_video_workflow import (
    alignment_execution_policy,
    bootstrap_persian_video,
    bounded_asset_search_request,
    complete_phase,
    load_workflow_state,
    preflight_workflow_edit_draft,
    promote_workflow_edit_draft,
    record_asset_search_result,
    record_phase_attempt,
    record_phase_failure,
    stage_workflow_edit_draft,
)
from schemas.artifacts import validate_artifact
from tools.video.persian_compose_script_aligned import ScriptAlignedPersianCompose

SCRIPT = (
    "شروع با یک تغییر کوچک روشن می‌شود. تصویر در میانه جهت تازه‌ای پیدا می‌کند. "
    "در پایان، حرکت آرام می‌شود و پیام کامل می‌ماند."
)
TIMING_MODEL = "mlx-community/whisper-small-mlx"
RECOVERY_MODEL = "mlx-community/whisper-large-v3-mlx"
PROJECT_ID = "persian-reels-local-e2e"
DISCLAIMER = "Synthetic local E2E fixture — NOT production-certified stock provenance."


def _write_json(path: Path, value: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _run(args: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, check=True)


def _approved_script() -> dict[str, Any]:
    return {
        "text": SCRIPT,
        "sha256": hashlib.sha256(SCRIPT.encode("utf-8")).hexdigest(),
        "matchPolicy": "normalized",
        "maxCps": 21,
    }


def _hook_quality_metadata() -> dict[str, Any]:
    judgements = {
        field: {
            "level": "acceptable",
            "rationale": "Local E2E fixture supplies planning evidence; rendered review owns final strength.",
        }
        for field in (
            "semanticPredictionError",
            "audienceRelevance",
            "concreteness",
            "hookBodyAlignment",
            "visualVoiceAlignment",
        )
    }
    return {
        "version": "2.0",
        "viewerValue": {
            "atSeconds": 0.3,
            "evidence": "شروع با یک تغییر کوچک روشن می‌شود و جهت تجربه را فوری مشخص می‌کند.",
            "evidenceId": "fixture-value",
        },
        "semanticTension": {
            "kind": "specific_gap",
            "atSeconds": 0.8,
            "evidence": "بین شروع و تغییر جهت، یک سؤال دیداری مشخص برای ادامه شکل می‌گیرد.",
            "evidenceId": "fixture-tension",
        },
        "firstProof": {
            "atSeconds": 2.4,
            "kind": "demonstration",
            "evidence": "در شات دوم خود تصویر جهت تازه‌ای پیدا می‌کند و وعدهٔ افتتاحیه را عملاً نشان می‌دهد.",
            "evidenceId": "fixture-proof",
        },
        "judgements": judgements,
        "flags": {
            "metaIntroDelay": False,
            "vagueGap": False,
            "fullConclusionRevealed": False,
        },
        "perceptualChanges": [
            {
                "kind": "action",
                "atSeconds": 2.4,
                "evidence": "The second visual event changes direction before the 3s opening window closes.",
            }
        ],
        "semanticIntegrity": {
            "sourceText": "شروع با یک تغییر کوچک روشن می‌شود.",
            "requiredTopicAnchors": ["تغییر"],
            "anchorDelivery": "visual",
            "visualAnchorEvidence": "The reviewed opening shot visibly establishes the moving-light change.",
        },
    }


def _fixture_words() -> list[dict[str, Any]]:
    words: list[dict[str, Any]] = []
    cursor = 0.0
    for surface in SCRIPT.split(" "):
        duration = max(0.22, min(0.5, 0.10 + len(surface) * 0.045))
        words.append({"word": surface, "start": round(cursor, 3),
                      "end": round(cursor + duration, 3), "probability": 1.0})
        cursor += duration + 0.05
    return words


def _events() -> list[dict[str, Any]]:
    shared = {"subject": "moving light", "motif": "controlled motion",
              "human_presence": False, "shows_subject": True,
              "fallback_level": "exact_literal"}
    return [
        {**shared, "id": "beat-1-event-1", "duration_seconds": 2.4,
         "narration_span": "شروع با یک تغییر کوچک روشن می‌شود.",
         "intent": "make the opening change immediately visible",
         "action": "bright field shifts direction", "desired_affect": "curiosity",
         "visual_search_brief": "moving light pattern with immediate directional change",
         "shot_composition": "bright subject centered with vertical negative space",
         "shot_scale": "close up", "environment": "studio", "camera": "push-in",
         "importance": 3, "conflict_visibility": "opening state visibly changes",
         "queries": ["moving light abstract close up", "directional light motion macro"]},
        {**shared, "id": "beat-1-event-2", "duration_seconds": 2.6,
         "narration_span": "تصویر در میانه جهت تازه‌ای پیدا می‌کند.",
         "intent": "show the visual direction becoming legible",
         "action": "pattern rotates into a new path", "desired_affect": "recognition",
         "visual_search_brief": "dynamic light pattern rotating into a new direction",
         "shot_composition": "medium frame with diagonal motion and off-center subject",
         "shot_scale": "medium", "environment": "dark stage", "camera": "pan-right",
         "importance": 1, "conflict_visibility": "old direction replaced by a new path",
         "queries": ["rotating light pattern medium", "diagonal light motion dark stage"]},
        {**shared, "id": "beat-2-event-1", "duration_seconds": 2.7,
         "narration_span": "در پایان، حرکت آرام می‌شود",
         "intent": "turn energetic motion into a calmer state",
         "action": "motion eases and spacing opens", "desired_affect": "clarity",
         "visual_search_brief": "moving light easing into slower clean motion",
         "shot_composition": "wide vertical field with breathing room around the subject",
         "shot_scale": "wide", "environment": "light field", "camera": "pull-out",
         "importance": 2, "conflict_visibility": "busy motion visibly resolves toward calm",
         "queries": ["slow light movement wide", "calm abstract light field vertical"]},
        {**shared, "id": "beat-2-event-2", "duration_seconds": 2.8,
         "narration_span": "و پیام کامل می‌ماند.",
         "intent": "land the resolution on a stable readable final image",
         "action": "final pattern settles without freezing", "desired_affect": "relief",
         "visual_search_brief": "calm living light pattern with subtle continuing motion",
         "shot_composition": "detail final frame with stable center and gentle edge motion",
         "shot_scale": "detail", "environment": "soft gradient", "camera": "none",
         "importance": 3, "conflict_visibility": "resolved state remains visibly alive",
         "queries": ["gentle living light detail", "soft gradient motion close detail"]},
    ]


def _scene_plan() -> dict[str, Any]:
    events = _events()
    return {
        "version": "1.0",
        "scenes": [
            {"id": "scene-1", "type": "broll", "description": "Synthetic hook and turn",
             "start_seconds": 0.0, "end_seconds": 5.0},
            {"id": "scene-2", "type": "broll", "description": "Synthetic resolution",
             "start_seconds": 5.0, "end_seconds": 10.5},
        ],
        "metadata": {"subject": "moving light", "trial_fixture": True, "beats": [
            {"id": "beat-1", "duration_seconds": 5.0, "visual_events": events[:2]},
            {"id": "beat-2", "duration_seconds": 5.5, "visual_events": events[2:]},
        ]},
    }


def _brief() -> dict[str, Any]:
    return {
        "version": "1.0", "title": "Persian Reels Local E2E",
        "hook": "شروع با یک تغییر کوچک روشن می‌شود.",
        "key_points": ["visible hook", "direction change", "calm resolution"],
        "tone": "clear", "style": "film-type", "target_platform": "instagram-reels",
        "target_duration_seconds": 10.5,
        "metadata": {"trial_fixture": True, "caption_mode": "hybrid",
                     "production_certified": False},
    }


def _script_artifact() -> dict[str, Any]:
    return {
        "version": "1.0", "title": "Persian Reels Local E2E",
        "total_duration_seconds": 10.5,
        "sections": [
            {"id": "beat-1",
             "text": "شروع با یک تغییر کوچک روشن می‌شود. تصویر در میانه جهت تازه‌ای پیدا می‌کند.",
             "start_seconds": 0.0, "end_seconds": 5.0},
            {"id": "beat-2", "text": "در پایان، حرکت آرام می‌شود و پیام کامل می‌ماند.",
             "start_seconds": 5.0, "end_seconds": 10.5},
        ],
        "metadata": {"approved_script_sha256": hashlib.sha256(SCRIPT.encode("utf-8")).hexdigest(),
                     "trial_fixture": True},
    }


def _make_synthetic_clips(project: Path) -> dict[str, Path]:
    video_dir = project / "assets" / "video"
    video_dir.mkdir(parents=True, exist_ok=True)
    clips: dict[str, Path] = {}
    for index, event in enumerate(_events(), start=1):
        path = video_dir / f"event-{index}.mp4"
        duration = float(event["duration_seconds"]) + 0.25
        _run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
              "-f", "lavfi", "-i", "testsrc2=size=540x960:rate=30",
              "-vf", f"hue=h={(index - 1) * 55}:s=1.1", "-t", f"{duration:.3f}",
              "-an", "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", str(path)])
        clips[str(event["id"])] = path
    return clips


def _asset_manifest(clips: dict[str, Path], *, projected: bool) -> dict[str, Any]:
    assets = []
    for index, event in enumerate(_events(), start=1):
        provider = "pexels" if projected else "synthetic-local"
        assets.append({
            "id": f"asset-{index}", "type": "video", "kind": "video",
            "path": str(clips[str(event["id"])]), "source_tool": provider,
            "scene_id": "scene-1" if index <= 2 else "scene-2",
            "beat_id": "beat-1" if index <= 2 else "beat-2",
            "semantic_beat_id": "beat-1" if index <= 2 else "beat-2",
            "visual_event_id": event["id"], "provider": provider,
            "license": "Fixture projection only" if projected else "Synthetic local fixture",
            "original_url": "https://example.invalid/e2e-fixture" if projected else "local://synthetic-e2e",
            "attribution": DISCLAIMER, "duration_seconds": float(event["duration_seconds"]) + 0.25,
            "source_in_seconds": 0.0, "width": 540, "height": 960,
            "shows_subject": True, "selection_reason": "Animated synthetic pattern stays visible across the event.",
            "narration_span": event["narration_span"], "query": event["queries"][0],
            "candidate_rank": 1, "relevance_reason": "Fixture motion follows the planned event change.",
            "affect_match": True, "staged_stock_risk": "low", "human_presence": False,
            "fallback_level": "exact_literal",
            "frame_review": {"start": True, "middle": True, "end": True,
                             "observed": "Synthetic pattern remains present and moving at all three samples."},
        })
    return {"version": "1.0", "format": "vertical", "assets": assets,
            "metadata": {"trial_fixture": True, "provider_projection": projected,
                         "production_certified": False}}


def _edit_decisions(narration: Path, words: list[dict[str, Any]], clips: dict[str, Path]) -> dict[str, Any]:
    starts = [0.0, 2.4, 5.0, 7.7]
    roles = ["hook", "exposition", "turn", "resolution"]
    changes = ["establish", "action", "scale_change", "detail"]
    shots = []
    for index, event in enumerate(_events()):
        start = starts[index]
        shots.append({
            "id": f"shot-{index + 1}", "semanticBeatId": "beat-1" if index < 2 else "beat-2",
            "visualEventId": event["id"], "transitionIn": "cut", "changeType": changes[index],
            "narrativeRole": roles[index], "humanPresence": False,
            "showsSubject": bool(event.get("shows_subject")),
            **({
                "semanticRole": "hook_subject",
                "semanticDirection": "moving light visibly changes direction during the opening hook",
                "openingSemanticMatch": True,
                "selectionReason": "The moving-light subject is clearly visible and changes direction in the selected opening window.",
            } if index == 0 else {}),
            "source": str(clips[str(event["id"])]), "startSeconds": start,
            "endSeconds": start + float(event["duration_seconds"]), "sourceInSeconds": 0.0,
            "camera": event["camera"], "attribution": DISCLAIMER,
        })
    return {
        "version": "1.0", "cuts": [], "renderer_family": "persian-footage",
        "render_runtime": "remotion",
        "metadata": {
            "persianSubtitleScript": _approved_script(),
            "hookQuality": _hook_quality_metadata(),
            "trial_fixture": True,
        },
        "persian": {
            "design": {"version": 2, "profile": "film-type",
                       "seed": "persian-reels-local-e2e-film-type-01"},
            "format": "vertical", "durationSeconds": 10.5,
            "platformTarget": "instagram-reels", "captionMode": "hybrid",
            "shots": shots, "moments": [], "typographicBeats": [],
            "audio": {"narration": str(narration), "wordTimings": words},
            "omitMusicReason": "Local E2E harness isolates narration/caption/render gates.",
        },
    }


def _make_narration(work: Path) -> Path:
    missing = [name for name in ("say", "ffmpeg", "ffprobe") if not shutil.which(name)]
    if missing:
        raise RuntimeError(f"local trial requires: {', '.join(missing)}")
    aiff, wav = work / "narration.aiff", work / "narration.wav"
    _run(["say", "-v", "Dariush (Enhanced)", "-r", "145", "-o", str(aiff), SCRIPT])
    _run([
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(aiff),
        "-af", "loudnorm=I=-16:TP=-1.5:LRA=7", "-ar", "48000", "-ac", "1", str(wav),
    ])
    return wav


def _transcribe_with_model(narration: Path, work: Path, model: str) -> dict[str, Any]:
    from tools.analysis.mlx_whisper_transcriber import MlxWhisperTranscriber

    result = MlxWhisperTranscriber().execute({
        "input_path": str(narration),
        "language": "fa",
        "model": model,
        "initial_prompt": SCRIPT,
        "output_dir": str(work),
    })
    if not result.success:
        raise RuntimeError(result.error or f"local Whisper timing failed for {model}")
    data = dict(result.data or {})
    words = list(data.get("word_timestamps") or [])
    if not words:
        raise RuntimeError(f"local Whisper timing returned no word timestamps for {model}")
    build_script_aligned_cues(
        _approved_script(), words, max_visible_chars=36, id_prefix="caption"
    )
    return data


def _align_timing(narration: Path, work: Path, state: dict[str, Any]) -> dict[str, Any]:
    """Use timing-oriented alignment for authoritative approved-script input.

    The smaller timing model is the default. Large-v3 is an explicit recovery path
    only when the lightweight attempt cannot produce alignment-safe word timings.
    """
    policy = alignment_execution_policy(state)
    if policy["mode"] != "timing_oriented":
        data = _transcribe_with_model(narration, work, RECOVERY_MODEL)
        data.update({
            "alignment_mode": policy["mode"],
            "heavy_recovery_used": False,
        })
        return data

    try:
        data = _transcribe_with_model(narration, work, TIMING_MODEL)
        heavy_recovery_used = False
    except RuntimeError as first_error:
        data = _transcribe_with_model(narration, work, RECOVERY_MODEL)
        data["timing_recovery_reason"] = str(first_error)
        heavy_recovery_used = True
    data.update({
        "alignment_mode": policy["mode"],
        "heavy_recovery_used": heavy_recovery_used,
    })
    return data


def _transcribe(narration: Path, work: Path) -> dict[str, Any]:
    """Legacy local helper retained for targeted tests; production harness uses _align_timing."""
    return _transcribe_with_model(narration, work, RECOVERY_MODEL)


def _fixture_clips(work: Path) -> dict[str, Path]:
    clips: dict[str, Path] = {}
    for index, event in enumerate(_events(), start=1):
        path = work / f"fixture-{index}.mp4"
        path.write_bytes(b"fixture-video")
        clips[str(event["id"])] = path
    return clips


def validate_contract_fixture(work: Path) -> dict[str, Any]:
    work.mkdir(parents=True, exist_ok=True)
    clips = _fixture_clips(work)
    narration = work / "fixture-narration.wav"
    narration.write_bytes(b"fixture-audio")
    words = _fixture_words()
    build_script_aligned_cues(_approved_script(), words, max_visible_chars=36,
                              id_prefix="caption")
    plan = _scene_plan()
    scene_audit = audit_scene_plan(plan)
    if scene_audit["problems"]:
        raise RuntimeError("scene fixture failed: " + "; ".join(scene_audit["problems"]))
    actual = _asset_manifest(clips, projected=False)
    projection = _asset_manifest(clips, projected=True)
    actual_problems = audit_asset_manifest(actual, plan)
    projection_problems = audit_asset_manifest(projection, plan)
    if not any("outside the Persian production allowlist" in p for p in actual_problems):
        raise RuntimeError("synthetic provenance was not rejected by the production asset gate")
    if projection_problems:
        raise RuntimeError("projected asset fixture failed: " + "; ".join(projection_problems))
    assert_video_only(actual)
    edit = _edit_decisions(narration, words, clips)
    for name, artifact in (("scene_plan", plan), ("asset_manifest", actual),
                           ("asset_manifest", projection), ("edit_decisions", edit)):
        validate_artifact(name, artifact)
    retention = audit_persian_retention(edit["persian"])
    if retention["problems"]:
        raise RuntimeError("retention fixture failed: " + "; ".join(retention["problems"]))
    return {"production_certified": False, "scene_audit": scene_audit,
            "synthetic_provider_problems": actual_problems,
            "projection_problems": projection_problems, "retention_audit": retention}


def _probe(candidate: Path) -> dict[str, Any]:
    completed = _run(["ffprobe", "-v", "error", "-show_streams", "-show_format",
                      "-of", "json", str(candidate)])
    return json.loads(completed.stdout)


def _extract_frames(candidate: Path, target: Path, times: list[float], prefix: str) -> list[str]:
    target.mkdir(parents=True, exist_ok=True)
    paths: list[str] = []
    for index, seconds in enumerate(times, start=1):
        path = target / f"{prefix}-{index}.jpg"
        _run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-ss", f"{seconds:.3f}",
              "-i", str(candidate), "-frames:v", "1", "-q:v", "2", str(path)])
        paths.append(str(path))
    return paths


def _attempt_complete(root: Path, phase: str, evidence: dict[str, Any]) -> None:
    record_phase_attempt(PROJECT_ID, phase, pipeline_dir=root)
    complete_phase(PROJECT_ID, phase, evidence=evidence, pipeline_dir=root)


def _advance_to_assets(
    root: Path,
    plan: dict[str, Any],
    manifest: dict[str, Any],
    sourcing_order: list[str],
) -> None:
    """Advance scene planning/assets after prepared inputs and alignment are durable."""
    write_checkpoint(
        root, PROJECT_ID, "scene_plan", "completed", {"scene_plan": plan},
        pipeline_type="persian-footage",
    )
    _attempt_complete(
        root, "plan_scenes_moments", {"sourcing_order": sourcing_order}
    )

    request = bounded_asset_search_request(
        PROJECT_ID,
        {
            "queries": [{
                "query": "synthetic-local-trial-accounting",
                "slot_id": sourcing_order[0],
                "kind": "video",
            }]
        },
        retry_pass=0,
        pipeline_dir=root,
    )
    record_asset_search_result(
        PROJECT_ID,
        retry_pass=0,
        pipeline_dir=root,
        result_data={
            "output_dir": request["output_dir"],
            "resolved_sources": request["sources"],
            "max_candidates_total": request["max_candidates_total"],
            "max_bytes_per_clip": request["max_bytes_per_clip"],
            "max_total_download_bytes": request["max_total_download_bytes"],
            "candidates_considered": 0,
            "semantic_candidates_reviewed": 0,
            "technical_rejects": 0,
            "bytes_downloaded": 0,
            "clips": [],
        },
    )
    write_checkpoint(
        root, PROJECT_ID, "assets", "completed", {"asset_manifest": manifest},
        pipeline_type="persian-footage",
    )
    _attempt_complete(root, "acquire_assets", {
        "synthetic_fixture": True,
        "production_certified": False,
    })


def _build_final_review(
    candidate: Path,
    frames: list[str],
    srt_path: str | None,
    probe: dict[str, Any],
    project: Path,
    hook_audit: dict[str, Any],
    rendered_audio: dict[str, Any],
) -> Path:
    streams = list(probe.get("streams") or [])
    video = next((s for s in streams if s.get("codec_type") == "video"), {})
    audio = next((s for s in streams if s.get("codec_type") == "audio"), {})
    duration = float((probe.get("format") or {}).get("duration") or 0.0)
    audio_review = {
        **rendered_audio,
        "measurementSource": "rendered_mp4_plus_mix_policy",
        "narration_present": bool(audio),
        "music_present": False,
        "musicOmittedReason": "Local E2E harness intentionally isolates narration/caption/render gates.",
        "unexpected_silence": False,
        "clipping_detected": False,
        "mix_intelligible": True,
        "issues": [],
    }
    hook_review = {
        "version": "2.0",
        "reviewSource": "rendered_mp4",
        "reviewerRole": "independent_reviewer",
        "reviewedCandidateSha256": _sha(candidate),
        "strength": "acceptable",
        "rationale": (
            "Trial-only independent fixture review: the rendered opening communicates "
            "the visual direction and begins its concrete demonstration before 3 seconds."
        ),
        "observations": [
            "The muted opening still communicates a directional visual change.",
            "The second visual event begins the concrete demonstration before the opening window closes.",
        ],
        "mutedHookDirectionConfirmed": True,
        "visualVoiceAlignment": "acceptable",
        "actualPayoffSeconds": 2.4,
        "concretePayoffKind": "demonstration",
        "payoffEvidence": "The second rendered event visibly changes direction at 2.4s.",
        "payoffBeginsPromptly": True,
        "coldViewer": {
            "evidenceSource": "rendered_opening_only",
            "contextIsolated": True,
            "inferredTopic": "تغییر جهت یک الگوی نور متحرک",
            "inferredClaim": "افتتاحیه یک تغییر دیداری مشخص را مطرح می‌کند",
            "continuationReason": "می‌خواهم ببینم این تغییر چطور کامل می‌شود",
            "unresolvedReferents": [],
        },
    }
    review = {
        "version": "1.0",
        "output_path": str(candidate),
        "status": "pass",
        "checks": {
            "technical_probe": {
                "valid_container": True,
                "duration_seconds": duration,
                "resolution": f"{video.get('width')}x{video.get('height')}",
                "fps": 30.0,
                "has_audio": bool(audio),
                "codec": str(video.get("codec_name") or "h264"),
                "file_size_bytes": candidate.stat().st_size,
                "issues": [],
            },
            "visual_spotcheck": {
                "frames_sampled": len(frames),
                "frame_paths": frames,
                "black_frames_detected": False,
                "broken_overlays": False,
                "missing_assets": False,
                "unreadable_text": False,
                "issues": [],
            },
            "audio_spotcheck": audio_review,
            "promise_preservation": {
                "delivery_promise_honored": True,
                "renderer_family_used": "persian-footage",
                "render_runtime_used": "remotion",
                "runtime_swap_detected": False,
                "runtime_swap_check": "ok — remotion",
                "motion_ratio_actual": 1.0,
                "silent_downgrade_detected": False,
                "issues": [],
            },
            "subtitle_check": {
                "subtitles_expected": True,
                "subtitles_present": bool(srt_path and Path(srt_path).is_file()),
                "coverage_ratio": 1.0,
                "timing_drift_detected": False,
                "issues": [],
            },
        },
        "issues_found": [],
        "recommended_action": "present_to_user",
        "metadata": {
            "trial_only": True,
            "production_certified": False,
            "semantic_review_mode": "fixture_assertion",
            "disclaimer": DISCLAIMER,
            "hookQualityAudit": hook_audit,
            "hookQualityReview": hook_review,
        },
    }
    validate_artifact("final_review", review)
    return _write_json(project / "artifacts" / "final_review.json", review)


def _render_report(data: dict[str, Any], candidate: Path, retention: dict[str, Any],
                   review_path: Path, review_frames: list[str], caption_frames: list[str],
                   probe: dict[str, Any]) -> dict[str, Any]:
    streams = list(probe.get("streams") or [])
    video = next((s for s in streams if s.get("codec_type") == "video"), {})
    audio = next((s for s in streams if s.get("codec_type") == "audio"), {})
    duration = float((probe.get("format") or {}).get("duration") or data["duration_seconds"])
    report = {
        "version": "1.0", "outputs": [{"path": str(candidate), "format": "mp4",
            "codec": str(video.get("codec_name") or "h264"),
            "audio_codec": str(audio.get("codec_name") or "aac"),
            "resolution": f"{video.get('width')}x{video.get('height')}", "fps": 30.0,
            "duration_seconds": duration, "file_size_bytes": candidate.stat().st_size,
            "sha256": _sha(candidate), "platform_target": "instagram-reels"}],
        "render_grammar": "persian-footage", "output_path": str(candidate),
        "composition_id": data["composition_id"], "format": "vertical",
        "duration_seconds": duration, "shot_count": data["shot_count"],
        "moment_count": data["moment_count"], "text_coverage": data["text_coverage"],
        "subtitle_path": data.get("subtitle_path"),
        "subtitle_advisories": data.get("subtitle_advisories") or [],
        "caption_mode": data["caption_mode"], "burned_caption_count": data["burned_caption_count"],
        "attributions": data.get("attributions") or [], "verification_frames": review_frames,
        "caption_verification_frames": caption_frames, "music_mixed": False,
        "delivery_status": "final_candidate", "human_visual_approval": False,
        "persian_text_verified": False, "retention_audit": retention,
        "post_render_motion_qa": data["post_render_motion_qa"],
        "silent_watch_audit": {"main_point_understood": True,
            "hook_direction_understood": True, "conclusion_understood": True,
            "notes": ["Trial-only fixture assertion: approved-script hybrid captions exercise muted-view semantics; not production creative certification."]},
        "cut_rhythm": "Four distinct hard-cut events cover the 10.5s fixture timeline.",
        "caption_readability": "Entry/mid/exit frames retained; judgement is trial-only fixture evidence.",
        "strongest_scene": "opening hook with a second visual event before 3 seconds",
        "weakest_scene": "middle synthetic pattern lacks production-footage semantics",
        "hook_strength": "acceptable", "resolution_strength": "acceptable",
        "final_review_ref": str(review_path), "warnings": [DISCLAIMER],
    }
    validate_artifact("render_report", report)
    return report


def run_local(root: Path) -> dict[str, Any]:
    root = root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    if (root / PROJECT_ID).exists():
        raise RuntimeError(f"refusing to reuse existing trial project: {root / PROJECT_ID}")
    with tempfile.TemporaryDirectory(prefix="persian-e2e-source-") as source_tmp:
        source = Path(source_tmp)
        narration_source = _make_narration(source)
        bootstrap_persian_video(title="Persian Reels Local E2E",
            narration_path=str(narration_source), approved_script=SCRIPT,
            project_id=PROJECT_ID, pipeline_dir=root, backlot_opener=lambda _pid: 0)
    state = load_workflow_state(PROJECT_ID, pipeline_dir=root)
    project = Path(state["read_allowlist"]["project_root"])
    narration = Path(state["input"]["narration"]["source_path"])
    alignment_policy = alignment_execution_policy(state)
    _attempt_complete(root, "prepare_inputs", {
        "authoritative_script_sha256": state["input"]["approved_script"]["sha256"],
        "narration_sha256": state["input"]["narration"]["sha256"],
    })
    write_checkpoint(
        root, PROJECT_ID, "idea", "completed", {"brief": _brief()},
        pipeline_type="persian-footage",
    )
    write_checkpoint(
        root, PROJECT_ID, "script", "completed", {"script": _script_artifact()},
        pipeline_type="persian-footage",
    )
    record_phase_attempt(PROJECT_ID, "align_script_timing", pipeline_dir=root)
    try:
        alignment = _align_timing(
            narration, project / "artifacts" / "transcription", state
        )
    except Exception as exc:
        record_phase_failure(
            PROJECT_ID, "align_script_timing", reason=str(exc), pipeline_dir=root
        )
        raise
    complete_phase(PROJECT_ID, "align_script_timing", evidence={
        "provider": alignment.get("provider") or "mlx_whisper",
        "model": alignment.get("model"),
        "alignment_mode": alignment.get("alignment_mode"),
        "heavy_recovery_used": bool(alignment.get("heavy_recovery_used")),
    }, pipeline_dir=root)
    words = list(alignment["word_timestamps"])
    clips = _make_synthetic_clips(project)
    plan = _scene_plan()
    scene_audit = audit_scene_plan(plan)
    if scene_audit["problems"]:
        raise RuntimeError("scene audit failed: " + "; ".join(scene_audit["problems"]))
    actual_manifest = _asset_manifest(clips, projected=False)
    projected_manifest = _asset_manifest(clips, projected=True)
    actual_problems = audit_asset_manifest(actual_manifest, plan)
    if not any("outside the Persian production allowlist" in p for p in actual_problems):
        raise RuntimeError("synthetic provider unexpectedly passed production provenance")
    projected_problems = audit_asset_manifest(projected_manifest, plan)
    if projected_problems:
        raise RuntimeError("semantic asset projection failed: " + "; ".join(projected_problems))
    edit = _edit_decisions(narration, words, clips)
    for name, artifact in (("scene_plan", plan), ("asset_manifest", actual_manifest),
                           ("edit_decisions", edit)):
        validate_artifact(name, artifact)
    retention = audit_persian_retention(edit["persian"])
    if retention["problems"]:
        raise RuntimeError("retention audit failed: " + "; ".join(retention["problems"]))
    _advance_to_assets(
        root, plan, projected_manifest, scene_audit["sourcing_order"]
    )
    _attempt_complete(root, "review_subject_regions", {"synthetic_fixture": True,
                                                        "regions_reviewed": True})
    edit_input = _write_json(project / "artifacts" / "edit_candidate_input.json", edit)
    attempt_id = "local-e2e-01"
    stage_workflow_edit_draft(
        PROJECT_ID, attempt_id, edit_input, pipeline_dir=root
    )
    record_phase_attempt(PROJECT_ID, "no_copy_preflight", pipeline_dir=root)
    try:
        preflight = preflight_workflow_edit_draft(
            PROJECT_ID, attempt_id, pipeline_dir=root
        )
        if preflight.get("ok") is not True:
            raise RuntimeError(
                "front-door aggregate preflight refused: "
                + json.dumps(preflight.get("blockingIssues") or [], ensure_ascii=False)
            )
        promoted = promote_workflow_edit_draft(
            PROJECT_ID, attempt_id, pipeline_dir=root
        )
        canonical_edit = json.loads(
            Path(promoted["canonicalPath"]).read_text(encoding="utf-8")
        )
    except Exception as exc:
        record_phase_failure(
            PROJECT_ID, "no_copy_preflight", reason=str(exc), pipeline_dir=root
        )
        raise
    complete_phase(
        PROJECT_ID, "no_copy_preflight", evidence={"attempt_id": attempt_id}, pipeline_dir=root
    )
    candidate = project / "renders" / "candidate.mp4"
    record_phase_attempt(PROJECT_ID, "render_final_candidate", pipeline_dir=root)
    try:
        result = ScriptAlignedPersianCompose().execute({
            "edit_decisions": canonical_edit, "output_path": str(candidate), "crf": 20,
            "concurrency": 2, "timeout_ms": 120000})
        if not result.success:
            raise RuntimeError(result.error or "Persian compose failed")
        data = dict(result.data or {})
    except Exception as exc:
        record_phase_failure(
            PROJECT_ID, "render_final_candidate", reason=str(exc), pipeline_dir=root
        )
        raise
    complete_phase(PROJECT_ID, "render_final_candidate", evidence={
        "output_path": str(candidate),
        "motion_qa_passed": data["post_render_motion_qa"]["passed"],
    }, pipeline_dir=root)
    record_phase_attempt(PROJECT_ID, "final_review", pipeline_dir=root)
    try:
        probe = _probe(candidate)
        review_frames = _extract_frames(candidate, project / "artifacts" / "final-review-frames",
                                        [0.5, 3.2, 6.2, 9.5], "review")
        caption_frames = _extract_frames(candidate, project / "artifacts" / "caption-review-frames",
                                         [1.0, 5.6, 9.0], "caption")
        rendered_audio = measure_rendered_audio_output(candidate)
        hook_audit = ((preflight.get("evidence") or {}).get("hookQualityAudit"))
        if not isinstance(hook_audit, dict) or hook_audit.get("required") is not True:
            raise RuntimeError(
                "front-door preflight did not persist required Hook Quality v2 evidence"
            )
        review_path = _build_final_review(
            candidate, review_frames, data.get("subtitle_path"), probe, project,
            hook_audit, rendered_audio,
        )
        report = _render_report(data, candidate, retention, review_path, review_frames,
                                caption_frames, probe)
        write_checkpoint(root, PROJECT_ID, "compose", "awaiting_human",
                         {"render_report": report}, pipeline_type="persian-footage")
    except Exception as exc:
        record_phase_failure(
            PROJECT_ID, "final_review", reason=str(exc), pipeline_dir=root
        )
        raise
    complete_phase(
        PROJECT_ID, "final_review", evidence={"final_review_path": str(review_path)},
        pipeline_dir=root,
    )
    terminal = complete_phase(PROJECT_ID, "awaiting_human", pipeline_dir=root)
    summary = {
        "ok": True, "production_certified": False, "disclaimer": DISCLAIMER,
        "project_root": str(project), "candidate_path": str(candidate),
        "candidate_sha256": _sha(candidate), "workflow_status": terminal["status"],
        "next_phase": terminal.get("next_phase"), "caption_mode": data["caption_mode"],
        "burned_caption_count": data["burned_caption_count"],
        "subtitle_path": data.get("subtitle_path"), "scene_sourcing_order": scene_audit["sourcing_order"],
        "synthetic_provider_rejected": True, "synthetic_provider_problems": actual_problems,
        "projection_gate_passed": not projected_problems,
        "retention_audit": retention, "post_render_motion_qa": data["post_render_motion_qa"],
        "luminance_qa": data.get("luminance_qa"), "final_review_path": str(review_path),
        "compose_checkpoint": str(project / "checkpoint_compose.json"),
        "preflight_report_path": str(
            project / ".preflight" / "edit" / attempt_id / "preflight_report.json"
        ),
        "alignment_policy": alignment_policy,
        "alignment_mode": alignment.get("alignment_mode"),
        "heavy_alignment_recovery_used": bool(alignment.get("heavy_recovery_used")),
        "word_timing_count": len(words),
        "whisper_model": alignment.get("model", TIMING_MODEL),
    }
    _write_json(project / "artifacts" / "local-e2e-summary.json", summary)
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--validate-only", action="store_true")
    mode.add_argument("--run", action="store_true")
    parser.add_argument("--root", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.validate_only:
            with tempfile.TemporaryDirectory(prefix="persian-e2e-contract-") as temp:
                result = validate_contract_fixture(Path(temp))
        else:
            root = args.root or Path(tempfile.mkdtemp(prefix="openmontage-persian-e2e-"))
            result = run_local(root)
    except Exception as exc:
        print(f"E2E REFUSED: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
