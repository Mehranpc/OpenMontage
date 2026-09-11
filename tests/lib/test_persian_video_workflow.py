import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

import lib.persian_video_workflow as workflow
from tools.tool_registry import registry

from lib.persian_video_workflow import (
    PHASES,
    PersianVideoWorkflowError,
    assert_read_allowed,
    attach_narration,
    bounded_asset_search_request,
    bootstrap_persian_video,
    complete_phase,
    load_workflow_state,
    record_asset_search_result,
    record_phase_attempt,
    request_send_back,
    resume_workflow,
)

ROOT = Path(__file__).resolve().parents[2]
BASE = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
_AUTO_NARRATION = object()


def _bootstrap(
    tmp_path: Path,
    *,
    project_id: str = "run",
    narration_path: str | None | object = _AUTO_NARRATION,
    approved_script: str | None = "متن تأییدشده",
):
    if narration_path is _AUTO_NARRATION:
        external = tmp_path.parent / f"{tmp_path.name}-{project_id}-source.wav"
        external.write_bytes(b"audio")
        narration_path = str(external)
    calls: list[str | None] = []
    state = bootstrap_persian_video(
        title="Run",
        narration_path=narration_path,
        approved_script=approved_script,
        project_id=project_id,
        pipeline_dir=tmp_path,
        backlot_opener=lambda pid: calls.append(pid) or 0,
        now=BASE,
    )
    return state, calls


def _prepare_inputs_evidence(state: dict) -> dict:
    approved = state["input"].get("approved_script")
    script_sha = approved["sha256"] if approved else "a" * 64
    return {
        "authoritative_script_sha256": script_sha,
        "narration_sha256": state["input"]["narration"]["sha256"],
    }


def _advance_to(tmp_path: Path, target: str, *, project_id: str = "run") -> dict:
    state = load_workflow_state(project_id, pipeline_dir=tmp_path)
    while state.get("next_phase") != target:
        phase = state.get("next_phase")
        assert phase is not None
        state = record_phase_attempt(project_id, phase, pipeline_dir=tmp_path, now=BASE)
        evidence = _prepare_inputs_evidence(state) if phase == "prepare_inputs" else None
        state = complete_phase(
            project_id, phase, evidence=evidence, pipeline_dir=tmp_path, now=BASE
        )
    return state


def _report(
    candidate: Path, *, digest: str | None = None, fmt: str = "mp4", review_ref: str | None = None
) -> dict:
    review_ref = review_ref or str(candidate.parent.parent / "artifacts" / "final_review.json")
    return {
        "version": "1.0",
        "delivery_status": "final_candidate",
        "human_visual_approval": False,
        "persian_text_verified": False,
        "outputs": [{
            "path": str(candidate), "format": fmt, "resolution": "1080x1920",
            "duration_seconds": 12.0,
            "sha256": digest or hashlib.sha256(candidate.read_bytes()).hexdigest(),
        }],
        "final_review_ref": review_ref,
        "caption_mode": "sidecar_only",
        "retention_audit": {
            "problems": [], "advisories": [],
            "first3Seconds": {"eventCount": 2, "events": []},
            "averageVisualEventSeconds": 3.0,
            "longestVisualEvent": {"id": "s1", "seconds": 4.0},
            "meaningfulChangesPer15Seconds": [], "weakEmptyIntervals": [],
            "textOnlySeconds": 0.0, "endingTextOnlySeconds": 0.0,
            "cutGrammar": {"transitions": ["cut"], "nonCutCount": 0},
            "judgementRequired": ["silent_watch_main_point"],
        },
        "silent_watch_audit": {
            "main_point_understood": True, "hook_direction_understood": True,
            "conclusion_understood": True, "notes": ["Muted review preserves the main point."],
        },
        "cut_rhythm": "Purposeful hard-cut rhythm.",
        "caption_readability": "Readable without competing with moments.",
        "strongest_scene": "opening hook", "weakest_scene": "middle exposition",
        "hook_strength": "strong", "resolution_strength": "acceptable",
    }


def _checkpoint(report: dict, **overrides) -> dict:
    value = {
        "version": "1.0",
        "project_id": "run",
        "pipeline_type": "persian-footage",
        "stage": "compose",
        "status": "awaiting_human",
        "timestamp": "2026-09-11T12:00:00+00:00",
        "checkpoint_policy": "guided",
        "human_approval_required": True,
        "human_approved": False,
        "artifacts": {"render_report": report},
    }
    value.update(overrides)
    return value


