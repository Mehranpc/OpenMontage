"""#387: the v3 hook gate must not depend on an outside reviewer that may not exist.

2026-10-04 acceptance-3: three hooks in a row were rated `acceptable` by a separate
model run that the pipeline cannot guarantee (and which misread Persian digits and
once reversed the hook's meaning). With the rewrite budget spent the run stopped dead.
Under v3 the pipeline agent may review its own render with the canonical prompt, and
once the rewrite budget is spent an `acceptable` hook goes to the human with a clear
notice instead of blocking. A `weak` hook still blocks.
"""
from __future__ import annotations

import json

import pytest

from lib import persian_video_workflow as workflow
from lib.persian_rendered_review import PersianRenderedReviewError, validate_rendered_hook_review
from lib.persian_video_workflow import PersianVideoWorkflowError, load_workflow_state
from tests.lib.test_issue387_strong_hook_gate import OLD_HOOK, _at_review, _verdict, v3  # noqa: F401
from tests.lib.test_persian_rendered_review_v2 import DIGEST, _hook_review


def _exhaust_rewrites(project):
    path = workflow._state_path(project)
    raw = json.loads(path.read_text())
    raw["hook_rewrites"] = [
        {"text": f"هوک ردشده {i}", "sha256": f"{i}" * 64, "strength": "acceptable"} for i in (1, 2)
    ]
    path.write_text(json.dumps(raw, ensure_ascii=False))


# --- user decision instead of a dead end ---------------------------------------------

def test_acceptable_still_needs_a_rewrite_while_budget_remains(tmp_path, v3):
    _at_review(tmp_path)
    state = load_workflow_state("run", pipeline_dir=tmp_path)
    with pytest.raises(PersianVideoWorkflowError, match="hook-rewrite"):
        workflow._require_strong_staged_hook(state, _verdict("acceptable"), phase="opening_review")


def test_spent_budget_passes_acceptable_to_the_human_with_a_notice(tmp_path, v3):
    project = _at_review(tmp_path)
    _exhaust_rewrites(project)
    state = load_workflow_state("run", pipeline_dir=tmp_path)
    notice = workflow._require_strong_staged_hook(state, _verdict("acceptable"), phase="opening_review")
    assert notice["strength"] == "acceptable"
    assert notice["userDecisionRequired"] is True
    assert notice["rewritesUsed"] == 2
    assert notice["hookText"] == OLD_HOOK
    assert workflow._require_strong_staged_hook(state, _verdict("strong"), phase="opening_review") is None


def test_spent_budget_never_passes_a_weak_hook(tmp_path, v3):
    project = _at_review(tmp_path)
    _exhaust_rewrites(project)
    state = load_workflow_state("run", pipeline_dir=tmp_path)
    weak = _verdict("weak", A=1, B=1, C=1, D=0)
    with pytest.raises(PersianVideoWorkflowError, match="weak"):
        workflow._require_strong_staged_hook(state, weak, phase="final_review")


def test_status_surfaces_the_hook_notice(tmp_path, v3):
    project = _at_review(tmp_path)
    path = workflow._state_path(project)
    raw = json.loads(path.read_text())
    notice = {"strength": "acceptable", "userDecisionRequired": True, "rewritesUsed": 2,
              "hookText": OLD_HOOK}
    raw.setdefault("evidence", {})["opening_review"] = {"hook_strength_notice": notice}
    path.write_text(json.dumps(raw, ensure_ascii=False))
    status = workflow.workflow_status("run", pipeline_dir=tmp_path)
    assert status["hook_strength_notice"] == notice
    assert "hook below strong" in workflow.format_status_line(status)


# --- no outside reviewer required -----------------------------------------------------

def _self_review(**overrides):
    review = _hook_review(reviewerRole="pipeline_agent")
    review["coldViewer"] = dict(review["coldViewer"], contextIsolated=False)
    review.update(overrides)
    return review


def test_v2_still_requires_an_independent_isolated_reviewer():
    with pytest.raises(PersianRenderedReviewError, match="independent reviewer"):
        validate_rendered_hook_review(_self_review(), candidate_sha256=DIGEST, require_pass=True)


def test_v3_accepts_the_pipeline_agent_reviewing_its_own_render():
    validate_rendered_hook_review(_self_review(), candidate_sha256=DIGEST, require_pass=True,
                                  allow_pipeline_agent=True)
    # an outside reviewer stays welcome, but must still be context-isolated
    outside = _hook_review()
    outside["coldViewer"] = dict(outside["coldViewer"], contextIsolated=False)
    with pytest.raises(PersianRenderedReviewError, match="context-isolated"):
        validate_rendered_hook_review(outside, candidate_sha256=DIGEST, require_pass=True,
                                      allow_pipeline_agent=True)
    with pytest.raises(PersianRenderedReviewError, match="independent reviewer"):
        validate_rendered_hook_review(_self_review(reviewerRole="someone"), candidate_sha256=DIGEST,
                                      require_pass=True, allow_pipeline_agent=True)


# --- hook coherence ---------------------------------------------------------------

def test_canonical_prompt_requires_one_connected_thought():
    text = (workflow.Path(workflow.__file__).resolve().parents[1]
            / "docs/reference/persian-hooks/rendered-hook-reviewer-prompt.md").read_text(encoding="utf-8")
    assert "one connected thought" in text
    assert "pipeline agent" in text


# --- the human's own hook can be bound where the run hands them the decision ----------

def test_user_hook_at_v3_review_reopens_only_the_edit_and_binds_it(tmp_path, v3):
    from lib import persian_stage_locks as locks

    project = _at_review(tmp_path)
    _exhaust_rewrites(project)
    mine = "دیر پیام می‌دی که مشتاق به نظر نرسی؟ یه آزمایش نشون داد به ضررته"
    workflow.record_user_hook_override("run", selected_text=mine, reason="user chose this hook",
                                       pipeline_dir=tmp_path)
    state = load_workflow_state("run", pipeline_dir=tmp_path)
    assert state["next_phase"] == "no_copy_preflight"
    assert state["hook_selection"]["mode"] == "user_supplied"
    assert state["hook_selection"]["text"] == mine
    assert state["send_back_history"][-1]["user_directed_revision"] is True
    assert locks.is_locked(project, 0) and locks.is_locked(project, 1)
