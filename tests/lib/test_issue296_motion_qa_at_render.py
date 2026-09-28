"""#296 (#263 item B): a slideshow-like final render stops at its own commit.

The media job stores the measured post_render_motion_qa with the final render
(#286), but the anti-slideshow gate only ran at final_review: after mastering and
review had been spent on a candidate that was going to be refused.
"""
from __future__ import annotations

import hashlib
import sys
import time
from pathlib import Path

import pytest

from lib import persian_run_kernel as kernel
from lib import persian_video_workflow as workflow
from tests.lib.test_persian_video_workflow import BASE, _advance_to, _bootstrap

FAIL_RUN = {"startSeconds": 12.0, "endSeconds": 17.5, "durationSeconds": 5.5, "meanAbsDelta": 0.4}


def _render(tmp_path: Path, job: str, motion: dict) -> dict:
    _bootstrap(tmp_path)
    _advance_to(tmp_path, "render_final_candidate")
    output = tmp_path / "run" / "renders" / "rendered.mp4"
    child = (
        "import hashlib,json,os; from pathlib import Path; "
        f"p=Path({str(output)!r}); p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(b'final'); "
        "Path(os.environ['OPENMONTAGE_DURABLE_RESULT_PATH']).write_text(json.dumps({'success':True,'data':{"
        "'output_path':str(p),'output_sha256':hashlib.sha256(p.read_bytes()).hexdigest()}}))"
    )
    kernel.start_phase_job("run", job_id=job, phase="render_final_candidate",
                           argv=[sys.executable, "-c", child], idempotence_key=job,
                           telemetry_category="browser_render_execution", pipeline_dir=tmp_path, now=BASE)
    for _ in range(100):
        result = kernel.reconcile_phase_job("run", job, pipeline_dir=tmp_path, now=BASE)
        if result["status"] in {"succeeded", "failed", "interrupted"}:
            break
        time.sleep(0.05)
    return {"output_path": str(output), "output_sha256": hashlib.sha256(b"final").hexdigest(),
            "post_render_motion_qa": motion}


def test_failed_motion_qa_refuses_the_final_render_commit(tmp_path: Path) -> None:
    evidence = _render(tmp_path, "slideshow", {"passed": False, "failRuns": [FAIL_RUN]})
    with pytest.raises(workflow.PersianVideoWorkflowError, match=r"MOTION_QA_FAILED.*12\.0-17\.5s"):
        kernel.commit_phase_job("run", "slideshow", evidence=evidence, pipeline_dir=tmp_path)
    assert workflow.load_workflow_state("run", pipeline_dir=tmp_path)["next_phase"] == "render_final_candidate"


def test_passing_motion_qa_commits(tmp_path: Path) -> None:
    evidence = _render(tmp_path, "moving", {"passed": True, "failRuns": []})
    committed = kernel.commit_phase_job("run", "moving", evidence=evidence, pipeline_dir=tmp_path)
    assert committed["next_phase"] == "master_final_candidate"
