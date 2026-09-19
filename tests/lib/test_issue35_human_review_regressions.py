from lib.persian_moments import audit_moments, build_moments
from lib.persian_srt import PersianCue
from tools.video.persian_compose_script_aligned import ScriptAlignedPersianCompose


def _moment(display: str) -> dict:
    return {
        "id": "moment-02",
        "kind": "statement",
        "startSeconds": 0.2,
        "endSeconds": 4.2,
        "segments": [{"role": "hero", "text": display}],
        "anchorText": "توجه دیداری، درک فضایی، حافظه",
        "presentation": {"placement": "auto"},
    }


def test_hybrid_caption_drops_semantically_replaced_cue_before_moment_handoff() -> None:
    cues = [
        PersianCue(
            "caption-4",
            "توانایی‌های ذهنی مثل توجه دیداری، درک فضایی،",
            8.34,
            11.759,
        )
    ]
    moments = [
        {
            "id": "moment-02",
            "startSeconds": 9.73,
            "endSeconds": 12.91,
            "anchorText": "توجه دیداری، درک فضایی، حافظه",
            "segments": [{"role": "hero", "text": "توجه، درک فضایی، حافظه"}],
        }
    ]

    kept = ScriptAlignedPersianCompose._suppress_semantically_shadowed_burned_cues(
        cues, moments
    )

    assert kept == []


def test_hybrid_caption_keeps_overlapping_cue_when_copy_is_not_the_moment_subject() -> None:
    cue = PersianCue(
        "caption-3",
        "بررسی‌های علمی نشون می‌دن بازی کردن می‌تونه بعضی",
        7.0,
        10.0,
    )
    moments = [
        {
            "id": "moment-02",
            "startSeconds": 9.73,
            "endSeconds": 12.91,
            "anchorText": "توجه دیداری، درک فضایی، حافظه",
            "segments": [{"role": "hero", "text": "توجه، درک فضایی، حافظه"}],
        }
    ]

    kept = ScriptAlignedPersianCompose._suppress_semantically_shadowed_burned_cues(
        [cue], moments
    )

    assert kept == [cue]


def test_enumerated_anchor_refuses_invented_or_truncated_list_label() -> None:
    moments = build_moments([_moment("توجه، فضا، حافظه")])

    problems = audit_moments(moments, duration_seconds=8.0).problems

    assert any("enumerated anchor" in problem and "فضا" in problem for problem in problems)


def test_enumerated_anchor_allows_whole_token_shortening_without_changing_concept() -> None:
    moments = build_moments([_moment("توجه، درک فضایی، حافظه")])

    problems = audit_moments(moments, duration_seconds=8.0).problems

    assert not any("enumerated anchor" in problem for problem in problems)
