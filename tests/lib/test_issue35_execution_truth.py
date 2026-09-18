from __future__ import annotations

import json
from pathlib import Path
import time

from lib import persian_video_workflow as workflow


def _fresh_project(tmp_path: Path) -> None:
    workflow.bootstrap_persian_video(
        title="execution truth",
        approved_script="متن تأییدشده برای آزمون",
        project_id="run",
        pipeline_dir=tmp_path,
        backlot_opener=lambda _project_id: 0,
    )


def _wait_for_job(tmp_path: Path, job_id: str) -> dict:
    terminal = {"succeeded", "failed", "interrupted"}
    result = workflow.reconcile_workflow_job("run", job_id, pipeline_dir=tmp_path)
    for _ in range(100):
        if result.get("status") in terminal:
            return result
        time.sleep(0.05)
        result = workflow.reconcile_workflow_job("run", job_id, pipeline_dir=tmp_path)
    return result


def test_front_door_zero_exit_does_not_hide_failed_semantic_result(tmp_path: Path) -> None:
    _fresh_project(tmp_path)
    child = (
        "import json, os; from pathlib import Path; "
        "path = Path(os.environ['OPENMONTAGE_DURABLE_RESULT_PATH']); "
        "path.write_text(json.dumps({'success': False, 'error': 'provider unavailable'}))"
    )

    workflow.start_workflow_job(
        "run",
        job_id="semantic-failure",
        phase="prepare_inputs",
        argv=["python", "-c", child],
        idempotence_key="semantic-failure-v1",
        pipeline_dir=tmp_path,
        semantic_result_required=True,
    )

    final = _wait_for_job(tmp_path, "semantic-failure")
    assert final["status"] == "failed"
    assert final["processOutcome"] == "succeeded"
    assert final["semanticOutcome"] == "failed"
    assert final["executionOutcome"] == "failed"
    assert final["semanticResult"]["success"] is False
    assert final["semanticResult"]["error"] == "provider unavailable"
