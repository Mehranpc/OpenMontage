"""#344: two defects from the 2026-09-29 text-after-first-date run on 7f1ecd5.

1. Asset searches launched with ``--no-wait`` never had their causal span closed
   (nothing reconciles them through the kernel), so the #342 parked-time rule saw
   an eternally "running" job and charged every later silence as work: six budget
   extensions on a run that had parked for more than an hour.
2. A relative / placeholder narration path was refused only inside the candidate
   ledger (``path.missing`` excluded from the cheap precheck), so two convergence
   candidates went to a path typo and the run stopped at needs_revision.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from lib import persian_edit_workspace as workspace
from lib import persian_video_workflow as workflow
from lib.persian_edit_workspace import PersianEditWorkspaceError
from lib.persian_workflow_telemetry import parked_wall_seconds
from tests.lib.test_issue226_edit_precheck_before_candidate import _front_door
from tests.lib.test_issue35_convergence_workspace import _schema_valid_edit

T0 = datetime(2026, 9, 29, 16, 0, tzinfo=timezone.utc)


def _at(minutes: float) -> str:
    return (T0 + timedelta(minutes=minutes)).isoformat()


def _state(root: Path, *, job_finished: str | None) -> dict:
    job = root / ".jobs" / "asset-search-1-a0"
    job.mkdir(parents=True)
    if job_finished is not None:
        (job / "state.json").write_text(json.dumps({
            "status": "succeeded", "finishedAt": job_finished,
        }), encoding="utf-8")
    return {
        "read_allowlist": {"project_root": str(root)},
        "causal_telemetry": {
            "spans": [{
                "span_id": "job:asset-search-1-a0", "kind": "durable_job",
                "category": "provider_network_wait", "count_toward_wall": True,
                "job_id": "asset-search-1-a0", "started_at": _at(0),
                "finished_at": None, "outcome": "running",
            }],
            "command_events": [
                {"at": _at(0), "command": "workflow:asset-search", "edge": "start"},
                {"at": _at(0.01), "command": "workflow:asset-search", "edge": "finish"},
                # the operator walked away for 40 minutes after the job finished
                {"at": _at(42), "command": "workflow:asset-candidate-stage", "edge": "start"},
                {"at": _at(42.01), "command": "workflow:asset-candidate-stage", "edge": "finish"},
            ],
        },
    }


def test_a_finished_no_wait_job_no_longer_masks_the_silence_after_it(tmp_path: Path) -> None:
    state = _state(tmp_path, job_finished=_at(2))
    parked = parked_wall_seconds(state, since=T0, now=T0 + timedelta(minutes=43), silence_seconds=900)
    assert parked["silent_seconds"] == pytest.approx(40 * 60, abs=1)


def test_a_job_that_is_really_still_running_still_counts_as_work(tmp_path: Path) -> None:
    state = _state(tmp_path, job_finished=None)
    parked = parked_wall_seconds(state, since=T0, now=T0 + timedelta(minutes=43), silence_seconds=900)
    assert parked["parked_seconds"] == 0.0


def test_a_placeholder_narration_path_is_refused_before_any_candidate(tmp_path, monkeypatch) -> None:
    payload = _schema_valid_edit()
    payload["persian"]["audio"] = {"narration": "{project}/inputs/narration.mp3"}
    source = _front_door(tmp_path, monkeypatch, payload)
    with pytest.raises(
        PersianEditWorkspaceError,
        match=r"(?s)EDIT_PRECHECK.*path\.missing /persian/audio/narration.*relative path resolves against the repository root",
    ):
        workflow.stage_workflow_edit_draft("run", "base", source, pipeline_dir=tmp_path)
    assert workspace.convergence_status(tmp_path / "run", revision_cycle=0)["candidateCount"] == 0


def test_the_refusal_names_the_projects_real_narration(tmp_path, monkeypatch) -> None:
    payload = _schema_valid_edit()
    payload["persian"]["audio"] = {"narration": "inputs/narration.mp3"}
    real = tmp_path / "run" / "inputs" / "narration.mp3"
    with pytest.raises(PersianEditWorkspaceError, match=r"use this project's narration by absolute path: " + str(real)):
        workflow._refuse_cheap_preflight_defects_before_candidate(
            payload, {"authority": "t"}, narration_path=str(real),
        )


def test_shot_source_paths_stay_with_the_asset_binding() -> None:
    """The fixture's /tmp shot sources do not exist; the binding owns them, not this precheck."""
    workflow._refuse_cheap_preflight_defects_before_candidate(_schema_valid_edit(), {"authority": "t"})


def test_a_multi_word_accent_is_refused_before_any_candidate(tmp_path, monkeypatch) -> None:
    """pathfix-01 cleared the path and then died in the browser on accentWords 'پیام بدی'."""
    payload = _schema_valid_edit()
    segment = payload["persian"]["moments"][0]["segments"][0]
    words = segment["text"].split()
    if len(words) < 2:
        pytest.skip("fixture hook has a single word")
    segment["accentWords"] = [f"{words[0]} {words[1]}"]
    source = _front_door(tmp_path, monkeypatch, payload)
    with pytest.raises(PersianEditWorkspaceError, match=r"(?s)EDIT_PRECHECK.*moment\.invalid.*accents"):
        workflow.stage_workflow_edit_draft("run", "base", source, pipeline_dir=tmp_path)
    assert workspace.convergence_status(tmp_path / "run", revision_cycle=0)["candidateCount"] == 0