def test_bootstrap_accepts_only_approved_production_inputs_and_opens_backlot(tmp_path):
    audio = tmp_path / "source.wav"
    audio.write_bytes(b"audio")
    cases = [
        (None, "متن تأییدشده", "approved_script_only", "approved_script"),
        (str(audio), None, "narration_only", "spoken_narration"),
        (str(audio), "متن تأییدشده", "approved_script_with_narration", "approved_script"),
    ]
    for index, (narration, script, mode, authority) in enumerate(cases):
        root = tmp_path / f"projects-{index}"
        state, calls = _bootstrap(
            root,
            project_id=f"run-{index}",
            narration_path=narration,
            approved_script=script,
        )
        assert calls == [f"run-{index}"]
        assert state["completed_phases"] == list(PHASES[:3])
        assert state["next_phase"] == "prepare_inputs"
        assert state["input"]["mode"] == mode
        assert state["input"]["script_authority"] == authority
        marker = json.loads((root / f"run-{index}" / "project.json").read_text(encoding="utf-8"))
        assert marker["pipeline_type"] == "persian-footage"
        if script is not None:
            script_path = Path(state["input"]["approved_script"]["source_path"])
            assert script_path == (root / f"run-{index}" / "inputs" / "approved_script.txt").resolve()
            assert script_path.read_text(encoding="utf-8") == script
        if narration is not None:
            narration_copy = Path(state["input"]["narration"]["source_path"])
            assert narration_copy.parent == (root / f"run-{index}" / "inputs").resolve()
            assert narration_copy.read_bytes() == b"audio"
            assert narration_copy != audio.resolve()

    with pytest.raises(PersianVideoWorkflowError, match="requires an approved Persian script"):
        bootstrap_persian_video(
            title="Run", project_id="empty", pipeline_dir=tmp_path / "empty-root",
            backlot_opener=lambda _: 0, now=BASE,
        )


def test_bootstrap_refuses_existing_project_without_opening_backlot(tmp_path):
    (tmp_path / "run").mkdir()
    calls = []
    with pytest.raises(PersianVideoWorkflowError, match="refusing to reuse"):
        bootstrap_persian_video(
            title="Run", approved_script="متن", project_id="run",
            pipeline_dir=tmp_path, backlot_opener=lambda pid: calls.append(pid) or 0, now=BASE,
        )
    assert calls == []


def test_read_allowlist_permits_current_source_and_contracts_but_not_siblings(tmp_path):
    source = tmp_path / "source.wav"
    source.write_bytes(b"audio")
    projects = tmp_path / "projects"
    state, _ = _bootstrap(projects, narration_path=str(source), approved_script=None)
    project_root = projects / "run"
    own = project_root / "artifacts" / "own.json"
    own.write_text("{}", encoding="utf-8")
    sibling = projects / "other" / "artifacts" / "foreign.json"
    sibling.parent.mkdir(parents=True)
    sibling.write_text("{}", encoding="utf-8")
    arbitrary = tmp_path / "arbitrary.txt"
    arbitrary.write_text("x", encoding="utf-8")

    assert assert_read_allowed(state, own) == own.resolve()
    copied_source = Path(state["input"]["narration"]["source_path"])
    assert assert_read_allowed(state, copied_source) == copied_source.resolve()
    with pytest.raises(PersianVideoWorkflowError, match="outside"):
        assert_read_allowed(state, source)
    required_contracts = [
        ROOT / "skills" / "persian-video" / "SKILL.md",
        ROOT / "skills" / "meta" / "reviewer.md",
        ROOT / "docs" / "persian-film-type-2.12-patch.md",
        ROOT / "docs" / "film-type-visual-regression.md",
        ROOT / "styles" / "persian-footage" / "film-type.json",
        ROOT / ".agents" / "skills" / "music" / "SKILL.md",
        ROOT / ".agents" / "skills" / "speech-to-text" / "SKILL.md",
        ROOT / ".agents" / "skills" / "ffmpeg" / "SKILL.md",
        ROOT / ".agents" / "skills" / "video-toolkit" / "SKILL.md",
    ]
    for contract in required_contracts:
        assert contract.exists()
        assert assert_read_allowed(state, contract) == contract.resolve()
    with pytest.raises(PersianVideoWorkflowError, match="sibling project"):
        assert_read_allowed(state, sibling)
    with pytest.raises(PersianVideoWorkflowError, match="outside"):
        assert_read_allowed(state, arbitrary)
    with pytest.raises(PersianVideoWorkflowError, match="outside"):
        assert_read_allowed(state, ROOT / "README.md")
    unrelated_layer3 = ROOT / ".agents" / "skills" / "ai-video-gen" / "SKILL.md"
    assert unrelated_layer3.exists()
    with pytest.raises(PersianVideoWorkflowError, match="outside"):
        assert_read_allowed(state, unrelated_layer3)


def test_read_allowlist_covers_layer3_skills_required_by_persian_tools(tmp_path):
    manifest = yaml.safe_load(
        (ROOT / "pipeline_defs" / "persian-footage.yaml").read_text(encoding="utf-8")
    )
    tool_names: set[str] = set()
    for mode in manifest.get("production_modes", []):
        for key in ("required_tools", "optional_tools"):
            tool_names.update(mode.get(key) or [])
    for stage in manifest.get("stages", []):
        for key in ("required_tools", "optional_tools", "tools_available", "preferred_tools", "fallback_tools"):
            tool_names.update(stage.get(key) or [])

    registry.discover()
    unknown = {name for name in tool_names if name not in registry._tools}
    assert unknown == {"web_search"}, (
        "Only the agent-native web_search capability may live outside the local tool registry; "
        f"unexpected names: {sorted(unknown - {'web_search'})}"
    )

    layer3: set[str] = set()
    for tool_name in tool_names - unknown:
        layer3.update(registry._tools[tool_name].get_info().get("agent_skills") or [])

    assert layer3 == {"music", "speech-to-text", "ffmpeg", "video-toolkit"}
    state, _ = _bootstrap(tmp_path)
    for skill in layer3:
        path = ROOT / ".agents" / "skills" / skill / "SKILL.md"
        assert path.exists()
        assert assert_read_allowed(state, path) == path.resolve()


