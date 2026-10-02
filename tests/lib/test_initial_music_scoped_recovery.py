from __future__ import annotations

import json
from pathlib import Path

import pytest

from lib.checkpoint import write_checkpoint
from lib import persian_asset_commands as assets
from lib import persian_asset_workspace as workspace
from lib import persian_music_commands as music
from lib import persian_video_workflow as workflow
from tests.lib.test_issue35_asset_candidate_workspace import _selected_candidate
from tests.lib.test_persian_music_commands import _FakeMusicTool, _metadata, _request
from tests.lib.test_persian_video_workflow import _bootstrap_to_assets


def _prepared(tmp_path, monkeypatch):
    _bootstrap_to_assets(tmp_path)
    project = tmp_path / "run"
    candidate, _ = _selected_candidate(project)
    plan = json.loads((project / "checkpoint_scene_plan.json").read_text())["artifacts"]["scene_plan"]
    brief = {
        "version": "1.0", "title": "Sample", "hook": "نمونه",
        "key_points": ["نمونه"], "tone": "conversational", "style": "real footage",
        "target_platform": "instagram-reels", "target_duration_seconds": 4.0,
        "metadata": {"music_plan": "warm minimal instrumental beneath narration"},
    }
    script = {
        "version": "1.0", "title": "Sample", "total_duration_seconds": 4.0,
        "sections": [{"id": "beat-1", "text": "این یک جمله نمونه است",
                      "start_seconds": 0.0, "end_seconds": 4.0}],
    }
    for stage, artifacts in [
        ("idea", {"brief": brief}), ("script", {"script": script}),
        ("scene_plan", {"scene_plan": plan}),
    ]:
        write_checkpoint(tmp_path, "run", stage, "completed", artifacts,
                         pipeline_type="persian-footage")
    (project / "artifacts" / "brief.json").write_text(json.dumps(brief))
    assets.build_manifest(tmp_path, "run")
    assets.write_assets_checkpoint(tmp_path, "run", tool_gap="MUSIC_MISSING_SCOPED_RECOVERY")
    state = workflow.load_workflow_state("run", pipeline_dir=tmp_path)
    state["asset_reacquisition_scope"] = {
        "version": "1.0", "diagnosticCode": "ASSET_QUERY_EXHAUSTED",
        "reasonCode": "ASSET_QUERY_EXHAUSTED", "shotIds": [],
        "visualEventIds": ["event-1"], "reason": "Scoped early query recovery",
    }
    state["asset_usage"] = {"completed_passes": [0, 1], "pending_pass": None}
    state["send_backs"] = 1
    (project / workflow.STATE_FILENAME).write_text(json.dumps(state))
    request = project / "music-request.json"
    request.write_text(json.dumps(_request()))
    metadata = project / "music-metadata.json"
    metadata.write_text(json.dumps(_metadata()))
    tool = _FakeMusicTool()
    original_search = music.search_music
    monkeypatch.setattr(workflow, "search_music_command",
                        lambda root, pid, payload: original_search(
                            root, pid, payload, tool_factory=lambda provider: tool))
    return project, candidate, request, metadata, tool


def _protected_bytes(project):
    return {str(p.relative_to(project)): p.read_bytes()
            for p in project.rglob("*") if p.is_file()
            and (".asset-workspace/candidates/" in str(p)
                 or p.name in {workflow.STATE_FILENAME, "selections.json",
                               "checkpoint_scene_plan.json", "asset_manifest.json"})}


