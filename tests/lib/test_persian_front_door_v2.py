from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import lib.persian_edit_workspace as edit_workspace
from lib.persian_hook_quality import audit_persian_hook_quality
from lib.persian_moments import audit_moments, build_moments
from lib.persian_edit_workspace import artifact_sha256
import scripts.persian_reels_local_e2e as e2e


def _fake_alignment(*_args, **_kwargs):
    return {
        "word_timestamps": e2e._fixture_words(),
        "model": "fixture-word-timing",
        "provider": "fixture",
        "alignment_mode": "timing_oriented",
        "heavy_recovery_used": False,
    }


def _fake_clips(project: Path) -> dict[str, Path]:
    target = project / "assets" / "video"
    target.mkdir(parents=True, exist_ok=True)
    clips: dict[str, Path] = {}
    for index, event in enumerate(e2e._events(), start=1):
        path = target / f"event-{index}.mp4"
        path.write_bytes(b"fixture-video" * 200)
        clips[str(event["id"])] = path
    return clips


def _fake_aggregate(payload: dict, *, base_dir=None) -> dict:
    audit = audit_persian_hook_quality(payload)
    assert audit["required"] is True
    assert audit["problems"] == []
    return {
        "version": 1,
        "ok": True,
        "status": "pass",
        "artifactSha256": artifact_sha256(payload),
        "blockingIssues": [],
        "warnings": [],
        "watermarkDiagnostics": None,
        "nextActions": [],
        "diagnosticLayers": ["contract", "retention", "hook", "browser"],
        "mediaCopies": 0,
        "evidence": {
            "retentionAudit": {"problems": [], "advisories": []},
            "hookQualityAudit": audit,
        },
    }


def _fake_compose(_self, inputs: dict):
    candidate = Path(inputs["output_path"])
    candidate.parent.mkdir(parents=True, exist_ok=True)
    payload = b"opening-candidate" if inputs.get("frames") else b"rendered-candidate"
    candidate.write_bytes(payload * 500)
    subtitle = candidate.with_suffix(".srt")
    subtitle.write_text(
        "1\n00:00:00,000 --> 00:00:03,000\nشروع با یک تغییر کوچک روشن می‌شود.\n",
        encoding="utf-8",
    )
    return SimpleNamespace(
        success=True,
        error=None,
        data={
            "composition_id": "PersianSubtitleVideo",
            "duration_seconds": 10.5,
            "shot_count": 4,
            "moment_count": 1,
            "text_coverage": 0.30,
            "caption_mode": "hybrid",
            "burned_caption_count": 3,
            "subtitle_path": str(subtitle),
            "subtitle_advisories": [],
            "attributions": [e2e.DISCLAIMER],
            "post_render_motion_qa": {
                "passed": True,
                "sampleFps": 2.0,
                "nearStaticDeltaMax": 1.0,
                "warningRunSeconds": 7.0,
                "failRunSeconds": 9.0,
                "deltas": [],
                "warnRuns": [],
                "failRuns": [],
                "elapsedSeconds": 0.1,
            },
            "luminance_qa": {"passed": True},
        },
    )


def _fake_extract(_candidate: Path, target: Path, times: list[float], prefix: str) -> list[str]:
    target.mkdir(parents=True, exist_ok=True)
    paths = []
    for index, _seconds in enumerate(times, start=1):
        path = target / f"{prefix}-{index}.jpg"
        path.write_bytes(b"frame")
        paths.append(str(path))
    return paths


