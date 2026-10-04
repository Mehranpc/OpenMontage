"""#387: under v3_staged an automatic hook must be compared properly and judged strong.

2026-10-04 acceptance: the hook was the narrator's first clause, chosen from three
near-paraphrases with a self-assigned 8/10, and the opening passed on an independent
`acceptable` verdict whose own rationale explained why it was not strong.
"""
from __future__ import annotations

import json
from datetime import timedelta

import pytest

from lib import persian_pipeline_profile as profile
from lib import persian_stage_locks as locks
from lib import persian_video_workflow as workflow
from lib.persian_editorial_hook import (
    PersianEditorialHookError, STAGED_HOOK_SELECTION_POLICY_VERSION, build_initial_hook_selection,
    validate_staged_hook_candidates,
)
from lib.persian_rendered_review import (
    PersianRenderedReviewError, hook_reviewer_prompt_sha256, validate_staged_hook_verdict,
)
from lib.persian_video_workflow import PersianVideoWorkflowError, load_workflow_state
from tests.lib.test_issue195_scene_plan_duration_gate import BASE
from tests.lib.test_issue387_topic_admission import V3, _run

OLD_HOOK = "بعد از قرار اول باید صبر کنی؟"


def _cand(text, family, a=1, b=1, c=1, d=1, e=2):
    return {"text": text, "family": family, "criteria": {"A": a, "B": b, "C": c, "D": d, "E": e}}


def _five(winner="۵۴۳ نفر گفتن پیامِ زود بهتره", **override):
    rows = [
        _cand(winner, "number_first", 2, 2, 2, 2, 2),
        _cand("تو هم بعد از قرار اول گوشی رو چک می‌کنی؟", "recognition", 2, 1, 1, 0, 2),
        _cand("قانونِ سه روز صبر، اشتباهه", "myth_bust", 1, 1, 1, 2, 2),
        _cand("یه پیام کوتاه بعد از قرار، همه‌چیز رو عوض می‌کنه", "result_first", 1, 2, 1, 1, 2),
        _cand(OLD_HOOK, "question", 1, 1, 1, 0, 2),
    ]
    return rows


def _verdict(strength, **scores):
    base = {"A": 2, "B": 2, "C": 2, "D": 1, "E": 2}
    base.update(scores)
    return {"strength": strength, "criteriaScores": base,
            "reviewerPromptSha256": hook_reviewer_prompt_sha256()}


# --- hook-select comparison -------------------------------------------------------

def test_the_acceptance_runs_three_paraphrases_are_not_a_v3_comparison():
    three = [{"text": OLD_HOOK, "score": 8}, {"text": "صبر کردن یک بازیه", "score": 6},
             {"text": "کی پیام بدی؟", "score": 7}]
    with pytest.raises(PersianEditorialHookError, match="family|criteria"):
        validate_staged_hook_candidates(three, selected_text=OLD_HOOK, score=8)
    with pytest.raises(PersianEditorialHookError, match="at least 5"):
        validate_staged_hook_candidates(_five()[:4], selected_text=_five()[0]["text"], score=10)


def test_five_candidates_must_span_three_families():
    rows = _five()
    for row in rows:
        row["family"] = "question" if row is not rows[0] else "number_first"
    with pytest.raises(PersianEditorialHookError, match="3 hook families"):
        validate_staged_hook_candidates(rows, selected_text=rows[0]["text"], score=10)


def test_winner_must_be_top_scored_with_e2_and_score_equal_to_its_total():
    rows = _five()
    with pytest.raises(PersianEditorialHookError, match="highest"):
        validate_staged_hook_candidates(rows, selected_text=rows[2]["text"], score=7)
    with pytest.raises(PersianEditorialHookError, match="equal the winner"):
        validate_staged_hook_candidates(rows, selected_text=rows[0]["text"], score=9)
    rows[0]["criteria"]["E"] = 1
    with pytest.raises(PersianEditorialHookError, match="E \\(content match\\) = 2"):
        validate_staged_hook_candidates(rows, selected_text=rows[0]["text"], score=9)
    with pytest.raises(PersianEditorialHookError, match="one of the scored"):
        validate_staged_hook_candidates(_five(), selected_text="جملهٔ دیگر", score=10)