@pytest.mark.parametrize("music_field", ["music", "musicTrack"])
def test_initial_music_after_complete_early_visual_repair_keeps_scope_and_bindings(
    tmp_path: Path, monkeypatch, music_field,
):
    project, candidate, request, metadata, tool = _prepared(tmp_path, monkeypatch)
    before = _protected_bytes(project)
    first = workflow.search_workflow_music("run", request, pipeline_dir=tmp_path)
    again = workflow.search_workflow_music("run", request, pipeline_dir=tmp_path)
    assert again["idempotent"] is True
    assert tool.calls == 1
    fetched = workflow.fetch_workflow_music(
        "run", first["searchId"], metadata, pipeline_dir=tmp_path)
    assert Path(fetched["audioPath"]).read_bytes() == b"deterministic-music-bytes"
    assert fetched["track"]["source"] == "pixabay_music"
    assert _protected_bytes(project) == before
    # The exception must not release visual scope or admit an unrelated selection.
    unrelated = project / "unrelated-stage.json"
    record = workspace.load_asset_candidate(project, candidate["candidateId"])
    unrelated.write_text(json.dumps({
        "discovery_id": record["discoveryId"], "visual_event_id": "unrelated",
        "semantic_beat_id": "beat-1", "source_in_seconds": 1.0,
        "duration_seconds": 4.0, "intended_crop": record["identity"]["intendedCrop"],
        "candidate_rank": 1, "query": "person thinking at desk",
        "narration_span": "این یک جمله نمونه است",
    }))
    with pytest.raises(workflow.PersianVideoWorkflowError, match="outside scoped"):
        workflow.stage_workflow_asset_candidate("run", unrelated, pipeline_dir=tmp_path)
    overrides = project / "manifest-with-music.json"
    overrides.write_text(json.dumps({music_field: fetched["track"]}))
    workflow.build_workflow_asset_manifest(
        "run", overrides_path=overrides, pipeline_dir=tmp_path)
    result = workflow.write_workflow_assets_checkpoint("run", pipeline_dir=tmp_path)
    assert result["status"] == "completed"
    checkpoint = json.loads((project / "checkpoint_assets.json").read_text())
    assert checkpoint["artifacts"]["asset_manifest"][music_field] == fetched["track"]


@pytest.mark.parametrize("damage", [
    "manifest_missing", "manifest_incomplete", "manifest_stale", "candidate_torn",
    "plan_changed", "pending_pass", "late_scope", "prior_completion",
    "existing_music", "existing_record", "music_not_approved", "provider_change",
])
def test_scoped_music_refuses_without_current_initial_completion_proof(
    tmp_path: Path, monkeypatch, damage: str,
):
    project, candidate, request, metadata, tool = _prepared(tmp_path, monkeypatch)
    state_path = project / workflow.STATE_FILENAME
    state = json.loads(state_path.read_text())
    manifest_path = project / "artifacts" / "asset_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    if damage == "manifest_missing":
        manifest_path.unlink()
    elif damage == "manifest_incomplete":
        manifest["assets"] = []
        manifest_path.write_text(json.dumps(manifest))
    elif damage == "manifest_stale":
        manifest["assets"][0]["asset_review_sha256"] = "0" * 64
        manifest_path.write_text(json.dumps(manifest))
    elif damage == "candidate_torn":
        path = project / ".asset-workspace" / "candidates" / (candidate["candidateId"] + ".json")
        data = json.loads(path.read_text())
        data["review"]["human_presence"] = False
        path.write_text(json.dumps(data))
    elif damage == "plan_changed":
        path = project / "checkpoint_scene_plan.json"
        plan = json.loads(path.read_text())
        plan["artifacts"]["scene_plan"]["beats"][0]["visual_events"][0]["fallback_level"] = "emotional_human"
        path.write_text(json.dumps(plan))
    elif damage == "pending_pass":
        state["asset_usage"]["pending_pass"] = 1
    elif damage == "late_scope":
        state["asset_reacquisition_scope"]["diagnosticCode"] = "ASSET_SELECTION_HARD_REGION_COLLISION"
        state["asset_reacquisition_scope"]["shotIds"] = ["shot-1"]
    elif damage == "prior_completion":
        state.setdefault("evidence", {})["acquire_assets"] = {"previous": True}
    elif damage == "existing_music":
        manifest["musicTrack"] = {"path": "existing.mp3"}
        manifest_path.write_text(json.dumps(manifest))
    elif damage == "existing_record":
        (project / "artifacts" / "music_track.json").write_text("{}")
    elif damage == "music_not_approved":
        (project / "artifacts" / "brief.json").write_text("{}")
    elif damage == "provider_change":
        payload = _request()
        payload["provider"] = "freesound_music"
        request.write_text(json.dumps(payload))
    state_path.write_text(json.dumps(state))
    before = {str(p.relative_to(project)): p.read_bytes()
              for p in project.rglob("*") if p.is_file()}
    with pytest.raises((workflow.PersianVideoWorkflowError, assets.PersianAssetCommandError,
                        workspace.PersianAssetWorkspaceError)):
        workflow.search_workflow_music("run", request, pipeline_dir=tmp_path)
    assert tool.calls == 0
    after = {str(p.relative_to(project)): p.read_bytes()
             for p in project.rglob("*") if p.is_file()}
    assert before == after


