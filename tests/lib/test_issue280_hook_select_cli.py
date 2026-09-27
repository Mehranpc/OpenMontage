"""#280: automatic hook selection has a front-door command.

The agent had to call `record_hook_selection` through ad-hoc Python, since only
`hook-override` was a CLI command. `hook-select` persists the reviewed automatic winner.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from lib import persian_video_workflow as workflow

HOOK = "پیام بدی یا صبر کنی؟ بعد از یه قرار خوب"


def _project(tmp_path: Path, monkeypatch) -> Path:
    source = tmp_path.parent / f"{tmp_path.name}-280.wav"
    source.write_bytes(b"audio")
    workflow.bootstrap_persian_video(
        title="280", approved_script=HOOK + " و بعد", narration_path=str(source),
        project_id="run", pipeline_dir=tmp_path, backlot_opener=lambda _pid: 0,
        now=datetime.now(timezone.utc),
    )
    monkeypatch.setattr(workflow, "PROJECTS_DIR", tmp_path)
    return tmp_path / "run"


def _write(project: Path, value: dict) -> str:
    path = project / "hook.json"
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    return str(path)


HOOK_JSON = {
    "text": HOOK, "hook_family": "شکاف کنجکاوی", "score": 8.5, "content_match_score": 2,
    "evidence_checked": True, "unsupported_claims_rejected": True,
    "rationale": "The film's own opening line asks the viewer's question.",
    "candidates": [{"text": HOOK}, {"text": "دیر پیام دادن استراتژی خوبی نیست"}],
}


def test_hook_select_persists_the_automatic_winner(tmp_path: Path, monkeypatch, capsys) -> None:
    project = _project(tmp_path, monkeypatch)
    assert workflow.main(["hook-select", "run", "--json", _write(project, HOOK_JSON)]) == 0
    state = workflow.load_workflow_state("run", pipeline_dir=tmp_path)
    assert state["hook_selection"]["mode"] == "automatic"
    assert state["hook_selection"]["text"] == HOOK
    assert state["hook_selection"]["status"] == "selected"


def test_hook_select_names_missing_fields(tmp_path: Path, monkeypatch) -> None:
    project = _project(tmp_path, monkeypatch)
    partial = {k: v for k, v in HOOK_JSON.items() if k != "rationale"}
    with pytest.raises(SystemExit):
        workflow.main(["hook-select", "run", "--json", _write(project, partial)])
