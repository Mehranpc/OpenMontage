from __future__ import annotations

import pytest

from lib.persian_edit_contract import validate_persian_edit_contract
from lib.persian_moments import build_moments


def _moment(segment: dict) -> dict:
    return {
        "id": "m",
        "kind": "statement",
        "startSeconds": 1.0,
        "endSeconds": 7.0,
        "segments": [segment],
    }


def test_phrase_locks_round_trip_through_moment_props() -> None:
    authored = _moment({
        "role": "hero",
        "text": "تمرین‌های روزانه سلامت روان را بهتر می‌کنند",
        "phraseLocks": ["سلامت روان"],
    })
    (moment,) = build_moments([authored])
    assert moment.segments[0].phrase_locks == ["سلامت روان"]

    props = moment.to_props()
    assert props["segments"][0]["phraseLocks"] == ["سلامت روان"]
    (rebuilt,) = build_moments([props])
    assert rebuilt.segments[0].phrase_locks == ["سلامت روان"]


def test_phrase_lock_must_be_a_contiguous_phrase_in_its_segment() -> None:
    authored = _moment({
        "role": "hero",
        "text": "تمرین‌های روزانه سلامت روان را بهتر می‌کنند",
        "phraseLocks": ["کنترل توجه"],
    })
    with pytest.raises(ValueError, match="phraseLocks.*contiguous"):
        build_moments([authored])


def test_phrase_lock_cannot_cross_an_authored_line_break() -> None:
    authored = _moment({
        "role": "hero",
        "text": "تمرین‌های روزانه سلامت\nروان را بهتر می‌کنند",
        "phraseLocks": ["سلامت روان"],
    })
    with pytest.raises(ValueError, match="phraseLocks.*contiguous"):
        build_moments([authored])


def test_phrase_lock_must_contain_at_least_two_words() -> None:
    authored = _moment({
        "role": "hero",
        "text": "سلامت روان مهم است",
        "phraseLocks": ["سلامت"],
    })
    with pytest.raises(ValueError, match="phraseLocks.*two words"):
        build_moments([authored])


def test_phrase_locks_are_accepted_by_the_edit_front_door_schema() -> None:
    edit = {
        "persian": {
            "format": "vertical",
            "durationSeconds": 12.0,
            "shots": [{
                "id": "shot-1",
                "source": "clip.mp4",
                "startSeconds": 0.0,
                "endSeconds": 12.0,
                "camera": "none",
                "attribution": "Video by Test on Pexels",
                "avoidRegions": [{"x": 0.1, "y": 0.2, "w": 0.3, "h": 0.4}],
            }],
            "moments": [{
                "id": "moment-1",
                "kind": "statement",
                "startSeconds": 1.0,
                "endSeconds": 7.0,
                "segments": [{
                    "role": "hero",
                    "text": "تمرین‌های روزانه سلامت روان را بهتر می‌کنند",
                    "phraseLocks": ["سلامت روان"],
                }],
            }],
            "typographicBeats": [],
            "audio": {},
            "watermark": {
                "persianText": "طریقت تسلیم",
                "latinText": "Pathway_of_Surrender",
            },
        }
    }
    validate_persian_edit_contract(edit)
