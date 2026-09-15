from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from lib.persian_rendered_review import (
    PersianRenderedReviewError,
    measure_rendered_audio_output,
    validate_rendered_audio_review,
    validate_rendered_hook_review,
)


DIGEST = "a" * 64


def _hook_review(**overrides) -> dict:
    value = {
        "version": "2.0",
        "reviewSource": "rendered_mp4",
        "reviewerRole": "independent_reviewer",
        "reviewedCandidateSha256": DIGEST,
        "strength": "acceptable",
        "rationale": "The rendered opening communicates a concrete promise and starts resolving it promptly.",
        "observations": [
            "Muted opening still communicates the topic direction.",
            "The first concrete result is spoken while matching footage is visible.",
        ],
        "mutedHookDirectionConfirmed": True,
        "visualVoiceAlignment": "acceptable",
        "actualPayoffSeconds": 4.8,
        "concretePayoffKind": "result",
        "payoffEvidence": "The actual finding is stated at 4.8s; this is not an authority/setup phrase.",
        "payoffBeginsPromptly": True,
    }
    value.update(overrides)
    return value


def _audio_review(**overrides) -> dict:
    value = {
        "narration_present": True,
        "music_present": True,
        "unexpected_silence": False,
        "clipping_detected": False,
        "mix_intelligible": True,
        "issues": [],
        "policyVersion": "1.0",
        "measurementSource": "rendered_mp4_plus_mix_policy",
        "candidateSha256": DIGEST,
        "outputIntegratedLufs": -13.0,
        "truePeakDbfs": -1.4,
        "narrationLufs": -13.2,
        "musicLufs": -10.3,
        "speechMusicGain": 0.226,
        "speechMusicSeparationLu": 10.0,
        "separationMethod": "source_lufs_plus_render_gain",
    }
    value.update(overrides)
    return value


def test_rendered_hook_v2_requires_independent_mp4_review_and_digest_binding() -> None:
    validate_rendered_hook_review(_hook_review(), candidate_sha256=DIGEST, require_pass=True)

    with pytest.raises(PersianRenderedReviewError, match="independent"):
        validate_rendered_hook_review(
            _hook_review(reviewerRole="authoring_agent"),
            candidate_sha256=DIGEST,
            require_pass=True,
        )
    with pytest.raises(PersianRenderedReviewError, match="digest"):
        validate_rendered_hook_review(
            _hook_review(reviewedCandidateSha256="b" * 64),
            candidate_sha256=DIGEST,
            require_pass=True,
        )


def test_rendered_hook_v2_uses_actual_concrete_payoff_not_meta_authority() -> None:
    with pytest.raises(PersianRenderedReviewError, match="concrete payoff"):
        validate_rendered_hook_review(
            _hook_review(
                actualPayoffSeconds=5.42,
                concretePayoffKind="authority_cue",
                payoffEvidence="بررسی‌های علمی نشان می‌دهند...",
            ),
            candidate_sha256=DIGEST,
            require_pass=True,
        )
    with pytest.raises(PersianRenderedReviewError, match="prompt payoff"):
        validate_rendered_hook_review(
            _hook_review(actualPayoffSeconds=6.8),
            candidate_sha256=DIGEST,
            require_pass=True,
        )


def test_audio_mix_intelligible_requires_numeric_evidence_and_safe_separation() -> None:
    validate_rendered_audio_review(_audio_review(), candidate_sha256=DIGEST, require_pass=True)

    missing = _audio_review()
    missing.pop("speechMusicSeparationLu")
    with pytest.raises(PersianRenderedReviewError, match="separation"):
        validate_rendered_audio_review(missing, candidate_sha256=DIGEST, require_pass=True)

    with pytest.raises(PersianRenderedReviewError, match="too loud"):
        validate_rendered_audio_review(
            _audio_review(
                speechMusicGain=0.55,
                speechMusicSeparationLu=2.3,
            ),
            candidate_sha256=DIGEST,
            require_pass=True,
        )


def test_audio_review_rejects_clipping_or_unsafe_output_loudness() -> None:
    with pytest.raises(PersianRenderedReviewError, match="true peak"):
        validate_rendered_audio_review(
            _audio_review(truePeakDbfs=0.2, clipping_detected=True),
            candidate_sha256=DIGEST,
            require_pass=True,
        )
    with pytest.raises(PersianRenderedReviewError, match="output loudness"):
        validate_rendered_audio_review(
            _audio_review(outputIntegratedLufs=-27.0),
            candidate_sha256=DIGEST,
            require_pass=True,
        )


def test_measure_rendered_audio_output_reads_real_mp4_when_ffmpeg_available(tmp_path: Path) -> None:
    import shutil
    import subprocess

    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        pytest.skip("ffmpeg unavailable")
    video = tmp_path / "candidate.mp4"
    subprocess.run(
        [
            ffmpeg, "-y", "-loglevel", "error",
            "-f", "lavfi", "-i", "color=c=black:s=320x568:d=2:r=30",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
            "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(video),
        ],
        check=True,
    )
    evidence = measure_rendered_audio_output(video)
    assert evidence["candidateSha256"] == hashlib.sha256(video.read_bytes()).hexdigest()
    assert isinstance(evidence["outputIntegratedLufs"], float)
    assert isinstance(evidence["truePeakDbfs"], float)
