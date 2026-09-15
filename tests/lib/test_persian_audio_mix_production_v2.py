from __future__ import annotations

import json
from pathlib import Path

import pytest

from lib.persian_edit_contract import collect_persian_edit_diagnostics, inspect_persian_audio_mix
from lib.persian_edit_workspace import stage_edit_draft
from tests.lib.test_persian_edit_contract import _add_audible_music_fixture, _edit
from tests.tools.test_persian_compose_props import _build, _persian


def _loudness(path: Path) -> float:
    return -10.3 if path.name == "bed.mp3" else -13.2


def test_explicit_old_fixed_duck_is_rejected_as_music_too_loud(tmp_path: Path, monkeypatch) -> None:
    edit = _edit()
    _add_audible_music_fixture(edit, tmp_path)
    edit["persian"]["audio"]["musicDuckVolume"] = 0.55
    monkeypatch.setattr("lib.persian_edit_contract.measure_integrated_loudness", _loudness)

    diagnostics = collect_persian_edit_diagnostics(edit, base_dir=tmp_path)

    assert any(
        item.code == "music.mix_too_loud" and "2.3 LU" in item.message
        for item in diagnostics
    )


def test_mix_inspection_exposes_measured_and_derived_policy_evidence(tmp_path: Path, monkeypatch) -> None:
    edit = _edit()
    _add_audible_music_fixture(edit, tmp_path)
    monkeypatch.setattr("lib.persian_edit_contract.measure_integrated_loudness", _loudness)

    evidence = inspect_persian_audio_mix(edit, base_dir=tmp_path)

    assert evidence is not None
    assert evidence["policyVersion"] == "1.0"
    assert evidence["measuredNarrationLufs"] == pytest.approx(-13.2)
    assert evidence["measuredMusicLufs"] == pytest.approx(-10.3)
    assert evidence["speechMusicGain"] == pytest.approx(0.226, abs=0.005)
    assert evidence["predictedSeparationLu"] == pytest.approx(10.0, abs=0.05)
    assert evidence["gainSource"] == "derived_loudness_policy"


def test_production_draft_materializes_derived_gain_before_compose(
    tmp_path: Path, monkeypatch
) -> None:
    staging = tmp_path / "staging"
    clip = tmp_path / "clip.mp4"
    narration = tmp_path / "vo.wav"
    bed = tmp_path / "bed.mp3"
    clip.write_bytes(b"clip")
    narration.write_bytes(b"audio")
    bed.write_bytes(b"music")
    persian = _persian(
        clip,
        audio={"narration": str(narration)},
        musicTrack={
            "path": str(bed),
            "source": "pixabay_music",
            "license": {
                "name": "Pixabay Content License",
                "url": "https://pixabay.com/music/",
                "downloadedAt": "2026-09-15",
            },
            "contentIdRisk": {"level": "low", "reason": "fixture"},
        },
    )
    monkeypatch.setattr("lib.persian_edit_contract.measure_integrated_loudness", _loudness)

    staged = stage_edit_draft(tmp_path / "project", "mix-v2", {"persian": persian})
    draft = json.loads(Path(staged["draftPath"]).read_text(encoding="utf-8"))
    props, _ = _build(draft["persian"], staging)

    assert draft["persian"]["audio"]["musicDuckVolume"] == pytest.approx(0.226, abs=0.005)
    assert props["audio"]["musicDuckVolume"] == pytest.approx(0.226, abs=0.005)
    assert props["audio"]["musicDuckVolume"] != pytest.approx(0.55)
