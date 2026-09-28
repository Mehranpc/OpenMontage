"""#263 item F: the music decision is checked on the draft, and final review restates it.

Before: compose's ``audit_music`` gate (no bed in narrated mode, a deferring
``omitMusicReason``, an incomplete licence record) ran only while the browser pass
built render props, after an edit candidate was spent; and final review accepted any
non-deferring ``musicOmittedReason`` free text, unrelated to the edit it reviewed.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lib.persian_edit_contract import collect_persian_edit_diagnostics
from lib.persian_video_workflow import PersianVideoWorkflowError, complete_phase

from tests.lib.test_persian_video_workflow import BASE, _review_ready_project

_DECISION = "The film is deliberately narration-only; the pacing carries without a bed."


def _codes(persian: dict) -> set[str]:
    return {item.code for item in collect_persian_edit_diagnostics({"persian": persian})}


def test_a_narrated_draft_without_a_bed_or_reason_is_refused_before_the_browser() -> None:
    codes = _codes({"audio": {"narration": "assets/narration.mp3"}})
    assert "music.omission_unjustified" in codes


def test_a_deferring_omission_reason_is_refused_on_the_draft() -> None:
    codes = _codes({
        "audio": {"narration": "assets/narration.mp3"},
        "omitMusicReason": "music bed to be attached before promote",
    })
    assert "music.omission_unjustified" in codes


def test_a_recorded_decision_passes_the_draft_check() -> None:
    codes = _codes({"audio": {"narration": "assets/narration.mp3"}, "omitMusicReason": _DECISION})
    assert not {code for code in codes if code.startswith("music.")}


def test_an_incomplete_licence_record_is_refused_on_the_draft() -> None:
    codes = _codes({
        "audio": {"narration": "assets/narration.mp3"},
        "musicTrack": {"path": "assets/music/bed.mp3", "source": "pixabay"},
    })
    assert "music.record_invalid" in codes


def test_an_unacknowledged_unknown_risk_is_refused_on_the_draft() -> None:
    track = {
        "path": "assets/music/bed.mp3", "source": "pixabay",
        "license": {"name": "Pixabay Content License", "url": "https://pixabay.com/service/license-summary/",
                    "downloadedAt": "2026-09-28T00:00:00Z"},
        "contentIdRisk": {"level": "unknown"},
    }
    persian = {"audio": {"narration": "assets/narration.mp3"}, "musicTrack": track}
    assert "music.licence_refused" in _codes(persian)
    persian["acknowledgeUnknownMusicRisk"] = True
    assert "music.licence_refused" not in _codes(persian)


def _write_edit(project: Path, persian: dict) -> None:
    path = project / "artifacts" / "edit_decisions.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"version": "1.0", "persian": persian}), encoding="utf-8")


def _set_audio(review_path: Path, **fields) -> None:
    review = json.loads(review_path.read_text(encoding="utf-8"))
    audio = review["checks"]["audio_spotcheck"]
    for key in ("separationMethod", "narrationLufs", "musicLufs", "speechMusicGain",
                "speechMusicSeparationLu"):
        audio.pop(key, None)
    audio.update(fields)
    review_path.write_text(json.dumps(review), encoding="utf-8")


def _complete(tmp_path: Path, review_path: Path) -> None:
    complete_phase(
        "run", "final_review", evidence={"final_review_path": str(review_path)},
        pipeline_dir=tmp_path, now=BASE,
    )


def test_final_review_omission_reason_must_restate_the_edit(tmp_path) -> None:
    _, _, review_path, _ = _review_ready_project(tmp_path)
    _write_edit(tmp_path / "run", {"audio": {"narration": "a.mp3"}, "omitMusicReason": _DECISION})
    _set_audio(review_path, music_present=False,
               musicOmittedReason="The reviewer felt the voice was enough.")
    with pytest.raises(PersianVideoWorkflowError, match="restate the edit's omitMusicReason"):
        _complete(tmp_path, review_path)


def test_final_review_cannot_report_no_music_for_an_edit_with_a_bed(tmp_path) -> None:
    _, _, review_path, _ = _review_ready_project(tmp_path)
    _write_edit(tmp_path / "run", {"audio": {"narration": "a.mp3"},
                                   "musicTrack": {"path": "assets/music/bed.mp3"}})
    _set_audio(review_path, music_present=False, musicOmittedReason=_DECISION)
    with pytest.raises(PersianVideoWorkflowError, match="ships a music bed"):
        _complete(tmp_path, review_path)


def test_final_review_cannot_report_music_for_an_edit_without_a_bed(tmp_path) -> None:
    _, _, review_path, _ = _review_ready_project(tmp_path)
    _write_edit(tmp_path / "run", {"audio": {"narration": "a.mp3"}, "omitMusicReason": _DECISION})
    with pytest.raises(PersianVideoWorkflowError, match="has no music bed"):
        _complete(tmp_path, review_path)


def test_final_review_that_restates_the_edit_completes(tmp_path) -> None:
    _, _, review_path, _ = _review_ready_project(tmp_path)
    _write_edit(tmp_path / "run", {"audio": {"narration": "a.mp3"}, "omitMusicReason": _DECISION})
    _set_audio(review_path, music_present=False, musicOmittedReason=_DECISION)
    _complete(tmp_path, review_path)
