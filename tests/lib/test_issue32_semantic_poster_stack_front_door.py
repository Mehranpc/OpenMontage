from __future__ import annotations

import json
from pathlib import Path

import pytest

from lib.persian_editorial_hook import PersianEditorialHookError
from lib.persian_video_workflow import bootstrap_persian_video, stage_workflow_edit_draft
from schemas.artifacts import validate_artifact
from tests.lib.test_persian_preflight_contract import _payload
from tests.lib.test_persian_video_workflow import BASE, _advance_to


HOOK = "بزرگ‌ترین اشتباه دربارهٔ بازی‌های ویدیویی اینه که فکر کنیم فقط وقت تلف کردنه!"


def test_front_door_persists_explicit_semantic_poster_stack_before_preflight(tmp_path: Path) -> None:
    narration = tmp_path.parent / f"{tmp_path.name}-semantic-hook.wav"
    narration.write_bytes(b"audio")
    bootstrap_persian_video(
        title="Semantic poster stack",
        approved_script=HOOK,
        narration_path=str(narration),
        hook_text=HOOK,
        project_id="run",
        pipeline_dir=tmp_path,
        backlot_opener=lambda _pid: 0,
        now=BASE,
    )
    _advance_to(tmp_path, "no_copy_preflight")

    payload = _payload()
    payload["version"] = "1.0"
    payload["renderer_family"] = "persian-footage"
    payload["render_runtime"] = "remotion"
    hook = payload["persian"]["moments"][0]
    hook.update({
        "kind": "hook",
        "purpose": "hook-pattern-interrupt",
        "startSeconds": 0.0,
        "endSeconds": 5.0,
        "presentation": {"placement": "upper-right", "recipeId": "editorial-hero-balanced"},
        "segments": [
            {"role": "lead", "semanticRole": "setup", "text": "بزرگ‌ترین اشتباه"},
            {"role": "lead", "semanticRole": "bridge", "text": "دربارهٔ"},
            {"role": "hero", "semanticRole": "subject_hero", "text": "بازی‌های ویدیویی"},
            {"role": "tail", "semanticRole": "connector", "text": "اینه که فکر کنیم فقط"},
            {"role": "tail", "semanticRole": "payoff", "text": "وقت تلف کردنه!"},
        ],
    })
    source = tmp_path / "run" / "semantic-edit.json"
    source.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    staged = stage_workflow_edit_draft("run", "semantic-v1", source, pipeline_dir=tmp_path)
    poster = staged["hookAuthority"]["semanticPosterStack"]
    assert poster["version"] == "1.0"
    assert poster["authoritativeHookText"] == HOOK
    assert [phrase["role"] for phrase in poster["phrases"]] == [
        "setup", "bridge", "subject_hero", "connector", "payoff"
    ]
    assert " ".join(phrase["text"] for phrase in poster["phrases"]) == HOOK

    persisted = json.loads(Path(staged["draftPath"]).read_text(encoding="utf-8"))
    assert persisted["metadata"]["semanticPosterStack"] == poster
    assert all(
        "semanticRole" not in segment
        for segment in persisted["persian"]["moments"][0]["segments"]
    )
    validate_artifact("edit_decisions", persisted)


def test_editorial_opening_cannot_fall_back_to_position_inferred_roles(tmp_path: Path) -> None:
    narration = tmp_path.parent / f"{tmp_path.name}-missing-semantic-hook.wav"
    narration.write_bytes(b"audio")
    bootstrap_persian_video(
        title="No positional semantic fallback",
        approved_script=HOOK,
        narration_path=str(narration),
        hook_text=HOOK,
        project_id="run",
        pipeline_dir=tmp_path,
        backlot_opener=lambda _pid: 0,
        now=BASE,
    )
    _advance_to(tmp_path, "no_copy_preflight")

    payload = _payload()
    payload["persian"]["moments"][0].update({
        "kind": "hook",
        "purpose": "hook-pattern-interrupt",
        "startSeconds": 0.0,
        "endSeconds": 5.0,
        "presentation": {"placement": "upper-right", "recipeId": "editorial-hero-balanced"},
        "segments": [
            {"role": "lead", "text": "بزرگ‌ترین اشتباه"},
            {"role": "lead", "text": "دربارهٔ"},
            {"role": "hero", "text": "بازی‌های ویدیویی"},
            {"role": "tail", "text": "اینه که فکر کنیم فقط"},
            {"role": "tail", "text": "وقت تلف کردنه!"},
        ],
    })
    source = tmp_path / "run" / "missing-semantic-edit.json"
    source.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(PersianEditorialHookError, match="explicit semanticRole"):
        stage_workflow_edit_draft("run", "semantic-missing", source, pipeline_dir=tmp_path)