def test_phase_order_is_exact_and_skips_are_refused(tmp_path):
    assert PHASES == (
        "validate_input", "create_project", "open_backlot", "prepare_inputs",
        "align_script_timing", "plan_scenes_moments", "acquire_assets",
        "review_subject_regions", "no_copy_preflight", "render_final_candidate",
        "final_review", "awaiting_human",
    )
    state, _ = _bootstrap(tmp_path)
    with pytest.raises(PersianVideoWorkflowError, match="next phase"):
        record_phase_attempt("run", "align_script_timing", pipeline_dir=tmp_path, now=BASE)
    with pytest.raises(PersianVideoWorkflowError, match="must be attempted"):
        complete_phase("run", "prepare_inputs", pipeline_dir=tmp_path, now=BASE)
    state = record_phase_attempt("run", "prepare_inputs", pipeline_dir=tmp_path, now=BASE)
    with pytest.raises(PersianVideoWorkflowError, match="authoritative_script_sha256"):
        complete_phase("run", "prepare_inputs", pipeline_dir=tmp_path, now=BASE)
    state = complete_phase(
        "run", "prepare_inputs", evidence=_prepare_inputs_evidence(state),
        pipeline_dir=tmp_path, now=BASE,
    )
    assert state["next_phase"] == "align_script_timing"


def test_retry_budget_is_deterministic(tmp_path):
    _bootstrap(tmp_path)
    for expected in range(1, 5):
        state = record_phase_attempt("run", "prepare_inputs", pipeline_dir=tmp_path, now=BASE)
        assert state["attempts"]["prepare_inputs"] == expected
    with pytest.raises(PersianVideoWorkflowError, match="retry budget exhausted"):
        record_phase_attempt("run", "prepare_inputs", pipeline_dir=tmp_path, now=BASE)


def test_send_back_budget_and_resume_preserve_durable_counters(tmp_path):
    _bootstrap(tmp_path)
    state = record_phase_attempt("run", "prepare_inputs", pipeline_dir=tmp_path, now=BASE)
    complete_phase(
        "run", "prepare_inputs", evidence=_prepare_inputs_evidence(state),
        pipeline_dir=tmp_path, now=BASE,
    )
    state = request_send_back("run", "prepare_inputs", reason="revise", pipeline_dir=tmp_path, now=BASE)
    assert state["send_backs"] == 1
    assert state["attempts"]["prepare_inputs"] == 1
    state = record_phase_attempt("run", "prepare_inputs", pipeline_dir=tmp_path, now=BASE)
    complete_phase(
        "run", "prepare_inputs", evidence=_prepare_inputs_evidence(state),
        pipeline_dir=tmp_path, now=BASE,
    )
    state = request_send_back("run", "prepare_inputs", reason="revise again", pipeline_dir=tmp_path, now=BASE)
    assert state["send_backs"] == 2
    state = record_phase_attempt("run", "prepare_inputs", pipeline_dir=tmp_path, now=BASE)
    complete_phase(
        "run", "prepare_inputs", evidence=_prepare_inputs_evidence(state),
        pipeline_dir=tmp_path, now=BASE,
    )
    with pytest.raises(PersianVideoWorkflowError, match="send-back budget exhausted"):
        request_send_back("run", "prepare_inputs", reason="too many", pipeline_dir=tmp_path, now=BASE)

    calls = []
    resumed = resume_workflow(
        "run", pipeline_dir=tmp_path, backlot_opener=lambda pid: calls.append(pid) or 0,
        now=BASE + timedelta(hours=4),
    )
    assert calls == ["run"]
    assert resumed["send_backs"] == 2
    assert resumed["attempts"]["prepare_inputs"] == 3
    assert resumed["budget_window_started_at"] == (BASE + timedelta(hours=4)).isoformat()


def test_wall_time_expires_until_resume_starts_a_new_window(tmp_path):
    _bootstrap(tmp_path)
    expired = BASE + timedelta(minutes=46)
    with pytest.raises(PersianVideoWorkflowError, match="wall-time budget exceeded"):
        record_phase_attempt("run", "prepare_inputs", pipeline_dir=tmp_path, now=expired)
    resumed = resume_workflow("run", pipeline_dir=tmp_path, backlot_opener=lambda _: 0, now=expired)
    state = record_phase_attempt("run", "prepare_inputs", pipeline_dir=tmp_path, now=expired)
    assert state["attempts"]["prepare_inputs"] == 1
    assert resumed["budget_window_started_at"] == expired.isoformat()


def _bootstrap_to_assets(tmp_path: Path) -> None:
    _bootstrap(tmp_path)
    _advance_to(tmp_path, "acquire_assets")


def _asset_result(request: dict, *, candidates: int, downloaded_bytes: int, clips=None) -> dict:
    return {
        "output_dir": request["output_dir"],
        "resolved_sources": request["sources"],
        "max_candidates_total": request["max_candidates_total"],
        "max_bytes_per_clip": request["max_bytes_per_clip"],
        "max_total_download_bytes": request["max_total_download_bytes"],
        "candidates_considered": candidates,
        "bytes_downloaded": downloaded_bytes,
        "clips": list(clips or []),
    }


