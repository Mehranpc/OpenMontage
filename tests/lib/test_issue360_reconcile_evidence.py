"""#360: plan reconciliation may correct a declaration, never disguise an unsuitable clip.

Lowering scene intent (dropping ``shows_subject`` or moving ``fallback_level`` down the
ladder) needs a reviewed, unrejected candidate of the same event whose review records
the corrected value. Essential requirements stay out of reach: ``human_presence`` is
not reconcilable, and the opening reward hook must show its subject.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from lib import persian_asset_workspace as workspace
from lib.persian_video_workflow import (
    PersianVideoWorkflowError,
    load_workflow_state,
    reconcile_scene_plan,
    select_workflow_asset_candidate,
)
from tests.lib.test_issue224_plan_reconcile import BASE, _event, _plan, _run_at_acquire
from tests.lib.test_issue360_truthful_readiness import _candidate, _project_bytes


def _reconcile(tmp_path: Path, event: str, fields: dict, **extra):
    return reconcile_scene_plan(
        "run", [{"visual_event_id": event, "set": fields, **extra}],
        reason="reviewed footage contradicts the declaration", pipeline_dir=tmp_path, now=BASE,
    )


def test_dropping_the_subject_needs_reviewed_evidence_of_its_absence(tmp_path: Path) -> None:
    project = _run_at_acquire(tmp_path)
    with_subject = _candidate(tmp_path, "event-0", "with-subject")
    without = _candidate(tmp_path, "event-0", "without", shows_subject=False)
    other = _candidate(tmp_path, "event-1", "elsewhere", shows_subject=False)
    before = _project_bytes(project)

    with pytest.raises(PersianVideoWorkflowError, match="give evidence_candidate_id"):
        _reconcile(tmp_path, "event-0", {"shows_subject": False})
    with pytest.raises(PersianVideoWorkflowError, match="does not support the change"):
        _reconcile(tmp_path, "event-0", {"shows_subject": False}, evidence_candidate_id=with_subject)
    with pytest.raises(PersianVideoWorkflowError, match="candidate of this visual event"):
        _reconcile(tmp_path, "event-0", {"shows_subject": False}, evidence_candidate_id=other)
    assert _project_bytes(project) == before  # every refusal writes nothing
    assert _event(_plan(tmp_path), "event-0")["shows_subject"] is True

    result = _reconcile(tmp_path, "event-0", {"shows_subject": False}, evidence_candidate_id=without)
    assert result["amendments"][0]["evidence"] == {
        "candidateId": without,
        "reviewSha256": workspace.load_asset_candidate(project, without)["reviewSha256"],
    }
    assert load_workflow_state("run", pipeline_dir=tmp_path)["send_backs"] == 0
    # The corrected plan now admits the reviewed clip with no new download or re-review.
    select_workflow_asset_candidate(
        "run", "event-0", without, rejected_alternatives={with_subject: "plan corrected"},
        pipeline_dir=tmp_path,
    )


def test_rejected_evidence_cannot_back_a_reconciliation(tmp_path: Path) -> None:
    _run_at_acquire(tmp_path)
    without = _candidate(tmp_path, "event-0", "without", shows_subject=False)
    workspace.reject_asset_candidate(tmp_path / "run", without, category="semantic", reason="no phone")
    with pytest.raises(PersianVideoWorkflowError, match="reviewed, unrejected"):
        _reconcile(tmp_path, "event-0", {"shows_subject": False}, evidence_candidate_id=without)


def test_a_lower_fallback_needs_a_review_that_records_it(tmp_path: Path) -> None:
    _run_at_acquire(tmp_path)
    literal = _candidate(tmp_path, "event-1", "literal")
    metaphor = _candidate(
        tmp_path, "event-1", "metaphor",
        fallback_level="adjacent_metaphor", fallback_reason="no literal footage of the moment exists",
    )
    with pytest.raises(PersianVideoWorkflowError, match="give evidence_candidate_id"):
        _reconcile(tmp_path, "event-1", {"fallback_level": "adjacent_metaphor"})
    with pytest.raises(PersianVideoWorkflowError, match="does not support the change"):
        _reconcile(tmp_path, "event-1", {"fallback_level": "adjacent_metaphor"},
                   evidence_candidate_id=literal)
    _reconcile(tmp_path, "event-1", {"fallback_level": "adjacent_metaphor"},
               evidence_candidate_id=metaphor)
    assert _event(_plan(tmp_path), "event-1")["fallback_level"] == "adjacent_metaphor"
    # Moving back up the ladder raises intent, so it needs no evidence.
    _reconcile(tmp_path, "event-1", {"fallback_level": "exact_literal"})


def test_essential_requirements_cannot_be_reconciled_away(tmp_path: Path) -> None:
    _run_at_acquire(tmp_path)
    with pytest.raises(PersianVideoWorkflowError, match="human_presence cannot be reconciled"):
        _reconcile(tmp_path, "event-0", {"human_presence": False})


def test_the_reward_hook_subject_is_not_reconcilable(tmp_path: Path, monkeypatch) -> None:
    project = _run_at_acquire(tmp_path)
    from lib import persian_video_workflow as workflow

    real = workflow.read_checkpoint

    def hooked(*args, **kwargs):
        checkpoint = real(*args, **kwargs)
        if args[2:3] == ("scene_plan",) and checkpoint:
            event = checkpoint["artifacts"]["scene_plan"]["beats"][0]["visual_events"][0]
            event["semantic_role"] = "reward_problem_hook"
        return checkpoint

    monkeypatch.setattr(workflow, "read_checkpoint", hooked)
    without = _candidate(tmp_path, "event-0", "without", shows_subject=False)
    with pytest.raises(PersianVideoWorkflowError, match="must show its subject"):
        _reconcile(tmp_path, "event-0", {"shows_subject": False}, evidence_candidate_id=without)
    assert project.is_dir()
