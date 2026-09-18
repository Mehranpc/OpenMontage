from __future__ import annotations

from pathlib import Path

from lib.persian_video_workflow import bootstrap_persian_video, record_hook_selection, stage_workflow_edit_draft
from tests.lib.test_persian_preflight_contract import _payload
from tests.lib.test_persian_video_workflow import _advance_to


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



def _bootstrap_to_preflight(tmp_path: Path, *, hook_text: str | None) -> None:
    source = tmp_path.parent / f"{tmp_path.name}-issue32-hook.wav"
    source.write_bytes(b"audio")
    bootstrap_persian_video(
        title="Hook staging authority",
        approved_script=SCRIPT,
        narration_path=str(source),
        hook_text=hook_text,
        project_id="run",
        pipeline_dir=tmp_path,
        backlot_opener=lambda _pid: 0,
    )
    _advance_to(tmp_path, "no_copy_preflight")


def _stage_payload(tmp_path: Path, hook_text: str, *, attempt: str = "edit-v1") -> dict:
    import json

    payload = _payload()
    payload["persian"]["moments"][0]["segments"] = [
        {"role": "hero", "text": hook_text}
    ]
    source = tmp_path / "run" / f"{attempt}.json"
    source.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return stage_workflow_edit_draft("run", attempt, source, pipeline_dir=tmp_path)


def test_edit_stage_refuses_rewrite_of_user_authoritative_hook(tmp_path: Path) -> None:
    import pytest
    from lib.persian_editorial_hook import PersianEditorialHookError

    _bootstrap_to_preflight(tmp_path, hook_text=HOOK)

    with pytest.raises(PersianEditorialHookError, match="authoritative"):
        _stage_payload(tmp_path, "یک هوک دیگر")

    staged = _stage_payload(tmp_path, HOOK, attempt="edit-v2")
    assert staged["hookAuthority"]["mode"] == "user_supplied"
    assert staged["hookAuthority"]["verified"] is True


def test_edit_stage_requires_auto_selection_and_locks_its_winner(tmp_path: Path) -> None:
    import pytest
    from lib.persian_editorial_hook import PersianEditorialHookError

    _bootstrap_to_preflight(tmp_path, hook_text=None)
    with pytest.raises(PersianEditorialHookError, match="selection required"):
        _stage_payload(tmp_path, SCRIPT)

    record_hook_selection(
        "run",
        selected_text=SCRIPT,
        hook_family="common-mistake",
        candidates=[{"text": "بازی فقط سرگرمیه؟"}, {"text": SCRIPT}],
        score=8.6,
        content_match_score=2,
        evidence_checked=True,
        unsupported_claims_rejected=True,
        rationale="The selected hook names the topic and preserves the supported claim.",
        pipeline_dir=tmp_path,
    )

    with pytest.raises(PersianEditorialHookError, match="selected hook"):
        _stage_payload(tmp_path, "هوک تغییر کرده", attempt="edit-v2")

    staged = _stage_payload(tmp_path, SCRIPT, attempt="edit-v3")
    assert staged["hookAuthority"]["mode"] == "automatic"
    assert staged["hookAuthority"]["verified"] is True
