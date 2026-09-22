"""Canonical child command for measured Persian media work.

Run through `persian_run_kernel run`; its result file binds produced bytes to the
same job that measured browser/ffmpeg execution. This module never advances state.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from lib.persian_edit_workspace import artifact_sha256
from lib.persian_finalization import master_final_candidate
from lib.persian_video_workflow import load_workflow_state, _hash_file
from tools.video.persian_compose_script_aligned import ScriptAlignedPersianCompose

_PHASE_OUTPUT = {
    "render_opening_candidate": "opening-candidate.mp4",
    "render_final_candidate": "rendered.mp4",
    "master_final_candidate": "candidate.mp4",
}


def execute(project_id: str, phase: str) -> dict[str, Any]:
    state = load_workflow_state(project_id)
    if state.get("next_phase") != phase or phase not in _PHASE_OUTPUT:
        raise ValueError(f"media job requires current phase {phase!r}")
    project = Path(state["read_allowlist"]["project_root"]).resolve()
    output = project / "renders" / _PHASE_OUTPUT[phase]
    edit_path = project / "artifacts" / "edit_decisions.json"
    edit = json.loads(edit_path.read_text(encoding="utf-8"))
    edit_digest = artifact_sha256(edit)

    if phase == "master_final_candidate":
        mastering = master_final_candidate(project / "renders" / "rendered.mp4", output)
        evidence = {**mastering, "edit_artifact_sha256": edit_digest}
    else:
        params: dict[str, Any] = {
            "edit_decisions": edit, "output_path": str(output), "crf": 16,
            "concurrency": 2, "timeout_ms": 120000,
        }
        if phase == "render_opening_candidate":
            params["frames"] = "0-149"
        result = ScriptAlignedPersianCompose().execute(params)
        if not result.success:
            raise RuntimeError(result.error or "Persian compose failed")
        data = dict(result.data or {})
        evidence = {"output_path": str(output), "edit_artifact_sha256": edit_digest}
        if phase == "render_opening_candidate":
            evidence["opening_candidate_sha256"] = _hash_file(output)
        else:
            evidence["output_sha256"] = _hash_file(output)
            evidence["motion_qa_passed"] = (data.get("post_render_motion_qa") or {}).get("passed") is True
    digest = _hash_file(output)
    return {
        "success": True,
        "data": {
            "output_path": str(output), "output_sha256": digest,
            "phase_evidence": evidence,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(prog="persian-media-job")
    parser.add_argument("project_id")
    parser.add_argument("--phase", choices=sorted(_PHASE_OUTPUT), required=True)
    args = parser.parse_args()
    result_path = os.environ.get("OPENMONTAGE_DURABLE_RESULT_PATH")
    if not result_path:
        parser.error("this command must run inside the Persian run kernel")
    try:
        result = execute(args.project_id, args.phase)
    except Exception as exc:
        result = {"success": False, "error": str(exc)}
    Path(result_path).write_text(json.dumps(result, ensure_ascii=False) + "\n", encoding="utf-8")
    return 0 if result["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
