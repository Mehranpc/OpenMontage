from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

import lib.persian_edit_workspace as edit_workspace
import lib.persian_preflight as preflight
from lib.persian_edit_contract import collect_persian_edit_diagnostics
from lib.persian_edit_workspace import preflight_edit_draft, stage_edit_draft
from lib.persian_recovery_policy import recovery_policy_for_issue
from lib.persian_video_workflow import (
    load_workflow_state,
    record_phase_attempt,
    record_phase_failure,
    record_recovery_attempt,
    request_send_back,
)
from tests.lib.test_persian_hook_quality_controls import _hook
from tests.lib.test_persian_preflight_contract import _payload
from tests.lib.test_persian_video_workflow import BASE, _advance_to, _bootstrap


def test_missing_topic_anchor_emits_named_bounded_recovery_before_browser(monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"fixture")
    payload = _payload(str(source))
    payload["persian"]["typographicBeats"] = [
        {"id": "opening-plate", "startSeconds": 0.2, "endSeconds": 4.2}
    ]
    payload["persian"]["moments"][0]["segments"] = [
        {"role": "hero", "text": "فقط وقت تلف کردنه؟"}
    ]
    hook = _hook()
    hook["semanticIntegrity"] = {
        "sourceText": "بازی فقط وقت تلف کردنه؟",
        "requiredTopicAnchors": ["بازی"],
        "anchorDelivery": "text",
    }
    payload["metadata"] = {"target_platform": "instagram-reels", "hookQuality": hook}

    monkeypatch.setattr(
        preflight.NoCopyPersianCompose,
        "_build_props",
        lambda *_args, **_kwargs: pytest.fail("browser must not run after semantic refusal"),
    )
    report = preflight.aggregate_preflight_edit_decisions(payload, base_dir=tmp_path)

    issue = next(item for item in report["blockingIssues"] if item["code"] == "HOOK_TOPIC_ANCHOR_MISSING")
    assert issue["recoveryClass"] == "HOOK_SEMANTIC"
    assert issue["recoveryPlan"]["maxAttempts"] == 2
    assert issue["recoveryPlan"]["strategies"][0] == "restore_required_topic_anchor_in_viewer_visible_hook"
    assert report["recoveryBudgets"]["HOOK_SEMANTIC"] == 2


def test_named_caption_handoff_failure_maps_to_caption_continuity(monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"fixture")
    payload = _payload(str(source))
    monkeypatch.setattr(preflight, "collect_persian_edit_diagnostics", lambda *_a, **_k: [])
    monkeypatch.setattr(preflight, "audit_persian_retention", lambda _p: {"problems": []})
    monkeypatch.setattr(
        preflight,
        "audit_persian_hook_quality",
        lambda _p: {"version": "2.0", "required": False, "problems": [], "advisories": []},
    )
    monkeypatch.setattr(
        preflight,
        "browser_preflight_edit_decisions",
        lambda *_a, **_k: (_ for _ in ()).throw(
            ValueError("[CAPTION_HANDOFF_FRAGMENT] first burned caption starts mid-sentence")
        ),
    )

    report = preflight.aggregate_preflight_edit_decisions(payload, base_dir=tmp_path)

    issue = report["blockingIssues"][0]
    assert issue["code"] == "CAPTION_HANDOFF_FRAGMENT"
    assert issue["recoveryClass"] == "CAPTION_CONTINUITY"
    assert issue["recoveryPlan"]["maxAttempts"] == 2


def test_frame_grid_gap_is_a_named_pre_render_contract_failure(tmp_path: Path) -> None:
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"fixture")
    payload = _payload(str(source))
    payload["persian"]["platformTarget"] = "instagram-reels"
    payload["persian"]["shots"][0]["endSeconds"] = 11.96

    diagnostics = collect_persian_edit_diagnostics(payload, base_dir=tmp_path)

    gap = next(item for item in diagnostics if item.code == "TIMELINE_FRAME_GAP")
    assert "1 frame" in gap.message or "1-frame" in gap.message
    plan = recovery_policy_for_issue({"code": gap.code})
    assert plan["recoveryClass"] == "TIMELINE_GRID"
    assert plan["maxAttempts"] == 1