def test_fetch_rechecks_visual_proof_and_refuses_existing_music(
    tmp_path: Path, monkeypatch,
):
    project, candidate, request, metadata, tool = _prepared(tmp_path, monkeypatch)
    searched = workflow.search_workflow_music("run", request, pipeline_dir=tmp_path)
    path = project / "artifacts" / "asset_manifest.json"
    before = path.read_bytes()
    path.unlink()
    with pytest.raises(workflow.PersianVideoWorkflowError):
        workflow.fetch_workflow_music("run", searched["searchId"], metadata, pipeline_dir=tmp_path)
    assert not (project / "artifacts" / "music_track.json").exists()
    path.write_bytes(before)
    fetched = workflow.fetch_workflow_music("run", searched["searchId"], metadata, pipeline_dir=tmp_path)
    music_bytes = Path(fetched["audioPath"]).read_bytes()
    track_bytes = Path(fetched["trackPath"]).read_bytes()
    with pytest.raises(workflow.PersianVideoWorkflowError):
        workflow.fetch_workflow_music("run", searched["searchId"], metadata, pipeline_dir=tmp_path)
    assert Path(fetched["audioPath"]).read_bytes() == music_bytes
    assert Path(fetched["trackPath"]).read_bytes() == track_bytes


def test_cli_genuine_stop_still_blocks_initial_music(tmp_path: Path, monkeypatch):
    project, candidate, request, metadata, tool = _prepared(tmp_path, monkeypatch)
    state_path = project / workflow.STATE_FILENAME
    state = json.loads(state_path.read_text())
    state["status"] = "failed"
    state["budget_stop"] = {"reason": "phase_budget_exceeded"}
    state_path.write_text(json.dumps(state))
    original_load = workflow.load_workflow_state
    monkeypatch.setattr(workflow, "load_workflow_state",
                        lambda pid, **kwargs: original_load(pid, pipeline_dir=tmp_path))
    with pytest.raises(SystemExit):
        workflow.main(["assets", "music", "search", "run", "--json", str(request)])
    assert tool.calls == 0
    assert json.loads(state_path.read_text())["status"] == "failed"


@pytest.mark.parametrize("music_field", ["music", "musicTrack"])
@pytest.mark.parametrize("field,value", [
    ("acknowledged", False), ("acknowledged", ""), ("unrecognized", "invented"),
])
def test_music_manifest_still_rejects_malformed_or_unknown_risk_fields(
    tmp_path: Path, monkeypatch, field, value, music_field,
):
    from lib.persian_music import build_music_track

    project, candidate, request, metadata, tool = _prepared(tmp_path, monkeypatch)
    track = build_music_track({
        **_metadata(), "path": str(project / "assets/music/bed.mp3"),
        "source": "pixabay_music", "attribution": "Calm Track — Test Artist",
    }).to_dict()
    track["contentIdRisk"][field] = value
    before = (project / "artifacts/asset_manifest.json").read_bytes()
    with pytest.raises(assets.PersianAssetCommandError):
        assets.build_manifest(tmp_path, "run", overrides={music_field: track})
    assert (project / "artifacts/asset_manifest.json").read_bytes() == before


def test_late_scoped_fetch_refuses_before_unrelated_cache_lookup(tmp_path: Path, monkeypatch):
    project, candidate, request, metadata, tool = _prepared(tmp_path, monkeypatch)
    state_path = project / workflow.STATE_FILENAME
    state = json.loads(state_path.read_text())
    state["asset_reacquisition_scope"]["diagnosticCode"] = "ASSET_SELECTION_HARD_REGION_COLLISION"
    state["asset_reacquisition_scope"]["shotIds"] = ["shot-1"]
    state_path.write_text(json.dumps(state))
    before = {str(p.relative_to(project)): p.read_bytes()
              for p in project.rglob("*") if p.is_file()}
    with pytest.raises(workflow.PersianVideoWorkflowError, match="music acquisition is forbidden"):
        workflow.fetch_workflow_music("run", "music-" + "a" * 24, metadata,
                                      pipeline_dir=tmp_path)
    assert tool.calls == 0
    assert before == {str(p.relative_to(project)): p.read_bytes()
                      for p in project.rglob("*") if p.is_file()}


