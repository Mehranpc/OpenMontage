from __future__ import annotations

from pathlib import Path

import pytest

from lib.persian_edit_contract import (
    PersianEditContractError,
    collect_persian_edit_diagnostics,
    validate_persian_edit_contract,
)


def _edit(source: str = "clip.mp4") -> dict:
    return {
        "persian": {
            "format": "vertical",
            "durationSeconds": 12.0,
            "shots": [
                {
                    "id": "shot-1",
                    "source": source,
                    "startSeconds": 0.0,
                    "endSeconds": 12.0,
                    "camera": "none",
                    "attribution": "Video by Test on Pexels",
                    "avoidRegions": [
                        {"x": 0.1, "y": 0.2, "w": 0.3, "h": 0.4}
                    ],
                }
            ],
            "moments": [
                {
                    "id": "moment-1",
                    "kind": "hook",
                    "startSeconds": 0.2,
                    "endSeconds": 4.2,
                    "segments": [
                        {"role": "hero", "text": "آهسته‌تر جلو برو", "accentWords": ["آهسته‌تر"]}
                    ],
                }
            ],
            "typographicBeats": [],
            "audio": {},
            "watermark": {"persianText": "طریقت تسلیم", "latinText": "Pathway_of_Surrender"},
        }
    }


def test_valid_partial_edit_contract_passes_schema_and_semantics() -> None:
    validate_persian_edit_contract(_edit())


@pytest.mark.parametrize(
    ("bad", "replacement"),
    [("width", "w"), ("height", "h"), ("start", "startSeconds"), ("end", "endSeconds")],
)
def test_region_aliases_get_json_pointer_and_actionable_hint(bad: str, replacement: str) -> None:
    edit = _edit()
    region = edit["persian"]["shots"][0]["avoidRegions"][0]
    if bad == "width":
        region.pop("w")
        region[bad] = 0.3
    elif bad == "height":
        region.pop("h")
        region[bad] = 0.4
    else:
        region[bad] = 1.0 if bad == "start" else 2.0
    diagnostics = collect_persian_edit_diagnostics(edit)
    assert any(
        item.pointer == f"/persian/shots/0/avoidRegions/0/{bad}"
        and item.hint is not None
        and replacement in item.hint
        for item in diagnostics
    )


def test_region_time_must_stay_inside_owning_shot() -> None:
    edit = _edit()
    edit["persian"]["shots"][0]["avoidRegions"][0].update(
        {"startSeconds": -0.1, "endSeconds": 12.5}
    )
    diagnostics = collect_persian_edit_diagnostics(edit)
    codes = {item.code for item in diagnostics}
    assert "region.before_shot" in codes
    assert "region.after_shot" in codes


def test_duplicate_music_ownership_is_refused_before_compose() -> None:
    edit = _edit()
    edit["persian"]["audio"]["music"] = "bed.mp3"
    edit["persian"]["musicTrack"] = {
        "path": "bed.mp3",
        "source": "pixabay_music",
        "license": {"name": "Pixabay Content License", "url": "https://pixabay.com/service/license-summary/", "downloadedAt": "2026-09-13"},
        "contentIdRisk": {"level": "low"},
    }
    with pytest.raises(PersianEditContractError, match="canonical licensed record"):
        validate_persian_edit_contract(edit)


def test_stale_audio_music_track_location_names_canonical_location() -> None:
    edit = _edit()
    edit["persian"]["audio"]["musicTrack"] = {"path": "bed.mp3"}
    diagnostics = collect_persian_edit_diagnostics(edit)
    assert any(
        item.code == "music.stale_location"
        and item.pointer == "/persian/audio/musicTrack"
        and "/persian/musicTrack" in (item.hint or "")
        for item in diagnostics
    )


def test_missing_media_path_is_reported_before_browser(tmp_path: Path) -> None:
    edit = _edit("missing.mp4")
    diagnostics = collect_persian_edit_diagnostics(edit, base_dir=tmp_path)
    assert any(
        item.code == "path.missing"
        and item.pointer == "/persian/shots/0/source"
        and "missing.mp4" in item.message
        for item in diagnostics
    )


def test_existing_media_path_passes_path_contract(tmp_path: Path) -> None:
    (tmp_path / "clip.mp4").write_bytes(b"fixture")
    diagnostics = collect_persian_edit_diagnostics(_edit(), base_dir=tmp_path)
    assert not [item for item in diagnostics if item.code == "path.missing"]


