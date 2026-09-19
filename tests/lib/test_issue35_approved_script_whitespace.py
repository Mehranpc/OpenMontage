from __future__ import annotations

import hashlib

import pytest

from lib.persian_srt_alignment import SubtitleAlignmentError, build_script_aligned_cues


def _approved(text: str) -> dict:
    return {
        "text": text,
        "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "matchPolicy": "exact",
        "maxCps": 21,
    }


def _timed(words: list[str]) -> list[dict]:
    return [
        {"word": word, "start": index * 0.7, "end": index * 0.7 + 0.55}
        for index, word in enumerate(words)
    ]


def test_front_door_multiline_approved_script_uses_line_breaks_as_token_separators() -> None:
    script = "این یک آزمون است.\nخط دوم هم ادامه دارد.\n"
    words = ["این", "یک", "آزمون", "است.", "خط", "دوم", "هم", "ادامه", "دارد."]

    cues = build_script_aligned_cues(_approved(script), _timed(words))

    assert " ".join(cue.text for cue in cues) == "این یک آزمون است. خط دوم هم ادامه دارد."


def test_multiline_support_does_not_allow_tabs_as_token_separators() -> None:
    script = "این\tیک آزمون است."
    with pytest.raises(SubtitleAlignmentError, match="whitespace|tabs|ASCII space"):
        build_script_aligned_cues(_approved(script), _timed(["این", "یک", "آزمون", "است."]))
