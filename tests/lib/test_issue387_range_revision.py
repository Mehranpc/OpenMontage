"""#387 increment 5: the human time-range revision is the only v3 backward path."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from lib import persian_pipeline_profile as profile
from lib import persian_range_revision as rr
from lib import persian_stage_locks as locks
from lib import persian_video_workflow as workflow
from lib.persian_video_workflow import PersianVideoWorkflowError, load_workflow_state
from tests.lib.test_issue387_topic_admission import V3, _run

SPANS = [{"visualEventId": f"event-{i}", "startSeconds": 5.0 * i, "endSeconds": 5.0 * (i + 1)} for i in range(12)]


@pytest.fixture
def v3(monkeypatch):
    monkeypatch.setenv(profile.OPT_IN_ENV, "v3_staged")


def test_event_spans_follow_the_locked_plan_order():
    rows = [{"visual_event_id": "a", "duration_seconds": 2.0}, {"visual_event_id": None, "duration_seconds": 1.5},
            {"visual_event_id": "b", "duration_seconds": 3.0}]
    assert rr.footage_event_spans(rows) == [
        {"visualEventId": "a", "startSeconds": 0.0, "endSeconds": 2.0},
        {"visualEventId": "b", "startSeconds": 3.5, "endSeconds": 6.5},
    ]
    with pytest.raises(rr.RangeRevisionError, match="positive duration"):
        rr.footage_event_spans([{"visual_event_id": "a", "duration_seconds": 0}])


def test_a_range_expands_to_the_footage_events_it_overlaps():
    assert rr.events_in_range(SPANS, 12.0, 15.5) == ["event-2", "event-3"]
    assert rr.expanded_range(SPANS, ["event-2", "event-3"]) == {"startSeconds": 10.0, "endSeconds": 20.0}
    assert rr.events_in_range(SPANS, 10.0, 10.5) == ["event-2"]
    with pytest.raises(rr.RangeRevisionError, match="--from < --to"):
        rr.events_in_range(SPANS, 3.0, 3.0)
    with pytest.raises(rr.RangeRevisionError, match="outside the locked timeline"):
        rr.events_in_range(SPANS, 61.0, 62.0)


def test_outside_events_must_keep_identical_manifest_evidence():
    manifest = {"assets": [{"visual_event_id": f"event-{i}", "path": f"{i}.mp4"} for i in range(3)]}
    before = rr.manifest_event_digests(manifest)
    changed = {"assets": [dict(row) for row in manifest["assets"]]}
    changed["assets"][1]["path"] = "new.mp4"
    assert rr.outside_changes(before, rr.manifest_event_digests(changed), ["event-1"]) == []
    changed["assets"][0]["path"] = "drift.mp4"
    assert rr.outside_changes(before, rr.manifest_event_digests(changed), ["event-1"]) == ["event-0"]


def _clip(path: Path, *, box_from: float | None, duration: int = 4) -> Path:
    vf = "null" if box_from is None else f"drawbox=x=10:y=10:w=60:h=60:color=red:t=fill:enable='between(t,{box_from},{box_from + 1})'"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc=size=160x120:rate=30:duration={duration}",
                    "-vf", vf, "-c:v", "libx264", "-qp", "0", "-pix_fmt", "yuv444p", str(path)],
                   check=True, timeout=120)
    return path


def test_frame_proof_compares_decoded_frames_outside_the_range(tmp_path):
    previous = _clip(tmp_path / "previous.mp4", box_from=None)
    candidate = _clip(tmp_path / "candidate.mp4", box_from=2.0)
    inside = rr.outside_range_frame_proof(previous, candidate, 2.0, 3.0)
    assert inside["status"] == "pass", inside
    assert inside["framesCompared"] > 60
    outside = rr.outside_range_frame_proof(previous, candidate, 0.5, 1.5)
    assert outside["status"] == "fail" and outside["mismatchCount"] >= 29


def test_archived_lock_keeps_history_and_a_new_version_records_provenance(tmp_path):
    project = tmp_path / "p"
    project.mkdir()
    for name in ("a.json", "b.json"):
        (project / name).write_text("{}")
    locks.write_stage_lock(project, 0, ["a.json"], implementation_sha="x")
    first = locks.write_stage_lock(project, 1, ["b.json"], implementation_sha="x")
    with pytest.raises(locks.StageLockError, match="later stages"):
        locks.archive_stage_lock(project, 0, reason="no")
    locks.archive_stage_lock(project, 1, reason="rev-001")
    assert not locks.is_locked(project, 1)
    assert json.loads((project / "stage_locks/history/stage-1.v1.json").read_text())["content_digest"] == first["content_digest"]
    (project / "b.json").write_text('{"new": 1}')
    second = locks.write_stage_lock(project, 1, ["b.json"], implementation_sha="y", lock_version=2,
                                    provenance={"revision": 1})
    assert second["lock_version"] == 2 and second["provenance"] == {"revision": 1}
    assert second["input_digests"] == first["input_digests"]


def _stop_for_review(tmp_path: Path, project: Path, monkeypatch) -> Path:
    manifest = {"assets": [{"visual_event_id": f"event-{i}", "path": f"clip-{i}.mp4"} for i in range(12)]}
    (project / "checkpoint_assets.json").write_text(json.dumps(
        {"stage": "assets", "status": "completed", "artifacts": {"asset_manifest": manifest}}))
    locks.write_stage_lock(project, 1, ["checkpoint_assets.json"], implementation_sha="abc")
    candidate = _clip(project / "candidate.mp4", box_from=None)
    path = workflow._state_path(project)
    state = json.loads(path.read_text())
    state.update(status="awaiting_human", next_phase=None)
    path.write_text(json.dumps(state))
    monkeypatch.setattr(workflow, "_validate_awaiting_human_candidate", lambda state, **_: {
        "candidate_path": str(candidate), "candidate_sha256": workflow._hash_file(candidate),
        "checkpoint": "checkpoint_compose.json"})
    monkeypatch.setattr(workflow, "read_checkpoint", lambda root, pid, stage: json.loads(
        (root / pid / f"checkpoint_{stage}.json").read_text()))
    return candidate


def test_revise_reopens_only_the_overlapping_events(tmp_path, v3, monkeypatch):
    project = _run(tmp_path, V3)
    _stop_for_review(tmp_path, project, monkeypatch)
    result = workflow.revise_time_range("run", 12.0, 15.5, reason="the glance reads wrong", pipeline_dir=tmp_path)
    assert result["visualEventIds"] == ["event-2", "event-3"]
    assert result["range"] == {"startSeconds": 10.0, "endSeconds": 20.0}
    state = load_workflow_state("run", pipeline_dir=tmp_path)
    assert state["next_phase"] == "acquire_assets"
    assert state["asset_reacquisition_scope"]["visualEventIds"] == ["event-2", "event-3"]
    assert state["asset_reacquisition_grant"]["candidates"] == 4
    assert not locks.is_locked(project, 1) and locks.is_locked(project, 0)
    record = rr.active_revision(project)
    assert record["status"] == "open" and record["requestedBy"] == "human"
    assert (project / record["previousCandidate"]["path"]).is_file()
    with pytest.raises(PersianVideoWorkflowError, match="already open|human review"):
        workflow.revise_time_range("run", 0.0, 1.0, reason="again", pipeline_dir=tmp_path)


def test_new_footage_lock_refuses_changes_outside_the_range(tmp_path, v3, monkeypatch):
    project = _run(tmp_path, V3)
    _stop_for_review(tmp_path, project, monkeypatch)
    workflow.revise_time_range("run", 12.0, 13.0, reason="swap", pipeline_dir=tmp_path)
    manifest = {"assets": [{"visual_event_id": f"event-{i}", "path": f"clip-{i}.mp4"} for i in range(12)]}
    manifest["assets"][2]["path"] = "replacement.mp4"
    manifest["assets"][7]["path"] = "drift.mp4"
    (project / "checkpoint_assets.json").write_text(json.dumps(
        {"stage": "assets", "status": "completed", "artifacts": {"asset_manifest": manifest}}))
    state = load_workflow_state("run", pipeline_dir=tmp_path)
    with pytest.raises(PersianVideoWorkflowError, match=r"outside its range: \['event-7'\]"):
        workflow._apply_v3_stage_locks(state, "acquire_assets", now=None)
    manifest["assets"][7]["path"] = "clip-7.mp4"
    (project / "checkpoint_assets.json").write_text(json.dumps(
        {"stage": "assets", "status": "completed", "artifacts": {"asset_manifest": manifest}}))
    lock = workflow._apply_v3_stage_locks(state, "acquire_assets", now=None)
    assert lock["stage"] == 1
    record = locks.read_stage_lock(project, 1)
    assert record["lock_version"] == 2 and record["provenance"]["visualEventIds"] == ["event-2"]
    assert rr.active_revision(project)["status"] == "footage_locked"


def test_revised_candidate_must_keep_frames_outside_the_range(tmp_path, v3, monkeypatch):
    project = _run(tmp_path, V3)
    _stop_for_review(tmp_path, project, monkeypatch)
    workflow.revise_time_range("run", 2.0, 2.5, reason="swap", pipeline_dir=tmp_path)
    revision = rr.active_revision(project)
    rr.write_revision(project, {**revision, "status": "footage_locked"})
    state = load_workflow_state("run", pipeline_dir=tmp_path)
    long_previous = _clip(tmp_path / "long-prev.mp4", box_from=None, duration=8)
    (project / revision["previousCandidate"]["path"]).write_bytes(long_previous.read_bytes())
    revised = _clip(tmp_path / "revised.mp4", box_from=2.0, duration=8)  # changes 2-3s, inside event-0 (0-5s)
    ok = workflow._close_range_revision(state, {"candidate_path": str(revised), "candidate_sha256": "x"})
    assert ok["proof"]["status"] == "pass" and not ok["proof"]["vacuous"]
    assert ok["proof"]["framesCompared"] > 60
    assert rr.active_revision(project) is None


def test_revised_candidate_with_changed_outside_frames_is_refused(tmp_path, v3, monkeypatch):
    project = _run(tmp_path, V3)
    candidate = _stop_for_review(tmp_path, project, monkeypatch)
    workflow.revise_time_range("run", 5.5, 6.0, reason="swap", pipeline_dir=tmp_path)  # event-1: 5-10s
    revision = rr.active_revision(project)
    rr.write_revision(project, {**revision, "status": "footage_locked"})
    state = load_workflow_state("run", pipeline_dir=tmp_path)
    bad = _clip(tmp_path / "bad.mp4", box_from=1.0)  # 1-2s lies outside 5-10s
    with pytest.raises(PersianVideoWorkflowError, match="frames outside 5.0-10.0s changed"):
        workflow._close_range_revision(state, {"candidate_path": str(bad), "candidate_sha256": "x"})
    assert rr.active_revision(project)["proofAttempts"][0]["status"] == "fail"


def test_v2_has_no_range_revision(tmp_path, monkeypatch):
    monkeypatch.delenv(profile.OPT_IN_ENV, raising=False)
    _run(tmp_path, None)
    with pytest.raises(PersianVideoWorkflowError, match="v2 uses send-back"):
        workflow.revise_time_range("run", 0.0, 1.0, reason="x", pipeline_dir=tmp_path)