def _clip_file(tmp_path: Path, size: int, name: str = "clip.mp4") -> dict:
    path = tmp_path / "run" / "assets" / "clips" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    return {"path": str(path), "file_size_bytes": size}


def test_asset_request_enforces_fixed_sources_and_hard_ceilings(tmp_path):
    _bootstrap_to_assets(tmp_path)
    invalid_requests = [
        ({"sources": ["pexels"]}, "sources must be exactly"),
        ({"clips_per_query": 2}, "clips_per_query is fixed"),
        ({"max_candidates_total": 17}, "max_candidates_total"),
        ({"max_bytes_per_clip": 96 * 1024 * 1024 + 1}, "max_bytes_per_clip"),
        ({"max_total_download_bytes": 512 * 1024 * 1024 + 1}, "max_total_download_bytes"),
    ]
    for request, message in invalid_requests:
        with pytest.raises(PersianVideoWorkflowError, match=message):
            bounded_asset_search_request("run", request, retry_pass=0, pipeline_dir=tmp_path, now=BASE)
    with pytest.raises(PersianVideoWorkflowError, match="exceeds max"):
        bounded_asset_search_request("run", {}, retry_pass=2, pipeline_dir=tmp_path, now=BASE)
    with pytest.raises(PersianVideoWorkflowError, match="output_dir must stay inside"):
        bounded_asset_search_request(
            "run", {"output_dir": str(tmp_path / "outside")}, retry_pass=0,
            pipeline_dir=tmp_path, now=BASE,
        )

    bounded = bounded_asset_search_request("run", {}, retry_pass=0, pipeline_dir=tmp_path, now=BASE)
    assert bounded["output_dir"] == str((tmp_path / "run" / "assets").resolve())
    assert bounded["sources"] == ["pexels", "pixabay_video"]
    assert bounded["clips_per_query"] == 1
    assert bounded["max_candidates_total"] == 16
    assert bounded["max_bytes_per_clip"] == 96 * 1024 * 1024
    assert bounded["max_total_download_bytes"] == 512 * 1024 * 1024
    with pytest.raises(PersianVideoWorkflowError, match="pending result accounting"):
        bounded_asset_search_request("run", {}, retry_pass=0, pipeline_dir=tmp_path, now=BASE)
    record_phase_attempt("run", "acquire_assets", pipeline_dir=tmp_path, now=BASE)
    with pytest.raises(PersianVideoWorkflowError, match="result accounting"):
        complete_phase("run", "acquire_assets", pipeline_dir=tmp_path, now=BASE)


def test_asset_result_is_bound_to_issued_request_and_remaining_budget(tmp_path):
    _bootstrap_to_assets(tmp_path)
    with pytest.raises(PersianVideoWorkflowError, match="no matching issued request"):
        record_asset_search_result(
            "run", retry_pass=0, result_data={}, pipeline_dir=tmp_path, now=BASE,
        )

    first = bounded_asset_search_request(
        "run",
        {"max_candidates_total": 6, "max_total_download_bytes": 1000, "max_bytes_per_clip": 500},
        retry_pass=0, pipeline_dir=tmp_path, now=BASE,
    )
    assert first["max_candidates_total"] == 6

    wrong_output = _asset_result(first, candidates=1, downloaded_bytes=100)
    wrong_output["output_dir"] = str(tmp_path / "outside")
    with pytest.raises(PersianVideoWorkflowError, match="output_dir does not match"):
        record_asset_search_result(
            "run", retry_pass=0, result_data=wrong_output, pipeline_dir=tmp_path, now=BASE,
        )

    sibling_clip_path = tmp_path / "other" / "clip.mp4"
    sibling_clip_path.parent.mkdir(parents=True, exist_ok=True)
    sibling_clip_path.write_bytes(b"x" * 100)
    sibling_clip = {"path": str(sibling_clip_path), "file_size_bytes": 100}
    with pytest.raises(PersianVideoWorkflowError, match="must stay inside the current project"):
        record_asset_search_result(
            "run", retry_pass=0,
            result_data=_asset_result(
                first, candidates=1, downloaded_bytes=100, clips=[sibling_clip]
            ),
            pipeline_dir=tmp_path, now=BASE,
        )

    wrong_sources = _asset_result(first, candidates=1, downloaded_bytes=100)
    wrong_sources["resolved_sources"] = ["pexels"]
    with pytest.raises(PersianVideoWorkflowError, match="sources do not match"):
        record_asset_search_result(
            "run", retry_pass=0, result_data=wrong_sources, pipeline_dir=tmp_path, now=BASE,
        )
    wrong_limit = _asset_result(first, candidates=1, downloaded_bytes=100)
    wrong_limit["max_candidates_total"] = 7
    with pytest.raises(PersianVideoWorkflowError, match="does not match the issued request"):
        record_asset_search_result(
            "run", retry_pass=0, result_data=wrong_limit, pipeline_dir=tmp_path, now=BASE,
        )
    missing_counter = _asset_result(first, candidates=1, downloaded_bytes=100)
    del missing_counter["candidates_considered"]
    with pytest.raises(PersianVideoWorkflowError, match="requires integer"):
        record_asset_search_result(
            "run", retry_pass=0, result_data=missing_counter, pipeline_dir=tmp_path, now=BASE,
        )

    with pytest.raises(PersianVideoWorkflowError, match="candidate ceiling"):
        record_asset_search_result(
            "run", retry_pass=0,
            result_data=_asset_result(first, candidates=7, downloaded_bytes=900),
            pipeline_dir=tmp_path, now=BASE,
        )
    too_large_clip = _clip_file(tmp_path, 501, "too-large.mp4")
    with pytest.raises(PersianVideoWorkflowError, match="per-clip byte ceiling"):
        record_asset_search_result(
            "run", retry_pass=0,
            result_data=_asset_result(
                first, candidates=6, downloaded_bytes=900, clips=[too_large_clip]
            ),
            pipeline_dir=tmp_path, now=BASE,
        )
    with pytest.raises(PersianVideoWorkflowError, match="download-byte ceiling"):
        record_asset_search_result(
            "run", retry_pass=0,
            result_data=_asset_result(first, candidates=6, downloaded_bytes=1001),
            pipeline_dir=tmp_path, now=BASE,
        )
    valid_clip = _clip_file(tmp_path, 500, "valid.mp4")
    state = record_asset_search_result(
        "run", retry_pass=0,
        result_data=_asset_result(
            first, candidates=6, downloaded_bytes=900, clips=[valid_clip]
        ),
        pipeline_dir=tmp_path, now=BASE,
    )
    assert state["asset_usage"]["completed_passes"] == [0]
    assert "pending_pass" not in state["asset_usage"]

    second = bounded_asset_search_request("run", {}, retry_pass=1, pipeline_dir=tmp_path, now=BASE)
    assert second["max_candidates_total"] == 10
    assert second["max_total_download_bytes"] == 512 * 1024 * 1024 - 900
    record_asset_search_result(
        "run", retry_pass=1,
        result_data=_asset_result(second, candidates=0, downloaded_bytes=0),
        pipeline_dir=tmp_path, now=BASE,
    )
    with pytest.raises(PersianVideoWorkflowError, match="exceeds max"):
        bounded_asset_search_request("run", {}, retry_pass=2, pipeline_dir=tmp_path, now=BASE)