def _browser_request(project, request):
    import hashlib
    audio = project / "assets/music/browser.mp3"
    audio.parent.mkdir(parents=True, exist_ok=True)
    audio.write_bytes(b"browser-downloaded-music")
    payload = {
        **_request(), "audio_url": "https://cdn.pixabay.com/download/audio/2026/audio_test.mp3",
        "source_url": "https://pixabay.com/music/ambient-calm-track-123/",
        "track_title": "Calm Track", "artist": "Test Artist", "duration_seconds": 90,
        "browser_download": {"path": "assets/music/browser.mp3",
                             "sha256": hashlib.sha256(audio.read_bytes()).hexdigest()},
    }
    request.write_text(json.dumps(payload))
    return audio, payload


def test_browser_download_enters_initial_music_without_second_network_download(tmp_path, monkeypatch):
    project, candidate, request, metadata, tool = _prepared(tmp_path, monkeypatch)
    audio, payload = _browser_request(project, request)
    original = audio.read_bytes()
    before = _protected_bytes(project)
    result = workflow.search_workflow_music("run", request, pipeline_dir=tmp_path)
    repeat = workflow.search_workflow_music("run", request, pipeline_dir=tmp_path)
    assert repeat["idempotent"]
    assert tool.calls == 0
    assert Path(result["cachedPath"]).read_bytes() == original
    assert result["result"]["source_url"] == payload["source_url"]
    assert result["result"]["search_strategy"] == "direct_cdn_browser_download"
    fetched = workflow.fetch_workflow_music("run", result["searchId"], metadata,
                                           pipeline_dir=tmp_path)
    assert Path(fetched["audioPath"]).read_bytes() == original
    assert audio.read_bytes() == original
    assert _protected_bytes(project) == before
    overrides = project / "browser-music-overrides.json"
    overrides.write_text(json.dumps({"musicTrack": fetched["track"]}))
    workflow.build_workflow_asset_manifest("run", overrides_path=overrides, pipeline_dir=tmp_path)
    assert workflow.write_workflow_assets_checkpoint("run", pipeline_dir=tmp_path)["status"] == "completed"
    with pytest.raises(workflow.PersianVideoWorkflowError):
        workflow.search_workflow_music("run", request, pipeline_dir=tmp_path)


@pytest.mark.parametrize("damage", ["digest", "foreign_path", "unbound_file", "cdn", "source", "provider", "changed_before_fetch"])
def test_browser_import_refuses_unbound_or_changed_evidence(tmp_path, monkeypatch, damage):
    project, candidate, request, metadata, tool = _prepared(tmp_path, monkeypatch)
    audio, payload = _browser_request(project, request)
    if damage == "changed_before_fetch":
        result = workflow.search_workflow_music("run", request, pipeline_dir=tmp_path)
        audio.write_bytes(b"changed")
        with pytest.raises((workflow.PersianVideoWorkflowError, music.PersianMusicCommandError)):
            workflow.fetch_workflow_music("run", result["searchId"], metadata, pipeline_dir=tmp_path)
        assert not (project / "artifacts/music_track.json").exists()
        assert tool.calls == 0
        return
    if damage == "digest": payload["browser_download"]["sha256"] = "0" * 64
    elif damage == "foreign_path": payload["browser_download"]["path"] = "../outside.mp3"
    elif damage == "unbound_file": (audio.parent / "unrelated.mp3").write_bytes(b"unrelated")
    elif damage == "cdn": payload["audio_url"] = "https://example.com/audio/test.mp3"
    elif damage == "source": payload["source_url"] = "https://example.com/music/test/"
    elif damage == "provider": payload["provider"] = "freesound_music"
    request.write_text(json.dumps(payload))
    before = {str(p.relative_to(project)): p.read_bytes() for p in project.rglob("*") if p.is_file()}
    with pytest.raises((workflow.PersianVideoWorkflowError, music.PersianMusicCommandError)):
        workflow.search_workflow_music("run", request, pipeline_dir=tmp_path)
    assert tool.calls == 0
    assert before == {str(p.relative_to(project)): p.read_bytes() for p in project.rglob("*") if p.is_file()}
