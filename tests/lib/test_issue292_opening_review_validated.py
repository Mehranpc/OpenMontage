"""#292: opening_review judges the opening it names, where it was rendered.

Before, `_complete_phase_impl` had no opening_review branch: any evidence
completed it, and the rendered hook review first ran at final_review, after the
full render and mastering.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from lib import persian_video_workflow as workflow
from tests.lib.test_persian_video_workflow import BASE, _advance_to, _bootstrap


def _at_opening_review(tmp_path: Path) -> tuple[Path, str]:
    _bootstrap(tmp_path)
    state = _advance_to(tmp_path, "opening_review")
    opening = tmp_path / "run" / "renders" / "opening-candidate.mp4"
    opening.parent.mkdir(parents=True, exist_ok=True)
    opening.write_bytes(b"measured opening")
    sha = hashlib.sha256(opening.read_bytes()).hexdigest()
    state["evidence"] = {**(state.get("evidence") or {}),
                         "render_opening_candidate": {"opening_candidate_sha256": sha}}
    workflow._write_state(tmp_path / "run", state)
    workflow.record_phase_attempt("run", "opening_review", pipeline_dir=tmp_path, now=BASE)
    return opening, sha


def _complete(tmp_path: Path, review: dict, sha: str):
    path = tmp_path / "run" / "artifacts" / "opening_review.json"
    path.write_text(json.dumps(review, ensure_ascii=False), encoding="utf-8")
    return workflow.complete_phase("run", "opening_review", pipeline_dir=tmp_path, now=BASE, evidence={
        "opening_review_path": str(path), "opening_candidate_sha256": sha})


def test_any_evidence_no_longer_completes_opening_review(tmp_path: Path) -> None:
    _at_opening_review(tmp_path)
    with pytest.raises(workflow.PersianVideoWorkflowError, match="opening_review is not bound"):
        workflow.complete_phase("run", "opening_review", pipeline_dir=tmp_path, now=BASE, evidence={})


def test_a_review_of_another_opening_is_refused(tmp_path: Path) -> None:
    _, sha = _at_opening_review(tmp_path)
    with pytest.raises(workflow.PersianVideoWorkflowError, match="different opening candidate"):
        _complete(tmp_path, {"status": "pass", "openingCandidateSha256": "0" * 64}, sha)


def test_a_weak_rendered_hook_is_refused_at_the_opening(tmp_path: Path) -> None:
    _, sha = _at_opening_review(tmp_path)
    hook = {"version": "2.1", "reviewSource": "rendered_mp4", "reviewerRole": "independent_reviewer",
            "reviewedCandidateSha256": sha, "strength": "weak"}
    with pytest.raises(workflow.PersianVideoWorkflowError, match="opening_review hook-quality review failed"):
        _complete(tmp_path, {"status": "pass", "openingCandidateSha256": sha, "hookQualityReview": hook}, sha)
    assert workflow.load_workflow_state("run", pipeline_dir=tmp_path)["next_phase"] == "opening_review"


def test_a_passing_opening_needs_a_rendered_hook_review(tmp_path: Path) -> None:
    _, sha = _at_opening_review(tmp_path)
    with pytest.raises(workflow.PersianVideoWorkflowError, match="rendered Hook Quality review"):
        _complete(tmp_path, {"status": "pass", "openingCandidateSha256": sha,
                             "hookQualityReview": {"version": "1.0"}}, sha)