def test_a_rejected_hook_cannot_be_selected_again():
    rows = _five()
    with pytest.raises(PersianEditorialHookError, match="already rejected"):
        validate_staged_hook_candidates(rows, selected_text=rows[0]["text"], score=10,
                                        rejected_texts=[rows[0]["text"]])
    terms = validate_staged_hook_candidates(rows, selected_text=rows[0]["text"], score=10,
                                            rejected_texts=[OLD_HOOK])
    assert terms["selection_policy"] == STAGED_HOOK_SELECTION_POLICY_VERSION
    assert terms["family_count"] == 5 and terms["criteria"]["E"] == 2


# --- rendered verdict ---------------------------------------------------------------

def test_verdict_requires_the_canonical_prompt_and_scores():
    review = _verdict("strong")
    review["reviewerPromptSha256"] = "0" * 64
    with pytest.raises(PersianRenderedReviewError, match="canonical reviewer prompt"):
        validate_staged_hook_verdict(review)
    review = _verdict("strong")
    del review["criteriaScores"]["D"]
    with pytest.raises(PersianRenderedReviewError, match="criteriaScores A..E"):
        validate_staged_hook_verdict(review)


def test_acceptable_does_not_pass_and_strong_must_be_earned():
    assert validate_staged_hook_verdict(_verdict("acceptable"))["strong"] is False
    assert validate_staged_hook_verdict(_verdict("strong"))["strong"] is True
    with pytest.raises(PersianRenderedReviewError, match="do not support"):
        validate_staged_hook_verdict(_verdict("strong", A=1, B=1))  # total 7
    with pytest.raises(PersianRenderedReviewError, match="do not support"):
        validate_staged_hook_verdict(_verdict("strong", D=0, A=2))  # a zero criterion


def test_canonical_prompt_names_all_five_criteria():
    text = (workflow.Path(workflow.__file__).resolve().parents[1]
            / "docs/reference/persian-hooks/rendered-hook-reviewer-prompt.md").read_text(encoding="utf-8")
    for label in ("A. Personal relevance", "B. Information gap", "C. Specificity",
                  "D. Contrast / novelty", "E. Content match", "criteriaScores"):
        assert label in text


# --- workflow gate and rewrite ------------------------------------------------------

@pytest.fixture
def v3(monkeypatch):
    monkeypatch.setenv(profile.OPT_IN_ENV, "v3_staged")


def _at_review(tmp_path, phase="opening_review", mode="automatic"):
    project = _run(tmp_path, V3)
    (project / "checkpoint_assets.json").write_text(json.dumps({"stage": "assets", "status": "completed"}))
    locks.write_stage_lock(project, 1, ["checkpoint_assets.json"], implementation_sha="abc")
    path = workflow._state_path(project)
    state = json.loads(path.read_text())
    selection = build_initial_hook_selection(OLD_HOOK if mode == "user_supplied" else None)
    if mode == "automatic":
        selection.update(status="selected", text=OLD_HOOK, sha256=workflow.hashlib.sha256(
            OLD_HOOK.encode("utf-8")).hexdigest())
    state.update(next_phase=phase, hook_selection=selection)
    path.write_text(json.dumps(state, ensure_ascii=False))
    return project


def _review_file(project, strength, name="opening_review.json"):
    target = project / "artifacts" / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({"hookQualityReview": _verdict(strength)}), encoding="utf-8")
    return target


def test_acceptable_opening_is_refused_under_v3(tmp_path, v3):
    _at_review(tmp_path)
    state = load_workflow_state("run", pipeline_dir=tmp_path)
    with pytest.raises(PersianVideoWorkflowError, match="requires a strong rendered hook verdict.*hook-rewrite"):
        workflow._require_strong_staged_hook(state, _verdict("acceptable"), phase="opening_review")
    workflow._require_strong_staged_hook(state, _verdict("strong"), phase="opening_review")


def test_user_supplied_hook_keeps_the_v2_bar(tmp_path, v3):
    _at_review(tmp_path, mode="user_supplied")
    state = load_workflow_state("run", pipeline_dir=tmp_path)
    workflow._require_strong_staged_hook(state, {"strength": "acceptable"}, phase="opening_review")
    with pytest.raises(PersianVideoWorkflowError, match="automatic hook"):
        workflow.request_hook_rewrite("run", review_path=_review_file(tmp_path / "run", "acceptable"),
                                      reason="x", pipeline_dir=tmp_path, now=BASE + timedelta(minutes=5))


