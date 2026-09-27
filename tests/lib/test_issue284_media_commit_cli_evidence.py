"""#284: the documented `run` route for media phases, without --evidence-json.

SKILL.md says the media child writes phase evidence into its semantic result, so
`--evidence-json` is unnecessary for the three media phases. The CLI turned the
missing flag into `{}` instead of None, the kernel skipped the derived evidence,
and the commit refused real, measured bytes as "does not match measured execution".
"""
from __future__ import annotations

import sys
from pathlib import Path

from lib import persian_run_kernel as kernel
from lib import persian_video_workflow as workflow
from tests.lib.test_persian_video_workflow import BASE, _advance_to, _bootstrap


def test_run_without_evidence_json_commits_the_childs_phase_evidence(tmp_path: Path, monkeypatch) -> None:
    _bootstrap(tmp_path)
    _advance_to(tmp_path, "render_opening_candidate")
    output = tmp_path / "run" / "renders" / "opening-candidate.mp4"
    child = (
        "import hashlib,json,os; from pathlib import Path; "
        f"p=Path({str(output)!r}); p.write_bytes(b'fresh measured video'); "
        "d=hashlib.sha256(p.read_bytes()).hexdigest(); "
        "Path(os.environ['OPENMONTAGE_DURABLE_RESULT_PATH']).write_text(json.dumps("
        "{'success':True,'data':{'output_path':str(p),'output_sha256':d,"
        "'phase_evidence':{'output_path':str(p),'opening_candidate_sha256':d}}}))"
    )
    # Exactly what the CLI passes when --evidence-json is absent.
    kernel.run_phase_job(
        "run", job_id="cli-opening", phase="render_opening_candidate",
        argv=[sys.executable, "-c", child], idempotence_key="cli-opening",
        telemetry_category="browser_render_execution",
        evidence=kernel._read_evidence(None), poll_interval_seconds=0.05,
        timeout_seconds=60, pipeline_dir=tmp_path, now=BASE,
    )
    assert workflow.load_workflow_state("run", pipeline_dir=tmp_path)["next_phase"] == "opening_review"


def test_absent_flag_is_none_not_empty_evidence() -> None:
    assert kernel._read_evidence(None) is None
