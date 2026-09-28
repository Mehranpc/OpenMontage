"""#327: the terminal candidate must be the mastering output, not the raw render.

On the 2026-09-28 Mac run final_review measured −24.7 LUFS after mastering had
run; mastering loudnorms any out-of-policy render to −16 LUFS, so the reviewed
file was the unmastered render. Its digest matched its own bytes, which was all
the candidate check verified.
"""
from __future__ import annotations

import hashlib
import json

import pytest

from lib import persian_video_workflow as workflow
from lib.persian_video_workflow import PersianVideoWorkflowError, complete_phase, record_phase_attempt
from tests.lib.test_persian_video_workflow import (
    BASE, _advance_to, _bootstrap, _checkpoint, _report, _write_final_review,
)


def _project_with_mastering(tmp_path, *, review_raw: bool):
    _bootstrap(tmp_path)
    _advance_to(tmp_path, "final_review")
    project = tmp_path / "run"
    renders = project / "renders"
    renders.mkdir(parents=True, exist_ok=True)
    raw, mastered = renders / "rendered.mp4", renders / "candidate.mp4"
    raw.write_bytes(b"raw-mix")
    mastered.write_bytes(b"loudnormed-mix")
    state = workflow.load_workflow_state("run", pipeline_dir=tmp_path)
    state.setdefault("evidence", {})["master_final_candidate"] = {
        "candidatePath": str(mastered),
        "candidateSha256": hashlib.sha256(mastered.read_bytes()).hexdigest(),
    }
    workflow._write_state(project, state)
    reviewed = raw if review_raw else mastered
    review_path = _write_final_review(project, reviewed)
    report = _report(reviewed, review_ref=str(review_path))
    (project / "checkpoint_compose.json").write_text(json.dumps(_checkpoint(report)), encoding="utf-8")
    record_phase_attempt("run", "final_review", pipeline_dir=tmp_path, now=BASE)
    return review_path


def test_reviewing_the_raw_render_is_refused_once_mastering_committed(tmp_path) -> None:
    review_path = _project_with_mastering(tmp_path, review_raw=True)
    with pytest.raises(PersianVideoWorkflowError, match="not the mastered output candidate.mp4"):
        complete_phase("run", "final_review", evidence={"final_review_path": str(review_path)},
                       pipeline_dir=tmp_path, now=BASE)


def test_reviewing_the_mastered_output_passes(tmp_path) -> None:
    review_path = _project_with_mastering(tmp_path, review_raw=False)
    state = complete_phase("run", "final_review", evidence={"final_review_path": str(review_path)},
                           pipeline_dir=tmp_path, now=BASE)
    assert state["next_phase"] == "awaiting_human"
