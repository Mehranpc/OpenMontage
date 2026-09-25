from __future__ import annotations

import hashlib

import pytest

from tools.video.persian_compose import PersianCompose
from tools.video.persian_compose_script_aligned import ScriptAlignedPersianCompose


def _approved(text: str) -> dict:
    return {
        "text": text,
        "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "matchPolicy": "exact",
        "maxCps": 21.0,
    }


def _edit(*, approved: str, raw_words: list[tuple[str, float, float]], anchor: str) -> dict:
    return {
        "metadata": {"persianSubtitleScript": _approved(approved)},
        "persian": {
            "format": "vertical",
            "durationSeconds": 10.0,
            "moments": [
                {
                    "id": "moment-01",
                    "kind": "statement",
                    "startSeconds": 0.0,
                    "endSeconds": 4.5,
                    "anchorText": anchor,
                    "segments": [
                        {"role": "hero", "text": "۵۴۳ نفر"},
                        {"role": "tail", "text": "یک قرار اول"},
                    ],
                }
            ],
            "audio": {
                "wordTimings": [
                    {"word": word, "start": start, "end": end, "probability": 0.99}
                    for word, start, end in raw_words
                ]
            },
        },
    }


_APPROVED = "مطالعه جالب‌ترین نتیجه را نشان داد"
# A lightly misspelled lightweight-model transcript: the words are recognisably the
# same spoken content, but they are not the approved script's lexical wording.
_RAW_ASR = [
    ("مطاله", 0.20, 0.80),
    ("جالترین", 0.80, 1.40),
    ("نتجه", 1.40, 2.00),
    ("را", 2.00, 2.20),
    ("نشان", 2.20, 2.70),
    ("داد", 2.70, 3.10),
]


def test_script_derived_anchor_locates_against_aligned_timings() -> None:
    """#152: a moment anchored on the approved script must locate even when the raw
    ASR rows misspell those words.

    Moment sync used to prefer the raw lightweight-ASR rows, so an anchor had to be
    written in ASR spellings to pass, and on the L3 run with the base model that
    meant transcribing «مطاله … نتجه»-style text into the edit artifact. Script
    alignment already produces provably-aligned script timings -- gated by
    ``SubtitleAlignmentError`` -- and those are the timings the pipeline actually
    aligns the script to.
    """
    edit = _edit(approved=_APPROVED, raw_words=_RAW_ASR, anchor="مطالعه جالب‌ترین نتیجه")

    runtime = ScriptAlignedPersianCompose._runtime_persian(edit)
    assert runtime is not None
    # The aligned wording is what the pipeline aligns the script to...
    assert [row["word"] for row in runtime["audio"]["wordTimings"]] == _APPROVED.split()
    # ...and it is now the only timing basis carried into the render.
    assert "_syncWordTimings" not in runtime["audio"]

    moments = PersianCompose._build_moments(runtime, 10.0, v2=True, measure_layout=False)

    assert [moment["id"] for moment in moments] == ["moment-01"]


def test_asr_spelled_anchor_is_no_longer_required() -> None:
    """The behaviour that forced ASR-spelling anchors is gone: the same moment
    anchored in the *raw ASR* wording no longer matches the aligned basis."""
    edit = _edit(approved=_APPROVED, raw_words=_RAW_ASR, anchor="مطاله جالترین نتجه")

    runtime = ScriptAlignedPersianCompose._runtime_persian(edit)
    assert runtime is not None

    with pytest.raises(ValueError, match="was not found in the narration word timings"):
        PersianCompose._build_moments(runtime, 10.0, v2=True, measure_layout=False)


def test_anchor_never_spoken_still_refuses() -> None:
    """Fixing the basis must not make the gate permissive: an anchor whose words the
    voiceover never says is still refused."""
    edit = _edit(
        approved=_APPROVED,
        raw_words=_RAW_ASR,
        anchor="اقتصاد جهانی بازارهای مالی",
    )

    runtime = ScriptAlignedPersianCompose._runtime_persian(edit)
    assert runtime is not None

    with pytest.raises(ValueError, match="was not found in the narration word timings"):
        PersianCompose._build_moments(runtime, 10.0, v2=True, measure_layout=False)
