from __future__ import annotations

import hashlib

import pytest

from lib.persian_srt_alignment import SubtitleAlignmentError, build_script_aligned_cues


def approved(text: str, policy: str = "exact", max_cps: float = 21.0) -> dict:
    return {
        "text": text,
        "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "matchPolicy": policy,
        "maxCps": max_cps,
    }


def timed(
    words: list[str],
    *,
    start: float = 0.0,
    duration: float = 0.50,
    gap: float = 0.05,
) -> list[dict]:
    result = []
    cursor = start
    for word in words:
        result.append(
            {
                "word": word,
                "start": cursor,
                "end": cursor + duration,
                "probability": 0.8,
            }
        )
        cursor += duration + gap
    return result


def joined(cues) -> str:
    return " ".join(cue.text for cue in cues)


def test_raw_whisper_spelling_never_reaches_delivery_copy() -> None:
    script = (
        "درخواست کردن همیشه آسان نیست. وقتی عذرخواهی می‌کنی، روشن حرف بزن. "
        "اگر لازم است عذرخواهی کن."
    )
    asr = timed([
        "درخواست", "گردن", "همیشه", "آسان", "نیست.",
        "وقتی", "اصخایی", "می", "کنی،", "روشن", "حرف", "بزن.",
        "اگر", "لازم", "است", "اوست", "خواهی", "کن.",
    ])
    cues = build_script_aligned_cues(approved(script), asr)
    delivery = joined(cues)
    assert delivery == script
    assert "درخواست گردن" not in delivery
    assert "اصخایی" not in delivery
    assert "اوست خواهی" not in delivery


def test_three_questions_cover_speech_instead_of_leaving_a_5_18_second_gap() -> None:
    script = (
        "چرا زیاد عذرخواهی می‌کنی؟ چه چیزی پشت این عادت است؟ "
        "چطور می‌توانی روشن‌تر حرف بزنی؟"
    )
    asr = timed([
        "چرا", "زیاد", "عذرخواهی", "می", "کنی؟",
        "چه", "چیزی", "پشت", "این", "عادت", "است؟",
        "چطور", "می", "توانی", "روشن", "تر", "حرف", "بزنی؟",
    ], duration=0.42, gap=0.04)
    cues = build_script_aligned_cues(approved(script), asr)
    assert joined(cues) == script
    for word in asr:
        midpoint = (word["start"] + word["end"]) / 2
        assert any(
            cue.start_seconds - 0.08 <= midpoint <= cue.end_seconds + 0.08
            for cue in cues
        )
    assert max(
        (
            later.start_seconds - earlier.end_seconds
            for earlier, later in zip(cues, cues[1:])
        ),
        default=0.0,
    ) < 0.10


def test_configured_reading_speed_is_a_delivery_gate() -> None:
    script = "این جمله باید آن‌قدر آرام گفته شود که خواندنی بماند."
    asr = timed(script.split(), duration=0.06, gap=0.01)
    with pytest.raises(SubtitleAlignmentError, match="chars/sec"):
        build_script_aligned_cues(approved(script, max_cps=14), asr)


def test_malformed_persian_spacing_and_missing_zwnj_are_rejected() -> None:
    script = "چرا عذرخواهی می کنی؟"
    with pytest.raises(SubtitleAlignmentError, match="ZWNJ"):
        build_script_aligned_cues(approved(script), timed(script.split()))


def test_digest_binds_the_exact_approved_script_bytes() -> None:
    script = "عذرخواهی کن."
    record = approved(script)
    record["text"] = "عذرخواهی نکن."
    with pytest.raises(SubtitleAlignmentError, match="sha256"):
        build_script_aligned_cues(record, timed(["عذرخواهی", "کن."]))


def test_unrelated_audio_is_rejected_instead_of_forced_into_script() -> None:
    script = "عذرخواهی روشن و دقیق بهتر است."
    asr = timed(["امروز", "هوا", "آفتابی", "و", "دریا", "آرام", "است."])
    with pytest.raises(SubtitleAlignmentError, match="confidence|low-confidence"):
        build_script_aligned_cues(approved(script), asr)


def test_normalized_policy_canonicalizes_digits_but_not_asr_spelling() -> None:
    script = "این کار 3 مرحله دارد."
    asr = timed(["این", "کار", "سه", "مرحله", "داره."])
    cues = build_script_aligned_cues(approved(script, policy="normalized"), asr)
    assert joined(cues) == "این کار ۳ مرحله دارد."


def test_exact_policy_preserves_ascii_digits_byte_for_byte() -> None:
    script = "این کار 3 مرحله دارد."
    asr = timed(["این", "کار", "سه", "مرحله", "داره."])
    cues = build_script_aligned_cues(approved(script, policy="exact"), asr)
    assert joined(cues) == script


def test_uncovered_or_overlapping_timing_is_rejected() -> None:
    script = "این یک آزمون است."
    asr = timed(script.split())
    asr[2]["start"] = asr[1]["start"]
    with pytest.raises(SubtitleAlignmentError, match="overlaps|not ordered"):
        build_script_aligned_cues(approved(script), asr)


def test_compose_preflight_requires_approved_script_for_narrated_srt() -> None:
    from tools.video.persian_compose import PersianCompose

    with pytest.raises(ValueError, match="approvedScript"):
        PersianCompose._aligned_subtitle_cues({
            "audio": {
                "wordTimings": timed(["متن", "خام"]),
            }
        })


def test_compose_writes_only_approved_copy(tmp_path) -> None:
    from tools.video.persian_compose import PersianCompose

    script = "درخواست کردن درست است."
    persian = {
        "audio": {
            "approvedScript": approved(script),
            "wordTimings": timed(["درخواست", "گردن", "درست", "است."]),
        }
    }
    output = tmp_path / "final.mp4"
    subtitle_path, advisories = PersianCompose._write_subtitles(persian, output)
    assert subtitle_path == str(tmp_path / "final.srt")
    assert advisories == []
    assert (tmp_path / "final.srt").read_text(encoding="utf-8-sig").endswith(
        "درخواست کردن درست است.\r\n"
    )
