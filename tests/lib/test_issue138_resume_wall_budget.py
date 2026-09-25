"""#138 F4: `resume` must not refresh the wall window of a still-active workflow.

An active caller could call ``resume_workflow`` repeatedly and, because it reset
``budget_window_started_at`` unconditionally, keep the 45-minute wall window from
ever expiring. The real failed run recorded four resumes and ~12531s of true wall
time while enforcement only ever measured ~3032s.

The fix ties the window refresh to the existing #107 P2 stall notion: a resume
starts a fresh window only when the project has genuinely gone idle, otherwise it
preserves the consumed budget. These tests assert persisted state, not logs.
"""

import os
from datetime import datetime, timedelta
from pathlib import Path
import sys

import pytest

from lib import persian_run_kernel as kernel
from lib import persian_video_workflow as workflow
from tests.lib.test_persian_video_workflow import BASE, _bootstrap

PROJECT = "run"


def _freeze_project_clock(tmp_path: Path, when: datetime) -> None:
    """Emulate the project's newest write landing at ``when`` (stall detection is mtime-based)."""
    stamp = when.timestamp()
    for path in (tmp_path / PROJECT).rglob("*"):
        if path.is_file():
            os.utime(path, (stamp, stamp))


def test_repeated_resume_does_not_extend_active_wall_window(tmp_path: Path) -> None:
    _bootstrap(tmp_path)
    created = workflow.load_workflow_state(PROJECT, pipeline_dir=tmp_path)[
        "budget_window_started_at"
    ]
    assert created == BASE.isoformat()

    # A live session keeps writing project files, so each resume lands within
    # seconds of the last write. Four resumes inside the 45-minute horizon must
    # therefore never look idle enough to refresh the window.
    marker = tmp_path / "resumed-work-ran.txt"
    for offset in (10, 20, 30, 40):
        resume_at = BASE + timedelta(minutes=offset)
        _freeze_project_clock(tmp_path, resume_at - timedelta(seconds=30))
        workflow.resume_workflow(
            PROJECT, pipeline_dir=tmp_path, backlot_opener=lambda _pid: 0, now=resume_at
        )
        assert workflow.load_workflow_state(PROJECT, pipeline_dir=tmp_path)[
            "budget_window_started_at"
        ] == created

    # The horizon still closes: the next front-door work command stops and no
    # expensive work starts.
    child = f"from pathlib import Path; Path({str(marker)!r}).write_text('ran')"
    with pytest.raises(kernel.PersianRunKernelError, match="wall_budget_exceeded"):
        kernel.start_phase_job(
            PROJECT,
            job_id="post-resume-work",
            phase="prepare_inputs",
            argv=[sys.executable, "-c", child],
            idempotence_key="post-resume-work-v1",
            pipeline_dir=tmp_path,
            now=BASE + timedelta(minutes=46),
        )

    stopped = workflow.load_workflow_state(PROJECT, pipeline_dir=tmp_path)
    assert stopped["status"] == "failed"
    assert stopped["budget_stop"]["reason"] == "wall_budget_exceeded"
    assert stopped["budget_stop"]["quality_disposition"] == "needs_decision"
    assert not marker.exists()


def test_stale_resume_starts_fresh_window_without_resetting_counters(tmp_path: Path) -> None:
    _bootstrap(tmp_path)
    state = workflow.load_workflow_state(PROJECT, pipeline_dir=tmp_path)
    state["attempts"] = {"prepare_inputs": 3}
    state["send_backs"] = 2
    state["recovery_attempts"] = {"FILM_TYPE_LAYOUT": [{"attempt": 1}]}
    state["user_revision_cycles"] = 1
    workflow._write_state(tmp_path / PROJECT, state)

    # Untouched for longer than the stall threshold: a genuine resume.
    _freeze_project_clock(tmp_path, BASE)
    resume_at = BASE + timedelta(minutes=20)
    resumed = workflow.resume_workflow(
        PROJECT, pipeline_dir=tmp_path, backlot_opener=lambda _pid: 0, now=resume_at
    )

    assert resumed["budget_window_started_at"] == resume_at.isoformat()
    assert resumed["attempts"] == {"prepare_inputs": 3}
    assert resumed["send_backs"] == 2
    assert resumed["recovery_attempts"] == {"FILM_TYPE_LAYOUT": [{"attempt": 1}]}
    assert resumed["user_revision_cycles"] == 1
