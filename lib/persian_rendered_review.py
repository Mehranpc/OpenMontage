"""Evidence-backed rendered Hook v2 and audio QA for Persian final candidates."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
from typing import Any, Mapping

from lib.persian_hook_quality import CONCRETE_PROOF_KINDS, PROOF_BLOCK_SECONDS
from lib.persian_music import (
    MAX_MUSIC_SEPARATION_LU,
    MIN_MUSIC_SEPARATION_LU,
    effective_music_loudness,
)

HOOK_RENDER_REVIEW_VERSION = "2.0"
COLD_VIEWER_POLICY_VERSION = "1.0"
RENDERED_AUDIO_POLICY_VERSION = "1.0"
VISUAL_TYPOGRAPHY_POLICY_VERSION = "2.0"
VISUAL_TYPOGRAPHY_LEGACY_POLICY_VERSION = "1.0"
VISUAL_TYPOGRAPHY_RECIPES = frozenset({"editorial-hero-balanced", "editorial-hero-compact", "editorial-callout-balanced"})
MIN_VISUAL_OCCUPANCY_RATIO = 0.16
MAX_VISUAL_OCCUPANCY_RATIO = 0.58
MIN_VISUAL_HOLD_SECONDS = 1.5
MAX_VISUAL_HOLD_SECONDS = 6.0
MIN_OUTPUT_INTEGRATED_LUFS = -20.0
MAX_OUTPUT_INTEGRATED_LUFS = -9.0
MAX_TRUE_PEAK_DBFS = -1.0
_SEPARATION_TOLERANCE_LU = 0.35
_LUFS_RE = re.compile(r"\bI:\s*(-?[0-9]+(?:\.[0-9]+)?)\s+LUFS")
_PEAK_RE = re.compile(r"\bPeak:\s*(-?[0-9]+(?:\.[0-9]+)?)\s+dBFS")


class PersianRenderedReviewError(ValueError):
    """Raised when final rendered evidence cannot authorize presentation."""


def _number(value: object, label: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(float(value)):
        raise PersianRenderedReviewError(f"{label} must be a finite number")
    return float(value)


def _digest(value: object, label: str) -> str:
    text = str(value or "").strip().lower()
    if len(text) != 64 or any(ch not in "0123456789abcdef" for ch in text):
        raise PersianRenderedReviewError(f"{label} must be a lowercase sha256 digest")
    return text


_COLD_VIEWER_EVIDENCE_FIELDS = frozenset(
    {"framePaths", "excerptPath", "startSeconds", "endSeconds"}
)


def build_cold_viewer_review_input(
    *, candidate_sha256: str, opening_evidence: Mapping[str, Any]
) -> dict[str, Any]:
    """Build the only payload a blind muted-opening reviewer may receive.

    The allowlist is intentionally narrow. Approved script, hook metadata, author
    rationale, scene-plan labels, and semantic annotations cannot enter this object
    accidentally because unknown evidence keys are refused rather than forwarded.
    """
    digest = _digest(candidate_sha256, "candidate digest")
    if not isinstance(opening_evidence, Mapping):
        raise PersianRenderedReviewError("cold-viewer opening evidence must be an object")
    unsupported = sorted(set(opening_evidence) - _COLD_VIEWER_EVIDENCE_FIELDS)
    if unsupported:
        raise PersianRenderedReviewError(
            "cold-viewer opening evidence contains unsupported authoring context fields: "
            + ", ".join(unsupported)
        )
    frames = opening_evidence.get("framePaths")
    excerpt = str(opening_evidence.get("excerptPath") or "").strip()
    if frames is not None and (
        not isinstance(frames, list)
        or not frames
        or any(not isinstance(item, str) or not item.strip() for item in frames)
    ):
        raise PersianRenderedReviewError("cold-viewer framePaths must be a non-empty array of paths")
    if not frames and not excerpt:
        raise PersianRenderedReviewError(
            "cold-viewer review requires rendered opening frames or a muted opening excerpt"
        )
    clean: dict[str, Any] = {}
    if frames:
        clean["framePaths"] = [str(item).strip() for item in frames]
    if excerpt:
        clean["excerptPath"] = excerpt
    for key in ("startSeconds", "endSeconds"):
        if key in opening_evidence:
            clean[key] = _number(opening_evidence[key], f"cold-viewer {key}")
    if "startSeconds" in clean and "endSeconds" in clean:
        if clean["endSeconds"] <= clean["startSeconds"]:
            raise PersianRenderedReviewError("cold-viewer opening interval must have positive duration")
    return {
        "policyVersion": COLD_VIEWER_POLICY_VERSION,
        "candidateSha256": digest,
        "reviewScope": "muted_opening",
        "evidenceSource": "rendered_opening_only",
        "openingEvidence": clean,
        "instructions": [
            "Infer only what a muted cold viewer can recover from the rendered opening.",
            "Record the apparent topic/referent, claim/question, reason to continue, and unresolved referents.",
        ],
    }


def validate_cold_viewer_review_input(
    payload: Mapping[str, Any], *, candidate_sha256: str
) -> None:
    """Validate the exact context-isolated payload shown to a cold reviewer."""
    if not isinstance(payload, Mapping):
        raise PersianRenderedReviewError("cold-viewer review input must be a JSON object")
    evidence = payload.get("openingEvidence")
    if not isinstance(evidence, Mapping):
        raise PersianRenderedReviewError("cold-viewer review input requires openingEvidence")
    expected = build_cold_viewer_review_input(
        candidate_sha256=candidate_sha256, opening_evidence=evidence
    )
    extras = sorted(set(payload) - set(expected))
    if extras:
        raise PersianRenderedReviewError(
            "cold-viewer review input contains unsupported authoring context fields: "
            + ", ".join(extras)
        )
    if dict(payload) != expected:
        raise PersianRenderedReviewError(
            "cold-viewer review input does not match the canonical context-isolated payload"
        )


def _validate_cold_viewer(review: Mapping[str, Any]) -> bool:
    """Validate context-isolated muted-opening evidence and return comprehension."""
    raw = review.get("coldViewer")
    if not isinstance(raw, Mapping):
        raise PersianRenderedReviewError(
            "rendered hook review requires cold-viewer evidence isolated from authoring context"
        )
    if str(raw.get("evidenceSource") or "") != "rendered_opening_only":
        raise PersianRenderedReviewError(
            "cold-viewer evidenceSource must be rendered_opening_only"
        )
    if raw.get("contextIsolated") is not True:
        raise PersianRenderedReviewError(
            "cold-viewer review must be context-isolated from script, hook metadata, rationale, and scene labels"
        )
    topic = str(raw.get("inferredTopic") or "").strip()
    claim = str(raw.get("inferredClaim") or "").strip()
    continuation = str(raw.get("continuationReason") or "").strip()
    unresolved = raw.get("unresolvedReferents")
    if not isinstance(unresolved, list) or any(not isinstance(item, str) for item in unresolved):
        raise PersianRenderedReviewError("cold-viewer unresolvedReferents must be an array of strings")
    return bool(topic and claim and continuation and not [item for item in unresolved if item.strip()])


def _validate_visual_typography(review: Mapping[str, Any], *, require_pass: bool) -> bool:
    raw = review.get("visualTypography")
    if not isinstance(raw, Mapping):
        if require_pass:
            raise PersianRenderedReviewError("passing rendered hook review requires visual typography evidence")
        return False
    policy_version = str(raw.get("policyVersion") or "")
    if policy_version not in {VISUAL_TYPOGRAPHY_LEGACY_POLICY_VERSION, VISUAL_TYPOGRAPHY_POLICY_VERSION}:
        raise PersianRenderedReviewError("visual typography policyVersion must be 1.0 or 2.0")
    if str(raw.get("evidenceSource") or "") != "rendered_opening_pixels":
        raise PersianRenderedReviewError("visual typography evidence must come from rendered opening pixels")
    recipe = str(raw.get("recipeId") or "")
    if recipe not in VISUAL_TYPOGRAPHY_RECIPES:
        raise PersianRenderedReviewError("visual typography recipe must be one of the curated recipes")
    occupancy = _number(raw.get("occupancyRatio"), "visual typography occupancy ratio")
    duration = _number(raw.get("durationSeconds"), "visual typography duration")
    passed = (
        raw.get("hierarchyPassed") is True
        and MIN_VISUAL_OCCUPANCY_RATIO <= occupancy <= MAX_VISUAL_OCCUPANCY_RATIO
        and raw.get("emphasisPassed") is True
        and raw.get("lineBalancePassed") is True
        and raw.get("opticalPlacementPassed") is True
        and MIN_VISUAL_HOLD_SECONDS <= duration <= MAX_VISUAL_HOLD_SECONDS
    )
    if policy_version == VISUAL_TYPOGRAPHY_POLICY_VERSION:
        family = str(raw.get("displayFontFamily") or "")
        if family != "KahrobaEditorial":
            raise PersianRenderedReviewError("visual typography v2 requires the KahrobaEditorial display family")
        alignment = str(raw.get("alignment") or "")
        if alignment not in {"right", "center"}:
            raise PersianRenderedReviewError("visual typography v2 alignment must be right or center")
        if raw.get("semanticYellowVisible") is not True:
            raise PersianRenderedReviewError("visual typography v2 requires visible semantic yellow emphasis")
        if str(raw.get("semanticAccentHex") or "").upper() != "#FFEA00":
            raise PersianRenderedReviewError("visual typography v2 semantic accent must be #FFEA00")
        if str(raw.get("supportInkHex") or "").upper() != "#FFFFFF":
            raise PersianRenderedReviewError("visual typography v2 support ink must be #FFFFFF")
        if raw.get("wholeHookVisible") is not True:
            raise PersianRenderedReviewError("visual typography v2 requires the whole hook to remain visible")
        if raw.get("plainSubtitleLike") is not False:
            raise PersianRenderedReviewError("visual typography v2 refuses plain subtitle-like opening treatment")
        if raw.get("localContrastFieldVisible") is not True:
            raise PersianRenderedReviewError("visual typography v2 requires a local contrast field behind the hook")
    if require_pass and not passed:
        raise PersianRenderedReviewError(
            "visual typography failed rendered-pixel hierarchy, occupancy, emphasis, line balance, optical placement, or duration QA"
        )
    return passed


def validate_rendered_hook_review(
    review: Mapping[str, Any], *, candidate_sha256: str, require_pass: bool
) -> None:
    """Validate independent review of what a cold viewer actually receives."""
    if str(review.get("version") or "") != HOOK_RENDER_REVIEW_VERSION:
        raise PersianRenderedReviewError("rendered hook review version must be 2.0")
    if str(review.get("reviewSource") or "") != "rendered_mp4":
        raise PersianRenderedReviewError("rendered hook review must inspect the rendered MP4")
    if str(review.get("reviewerRole") or "") != "independent_reviewer":
        raise PersianRenderedReviewError("rendered hook review requires an independent reviewer role")
    actual_digest = _digest(review.get("reviewedCandidateSha256"), "reviewed candidate digest")
    if actual_digest != _digest(candidate_sha256, "candidate digest"):
        raise PersianRenderedReviewError("rendered hook review digest does not match the candidate digest")

    observations = review.get("observations")
    if (
        not isinstance(observations, list)
        or len(observations) < 2
        or any(not isinstance(item, str) or not item.strip() for item in observations)
    ):
        raise PersianRenderedReviewError("rendered hook review requires at least two opening observations")
    if not str(review.get("rationale") or "").strip():
        raise PersianRenderedReviewError("rendered hook review requires rationale")

    cold_comprehension = _validate_cold_viewer(review)
    declared_muted = review.get("mutedHookDirectionConfirmed")
    if not isinstance(declared_muted, bool):
        raise PersianRenderedReviewError("mutedHookDirectionConfirmed must be boolean")
    if declared_muted != cold_comprehension:
        raise PersianRenderedReviewError(
            "mutedHookDirectionConfirmed must be derived from structured cold-viewer evidence"
        )

    strength = str(review.get("strength") or "")
    if strength not in {"weak", "acceptable", "strong"}:
        raise PersianRenderedReviewError("rendered hook review strength is invalid")
    visual_alignment = str(review.get("visualVoiceAlignment") or "")
    if visual_alignment not in {"weak", "acceptable", "strong"}:
        raise PersianRenderedReviewError("rendered hook visual/voice alignment is invalid")
    payoff_kind = str(review.get("concretePayoffKind") or "").strip()
    if payoff_kind not in CONCRETE_PROOF_KINDS:
        raise PersianRenderedReviewError(
            "rendered hook review requires a concrete payoff kind; authority/setup language is not proof"
        )
    payoff_seconds = _number(review.get("actualPayoffSeconds"), "actual rendered payoff seconds")
    if payoff_seconds < 0:
        raise PersianRenderedReviewError("actual rendered payoff seconds cannot be negative")
    if not str(review.get("payoffEvidence") or "").strip():
        raise PersianRenderedReviewError("rendered hook review requires concrete payoff evidence")

    _validate_visual_typography(review, require_pass=require_pass)

    if require_pass:
        if strength not in {"acceptable", "strong"}:
            raise PersianRenderedReviewError("passing rendered hook review must be acceptable or strong")
        if not cold_comprehension:
            raise PersianRenderedReviewError(
                "passing rendered hook review requires cold-viewer topic/referent comprehension"
            )
        if visual_alignment not in {"acceptable", "strong"}:
            raise PersianRenderedReviewError("passing rendered hook review requires visual/voice alignment")
        if review.get("payoffBeginsPromptly") is not True or payoff_seconds > PROOF_BLOCK_SECONDS:
            raise PersianRenderedReviewError(
                f"passing rendered hook review requires prompt payoff by {PROOF_BLOCK_SECONDS:.1f}s"
            )


def validate_rendered_audio_review(
    audio: Mapping[str, Any], *, candidate_sha256: str, require_pass: bool
) -> None:
    """Require numeric rendered-output and mix-policy evidence before intelligibility can pass."""
    if str(audio.get("policyVersion") or "") != RENDERED_AUDIO_POLICY_VERSION:
        raise PersianRenderedReviewError("rendered audio review policyVersion must be 1.0")
    if str(audio.get("measurementSource") or "") != "rendered_mp4_plus_mix_policy":
        raise PersianRenderedReviewError("rendered audio review must include rendered MP4 measurements")
    if _digest(audio.get("candidateSha256"), "audio candidate digest") != _digest(candidate_sha256, "candidate digest"):
        raise PersianRenderedReviewError("rendered audio review digest does not match the candidate digest")

    output_lufs = _number(audio.get("outputIntegratedLufs"), "output loudness")
    true_peak = _number(audio.get("truePeakDbfs"), "true peak")
    if not MIN_OUTPUT_INTEGRATED_LUFS <= output_lufs <= MAX_OUTPUT_INTEGRATED_LUFS:
        raise PersianRenderedReviewError(
            f"output loudness {output_lufs:.1f} LUFS is outside the {MIN_OUTPUT_INTEGRATED_LUFS:.1f}..{MAX_OUTPUT_INTEGRATED_LUFS:.1f} LUFS policy range"
        )
    if true_peak > MAX_TRUE_PEAK_DBFS:
        raise PersianRenderedReviewError(
            f"true peak {true_peak:.1f} dBFS exceeds the {MAX_TRUE_PEAK_DBFS:.1f} dBFS ceiling"
        )
    if audio.get("clipping_detected") is True:
        raise PersianRenderedReviewError("rendered audio true peak/clipping evidence reports clipping")
    if audio.get("unexpected_silence") is True:
        raise PersianRenderedReviewError("rendered audio contains unexpected silence")
    if audio.get("narration_present") is not True:
        raise PersianRenderedReviewError("rendered audio review requires narration presence")

    music_present = audio.get("music_present") is True
    if music_present:
        if str(audio.get("separationMethod") or "") != "source_lufs_plus_render_gain":
            raise PersianRenderedReviewError("speech/music separation requires the documented evidence method")
        narration_lufs = _number(audio.get("narrationLufs"), "narration loudness")
        music_lufs = _number(audio.get("musicLufs"), "music loudness")
        gain = _number(audio.get("speechMusicGain"), "speech-time music gain")
        if gain <= 0:
            raise PersianRenderedReviewError("speech-time music gain must be positive")
        reported_separation = _number(audio.get("speechMusicSeparationLu"), "speech/music separation")
        predicted_music = effective_music_loudness(music_lufs, gain)
        expected_separation = narration_lufs - predicted_music
        if abs(reported_separation - expected_separation) > _SEPARATION_TOLERANCE_LU:
            raise PersianRenderedReviewError("speech/music separation evidence is inconsistent with source LUFS and render gain")
        if reported_separation < MIN_MUSIC_SEPARATION_LU:
            raise PersianRenderedReviewError(
                f"music is too loud: {reported_separation:.1f} LU separation is below {MIN_MUSIC_SEPARATION_LU:.1f} LU"
            )
        if reported_separation > MAX_MUSIC_SEPARATION_LU:
            raise PersianRenderedReviewError(
                f"music is too quiet: {reported_separation:.1f} LU separation is above {MAX_MUSIC_SEPARATION_LU:.1f} LU"
            )
    elif not str(audio.get("musicOmittedReason") or "").strip():
        raise PersianRenderedReviewError("music absence requires an explicit musicOmittedReason")

    if require_pass:
        if audio.get("mix_intelligible") is not True:
            raise PersianRenderedReviewError("mix_intelligible cannot pass without the required evidence")
        if list(audio.get("issues") or []):
            raise PersianRenderedReviewError("rendered audio review has blocking issues")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def measure_rendered_audio_output(path: Path, *, timeout: int = 180) -> dict[str, Any]:
    """Measure integrated loudness and true peak from the actual rendered MP4."""
    candidate = path.expanduser().resolve()
    if not candidate.is_file():
        raise PersianRenderedReviewError(f"rendered candidate does not exist: {candidate}")
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise PersianRenderedReviewError("ffmpeg is required for rendered audio QA")
    completed = subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-nostats",
            "-i",
            str(candidate),
            "-af",
            "ebur128=peak=true:framelog=verbose",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if completed.returncode != 0:
        raise PersianRenderedReviewError(
            f"rendered audio QA failed for {candidate} (exit {completed.returncode})"
        )
    output = (completed.stdout or "") + "\n" + (completed.stderr or "")
    loudness = _LUFS_RE.findall(output)
    peaks = _PEAK_RE.findall(output)
    if not loudness or not peaks:
        raise PersianRenderedReviewError("rendered audio QA produced incomplete LUFS/true-peak evidence")
    return {
        "policyVersion": RENDERED_AUDIO_POLICY_VERSION,
        "measurementSource": "rendered_mp4",
        "candidateSha256": _sha256_file(candidate),
        "outputIntegratedLufs": float(loudness[-1]),
        "truePeakDbfs": float(peaks[-1]),
    }


__all__ = [
    "HOOK_RENDER_REVIEW_VERSION",
    "COLD_VIEWER_POLICY_VERSION",
    "RENDERED_AUDIO_POLICY_VERSION",
    "VISUAL_TYPOGRAPHY_POLICY_VERSION",
    "VISUAL_TYPOGRAPHY_RECIPES",
    "MIN_OUTPUT_INTEGRATED_LUFS",
    "MAX_OUTPUT_INTEGRATED_LUFS",
    "MAX_TRUE_PEAK_DBFS",
    "PersianRenderedReviewError",
    "build_cold_viewer_review_input",
    "validate_cold_viewer_review_input",
    "validate_rendered_hook_review",
    "validate_rendered_audio_review",
    "measure_rendered_audio_output",
]