def test_full_front_door_reaches_awaiting_human_with_opening_gate_and_mastering(monkeypatch, tmp_path: Path) -> None:
    compose_calls: list[str] = []
    master_calls: list[str] = []

    def assert_phase_running(phase: str) -> None:
        state = e2e.load_workflow_state(e2e.PROJECT_ID, pipeline_dir=tmp_path)
        entry = state["phase_telemetry"][phase][-1]
        assert entry["outcome"] == "running"
        assert entry["finished_at"] is None

    def fake_narration(work: Path) -> Path:
        path = work / "narration.wav"
        path.write_bytes(b"fixture-audio" * 200)
        return path

    def fake_alignment(*args, **kwargs):
        assert_phase_running("align_script_timing")
        return _fake_alignment(*args, **kwargs)

    def fake_aggregate(payload: dict, *, base_dir=None) -> dict:
        assert_phase_running("no_copy_preflight")
        return _fake_aggregate(payload, base_dir=base_dir)

    def fake_compose(self, inputs: dict):
        if inputs.get("frames"):
            assert_phase_running("render_opening_candidate")
            compose_calls.append("opening")
        else:
            assert_phase_running("render_final_candidate")
            state = e2e.load_workflow_state(e2e.PROJECT_ID, pipeline_dir=tmp_path)
            assert "opening_review" in state["completed_phases"]
            compose_calls.append("full")
        return _fake_compose(self, inputs)

    def fake_master(source: Path, output: Path) -> dict:
        assert_phase_running("master_final_candidate")
        master_calls.append("master")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(source.read_bytes() + b"-mastered")
        return {
            "policyVersion": "1.0",
            "inputPath": str(source),
            "inputSha256": e2e._sha(source),
            "candidatePath": str(output),
            "candidateSha256": e2e._sha(output),
            "reencoded": True,
            "reused": False,
            "outputIntegratedLufs": -16.0,
            "truePeakDbfs": -1.6,
        }

    def fake_extract(candidate: Path, target: Path, times: list[float], prefix: str) -> list[str]:
        expected = "opening_review" if prefix.startswith("opening") else "final_review"
        assert_phase_running(expected)
        return _fake_extract(candidate, target, times, prefix)

    monkeypatch.setattr(e2e, "_make_narration", fake_narration)
    monkeypatch.setattr(e2e, "_transcribe", fake_alignment)
    monkeypatch.setattr(e2e, "_align_timing", fake_alignment, raising=False)
    monkeypatch.setattr(e2e, "_make_synthetic_clips", _fake_clips)
    monkeypatch.setattr(edit_workspace, "aggregate_preflight_edit_decisions", fake_aggregate)
    monkeypatch.setattr(e2e.ScriptAlignedPersianCompose, "execute", fake_compose)
    monkeypatch.setattr(e2e, "master_final_candidate", fake_master, raising=False)
    monkeypatch.setattr(
        e2e,
        "_probe",
        lambda _candidate: {
            "streams": [
                {"codec_type": "video", "codec_name": "h264", "width": 1080, "height": 1920},
                {"codec_type": "audio", "codec_name": "aac"},
            ],
            "format": {"duration": "10.5"},
        },
    )
    monkeypatch.setattr(e2e, "_extract_frames", fake_extract)
    monkeypatch.setattr(
        e2e,
        "measure_rendered_audio_output",
        lambda candidate: {
            "policyVersion": "1.0",
            "measurementSource": "rendered_mp4",
            "candidateSha256": e2e._sha(candidate),
            "outputIntegratedLufs": -16.0,
            "truePeakDbfs": -1.6,
        },
        raising=False,
    )

    result = e2e.run_local(tmp_path)

    assert compose_calls == ["opening", "full"]
    assert master_calls == ["master"]
    assert result["workflow_status"] == "awaiting_human"
    assert result["next_phase"] is None
    assert result["alignment_policy"]["mode"] == "timing_oriented"
    assert result["alignment_policy"]["heavyTranscriptionRecoveryOnly"] is True
    assert result["preflight_report_path"]
    assert result["opening_review_path"]
    assert result["final_review_path"]
    assert result["candidate_sha256"] == result["mastering"]["candidateSha256"]


def test_local_e2e_opening_shot_and_typography_carry_film_type_contract(tmp_path: Path) -> None:
    narration = tmp_path / "narration.wav"
    narration.write_bytes(b"audio")
    clips = _fake_clips(tmp_path)
    edit = e2e._edit_decisions(narration, e2e._fixture_words(), clips)
    opening = edit["persian"]["shots"][0]

    assert opening["showsSubject"] is True
    assert opening["semanticRole"] == "hook_subject"
    assert opening["semanticDirection"]
    assert opening["openingSemanticMatch"] is True
    assert opening["selectionReason"]
    hook = edit["persian"]["moments"][0]
    assert hook["kind"] == "hook"
    assert [segment["role"] for segment in hook["segments"]] == ["lead", "hero", "tail"]
    assert hook["purpose"] == "hook-pattern-interrupt"
    assert "accentWords" not in hook["segments"][1]
    assert hook["presentation"]["recipeId"] == "editorial-hero-balanced"

    built = build_moments(edit["persian"]["moments"])
    audit = audit_moments(
        built,
        duration_seconds=float(edit["persian"]["durationSeconds"]),
        v2=True,
        adaptive_pixel_typography=True,
    )
    assert audit.problems == []