def test_second_asset_pass_is_sorted_by_scene_importance_order(tmp_path):
    _bootstrap(tmp_path)
    _advance_to(tmp_path, "plan_scenes_moments")
    record_phase_attempt("run", "plan_scenes_moments", pipeline_dir=tmp_path, now=BASE)
    complete_phase(
        "run", "plan_scenes_moments",
        evidence={"sourcing_order": ["event-high", "event-low"]},
        pipeline_dir=tmp_path, now=BASE,
    )

    first = bounded_asset_search_request("run", {}, retry_pass=0, pipeline_dir=tmp_path, now=BASE)
    record_asset_search_result(
        "run", retry_pass=0,
        result_data=_asset_result(first, candidates=0, downloaded_bytes=0),
        pipeline_dir=tmp_path, now=BASE,
    )
    second = bounded_asset_search_request(
        "run",
        {"queries": [
            {"query": "low alternate", "slot_id": "event-low", "kind": "video"},
            {"query": "high alternate", "slot_id": "event-high", "kind": "video"},
        ]},
        retry_pass=1, pipeline_dir=tmp_path, now=BASE,
    )
    assert [query["slot_id"] for query in second["queries"]] == ["event-high", "event-low"]


def test_second_asset_pass_rejects_slots_outside_scene_importance_order(tmp_path):
    _bootstrap(tmp_path)
    _advance_to(tmp_path, "plan_scenes_moments")
    record_phase_attempt("run", "plan_scenes_moments", pipeline_dir=tmp_path, now=BASE)
    complete_phase(
        "run", "plan_scenes_moments", evidence={"sourcing_order": ["event-1"]},
        pipeline_dir=tmp_path, now=BASE,
    )
    first = bounded_asset_search_request("run", {}, retry_pass=0, pipeline_dir=tmp_path, now=BASE)
    record_asset_search_result(
        "run", retry_pass=0, result_data=_asset_result(first, candidates=0, downloaded_bytes=0),
        pipeline_dir=tmp_path, now=BASE,
    )
    with pytest.raises(PersianVideoWorkflowError, match="absent from the scene sourcing_order"):
        bounded_asset_search_request(
            "run", {"queries": [{"query": "x", "slot_id": "other", "kind": "video"}]},
            retry_pass=1, pipeline_dir=tmp_path, now=BASE,
        )


def test_asset_actions_and_send_back_obey_session_wall_time(tmp_path):
    _bootstrap_to_assets(tmp_path)
    expired = BASE + timedelta(minutes=46)
    with pytest.raises(PersianVideoWorkflowError, match="wall-time budget exceeded"):
        bounded_asset_search_request("run", {}, retry_pass=0, pipeline_dir=tmp_path, now=expired)
    with pytest.raises(PersianVideoWorkflowError, match="wall-time budget exceeded"):
        request_send_back(
            "run", "prepare_inputs", reason="late", pipeline_dir=tmp_path, now=expired,
        )


