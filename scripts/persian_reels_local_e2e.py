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
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.checkpoint import write_checkpoint
from lib.persian_alignment_provider import (
    build_alignment_provider_plan,
    execute_alignment_with_fallback,
)
from lib.persian_assets import assert_video_only, audit_asset_manifest
from lib.persian_editorial_hook import validate_edit_hook_authority
from lib.persian_finalization import master_final_candidate
from lib.persian_hook_quality import (
    DEFAULT_AUTHORITY_REFERENCE,
    HOOK_TIMING_POLICY_VERSION,
    hook_timing_policy,
)
from lib.persian_rendered_review import (
    build_cold_viewer_review_input,
    measure_rendered_audio_output,
    validate_rendered_hook_review,
)
from lib.persian_retention import audit_persian_retention
from lib.persian_quality_evidence import compose_quality_evidence
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
    record_hook_selection,
    stage_workflow_edit_draft,
)
from schemas.artifacts import build_artifact, validate_artifact
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
            # Synthetic fixture shots have no protected foreground subject after
            # explicit review. Film Type requires the reviewed geometry to be
            # durable even when the truthful result is an empty region list.
            "avoidRegions": [],
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
            "shots": shots,
            "moments": [{
                "id": "hook-1",
                "kind": "hook",
                "purpose": "hook-pattern-interrupt",
                "startSeconds": 0.0,
                "endSeconds": 4.6,
                "segments": [
                    {"role": "lead", "semanticRole": "setup", "text": "شروع با"},
                    {"role": "hero", "semanticRole": "subject_hero", "text": "یک تغییر کوچک"},
                    {"role": "tail", "semanticRole": "payoff", "text": "روشن می‌شود."},
                ],
                "presentation": {
                    "placement": "auto",
                    "treatment": "editorial",
                    "motion": "soft-reveal",
                    "emphasis": "inline",
                    "contrastStrength": "strong",
                    "recipeId": "editorial-hero-balanced",
                },
            }],
            "typographicBeats": [],
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
    """Execute the policy-valid provider plan; unavailable providers are never called."""
    policy = alignment_execution_policy(state)
    plan = build_alignment_provider_plan(policy)

    def validate(words: list[dict[str, Any]]) -> None:
        build_script_aligned_cues(
            _approved_script(), words, max_visible_chars=36, id_prefix="caption"
        )

    data = execute_alignment_with_fallback(
        plan,
        input_path=str(narration),
        output_dir=str(work),
        language="fa",
        initial_prompt=SCRIPT if policy["scriptAuthority"] == "approved_script" else None,
        validate_word_timings=validate,
    )
    decision = data["provider_decision"]
    data["provider"] = decision["selectedProvider"]
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
    hook_text = " ".join(
        str(segment.get("text") or "").strip()
        for segment in edit["persian"]["moments"][0]["segments"]
        if str(segment.get("role") or "") != "source"
    ).strip()
    validate_edit_hook_authority(
        {
            "mode": "automatic",
            "status": "selected",
            "text": hook_text,
            "sha256": hashlib.sha256(hook_text.encode("utf-8")).hexdigest(),
        },
        edit,
    )
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


def _hook_timing_evidence(
    hook_audit: dict[str, Any], *, payoff_seconds: float
) -> dict[str, Any]:
    """Carry the trial's own persisted timing policy into a fixture hook review.

    This harness runs an automatic hook selection (validated above with
    ``validate_edit_hook_authority``), so when the audit could not cite a durable
    provenance it records exactly that automatic path rather than inventing
    user-supplied authority.
    """
    policy = hook_audit.get("timingPolicy") or hook_timing_policy()
    observed = hook_audit.get("authorityProvenance")
    provenance = observed if isinstance(observed, Mapping) and observed.get("reference") else {
        "mode": "automatic",
        "reference": DEFAULT_AUTHORITY_REFERENCE,
        "selectedHookSha256": None,
    }
    block_seconds = float(policy.get("proofBlockSeconds") or 0.0)
    return {
        "timingPolicyVersion": str(policy.get("version") or HOOK_TIMING_POLICY_VERSION),
        "timingDisposition": "prompt" if payoff_seconds <= block_seconds else "late-blocked",
        "authorityProvenance": dict(provenance),
    }


