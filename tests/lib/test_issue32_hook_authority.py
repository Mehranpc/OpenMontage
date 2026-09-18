from __future__ import annotations

from pathlib import Path

from lib.persian_video_workflow import bootstrap_persian_video


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
