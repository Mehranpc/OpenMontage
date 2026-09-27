"""#288: final review's speech/music separation has a producer.

validate_rendered_audio_review requires separationMethod
"source_lufs_plus_render_gain" plus measured narration/music LUFS and the applied
gain, but nothing produced them; the agent had to assemble them by hand.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from lib.persian_audio_policy import materialize_loudness_aware_mix, rendered_audio_review_evidence
from lib.persian_rendered_review import validate_rendered_audio_review

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")


def _tone(path: Path, freq: int, volume: float, seconds: int = 8) -> None:
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                    f"sine=frequency={freq}:duration={seconds}", "-af", f"volume={volume}",
                    str(path)], check=True)


def test_evidence_passes_the_rendered_audio_validator(tmp_path: Path) -> None:
    narration, music, candidate = tmp_path / "n.wav", tmp_path / "m.wav", tmp_path / "c.mp4"
    _tone(narration, 440, 0.5)
    _tone(music, 220, 0.5)
    edit = materialize_loudness_aware_mix(
        {"persian": {"audio": {"narration": str(narration)}, "musicTrack": {"path": str(music)}}}, base_dir=tmp_path)
    gain = edit["persian"]["audio"]["musicDuckVolume"]
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(narration), "-i", str(music),
                    "-filter_complex", f"[1]volume={gain}[b];[0][b]amix=inputs=2:normalize=0,"
                    "loudnorm=I=-14:TP=-1.5", "-c:a", "aac", str(candidate)], check=True)
    evidence = rendered_audio_review_evidence(edit, candidate, base_dir=tmp_path)
    assert evidence["separationMethod"] == "source_lufs_plus_render_gain"
    assert evidence["speechMusicGain"] == pytest.approx(gain)
    validate_rendered_audio_review(
        {**evidence, "narration_present": True, "unexpected_silence": False, "clipping_detected": False,
         "mix_intelligible": True},
        candidate_sha256=evidence["candidateSha256"], require_pass=True)


def test_a_gain_the_policy_did_not_derive_is_refused(tmp_path: Path) -> None:
    narration, music, candidate = tmp_path / "n.wav", tmp_path / "m.wav", tmp_path / "c.mp4"
    _tone(narration, 440, 0.5)
    _tone(music, 220, 0.5)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(narration), "-c:a", "aac", str(candidate)], check=True)
    edit = materialize_loudness_aware_mix(
        {"persian": {"audio": {"narration": str(narration)}, "musicTrack": {"path": str(music)}}}, base_dir=tmp_path)
    # The renderer applied a different bed gain than the policy the review certifies.
    (tmp_path / "c.mp4.props.json").write_text('{"audio": {"musicDuckVolume": 0.9}}', encoding="utf-8")
    with pytest.raises(ValueError, match="differs"):
        rendered_audio_review_evidence(edit, candidate, base_dir=tmp_path)