def test_nested_unknown_music_ack_names_top_level_location() -> None:
    edit = _edit()
    edit["persian"]["musicTrack"] = {
        "path": "bed.mp3", "source": "local_original",
        "license": {"name": "Original", "url": "local://generated", "downloadedAt": "2026-09-13"},
        "contentIdRisk": {"level": "unknown"}, "acknowledgeUnknownMusicRisk": True,
    }
    diagnostics = collect_persian_edit_diagnostics(edit)
    assert any(
        item.code == "music.stale_ack_location"
        and item.pointer == "/persian/musicTrack/acknowledgeUnknownMusicRisk"
        and "/persian/acknowledgeUnknownMusicRisk" in (item.hint or "")
        for item in diagnostics
    )

def test_overlapping_reuse_of_same_source_window_is_refused() -> None:
    edit = _edit()
    first = edit["persian"]["shots"][0]
    first["endSeconds"] = 6.0
    edit["persian"]["shots"].append({
        "id": "shot-2", "source": first["source"],
        "startSeconds": 6.0, "endSeconds": 12.0, "sourceInSeconds": 4.0,
        "camera": "none", "attribution": "Video by Test on Pexels", "avoidRegions": [],
    })
    diagnostics = collect_persian_edit_diagnostics(edit)
    assert any(item.code == "shot.duplicate_source_window" for item in diagnostics)


def test_distinct_nonoverlapping_windows_from_same_source_are_allowed() -> None:
    edit = _edit()
    first = edit["persian"]["shots"][0]
    first["endSeconds"] = 6.0
    edit["persian"]["shots"].append({
        "id": "shot-2", "source": first["source"],
        "startSeconds": 6.0, "endSeconds": 12.0, "sourceInSeconds": 6.0,
        "camera": "none", "attribution": "Video by Test on Pexels", "avoidRegions": [],
    })
    diagnostics = collect_persian_edit_diagnostics(edit)
    assert not [item for item in diagnostics if item.code == "shot.duplicate_source_window"]


def _add_audible_music_fixture(edit: dict, tmp_path: Path) -> None:
    (tmp_path / "clip.mp4").write_bytes(b"fixture")
    (tmp_path / "bed.mp3").write_bytes(b"fixture")
    (tmp_path / "narration.mp3").write_bytes(b"fixture")
    edit["persian"]["shots"][0]["source"] = "clip.mp4"
    edit["persian"]["audio"]["narration"] = "narration.mp3"
    edit["persian"]["musicTrack"] = {
        "path": "bed.mp3", "source": "local_original",
        "license": {"name": "Original project-generated audio", "url": "local://generated", "downloadedAt": "2026-09-13"},
        "contentIdRisk": {"level": "unknown", "reason": "local original"},
    }


def test_music_that_is_present_but_too_far_below_narration_is_refused(tmp_path: Path, monkeypatch) -> None:
    edit = _edit()
    _add_audible_music_fixture(edit, tmp_path)
    edit["persian"]["audio"]["musicDuckVolume"] = 0.36
    def loudness(path: Path) -> float:
        return -19.8 if path.name == "bed.mp3" else -11.4
    monkeypatch.setattr("lib.persian_edit_contract.measure_integrated_loudness", loudness)
    diagnostics = collect_persian_edit_diagnostics(edit, base_dir=tmp_path)
    assert any(
        item.code == "music.mix_too_quiet" and "LU gap" in item.message
        for item in diagnostics
    )


def test_default_duck_level_keeps_normalized_music_perceptible(tmp_path: Path, monkeypatch) -> None:
    edit = _edit()
    _add_audible_music_fixture(edit, tmp_path)
    def loudness(path: Path) -> float:
        return -19.8 if path.name == "bed.mp3" else -11.4
    monkeypatch.setattr("lib.persian_edit_contract.measure_integrated_loudness", loudness)
    diagnostics = collect_persian_edit_diagnostics(edit, base_dir=tmp_path)
    assert not [item for item in diagnostics if item.code == "music.mix_too_quiet"]


def test_near_silent_music_file_is_refused_before_browser(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "clip.mp4").write_bytes(b"fixture")
    (tmp_path / "bed.mp3").write_bytes(b"fixture")
    edit = _edit()
    edit["persian"]["musicTrack"] = {
        "path": "bed.mp3", "source": "local_original",
        "license": {"name": "Original project-generated audio", "url": "local://generated", "downloadedAt": "2026-09-13"},
        "contentIdRisk": {"level": "unknown", "reason": "local original"},
    }
    monkeypatch.setattr("lib.persian_edit_contract.measure_integrated_loudness", lambda _: -57.7)
    diagnostics = collect_persian_edit_diagnostics(edit, base_dir=tmp_path)
    assert any(
        item.code == "music.near_silent" and "-57.7 LUFS" in item.message
        for item in diagnostics
    )
