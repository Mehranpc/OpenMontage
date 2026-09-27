"""#286: the final render keeps the measured motion report, not only a boolean.

final_review requires render_report.post_render_motion_qa to be the full
anti-slideshow report (deltas, runs, sampleFps). The media job stored only
`motion_qa_passed`, so the only place the measured report existed was the
compose tool's return value, which nothing persisted.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from lib import persian_media_job as job

MOTION = {"passed": True, "sampleFps": 2.0, "nearStaticDeltaMax": 1.5, "warningRunSeconds": 2.0,
          "failRunSeconds": 4.0, "deltas": [3.0], "warnRuns": [], "failRuns": [], "elapsedSeconds": 1.0}


def test_final_render_evidence_carries_the_full_motion_report(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path / "run"
    (project / "artifacts").mkdir(parents=True)
    (project / "renders").mkdir()
    (project / "artifacts" / "edit_decisions.json").write_text(json.dumps({"persian": {}}), encoding="utf-8")
    monkeypatch.setattr(job, "load_workflow_state", lambda _pid: {
        "next_phase": "render_final_candidate", "read_allowlist": {"project_root": str(project)}})

    class Compose:
        def execute(self, params):
            Path(params["output_path"]).write_bytes(b"video")
            return SimpleNamespace(success=True, error=None,
                                   data={"post_render_motion_qa": MOTION, "luminance_qa": {"passed": True}})

    monkeypatch.setattr(job, "ScriptAlignedPersianCompose", Compose)
    evidence = job.execute("run", "render_final_candidate")["data"]["phase_evidence"]
    assert evidence["motion_qa_passed"] is True
    assert evidence["post_render_motion_qa"] == MOTION
    assert evidence["luminance_qa"] == {"passed": True}
