from __future__ import annotations

import hashlib

from tools.video.persian_compose import PersianCompose
from tools.video.persian_compose_script_aligned import ScriptAlignedPersianCompose


def _approved(text: str) -> dict:
    return {
        "text": text,
        "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "matchPolicy": "exact",
        "maxCps": 21.0,
    }


def test_script_alignment_does_not_replace_raw_sync_evidence() -> None:
    approved = "۵۴۳ نفر تصور کردند یک قرار اول داشتند"
    raw_words = [
        ("543", 0.20, 0.55),
        ("نفر", 0.55, 0.85),
        ("تصور", 0.85, 1.20),
        ("کردن", 1.20, 1.55),
        ("یه", 1.55, 1.75),
        ("قرار", 1.75, 2.05),
        ("اول", 2.05, 2.30),
        ("داشتن", 2.30, 2.65),
    ]
    edit = {
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
                    "anchorText": "543 نفر تصور کردن یه قرار اول داشتن",
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

    runtime = ScriptAlignedPersianCompose._runtime_persian(edit)
    assert runtime is not None
    assert [row["word"] for row in runtime["audio"]["wordTimings"]] == approved.split()

    moments = PersianCompose._build_moments(
        runtime,
        10.0,
        v2=True,
        measure_layout=False,
    )

    assert [moment["id"] for moment in moments] == ["moment-01"]
