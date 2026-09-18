from __future__ import annotations

from pathlib import Path

from lib.persian_video_workflow import bootstrap_persian_video, record_hook_selection


SCRIPT = "بزرگ‌ترین اشتباه دربارهٔ بازی‌های ویدیویی اینه که فکر کنیم فقط وقت تلف کردنه!"
HOOK = "بازی فقط وقت‌تلف‌کردن نیست؛ مغزت واقعاً درگیره"


def test_user_supplied_hook_is_authoritative_at_front_door(tmp_path: Path) -> None:
    state = bootstrap_persian_video(
        title="Hook authority",
        approved_script=SCRIPT,
        hook_text=HOOK,
        project_id="hook-authority",
        pipeline_dir=tmp_path,
        backlot_opener=lambda _pid: 0,
    )

    decision = state["hook_selection"]
    assert decision["mode"] == "user_supplied"
    assert decision["text"] == HOOK
    assert decision["authoritative"] is True
    assert decision["may_be_replaced_automatically"] is False
    assert decision["sha256"]


def test_missing_user_hook_activates_repo_owned_selector_corpus(tmp_path: Path) -> None:
    state = bootstrap_persian_video(
        title="Auto hook",
        approved_script=SCRIPT,
        project_id="auto-hook",
        pipeline_dir=tmp_path,
        backlot_opener=lambda _pid: 0,
    )

    decision = state["hook_selection"]
    assert decision["mode"] == "automatic"
    assert decision["authoritative"] is False
    assert decision["selection_policy"] == "retention-first-v1"
    assert decision["corpus"] == [
        "docs/reference/persian-hooks/hookbook.md",
        "docs/reference/persian-hooks/hook-library-fa.md",
        "docs/reference/persian-hooks/hook-selector-helper.md",
    ]


def test_automatic_hook_selection_is_persisted_with_truth_and_retention_evidence(tmp_path: Path) -> None:
    bootstrap_persian_video(
        title="Auto hook selection", approved_script=SCRIPT, project_id="auto-selected",
        pipeline_dir=tmp_path, backlot_opener=lambda _pid: 0,
    )

    state = record_hook_selection(
        "auto-selected",
        selected_text="بزرگ‌ترین اشتباه دربارهٔ بازی‌های ویدیویی اینه که فکر کنیم فقط وقت تلف کردنه!",
        hook_family="common-mistake",
        candidates=[
            {"text": "بازی فقط سرگرمیه؟", "score": 5.5},
            {"text": "بزرگ‌ترین اشتباه دربارهٔ بازی‌های ویدیویی اینه که فکر کنیم فقط وقت تلف کردنه!", "score": 8.6},
            {"text": "بازی و مغز", "score": 4.0},
        ],
        score=8.6,
        content_match_score=2,
        evidence_checked=True,
        unsupported_claims_rejected=True,
        rationale="The common-mistake family names the topic, creates tension, and stays inside the supplied evidence.",
        pipeline_dir=tmp_path,
    )

    decision = state["hook_selection"]
    assert decision["status"] == "selected"
    assert decision["hook_family"] == "common-mistake"
    assert decision["score"] == 8.6
    assert decision["content_match_score"] == 2
    assert decision["candidate_count"] == 3


def test_user_hook_cannot_be_replaced_by_automatic_selection(tmp_path: Path) -> None:
    bootstrap_persian_video(
        title="Locked hook", approved_script=SCRIPT, hook_text=HOOK, project_id="locked-hook",
        pipeline_dir=tmp_path, backlot_opener=lambda _pid: 0,
    )

    import pytest
    from lib.persian_editorial_hook import PersianEditorialHookError

    with pytest.raises(PersianEditorialHookError, match="authoritative"):
        record_hook_selection(
            "locked-hook", selected_text="یک هوک دیگر", hook_family="question",
            candidates=[{"text": "a"}, {"text": "b"}], score=9.0, content_match_score=2,
            evidence_checked=True, unsupported_claims_rejected=True, rationale="replacement",
            pipeline_dir=tmp_path,
        )
