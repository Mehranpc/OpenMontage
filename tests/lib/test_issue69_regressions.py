from __future__ import annotations

import subprocess

import pytest

from lib.persian_finalization import _run_ffmpeg_master, mastering_policy
from lib.persian_moments import audit_moments, build_moments
from lib.persian_srt import build_cues


def _timed(words: list[str], *, start: float = 0.0, duration: float = 0.38, gap: float = 0.02) -> list[dict]:
    cursor = start
    result = []
    for word in words:
        result.append({"word": word, "start": cursor, "end": cursor + duration})
        cursor += duration + gap
    return result


def test_mutually_exclusive_alternatives_support_replace_sequence() -> None:
    moments = build_moments([{
        "id": "timing-options",
        "kind": "statement",
        "startSeconds": 0.0,
        "endSeconds": 4.63,
        "presentation": {
            "placement": "auto",
            "motion": "cut-in",
            "sequenceMode": "replace",
        },
        "segments": [
            {"role": "hero", "text": "بلافاصله", "revealAfterSeconds": 0.0},
            {"role": "hero", "text": "صبح روز بعد", "revealAfterSeconds": 1.25},
            {"role": "hero", "text": "دو روز بعد", "revealAfterSeconds": 2.75},
        ],
    }])
    props = moments[0].to_props()
    assert props["presentation"]["sequenceMode"] == "replace"
    assert [s.get("revealAfterSeconds", 0) for s in props["segments"]] == [0, 1.25, 2.75]
    audit = audit_moments(moments, duration_seconds=62.16, adaptive_pixel_typography=True)
    assert audit.problems == []


def test_replace_sequence_rejects_non_increasing_reveal_order() -> None:
    moments = build_moments([{
        "id": "bad-options",
        "kind": "statement",
        "startSeconds": 2.0,
        "endSeconds": 7.0,
        "presentation": {"sequenceMode": "replace"},
        "segments": [
            {"role": "hero", "text": "اول", "revealAfterSeconds": 0.0},
            {"role": "hero", "text": "دوم", "revealAfterSeconds": 0.0},
        ],
    }])
    audit = audit_moments(moments, duration_seconds=10.0, adaptive_pixel_typography=True)
    assert any("replace sequence" in problem and "increasing" in problem for problem in audit.problems)


def test_caption_rebalances_sentence_tail_to_keep_predicate_with_its_head() -> None:
    words = [
        {"word": "«دیر", "start": 51.14, "end": 51.54},
        {"word": "پیام", "start": 51.54, "end": 51.98},
        {"word": "بده", "start": 51.98, "end": 52.22},
        {"word": "تا", "start": 52.22, "end": 52.44},
        {"word": "مشتاق", "start": 52.44, "end": 52.84},
        {"word": "به", "start": 52.84, "end": 52.96},
        {"word": "نظر", "start": 52.96, "end": 53.36},
        {"word": "نرسی»", "start": 53.36, "end": 53.78},
        {"word": "استراتژی", "start": 53.78, "end": 54.88},
        {"word": "خیلی", "start": 54.88, "end": 55.26},
        {"word": "خوبی", "start": 55.26, "end": 55.58},
        {"word": "نبود.", "start": 55.58, "end": 55.94},
    ]
    cues = build_cues(words, persian_digits=False, max_visible_chars=54)
    texts = [cue.text for cue in cues]
    assert any(text == "استراتژی خیلی خوبی نبود." for text in texts), texts
    assert not any(text.endswith("استراتژی") for text in texts[:-1]), texts


def test_mastering_uses_encoder_headroom_below_delivery_true_peak(monkeypatch, tmp_path) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"fixture")
    output = tmp_path / "out.mp4"
    captured = {}

    monkeypatch.setattr("lib.persian_finalization.shutil.which", lambda _name: "/usr/bin/ffmpeg")

    def fake_run(args, **kwargs):
        captured["args"] = list(args)
        output.write_bytes(b"mastered")
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr("lib.persian_finalization.subprocess.run", fake_run)
    policy = mastering_policy()
    _run_ffmpeg_master(source, output, policy)

    loudnorm = captured["args"][captured["args"].index("-af") + 1]
    assert policy["truePeakCeilingDbfs"] == -1.5
    assert policy["processingTruePeakDbfs"] <= -1.9
    assert f"TP={policy['processingTruePeakDbfs']}" in loudnorm