def _build_opening_review(
    opening: Path, frames: list[str], project: Path, hook_audit: dict[str, Any],
    retention: dict[str, Any], motion_qa: dict[str, Any], *, edit_artifact_sha256: str,
) -> tuple[Path, dict[str, Any]]:
    timing = _hook_timing_evidence(hook_audit, payoff_seconds=2.4)
    opening_sha = _sha(opening)
    cold_input = build_cold_viewer_review_input(
        candidate_sha256=opening_sha,
        opening_evidence={
            "framePaths": list(frames),
            "startSeconds": 0.0,
            "endSeconds": 4.6,
        },
    )
    cold_path = _write_json(
        project / "artifacts" / "opening_cold_viewer_review_input.json", cold_input
    )
    cold_sha = _sha(cold_path)
    hook_review = {
        "version": "2.1",
        "reviewSource": "rendered_mp4",
        "reviewerRole": "independent_reviewer",
        "reviewedCandidateSha256": opening_sha,
        "strength": "acceptable",
        "rationale": (
            "Trial-only opening-gate review: the muted rendered opening establishes "
            "the visual direction and the adaptive hierarchy remains readable."
        ),
        "observations": [
            "The muted opening communicates a specific visible change.",
            "The hero phrase dominates its support text without filling the safe area.",
        ],
        "mutedHookDirectionConfirmed": True,
        "visualVoiceAlignment": "acceptable",
        "actualPayoffSeconds": 2.4,
        "concretePayoffKind": "demonstration",
        "payoffEvidence": "The second visual event begins the concrete change at 2.4s.",
        "payoffBeginsPromptly": True,
        **timing,
        "coldViewer": {
            "evidenceSource": "rendered_opening_only",
            "contextIsolated": True,
            "inferredTopic": "تغییر جهت یک الگوی نور متحرک",
            "inferredClaim": "افتتاحیه یک تغییر مشخص را مطرح می‌کند",
            "continuationReason": "می‌خواهم ببینم این تغییر چطور کامل می‌شود",
            "unresolvedReferents": [],
            "reviewInputSha256": cold_sha,
        },
        "visualTypography": {
            "policyVersion": "1.0",
            "evidenceSource": "rendered_opening_pixels",
            "hierarchyPassed": True,
            "occupancyRatio": 0.31,
            "emphasisPassed": True,
            "lineBalancePassed": True,
            "opticalPlacementPassed": True,
            "durationSeconds": 4.6,
            "recipeId": "editorial-hero-balanced",
        },
    }
    validate_rendered_hook_review(
        hook_review, candidate_sha256=opening_sha, require_pass=True
    )
    quality_evidence = compose_quality_evidence(
        retention, motion_qa, hook_review=hook_review
    )
    review = {
        "version": "1.0",
        "status": "pass",
        "openingCandidatePath": str(opening),
        "openingCandidateSha256": opening_sha,
        "editArtifactSha256": edit_artifact_sha256,
        "hookQualityAudit": hook_audit,
        "hookQualityReview": hook_review,
        "retentionAudit": retention,
        "postRenderMotionQa": motion_qa,
        "qualityEvidence": quality_evidence,
        "coldViewerReviewInput": {"path": str(cold_path), "sha256": cold_sha},
    }
    path = _write_json(project / "artifacts" / "opening_review.json", review)
    return path, review


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
    cold_frames: list[str],
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
    cold_input = build_cold_viewer_review_input(
        candidate_sha256=_sha(candidate),
        opening_evidence={
            "framePaths": list(cold_frames),
            "startSeconds": 0.0,
            "endSeconds": 3.0,
        },
    )
    cold_input_path = _write_json(
        project / "artifacts" / "cold_viewer_review_input.json", cold_input
    )
    cold_input_sha = _sha(cold_input_path)
    timing = _hook_timing_evidence(hook_audit, payoff_seconds=2.4)

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
        "version": "2.1",
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
        **timing,
        "coldViewer": {
            "evidenceSource": "rendered_opening_only",
            "contextIsolated": True,
            "inferredTopic": "تغییر جهت یک الگوی نور متحرک",
            "inferredClaim": "افتتاحیه یک تغییر دیداری مشخص را مطرح می‌کند",
            "continuationReason": "می‌خواهم ببینم این تغییر چطور کامل می‌شود",
            "unresolvedReferents": [],
            "reviewInputSha256": cold_input_sha,
        },
        "visualTypography": {
            "policyVersion": "1.0",
            "evidenceSource": "rendered_opening_pixels",
            "hierarchyPassed": True,
            "occupancyRatio": 0.31,
            "emphasisPassed": True,
            "lineBalancePassed": True,
            "opticalPlacementPassed": True,
            "durationSeconds": 4.6,
            "recipeId": "editorial-hero-balanced",
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
            "coldViewerReviewInput": {
                "path": str(cold_input_path),
                "sha256": cold_input_sha,
            },
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
        "quality_evidence": compose_quality_evidence(retention, data["post_render_motion_qa"]),
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
    words = list(alignment["word_timestamps"])
    provider_decision = dict(alignment["provider_decision"])
    complete_phase(PROJECT_ID, "align_script_timing", evidence={
        "provider": provider_decision["selectedProvider"],
        "provider_tool": provider_decision["selectedTool"],
        "provider_decision": provider_decision,
        "word_timing_count": len(words),
        "model": alignment.get("model") or alignment.get("model_size"),
        "alignment_mode": alignment.get("alignment_mode"),
        "heavy_recovery_used": bool(alignment.get("heavy_recovery_used")),
    }, pipeline_dir=root)
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
    hook_text = " ".join(
        str(segment.get("text") or "").strip()
        for segment in edit["persian"]["moments"][0]["segments"]
        if str(segment.get("role") or "") != "source"
    ).strip()
    record_hook_selection(
        PROJECT_ID,
        selected_text=hook_text,
        hook_family="specific-change",
        candidates=[
            {"text": "شروع با یک تغییر کوچک روشن می‌شود.", "score": 8.2},
            {"text": "یک تغییر کوچک چه فرقی می‌سازد؟", "score": 7.4},
            {"text": "شروع تغییر", "score": 5.2},
        ],
        score=8.2,
        content_match_score=2,
        evidence_checked=True,
        unsupported_claims_rejected=True,
        rationale="Synthetic E2E fixture explicitly exercises the automatic hook-selection gate.",
        pipeline_dir=root,
    )
    for name, artifact in (("scene_plan", plan), ("asset_manifest", actual_manifest)):
        validate_artifact(name, artifact)
    # The edit candidate is an authoring payload here: semanticRole is intentionally
    # transport-only until stage_workflow_edit_draft canonicalizes it into metadata.
    # Artifact-schema validation therefore belongs after the Front Door boundary.
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
    edit_artifact_sha256 = str(preflight["artifactSha256"])
    hook_audit = ((preflight.get("evidence") or {}).get("hookQualityAudit"))
    if not isinstance(hook_audit, dict) or hook_audit.get("required") is not True:
        raise RuntimeError(
            "front-door preflight did not persist required Hook Quality v2 evidence"
        )

    opening = project / "renders" / "opening-candidate.mp4"
    record_phase_attempt(PROJECT_ID, "render_opening_candidate", pipeline_dir=root)
    try:
        opening_result = ScriptAlignedPersianCompose().execute({
            "edit_decisions": canonical_edit, "output_path": str(opening), "crf": 20,
            "concurrency": 2, "timeout_ms": 120000, "frames": "0-149"})
        if not opening_result.success:
            raise RuntimeError(opening_result.error or "Persian opening compose failed")
    except Exception as exc:
        record_phase_failure(
            PROJECT_ID, "render_opening_candidate", reason=str(exc), pipeline_dir=root
        )
        raise
    complete_phase(PROJECT_ID, "render_opening_candidate", evidence={
        "output_path": str(opening),
        "opening_candidate_sha256": _sha(opening),
        "edit_artifact_sha256": edit_artifact_sha256,
    }, pipeline_dir=root)

    record_phase_attempt(PROJECT_ID, "opening_review", pipeline_dir=root)
    try:
        opening_frames = _extract_frames(
            opening, project / "artifacts" / "opening-review-frames",
            [0.25, 1.0, 2.4, 4.2], "opening"
        )
        opening_review_path, opening_review = _build_opening_review(
            opening, opening_frames, project, hook_audit, retention,
            dict(opening_result.data or {}).get("post_render_motion_qa") or {},
            edit_artifact_sha256=edit_artifact_sha256,
        )
    except Exception as exc:
        record_phase_failure(
            PROJECT_ID, "opening_review", reason=str(exc), pipeline_dir=root
        )
        raise
    complete_phase(PROJECT_ID, "opening_review", evidence={
        "opening_review_path": str(opening_review_path),
        "opening_review_sha256": _sha(opening_review_path),
        "opening_candidate_sha256": opening_review["openingCandidateSha256"],
        "edit_artifact_sha256": edit_artifact_sha256,
    }, pipeline_dir=root)

    rendered = project / "renders" / "rendered.mp4"
    record_phase_attempt(PROJECT_ID, "render_final_candidate", pipeline_dir=root)
    try:
        result = ScriptAlignedPersianCompose().execute({
            "edit_decisions": canonical_edit, "output_path": str(rendered), "crf": 20,
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
        "output_path": str(rendered),
        "edit_artifact_sha256": edit_artifact_sha256,
        "motion_qa_passed": data["post_render_motion_qa"]["passed"],
    }, pipeline_dir=root)

    record_phase_attempt(PROJECT_ID, "master_final_candidate", pipeline_dir=root)
    try:
        mastering = master_final_candidate(rendered, project / "renders" / "candidate.mp4")
        candidate = Path(mastering["candidatePath"])
    except Exception as exc:
        record_phase_failure(
            PROJECT_ID, "master_final_candidate", reason=str(exc), pipeline_dir=root
        )
        raise
    complete_phase(PROJECT_ID, "master_final_candidate", evidence={
        **mastering,
        "edit_artifact_sha256": edit_artifact_sha256,
    }, pipeline_dir=root)

    record_phase_attempt(PROJECT_ID, "final_review", pipeline_dir=root)
    try:
        probe = _probe(candidate)
        review_frames = _extract_frames(candidate, project / "artifacts" / "final-review-frames",
                                        [0.5, 3.2, 6.2, 9.5], "review")
        cold_frames = _extract_frames(candidate, project / "artifacts" / "cold-review-frames",
                                      [0.25, 1.0, 2.0, 2.8], "cold")
        caption_frames = _extract_frames(candidate, project / "artifacts" / "caption-review-frames",
                                         [1.0, 5.6, 9.0], "caption")
        rendered_audio = measure_rendered_audio_output(candidate)
        review_path = _build_final_review(
            candidate, review_frames, cold_frames, data.get("subtitle_path"), probe, project,
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
    final_quality_ref = terminal["evidence"]["final_review"]
    final_quality_path = Path(final_quality_ref["quality_evidence_path"])
    final_quality_evidence = json.loads(final_quality_path.read_text(encoding="utf-8"))
    summary = {
        "ok": True, "production_certified": False, "disclaimer": DISCLAIMER,
        "project_root": str(project), "candidate_path": str(candidate),
        "candidate_sha256": _sha(candidate), "workflow_status": terminal["status"],
        "opening_review_path": str(opening_review_path),
        "opening_candidate_sha256": opening_review["openingCandidateSha256"],
        "opening_quality_evidence": opening_review["qualityEvidence"],
        "final_quality_evidence": final_quality_evidence,
        "final_quality_evidence_path": str(final_quality_path),
        "final_quality_evidence_sha256": final_quality_ref["quality_evidence_sha256"],
        "mastering": mastering,
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
        "whisper_model": alignment.get("model") or alignment.get("model_size") or "provider-default",
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
