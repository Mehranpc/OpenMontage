from __future__ import annotations

import hashlib

import pytest

from lib.persian_srt_alignment import (
    SubtitleAlignmentError,
    build_script_aligned_cues,
)


def approved(text: str, policy: str) -> dict:
    return {
        "text": text,
        "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "matchPolicy": policy,
        "maxCps": 21,
    }


def test_normalized_policy_canonicalizes_arabic_letters_and_ascii_digits() -> None:
    script = "اين كار 3 مرحله دارد."
    words = [
        {"word": word, "start": index * 0.6, "end": index * 0.6 + 0.5}
        for index, word in enumerate(["این", "کار", "سه", "مرحله", "داره."])
    ]
    cues = build_script_aligned_cues(approved(script, "normalized"), words)
    assert " ".join(cue.text for cue in cues) == "این کار ۳ مرحله دارد."


def test_word_overlap_above_one_millisecond_is_rejected() -> None:
    script = "این کار درست است."
    words = [
        {"word": "این", "start": 0.0, "end": 0.5},
        {"word": "کار", "start": 0.49, "end": 1.0},
        {"word": "درست", "start": 1.1, "end": 1.6},
        {"word": "است.", "start": 1.7, "end": 2.2},
    ]
    with pytest.raises(SubtitleAlignmentError, match="overlaps"):
        build_script_aligned_cues(approved(script, "exact"), words)
