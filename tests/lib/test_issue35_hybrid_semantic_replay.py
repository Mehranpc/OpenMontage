from __future__ import annotations

import hashlib

from lib.persian_srt import PersianCue
from tools.video.persian_compose_script_aligned import ScriptAlignedPersianCompose


def _approved(text: str) -> dict:
    return {
        "text": text,
        "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "matchPolicy": "exact",
        "maxCps": 21.0,
    }


def _moment(moment_id: str, start: float, end: float, anchor: str, *segments: str) -> dict:
    return {
        "id": moment_id,
        "kind": "statement",
        "startSeconds": start,
        "endSeconds": end,
        "anchorText": anchor,
        "segments": [
            {"role": "hero" if index == 0 else "tail", "text": text}
            for index, text in enumerate(segments)
        ],
    }


def test_real_hybrid_handoff_does_not_replay_styled_phrase_as_burned_caption() -> None:
    script = (
        "مدام باید حواسش جمع باشه، تصمیم بگیره، اطلاعات رو نگه داره "
        "و سریع واکنش نشون بده."
    )
    raw_words = [
        ("مدام", 33.72, 34.16), ("باید", 34.16, 34.42),
        ("حواسش", 34.42, 34.80), ("جمع", 34.80, 35.08),
        ("باشه،", 35.08, 35.46), ("تصمیم", 35.46, 36.00),
        ("بگیره،", 36.00, 36.50), ("اطلاعات", 36.50, 37.10),
        ("رو", 37.10, 37.24), ("نگه", 37.24, 37.50),
        ("داره", 37.50, 37.76), ("و", 37.76, 37.88),
        ("سریع", 37.88, 38.36), ("واکنش", 38.36, 38.80),
        ("نشون", 38.80, 39.04), ("بده.", 39.04, 39.30),
    ]
    persian = {
        "platformTarget": "instagram-reels",
        "captionMode": "hybrid",
        "_approvedSubtitleScript": _approved(script),
        "moments": [
            _moment(
                "moment-05", 33.5, 37.4, "مدام باید حواسش جمع باشه",
                "تصمیم بگیره", "سریع واکنش نشون بده",
            )
        ],
        "audio": {
            "wordTimings": [
                {"word": word, "start": start, "end": end, "probability": 0.99}
                for word, start, end in raw_words
            ]
        },
    }

    mode, captions = ScriptAlignedPersianCompose()._build_caption_props(persian)

    assert mode == "hybrid"
    assert all("سریع واکنش نشون بده" not in caption["text"] for caption in captions)


def test_shadow_suppression_uses_rendered_moment_copy_not_only_anchor_text() -> None:
    cases = [
        (
            PersianCue("caption-5", "حافظه و کنترل توجه و واکنش رو بهتر کنه.", 11.82, 15.199),
            _moment(
                "moment-02", 9.47, 12.79, "توجه دیداری، درک فضایی، حافظه",
                "توجه، درک فضایی، حافظه",
            ),
        ),
        (
            PersianCue("caption-10", "و داریم درباره بازی‌های معمولی حرف می‌زنیم،", 25.1, 27.52),
            _moment(
                "moment-04", 27.3, 31.2, "نه برنامه هایی که از اول",
                "بازی‌های معمولی", "نه فقط تمرین مغز",
            ),
        ),
        (
            PersianCue("caption-14", "اطلاعات رو نگه داره و سریع واکنش نشون بده.", 36.5, 39.3),
            _moment(
                "moment-05", 33.5, 37.4, "مدام باید حواسش جمع باشه",
                "تصمیم بگیره", "سریع واکنش نشون بده",
            ),
        ),
    ]

    for cue, moment in cases:
        kept = ScriptAlignedPersianCompose._suppress_semantically_shadowed_burned_cues(
            [cue], [moment]
        )
        assert kept == [], f"semantic replay survived for {moment['id']} / {cue.id}"
