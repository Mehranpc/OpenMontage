from __future__ import annotations

import pytest

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


def test_phrase_lock_must_contain_at_least_two_words() -> None:
    authored = _moment({
        "role": "hero",
        "text": "سلامت روان مهم است",
        "phraseLocks": ["سلامت"],
    })
    with pytest.raises(ValueError, match="phraseLocks.*two words"):
        build_moments([authored])