def test_hook_rewrite_reopens_only_the_edit_and_is_bounded(tmp_path, v3):
    project = _at_review(tmp_path)
    review = _review_file(project, "acceptable")
    now = BASE + timedelta(minutes=5)
    result = workflow.request_hook_rewrite("run", review_path=review, reason="static repeat of narration",
                                           pipeline_dir=tmp_path, now=now)
    state = load_workflow_state("run", pipeline_dir=tmp_path)
    assert result["rewrite"] == 1 and state["next_phase"] == "no_copy_preflight"
    assert state["hook_rewrites"][0]["text"] == OLD_HOOK
    assert state["hook_rewrites"][0]["strength"] == "acceptable"
    assert locks.is_locked(project, 0) and locks.is_locked(project, 1)
    # the rejected hook can no longer pass a review, even a strong one
    with pytest.raises(PersianVideoWorkflowError, match="already rejected"):
        workflow._require_strong_staged_hook(state, _verdict("strong"), phase="opening_review")
    # rewrite budget: two per run
    for _ in range(1):
        path = workflow._state_path(project)
        raw = json.loads(path.read_text()); raw["next_phase"] = "final_review"; path.write_text(json.dumps(raw))
        workflow.request_hook_rewrite("run", review_path=review, reason="again", pipeline_dir=tmp_path, now=now)
    path = workflow._state_path(project)
    raw = json.loads(path.read_text()); raw["next_phase"] = "opening_review"; path.write_text(json.dumps(raw))
    with pytest.raises(PersianVideoWorkflowError, match="budget exhausted"):
        workflow.request_hook_rewrite("run", review_path=review, reason="third", pipeline_dir=tmp_path, now=now)


def test_hook_rewrite_refuses_a_strong_review_and_other_phases(tmp_path, v3):
    project = _at_review(tmp_path)
    now = BASE + timedelta(minutes=5)
    with pytest.raises(PersianVideoWorkflowError, match="already rates the hook strong"):
        workflow.request_hook_rewrite("run", review_path=_review_file(project, "strong"), reason="x",
                                      pipeline_dir=tmp_path, now=now)
    path = workflow._state_path(project)
    raw = json.loads(path.read_text()); raw["next_phase"] = "render_final_candidate"; path.write_text(json.dumps(raw))
    with pytest.raises(PersianVideoWorkflowError, match="opening_review or final_review"):
        workflow.request_hook_rewrite("run", review_path=_review_file(project, "acceptable"), reason="x",
                                      pipeline_dir=tmp_path, now=now)


def test_ordinary_automatic_send_back_stays_refused_in_v3(tmp_path):
    with pytest.raises(locks.StageLockError, match="forward-only"):
        locks.assert_rewind_allowed(tmp_path, "opening_review", "no_copy_preflight", user_directed=False)
    with pytest.raises(locks.StageLockError, match="only rewinds"):
        locks.assert_rewind_allowed(tmp_path, "opening_review", "acquire_assets", user_directed=False,
                                    hook_rewrite=True)
    locks.assert_rewind_allowed(tmp_path, "final_review", "no_copy_preflight", user_directed=False,
                                hook_rewrite=True)


def test_v3_hook_select_refuses_the_rejected_text(tmp_path, v3):
    project = _at_review(tmp_path)
    workflow.request_hook_rewrite("run", review_path=_review_file(project, "acceptable"), reason="weak",
                                  pipeline_dir=tmp_path, now=BASE + timedelta(minutes=5))
    rows = _five(winner=OLD_HOOK)
    rows[4] = _cand("قرار دوم از پیام اول شروع می‌شه", "contrast", 1, 1, 1, 1, 2)
    with pytest.raises(PersianEditorialHookError, match="already rejected"):
        workflow.record_hook_selection(
            "run", selected_text=OLD_HOOK, hook_family="number_first", candidates=rows, score=10,
            content_match_score=2, evidence_checked=True, unsupported_claims_rejected=True,
            rationale="r", pipeline_dir=tmp_path)
    good = _five()
    after = workflow.record_hook_selection(
        "run", selected_text=good[0]["text"], hook_family="number_first", candidates=good, score=10,
        content_match_score=2, evidence_checked=True, unsupported_claims_rejected=True,
        rationale="r", pipeline_dir=tmp_path)
    assert after["hook_selection"]["selection_policy"] == STAGED_HOOK_SELECTION_POLICY_VERSION