def _write_final_review(project: Path, candidate: Path) -> Path:
    frame_dir = project / "artifacts" / "final-review-frames"
    frame_dir.mkdir(parents=True, exist_ok=True)
    frames = []
    for index in range(4):
        frame = frame_dir / f"frame-{index}.jpg"
        frame.write_bytes(b"frame")
        frames.append(str(frame))
    review = {
        "version": "1.0", "output_path": str(candidate), "status": "pass",
        "checks": {
            "technical_probe": {
                "valid_container": True, "duration_seconds": 12.0, "resolution": "1080x1920",
                "fps": 30.0, "has_audio": True, "codec": "h264",
                "file_size_bytes": candidate.stat().st_size, "issues": [],
            },
            "visual_spotcheck": {
                "frames_sampled": 4, "frame_paths": frames, "black_frames_detected": False,
                "broken_overlays": False, "missing_assets": False, "unreadable_text": False,
                "issues": [],
            },
            "audio_spotcheck": {
                "narration_present": True, "music_present": True, "unexpected_silence": False,
                "clipping_detected": False, "mix_intelligible": True, "issues": [],
            },
            "promise_preservation": {
                "delivery_promise_honored": True, "renderer_family_used": "persian-footage",
                "render_runtime_used": "remotion", "runtime_swap_detected": False,
                "runtime_swap_check": "ok — remotion", "motion_ratio_actual": 1.0,
                "silent_downgrade_detected": False, "issues": [],
            },
            "subtitle_check": {
                "subtitles_expected": False, "subtitles_present": False, "coverage_ratio": 0.0,
                "timing_drift_detected": False, "issues": [],
            },
        },
        "issues_found": [], "recommended_action": "present_to_user",
    }
    path = project / "artifacts" / "final_review.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(review), encoding="utf-8")
    return path


def _review_ready_project(tmp_path: Path) -> tuple[dict, Path, Path, dict]:
    _bootstrap(tmp_path)
    state = _advance_to(tmp_path, "final_review")
    project = tmp_path / "run"
    candidate = project / "renders" / "candidate.mp4"
    candidate.parent.mkdir(parents=True, exist_ok=True)
    candidate.write_bytes(b"candidate")
    review_path = _write_final_review(project, candidate)
    report = _report(candidate, review_ref=str(review_path))
    (project / "checkpoint_compose.json").write_text(
        json.dumps(_checkpoint(report)), encoding="utf-8"
    )
    state = record_phase_attempt("run", "final_review", pipeline_dir=tmp_path, now=BASE)
    return state, candidate, review_path, report


def _terminal_project(tmp_path: Path) -> tuple[dict, Path]:
    _, candidate, review_path, _ = _review_ready_project(tmp_path)
    state = complete_phase(
        "run", "final_review", evidence={"final_review_path": str(review_path)},
        pipeline_dir=tmp_path, now=BASE,
    )
    return state, candidate


def test_final_review_phase_requires_a_passing_artifact_and_semantic_review(tmp_path):
    _, candidate, review_path, report = _review_ready_project(tmp_path)
    review = json.loads(review_path.read_text(encoding="utf-8"))
    review["status"] = "revise"
    review["recommended_action"] = "revise_edit"
    review_path.write_text(json.dumps(review), encoding="utf-8")
    with pytest.raises(PersianVideoWorkflowError, match="must pass"):
        complete_phase(
            "run", "final_review", evidence={"final_review_path": str(review_path)},
            pipeline_dir=tmp_path, now=BASE,
        )

    review["status"] = "pass"
    review["recommended_action"] = "present_to_user"
    review_path.write_text(json.dumps(review), encoding="utf-8")
    report["silent_watch_audit"]["conclusion_understood"] = False
    (tmp_path / "run" / "checkpoint_compose.json").write_text(
        json.dumps(_checkpoint(report)), encoding="utf-8"
    )
    with pytest.raises(PersianVideoWorkflowError, match="conclusion_understood"):
        complete_phase(
            "run", "final_review", evidence={"final_review_path": str(review_path)},
            pipeline_dir=tmp_path, now=BASE,
        )


def test_final_review_rejects_retention_problems_and_weak_hook(tmp_path):
    _, _, review_path, report = _review_ready_project(tmp_path)
    report["retention_audit"]["problems"] = ["weak opening"]
    (tmp_path / "run" / "checkpoint_compose.json").write_text(
        json.dumps(_checkpoint(report)), encoding="utf-8"
    )
    with pytest.raises(PersianVideoWorkflowError, match="blocking problems"):
        complete_phase(
            "run", "final_review", evidence={"final_review_path": str(review_path)},
            pipeline_dir=tmp_path, now=BASE,
        )

    report["retention_audit"]["problems"] = []
    report["hook_strength"] = "weak"
    (tmp_path / "run" / "checkpoint_compose.json").write_text(
        json.dumps(_checkpoint(report)), encoding="utf-8"
    )
    with pytest.raises(PersianVideoWorkflowError, match="hook_strength"):
        complete_phase(
            "run", "final_review", evidence={"final_review_path": str(review_path)},
            pipeline_dir=tmp_path, now=BASE,
        )


