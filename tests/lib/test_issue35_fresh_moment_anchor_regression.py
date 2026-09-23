from __future__ import annotations

from lib.persian_moments import build_moments
from lib.persian_sync import ANCHOR_HOLD_SECONDS, TimedWord, audit_sync


def _words() -> list[TimedWord]:
    return [
        TimedWord("علمی", 5.94, 6.28),
        TimedWord("نشون", 6.28, 6.56),
        TimedWord("می دهند", 6.56, 6.98),
        TimedWord("توجه", 9.72, 10.14),
        TimedWord("دیداری", 10.14, 10.74),
        TimedWord("درک", 10.74, 11.20),
        TimedWord("فضایی", 11.20, 11.82),
        TimedWord("حافظه", 11.82, 12.44),
    ]


def _moment(*, anchor: str, display: str, start: float) -> dict:
    return {
        "id": "moment-02",
        "kind": "statement",
        "startSeconds": start,
        "endSeconds": start + 4.8,
        "segments": [
            {"role": "hero", "text": display},
            {"role": "tail", "text": "می تونن بهتر بشن"},
        ],
        "anchorText": anchor,
        "presentation": {"placement": "auto"},
    }


def test_list_callout_cannot_bind_to_unrelated_earlier_words() -> None:
    moments = build_moments([
        _moment(
            anchor="علمی نشون",
            display="توجه، حافظه، درک فضایی",
            start=5.70,
        )
    ])

    audit = audit_sync(moments, _words())

    assert any("enumerated display" in problem and "anchor" in problem for problem in audit.problems)


def test_list_callout_must_preserve_spoken_item_order() -> None:
    moments = build_moments([
        _moment(
            anchor="توجه دیداری، درک فضایی، حافظه",
            display="توجه، حافظه، درک فضایی",
            start=9.47,
        )
    ])

    audit = audit_sync(moments, _words())

    assert any("spoken order" in problem for problem in audit.problems)


def test_list_callout_allows_ordered_whole_word_shortening() -> None:
    moments = build_moments([
        _moment(
            anchor="توجه دیداری، درک فضایی، حافظه",
            display="توجه، درک فضایی، حافظه",
            start=9.47,
        )
    ])

    audit = audit_sync(moments, _words())

    assert audit.problems == []


def test_result_first_hook_prose_comma_is_not_treated_as_spoken_list() -> None:
    moments = build_moments([
        {
            "id": "opening-hook",
            "kind": "hook",
            "purpose": "hook-pattern-interrupt",
            "startSeconds": 5.69,
            "endSeconds": 10.29,
            "segments": [
                {"role": "hero", "text": "در این آزمایش، پیامِ صبح روز بعد"},
                {"role": "tail", "text": "بیشترین تمایل به ادامهٔ رابطه را نشان داد."},
            ],
            "anchorText": "علمی نشون",
            "presentation": {"placement": "auto"},
        }
    ])

    audit = audit_sync(moments, _words())

    assert not any("enumerated display" in problem for problem in audit.problems)


def test_asr_yeh_hamza_variant_consumes_full_enumerated_anchor_span() -> None:
    words = [
        TimedWord("توجه", 9.72, 10.14),
        TimedWord("دیداری", 10.14, 10.74),
        TimedWord("درک", 10.74, 11.20),
        TimedWord("فضائی،", 11.20, 11.82),
        TimedWord("حافظه", 11.82, 12.44),
    ]
    moments = build_moments([
        _moment(
            anchor="توجه دیداری، درک فضایی، حافظه",
            display="توجه، درک فضایی، حافظه",
            start=9.47,
        )
    ])

    audit = audit_sync(moments, words)
    binding = audit.bindings[0]

    assert binding.matched_words == ["توجه", "دیداری", "درک", "فضائی،", "حافظه"]
    assert binding.derived_end is not None
    assert binding.derived_end >= 12.44 + ANCHOR_HOLD_SECONDS