def test_same_edit_digest_reuses_persisted_preflight_without_recomputing(monkeypatch, tmp_path: Path) -> None:
    project = tmp_path / "project"
    payload = _payload()
    calls = 0

    def fake_preflight(edit, *, base_dir=None, precomputed_components=None):
        del precomputed_components
        nonlocal calls
        calls += 1
        digest = edit_workspace.artifact_sha256(edit)
        return {
            "version": 1,
            "policyVersion": preflight.PREFLIGHT_POLICY_VERSION,
            "ok": True,
            "status": "pass",
            "artifactSha256": digest,
            "blockingIssues": [],
            "recoveryBudgets": {},
            "warnings": [],
            "watermarkDiagnostics": None,
            "nextActions": [],
            "diagnosticLayers": ["browser"],
            "mediaCopies": 0,
            "evidence": {},
        }

    monkeypatch.setattr(edit_workspace, "aggregate_preflight_edit_decisions", fake_preflight)
    stage_edit_draft(project, "attempt-1", payload)
    first = preflight_edit_draft(project, "attempt-1")
    stage_edit_draft(project, "attempt-2", payload)
    second = preflight_edit_draft(project, "attempt-2")

    assert calls == 1
    assert first["cacheHit"] is False
    assert second["cacheHit"] is True
    assert second["cacheKey"] == first["cacheKey"]
    assert second["attemptId"] == "attempt-2"


def test_recovery_class_exhaustion_stops_cleanly_until_user_revision(tmp_path: Path) -> None:
    _bootstrap(tmp_path)
    _advance_to(tmp_path, "no_copy_preflight")
    strategy = "restore_required_topic_anchor_in_viewer_visible_hook"

    for _ in range(2):
        state = record_recovery_attempt(
            "run",
            diagnostic_code="HOOK_TOPIC_ANCHOR_MISSING",
            strategy=strategy,
            pipeline_dir=tmp_path,
            now=BASE,
        )
        assert state["status"] == "active"
    stopped = record_recovery_attempt(
        "run",
        diagnostic_code="HOOK_TOPIC_ANCHOR_MISSING",
        strategy=strategy,
        pipeline_dir=tmp_path,
        now=BASE,
    )

    assert stopped["status"] == "needs_revision"
    assert stopped["next_phase"] is None
    assert stopped["recovery_stop"]["outcome"] == "needs_human_editorial_revision"
    assert stopped["recovery_stop"]["attemptsUsed"] == 2

    reopened = request_send_back(
        "run",
        "no_copy_preflight",
        reason="user approved a new editorial recovery cycle",
        pipeline_dir=tmp_path,
        now=BASE + timedelta(minutes=1),
        user_directed_revision=True,
    )
    assert reopened["status"] == "active"
    assert reopened["next_phase"] == "no_copy_preflight"
    assert reopened["recovery_attempts"] == {}
    assert reopened.get("recovery_stop") is None


def test_preflight_phase_slo_is_recorded_without_weakening_correctness(tmp_path: Path) -> None:
    _bootstrap(tmp_path)
    _advance_to(tmp_path, "no_copy_preflight")
    record_phase_attempt("run", "no_copy_preflight", pipeline_dir=tmp_path, now=BASE)
    failed = record_phase_failure(
        "run",
        "no_copy_preflight",
        reason="synthetic long preflight",
        pipeline_dir=tmp_path,
        now=BASE + timedelta(seconds=301),
    )

    entry = failed["phase_telemetry"]["no_copy_preflight"][-1]
    assert entry["outcome"] == "failed"
    assert entry["slo_seconds"] == 300
    assert entry["slo_exceeded"] is True
    persisted = load_workflow_state("run", pipeline_dir=tmp_path)
    assert persisted["performance_slo"]["endToEndSeconds"] == 2700
    assert persisted["next_phase"] == "no_copy_preflight"