def test_burned_caption_review_requires_real_entry_mid_exit_frames(tmp_path):
    _, _, review_path, report = _review_ready_project(tmp_path)
    report["caption_mode"] = "hybrid"
    report["caption_verification_frames"] = []
    (tmp_path / "run" / "checkpoint_compose.json").write_text(
        json.dumps(_checkpoint(report)), encoding="utf-8"
    )
    with pytest.raises(PersianVideoWorkflowError, match="caption_verification_frames"):
        complete_phase(
            "run", "final_review", evidence={"final_review_path": str(review_path)},
            pipeline_dir=tmp_path, now=BASE,
        )

    frames = []
    for name in ("caption-entry.jpg", "caption-mid.jpg", "caption-exit.jpg"):
        frame = tmp_path / "run" / "artifacts" / name
        frame.write_bytes(b"caption")
        frames.append(str(frame))
    report["caption_verification_frames"] = frames
    (tmp_path / "run" / "checkpoint_compose.json").write_text(
        json.dumps(_checkpoint(report)), encoding="utf-8"
    )
    state = complete_phase(
        "run", "final_review", evidence={"final_review_path": str(review_path)},
        pipeline_dir=tmp_path, now=BASE,
    )
    assert state["next_phase"] == "awaiting_human"


def test_awaiting_human_refuses_review_artifact_changed_after_validation(tmp_path):
    state, candidate = _terminal_project(tmp_path)
    review_path = Path(state["evidence"]["final_review"]["final_review_path"])
    review = json.loads(review_path.read_text(encoding="utf-8"))
    review["issues_found"] = ["mutated after validation"]
    review_path.write_text(json.dumps(review), encoding="utf-8")
    with pytest.raises(PersianVideoWorkflowError, match="changed after"):
        complete_phase("run", "awaiting_human", pipeline_dir=tmp_path, now=BASE)


def test_terminal_rejects_missing_or_non_compose_checkpoint(tmp_path, monkeypatch):
    _terminal_project(tmp_path)
    monkeypatch.setattr(workflow, "read_checkpoint", lambda *args: None)
    with pytest.raises(PersianVideoWorkflowError, match="compose checkpoint is required"):
        complete_phase("run", "awaiting_human", pipeline_dir=tmp_path, now=BASE)

    candidate = tmp_path / "run" / "renders" / "candidate.mp4"
    monkeypatch.setattr(
        workflow, "read_checkpoint",
        lambda *args: _checkpoint(_report(candidate), stage="edit"),
    )
    with pytest.raises(PersianVideoWorkflowError, match="stage='compose'"):
        complete_phase("run", "awaiting_human", pipeline_dir=tmp_path, now=BASE)


def test_terminal_requires_unapproved_human_gate(tmp_path, monkeypatch):
    _, candidate = _terminal_project(tmp_path)
    monkeypatch.setattr(
        workflow, "read_checkpoint",
        lambda *args: _checkpoint(_report(candidate), human_approval_required=False),
    )
    with pytest.raises(PersianVideoWorkflowError, match="must require human approval"):
        complete_phase("run", "awaiting_human", pipeline_dir=tmp_path, now=BASE)

    monkeypatch.setattr(
        workflow, "read_checkpoint",
        lambda *args: _checkpoint(_report(candidate), status="completed"),
    )
    with pytest.raises(PersianVideoWorkflowError, match="status='awaiting_human'"):
        complete_phase("run", "awaiting_human", pipeline_dir=tmp_path, now=BASE)

    monkeypatch.setattr(
        workflow, "read_checkpoint",
        lambda *args: _checkpoint(_report(candidate), human_approved=True),
    )
    with pytest.raises(PersianVideoWorkflowError, match="remain unapproved"):
        complete_phase("run", "awaiting_human", pipeline_dir=tmp_path, now=BASE)


def test_terminal_rejects_outside_missing_digest_and_hash_mismatch(tmp_path, monkeypatch):
    _, candidate = _terminal_project(tmp_path)
    outside = tmp_path / "outside.mp4"
    outside.write_bytes(b"outside")
    monkeypatch.setattr(workflow, "read_checkpoint", lambda *args: _checkpoint(_report(outside)))
    with pytest.raises(PersianVideoWorkflowError, match="must live inside"):
        complete_phase("run", "awaiting_human", pipeline_dir=tmp_path, now=BASE)
    missing = _report(candidate)
    del missing["outputs"][0]["sha256"]
    monkeypatch.setattr(workflow, "read_checkpoint", lambda *args: _checkpoint(missing))
    with pytest.raises(PersianVideoWorkflowError, match="64-character sha256"):
        complete_phase("run", "awaiting_human", pipeline_dir=tmp_path, now=BASE)

    mismatch = _report(candidate, digest="b" * 64)
    monkeypatch.setattr(workflow, "read_checkpoint", lambda *args: _checkpoint(mismatch))
    with pytest.raises(PersianVideoWorkflowError, match="does not match the exact MP4 bytes"):
        complete_phase("run", "awaiting_human", pipeline_dir=tmp_path, now=BASE)

    wrong_format = _report(candidate, fmt="mov")
    monkeypatch.setattr(workflow, "read_checkpoint", lambda *args: _checkpoint(wrong_format))
    with pytest.raises(PersianVideoWorkflowError, match="reported MP4 path"):
        complete_phase("run", "awaiting_human", pipeline_dir=tmp_path, now=BASE)


