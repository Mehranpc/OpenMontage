from datetime import datetime, timedelta, timezone
from pathlib import Path

from lib import persian_video_workflow as workflow
from lib import persian_workflow_telemetry as telemetry

BASE = datetime(2026, 9, 24, 7, 30, tzinfo=timezone.utc)


def _fresh_project(tmp_path: Path) -> Path:
    root = tmp_path / "projects"
    narration = tmp_path / "narration.wav"
    narration.write_bytes(b"audio")
    workflow.bootstrap_persian_video(
        title="p4 telemetry",
        narration_path=str(narration),
        approved_script="متن تأییدشده",
        project_id="run",
        pipeline_dir=root,
        backlot_opener=lambda _project_id: 0,
        now=BASE,
    )
    return root


def test_agent_interphase_is_measured_without_starting_next_phase_attempt(tmp_path: Path) -> None:
    projects_root = _fresh_project(tmp_path)
    before = workflow.load_workflow_state("run", pipeline_dir=projects_root)
    assert before["next_phase"] == "prepare_inputs"
    assert before["attempts"] == {}

    span = workflow.start_explicit_work_span(
        "run",
        category="agent_interphase",
        name="inspect inputs before prepare phase",
        pipeline_dir=projects_root,
        now=BASE + timedelta(seconds=5),
    )
    during = workflow.load_workflow_state("run", pipeline_dir=projects_root)
    assert during["attempts"] == {}
    assert span["category"] == "agent_interphase"
    assert span["parent_span_id"] == during["causal_telemetry"]["run_span_id"]
    assert span["phase"] == "prepare_inputs"
    assert span["measurement_scope"] == "interphase"

    workflow.finish_explicit_work_span(
        "run", span["span_id"], pipeline_dir=projects_root,
        now=BASE + timedelta(seconds=20),
    )
    final = workflow.load_workflow_state("run", pipeline_dir=projects_root)
    accounting = workflow.phase_time_accounting(final, now=BASE + timedelta(seconds=20))
    assert accounting["agent_interphase_seconds"] == 15.0
    assert accounting["causal_covered_seconds"] == 15.0
    assert accounting["unattributed_wall_seconds"] == 5.0
    assert accounting["causal_coverage_percent"] == 75.0


def test_bootstrap_records_execution_environment_and_cache_state(tmp_path: Path) -> None:
    projects_root = _fresh_project(tmp_path)
    state = workflow.load_workflow_state("run", pipeline_dir=projects_root)
    metadata = state["execution_metadata"]

    assert len(metadata["code_revision"]) == 40
    assert metadata["runtime"]["python_version"]
    assert metadata["runtime"]["python_implementation"]
    assert metadata["runtime"]["node_version"]
    assert metadata["runtime"]["remotion_version"]
    assert metadata["runtime"]["ffmpeg_version"]
    assert metadata["hardware"]["system"]
    assert metadata["hardware"]["machine"]
    assert metadata["hardware"]["logical_cpu_count"] >= 1
    assert metadata["cache"]["classification"] in {"warm", "cold"}
    assert metadata["cache"]["project_preflight_entries"] == 0
    assert metadata["cache"]["project_search_entries"] == 0
    assert metadata["ad_hoc_script_count"] == 0


def test_execution_metadata_refresh_detects_project_cache_and_ad_hoc_scripts(tmp_path: Path) -> None:
    projects_root = _fresh_project(tmp_path)
    project = projects_root / "run"
    (project / ".preflight" / "cache" / "edit").mkdir(parents=True)
    (project / ".preflight" / "cache" / "edit" / "one.json").write_text("{}")
    (project / "assets" / ".search-cache").mkdir(parents=True)
    (project / "assets" / ".search-cache" / "one.json").write_text("{}")
    (project / ".workspace").mkdir(parents=True)
    (project / ".workspace" / "ad_hoc.py").write_text("print('legacy')\n")

    snapshot = telemetry.collect_execution_metadata(
        repo_root=workflow.REPO_ROOT,
        project_root=project,
    )
    assert snapshot["cache"]["classification"] == "warm"
    assert snapshot["cache"]["project_preflight_entries"] == 1
    assert snapshot["cache"]["project_search_entries"] == 1
    assert snapshot["ad_hoc_script_count"] == 1


def test_performance_summary_refreshes_execution_metadata_at_report_time(tmp_path: Path) -> None:
    projects_root = _fresh_project(tmp_path)
    project = projects_root / "run"
    (project / "assets" / ".search-cache").mkdir(parents=True)
    (project / "assets" / ".search-cache" / "late.json").write_text("{}")
    (project / ".workspace").mkdir(parents=True)
    (project / ".workspace" / "late.py").write_text("print('late')\n")

    state = workflow.load_workflow_state("run", pipeline_dir=projects_root)
    workflow._freeze_performance_summary(state, now=BASE + timedelta(seconds=30))
    latest = state["performance_summary"]["execution_metadata"]
    assert latest["cache"]["classification"] == "warm"
    assert latest["cache"]["project_search_entries"] == 1
    assert latest["ad_hoc_script_count"] == 1


def test_status_exposes_pinned_start_execution_metadata(tmp_path: Path) -> None:
    projects_root = _fresh_project(tmp_path)
    state = workflow.load_workflow_state("run", pipeline_dir=projects_root)
    status = workflow.workflow_status("run", pipeline_dir=projects_root, now=BASE)
    assert status["execution_metadata"] == state["execution_metadata"]


def test_shared_clip_cache_classification_uses_real_manifest_entries(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path / "project"
    project.mkdir()
    cache = tmp_path / "shared-cache"
    cache.mkdir()
    monkeypatch.setenv("OPENMONTAGE_CACHE_DIR", str(cache))
    (cache / "cache_manifest.lock").write_text("")
    (cache / "cache_manifest.jsonl").write_text("")

    cold = telemetry.collect_execution_metadata(repo_root=workflow.REPO_ROOT, project_root=project)
    assert cold["cache"]["shared_clip_entries"] == 0
    assert cold["cache"]["classification"] == "cold"

    (cache / "cache_manifest.jsonl").write_text(
        '{"clip_id":"pexels_1","file_name":"pexels_1.mp4","size_bytes":10,"added_at":1,"last_access_at":1}\n'
    )
    warm = telemetry.collect_execution_metadata(repo_root=workflow.REPO_ROOT, project_root=project)
    assert warm["cache"]["shared_clip_entries"] == 1
    assert warm["cache"]["classification"] == "warm"
