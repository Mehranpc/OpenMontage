"""#387: a render already inside the audio policy is the candidate itself.

``master_final_candidate`` returns ``candidatePath == rendered.mp4`` without
writing ``candidate.mp4`` when no re-encode is needed. The media job hashed the
fixed ``candidate.mp4`` path anyway and failed with ENOENT (2026-10-04 v3
acceptance run, job master-1), so a compliant render could never advance.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from lib import persian_media_job as job


def _project(tmp_path: Path, monkeypatch) -> Path:
    project = tmp_path / "run"
    (project / "artifacts").mkdir(parents=True)
    (project / "renders").mkdir()
    (project / "artifacts" / "edit_decisions.json").write_text(json.dumps({"persian": {}}), encoding="utf-8")
    (project / "renders" / "rendered.mp4").write_bytes(b"compliant render")
    monkeypatch.setattr(job, "load_workflow_state", lambda _pid: {
        "next_phase": "master_final_candidate", "read_allowlist": {"project_root": str(project)}})
    return project


def test_passthrough_master_reports_the_render_it_declared(tmp_path: Path, monkeypatch) -> None:
    project = _project(tmp_path, monkeypatch)
    rendered = (project / "renders" / "rendered.mp4").resolve()
    sha = hashlib.sha256(rendered.read_bytes()).hexdigest()

    def passthrough(source, _output):
        return {"candidatePath": str(source.resolve()), "candidateSha256": sha, "reencoded": False}

    monkeypatch.setattr(job, "master_final_candidate", passthrough)
    data = job.execute("run", "master_final_candidate")["data"]
    assert Path(data["output_path"]) == rendered
    assert data["output_sha256"] == sha
    assert data["phase_evidence"]["candidatePath"] == str(rendered)
    assert data["phase_evidence"]["candidateSha256"] == sha
    assert not (project / "renders" / "candidate.mp4").exists()


def test_reencoded_master_still_reports_candidate_mp4(tmp_path: Path, monkeypatch) -> None:
    project = _project(tmp_path, monkeypatch)

    def reencode(_source, output):
        output.write_bytes(b"mastered")
        return {"candidatePath": str(output), "candidateSha256": hashlib.sha256(b"mastered").hexdigest(),
                "reencoded": True}

    monkeypatch.setattr(job, "master_final_candidate", reencode)
    data = job.execute("run", "master_final_candidate")["data"]
    assert Path(data["output_path"]) == (project / "renders" / "candidate.mp4").resolve()
    assert data["output_sha256"] == hashlib.sha256(b"mastered").hexdigest()
