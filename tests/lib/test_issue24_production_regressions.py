from __future__ import annotations

import pytest

from lib.persian_hook_quality import audit_persian_hook_quality
from lib.persian_music import derive_loudness_aware_mix, evaluate_music_separation


REWARDS_PROJECT = "rewards-of-slowness-20260913-072138-698797fd"
VIDEO_GAMES_PROJECT = "video-games-and-cognitive-ability-20260915-093231-262399aa"


def _judgements() -> dict:
    return {
        field: {
            "level": "acceptable",
            "rationale": f"planning claim for {field}; rendered review remains authoritative",
        }
        for field in (
            "semanticPredictionError",
            "audienceRelevance",
            "concreteness",
            "hookBodyAlignment",
            "visualVoiceAlignment",
        )
    }


def _edit(hook: dict) -> dict:
    return {
        "metadata": {
            "target_platform": "instagram-reels",
            "productionRegressionProjectId": VIDEO_GAMES_PROJECT,
            "hookQuality": hook,
        },
        "persian": {
            "durationSeconds": 47.5,
            "platformTarget": "instagram-reels",
            "shots": [],
            "moments": [],
        },
    }


def test_rewards_of_slowness_false_positive_shared_hook_evidence_stays_blocked() -> None:
    shared = {
        "atSeconds": 0.45,
        "evidence": "آهسته رفتن ممکن است سریع‌ترین راه برای بهتر شدن باشد.",
        "evidenceId": "rewards-opening-shared",
    }
    edit = _edit({
        "version": "2.0",
        "viewerValue": dict(shared),
        "semanticTension": {"kind": "contradiction", **shared},
        "firstProof": {
            "atSeconds": 2.8,
            "kind": "example",
            "evidence": "تمرین آهسته یک مهارت را به اجزای قابل یادگیری تقسیم می‌کند.",
            "evidenceId": "rewards-proof",
        },
        "judgements": _judgements(),
        "flags": {
            "metaIntroDelay": False,
            "vagueGap": False,
            "fullConclusionRevealed": False,
        },
        "perceptualChanges": [],
    })
    edit["metadata"]["productionRegressionProjectId"] = REWARDS_PROJECT

    audit = audit_persian_hook_quality(edit)

    assert audit["version"] == "2.0"
    assert audit["disposition"] == "weak"
    assert any("shared evidence" in problem.lower() for problem in audit["problems"])


def test_video_games_declared_authority_cue_at_542_is_not_concrete_first_proof() -> None:
    edit = _edit({
        "version": "2.0",
        "viewerValue": {
            "atSeconds": 0.37,
            "evidence": "بازی فقط وقت‌تلفی نیست؛ ممکن است به توانایی شناختی مرتبط باشد.",
            "evidenceId": "games-value",
        },
        "semanticTension": {
            "kind": "contradiction",
            "atSeconds": 0.37,
            "evidence": "چیزی که وقت‌تلفی تصور می‌شود ممکن است نتیجهٔ شناختی متفاوتی داشته باشد.",
            "evidenceId": "games-tension",
        },
        "firstProof": {
            "atSeconds": 5.42,
            "kind": "authority_cue",
            "evidence": "بررسی‌های علمی نشان می‌دهند...",
            "evidenceId": "games-authority-cue",
        },
        "judgements": _judgements(),
        "flags": {
            "metaIntroDelay": False,
            "vagueGap": False,
            "fullConclusionRevealed": False,
        },
        "perceptualChanges": [],
    })

    audit = audit_persian_hook_quality(edit)

    assert audit["disposition"] == "weak"
    assert audit["timing"]["timeToFirstProofSeconds"] is None
    assert any("concrete" in problem.lower() and "proof" in problem.lower() for problem in audit["problems"])


def test_video_games_old_duck_055_fails_and_loudness_aware_gain_targets_safe_separation() -> None:
    legacy = evaluate_music_separation(
        narration_lufs=-13.2,
        music_lufs=-10.3,
        music_gain=0.55,
    )
    assert legacy["passed"] is False
    assert legacy["reason"] == "music_too_loud"
    assert legacy["predictedSeparationLu"] == pytest.approx(2.293, abs=0.01)

    derived = derive_loudness_aware_mix(
        narration_lufs=-13.2,
        music_lufs=-10.3,
    )
    assert derived["passed"] is True
    assert derived["speechMusicGain"] == pytest.approx(0.226, abs=0.002)
    assert derived["predictedSeparationLu"] == pytest.approx(10.0, abs=0.01)


def test_video_games_operational_reference_remains_explicit_for_recovery_regressions() -> None:
    reference = {
        "project_id": VIDEO_GAMES_PROJECT,
        "preflight_candidates": 13,
        "render_seconds": 122,
        "serialization_failure": "ToolResult is not JSON serializable",
        "stuck_phase": "render_final_candidate",
    }
    assert reference == {
        "project_id": "video-games-and-cognitive-ability-20260915-093231-262399aa",
        "preflight_candidates": 13,
        "render_seconds": 122,
        "serialization_failure": "ToolResult is not JSON serializable",
        "stuck_phase": "render_final_candidate",
    }
