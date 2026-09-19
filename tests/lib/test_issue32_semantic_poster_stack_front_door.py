from __future__ import annotations

import json
from pathlib import Path

import pytest

from lib.persian_editorial_hook import (
    PersianEditorialHookError,
    validate_edit_hook_authority,
)
from lib.persian_video_workflow import bootstrap_persian_video, stage_workflow_edit_draft
from schemas.artifacts import validate_artifact
from tests.lib.test_persian_preflight_contract import _payload
from tests.lib.test_persian_video_workflow import BASE, _advance_to
from tools.video.persian_compose_script_aligned import ScriptAlignedPersianCompose


HOOK = "بزرگ‌ترین اشتباه دربارهٔ بازی‌های ویدیویی اینه که فکر کنیم فقط وقت تلف کردنه!"
POSTER_ROLES = ["setup", "bridge", "subject_hero", "connector", "payoff"]


def _poster_plan() -> dict:
    return {
        "version": "1.0",
        "authoritativeHookText": HOOK,
        "authoritativeHookSha256": "691797db0dc2a07838f472d831ac543d70cf4e8eeba3087431a81b019b56d5d8",
        "phrases": [
            {"role": "setup", "text": "بزرگ‌ترین اشتباه"},
            {"role": "bridge", "text": "دربارهٔ"},
            {"role": "subject_hero", "text": "بازی‌های ویدیویی"},
            {"role": "connector", "text": "اینه که فکر کنیم فقط"},
            {"role": "payoff", "text": "وقت تلف کردنه!"},
        ],
    }


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
    assert [phrase["role"] for phrase in poster["phrases"]] == POSTER_ROLES
    assert " ".join(phrase["text"] for phrase in poster["phrases"]) == HOOK

    persisted = json.loads(Path(staged["draftPath"]).read_text(encoding="utf-8"))
    assert persisted["metadata"]["semanticPosterStack"] == poster
    assert all(
        "semanticRole" not in segment
        for segment in persisted["persian"]["moments"][0]["segments"]
    )
    validate_artifact("edit_decisions", persisted)

    # Bounded recovery restages the canonical artifact after transport-only
    # semanticRole fields have been stripped. A timing edit must not require the
    # agent to reconstruct those authoring-only fields.
    persisted["persian"]["moments"][0]["startSeconds"] = 0.1
    restage_source = tmp_path / "run" / "semantic-edit-restage.json"
    restage_source.write_text(json.dumps(persisted, ensure_ascii=False), encoding="utf-8")
    restaged = stage_workflow_edit_draft(
        "run",
        "semantic-v2",
        restage_source,
        pipeline_dir=tmp_path,
        parent_attempt_id="semantic-v1",
        diagnostic_code="EDIT_ARTIFACT",
        recovery_class="EDIT_ARTIFACT",
        strategy="repair_reported_contract_field_only",
        changed_fields=["persian.moments[0].startSeconds"],
    )
    assert restaged["hookAuthority"]["semanticPosterStack"] == poster
    restaged_payload = json.loads(Path(restaged["draftPath"]).read_text(encoding="utf-8"))
    assert all(
        "semanticRole" not in segment
        for segment in restaged_payload["persian"]["moments"][0]["segments"]
    )


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


def test_compose_runtime_rehydrates_semantic_roles_from_canonical_metadata() -> None:
    plan = _poster_plan()
    edit_decisions = {
        "metadata": {"semanticPosterStack": plan},
        "persian": {
            "moments": [{
                "id": "hook",
                "kind": "hook",
                "purpose": "hook-pattern-interrupt",
                "segments": [
                    {"role": "lead", "text": "بزرگ‌ترین اشتباه"},
                    {"role": "lead", "text": "دربارهٔ"},
                    {"role": "hero", "text": "بازی‌های ویدیویی"},
                    {"role": "tail", "text": "اینه که فکر کنیم فقط"},
                    {"role": "tail", "text": "وقت تلف کردنه!"},
                ],
            }],
        },
    }

    runtime = ScriptAlignedPersianCompose._runtime_persian(edit_decisions)
    assert runtime is not None
    assert runtime["_semanticPosterStack"] == plan
    hydrated = ScriptAlignedPersianCompose._rehydrate_semantic_poster_stack(
        runtime["moments"], runtime["_semanticPosterStack"]
    )
    segments = hydrated[0]["segments"]
    assert [segment["semanticRole"] for segment in segments] == POSTER_ROLES
    assert " ".join(segment["text"] for segment in segments) == HOOK


def test_canonical_semantic_poster_stack_rejects_stale_phrase_text() -> None:
    plan = _poster_plan()
    plan["phrases"][4]["text"] = "متن دستکاری‌شده"
    payload = {
        "metadata": {"semanticPosterStack": plan},
        "persian": {
            "moments": [{
                "id": "hook",
                "kind": "hook",
                "purpose": "hook-pattern-interrupt",
                "presentation": {"recipeId": "editorial-hero-balanced"},
                "segments": [
                    {"role": "lead", "text": "بزرگ‌ترین اشتباه"},
                    {"role": "lead", "text": "دربارهٔ"},
                    {"role": "hero", "text": "بازی‌های ویدیویی"},
                    {"role": "tail", "text": "اینه که فکر کنیم فقط"},
                    {"role": "tail", "text": "وقت تلف کردنه!"},
                ],
            }],
        },
    }
    decision = {
        "mode": "user_supplied",
        "text": HOOK,
        "sha256": _poster_plan()["authoritativeHookSha256"],
    }

    with pytest.raises(PersianEditorialHookError, match="no longer matches visible segments"):
        validate_edit_hook_authority(decision, payload)
