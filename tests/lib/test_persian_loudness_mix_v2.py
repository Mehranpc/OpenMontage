from __future__ import annotations

import pytest

from lib.persian_music import derive_loudness_aware_mix, evaluate_music_separation


def test_latest_production_old_fixed_duck_is_rejected_as_too_loud() -> None:
    result = evaluate_music_separation(
        narration_lufs=-13.2,
        music_lufs=-10.3,
        music_gain=0.55,
    )

    assert result["policyVersion"] == "1.0"
    assert result["predictedSeparationLu"] == pytest.approx(2.3, abs=0.15)
    assert result["passed"] is False
    assert result["reason"] == "music_too_loud"


def test_loudness_aware_gain_targets_versioned_speech_first_separation() -> None:
    plan = derive_loudness_aware_mix(narration_lufs=-13.2, music_lufs=-10.3)

    assert plan["policyVersion"] == "1.0"
    assert plan["targetSeparationLu"] == pytest.approx(10.0)
    assert plan["predictedSpeechMusicLufs"] == pytest.approx(-23.2, abs=0.05)
    assert plan["predictedSeparationLu"] == pytest.approx(10.0, abs=0.05)
    assert 0.20 < plan["speechMusicGain"] < 0.25
    assert plan["passed"] is True


def test_audio_policy_is_symmetric_for_too_loud_and_too_quiet_music() -> None:
    too_loud = evaluate_music_separation(
        narration_lufs=-14.0,
        music_lufs=-14.0,
        music_gain=0.7,
    )
    too_quiet = evaluate_music_separation(
        narration_lufs=-14.0,
        music_lufs=-14.0,
        music_gain=0.08,
    )

    assert too_loud["passed"] is False and too_loud["reason"] == "music_too_loud"
    assert too_quiet["passed"] is False and too_quiet["reason"] == "music_too_quiet"