def test_valid_digest_bound_candidate_stops_workflow_at_awaiting_human(tmp_path, monkeypatch):
    _, candidate = _terminal_project(tmp_path)
    digest = hashlib.sha256(candidate.read_bytes()).hexdigest()
    monkeypatch.setattr(workflow, "read_checkpoint", lambda *args: _checkpoint(_report(candidate, digest=digest)))
    state = complete_phase("run", "awaiting_human", pipeline_dir=tmp_path, now=BASE)
    assert state["status"] == "awaiting_human"
    assert state["next_phase"] is None
    assert state["completed_phases"] == list(PHASES)
    assert state["evidence"]["awaiting_human"]["candidate_sha256"] == digest
    with pytest.raises(PersianVideoWorkflowError, match="already stopped"):
        complete_phase("run", "awaiting_human", pipeline_dir=tmp_path, now=BASE)
    with pytest.raises(PersianVideoWorkflowError, match="already stopped"):
        request_send_back(
            "run", "prepare_inputs", reason="revise", pipeline_dir=tmp_path, now=BASE,
        )
    with pytest.raises(PersianVideoWorkflowError, match="next phase"):
        record_phase_attempt("run", "prepare_inputs", pipeline_dir=tmp_path, now=BASE)


def test_cli_bootstrap_inputs_are_production_only(tmp_path):
    parser = workflow.build_parser()
    args = parser.parse_args([
        "bootstrap", "--title", "Run", "--narration", "/tmp/n.wav",
        "--approved-script", "متن",
    ])
    assert workflow._bootstrap_inputs(args) == ("/tmp/n.wav", "متن")

    script_file = tmp_path / "approved.txt"
    script_file.write_text("متن فایل", encoding="utf-8")
    args = parser.parse_args([
        "bootstrap", "--title", "Run", "--approved-script-file", str(script_file),
    ])
    assert workflow._bootstrap_inputs(args) == (None, "متن فایل")

    args = parser.parse_args(["bootstrap", "--title", "Run", "--narration", "/tmp/n.wav"])
    assert workflow._bootstrap_inputs(args) == ("/tmp/n.wav", None)

    args = parser.parse_args(["bootstrap", "--title", "Run"])
    with pytest.raises(PersianVideoWorkflowError, match="bootstrap requires"):
        workflow._bootstrap_inputs(args)

    for retired in ("--raw-text", "--raw-text-file", "--english-article", "--english-article-file"):
        with pytest.raises(SystemExit):
            parser.parse_args(["bootstrap", "--title", "Run", retired, "x"])


def test_script_first_project_can_attach_narration_before_preparation(tmp_path):
    state, _ = _bootstrap(tmp_path, narration_path=None)
    assert state["input"]["mode"] == "approved_script_only"
    audio = tmp_path.parent / f"{tmp_path.name}-recorded.wav"
    audio.write_bytes(b"voice")

    state = attach_narration("run", str(audio), pipeline_dir=tmp_path)
    assert state["input"]["mode"] == "approved_script_with_narration"
    assert state["input"]["script_authority"] == "approved_script"
    stored = Path(state["input"]["narration"]["source_path"])
    assert stored == (tmp_path / "run" / "inputs" / "narration.wav").resolve()
    assert stored.read_bytes() == b"voice"

    with pytest.raises(PersianVideoWorkflowError, match="already has narration"):
        attach_narration("run", str(audio), pipeline_dir=tmp_path)


def test_front_door_skill_is_production_only_and_links_canonical_contracts():
    front = (ROOT / "skills" / "persian-video" / "SKILL.md").read_text(encoding="utf-8")
    for flag in ("--narration", "--approved-script-file", "attach-narration"):
        assert flag in front
    for retired in ("--raw-text", "--english-article", "author_persian_narration", "translate_and_author"):
        assert retired not in front
    for capability in (
        "prepare-production-inputs.md",
        "narration-to-persian-video.md",
        "persian-final-review.md",
    ):
        assert capability in front
    for contract in (
        "pipeline_defs/persian-footage.yaml",
        "skills/pipelines/persian-footage/executive-producer.md",
        "skills/pipelines/persian-footage/subtitle-alignment.md",
        "skills/pipelines/persian-footage/final-candidate-protocol.md",
        "skills/meta/checkpoint-protocol.md",
    ):
        assert contract in front
    assert "Do not reproduce or reorder its phase list in prose" in front
    assert "does not write, translate, improve, or rewrite narration" in front
    assert "Do not create a project for a text-only request" in front
    for duplicated_rule in ("7-9 designed moments", "0.9s of empty frame", "55% text coverage"):
        assert duplicated_rule not in front


def test_front_door_is_discoverable_from_index_and_agent_guide():
    index = (ROOT / "skills" / "INDEX.md").read_text(encoding="utf-8")
    guide = (ROOT / "AGENT_GUIDE.md").read_text(encoding="utf-8")
    for document in (index, guide):
        assert "skills/persian-video/SKILL.md" in document
        assert "approved Persian script" in document
        assert "raw text, or an English article" not in document
    assert "lib/persian_video_workflow.py" in guide
    assert "bounded workflow envelope" in guide
