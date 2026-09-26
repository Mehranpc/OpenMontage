import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

import lib.persian_video_workflow as workflow
from lib.persian_recovery_policy import shot_local_recovery_plan
from lib.persian_video_workflow import (
    PHASES,
    PersianVideoWorkflowError,
    bootstrap_persian_video,
    bounded_asset_search_request,
    complete_phase,
    load_workflow_state,
    record_phase_attempt,
    request_send_back,
)

BASE = datetime(2026, 9, 24, 9, 0, tzinfo=timezone.utc)


def _edit() -> dict:
    return {
        "version": "2.1",
        "persian": {
            "shots": [
                {"id": "shot-1", "visualEventId": "event-1"},
                {"id": "shot-2", "visualEventId": "event-2"},
            ]
        },
    }


def _candidate(
    candidate_id: str,
    source_id: str,
    *,
    disposition: str = "reviewed",
    crop_width: float = 1.0,
    window: tuple[float, float] = (0.0, 4.0),
) -> dict:
    return {
        "candidateId": candidate_id,
        "reviewSha256": "a" * 64,
        "candidateRank": 1,
        "disposition": disposition,
        "identity": {
            "provider": "pexels",
            "sourceId": source_id,
            "sourceWindow": {"startSeconds": window[0], "endSeconds": window[1]},
            "intendedCrop": {
                "mode": "cover", "x": 0.0, "y": 0.0, "w": crop_width, "h": 1.0,
            },
        },
    }


def _workspace(*, event1_alt: bool, event2_alt: bool = False) -> dict:
    reusable = {
        "event-1": [_candidate("sel-1", "source-a", disposition="selected")],
        "event-2": [_candidate("sel-2", "source-b", disposition="selected")],
    }
    if event1_alt:
        reusable["event-1"].extend([
            _candidate("alt-other", "source-z"),
            # Same source but a *different* crop: this genuinely changes the frame
            # geometry, so it can move a subject away from the type.
            _candidate("alt-same-source", "source-a", crop_width=0.8),
        ])
    if event2_alt:
        reusable["event-2"].append(_candidate("alt-2", "source-b"))
    return {
        "selectedCandidateIds": {"event-1": "sel-1", "event-2": "sel-2"},
        "reusableCandidatesByVisualEvent": reusable,
        "discoveryCandidateCount": 0,
        "discoveryPassCount": 0,
    }


def _scene_checkpoint(event_id: str, *queries: str) -> dict:
    return {
        "status": "completed",
        "artifacts": {
            "scene_plan": {
                "beats": [{
                    "id": "beat",
                    "visual_events": [{"id": event_id, "queries": list(queries)}],
                }],
            }
        },
    }


def test_layout_failure_must_stay_in_same_phase_before_asset_reacquisition() -> None:
    plan = shot_local_recovery_plan(
        {"code": "FILM_TYPE_LAYOUT_OVERFLOW", "details": {"shotIds": ["shot-1"]}},
        _edit(),
        _workspace(event1_alt=False),
    )
    assert plan["decision"] == "same_phase_repair"
    assert plan["sendBackAllowed"] is False
    assert plan["localRepairShotIds"] == ["shot-1"]
    assert plan["reacquireShotIds"] == []


def test_asset_collision_prefers_existing_reviewed_candidate_same_source_first() -> None:
    plan = shot_local_recovery_plan(
        {"code": "ASSET_SELECTION_HARD_REGION_COLLISION", "details": {"shotIds": ["shot-1"]}},
        _edit(),
        _workspace(event1_alt=True),
    )
    assert plan["decision"] == "same_phase_repair"
    assert plan["sendBackAllowed"] is False
    assert plan["localRepairShotIds"] == ["shot-1"]
    assert plan["reacquireShotIds"] == []
    options = plan["existingOptions"]["shot-1"]
    assert options[0]["candidateId"] == "alt-same-source"
    assert options[0]["sameSourceAsSelected"] is True


def test_geometry_equivalent_alternate_is_not_a_placement_repair() -> None:
    """A placement collision is a property of the frame's geometry: a subject sits
    where the type needs to be. An alternate sharing the selected source *and* crop
    shows the same geometry, so reusing it cannot move that subject -- only
    different footage or a different crop can.

    Observed on the L3 run: the only reviewed "alternates" were the same clip with a
    0.1s window shift. The plan promised a repair that could not possibly succeed, so
    the run dead-ended on a reuse strategy instead of asking for usable footage.
    """
    workspace = {
        "selectedCandidateIds": {"event-1": "sel-1"},
        "reusableCandidatesByVisualEvent": {
            "event-1": [
                _candidate("sel-1", "source-a", disposition="selected"),
                # Same source, same crop, window shifted by 0.1s.
                _candidate("alt-shifted", "source-a", window=(0.1, 4.1)),
            ]
        },
        "discoveryCandidateCount": 0,
        "discoveryPassCount": 0,
    }
    plan = shot_local_recovery_plan(
        {
            "code": "ASSET_SELECTION_HARD_REGION_COLLISION",
            "details": {"shotIds": ["shot-1"]},
        },
        _edit(),
        workspace,
    )

    assert plan["decision"] == "scoped_asset_reacquisition"
    assert plan["sendBackAllowed"] is True
    assert plan["reacquireShotIds"] == ["shot-1"]
    assert plan["reacquireVisualEventIds"] == ["event-1"]
    assert plan["existingOptions"]["shot-1"] == []


def test_geometry_equivalence_does_not_restrict_layout_recovery() -> None:
    """Layout failures are repaired in no_copy_preflight, where a re-crop is a real
    option: the geometry filter must not reach them."""
    workspace = {
        "selectedCandidateIds": {"event-1": "sel-1"},
        "reusableCandidatesByVisualEvent": {
            "event-1": [
                _candidate("sel-1", "source-a", disposition="selected"),
                _candidate("alt-shifted", "source-a", window=(0.1, 4.1)),
            ]
        },
        "discoveryCandidateCount": 0,
        "discoveryPassCount": 0,
    }
    plan = shot_local_recovery_plan(
        {"code": "FILM_TYPE_LAYOUT_OVERFLOW", "details": {"shotIds": ["shot-1"]}},
        _edit(),
        workspace,
    )

    assert plan["decision"] == "same_phase_repair"
    assert plan["localRepairShotIds"] == ["shot-1"]


def test_asset_collision_reacquires_only_shots_with_exhausted_existing_options() -> None:
    plan = shot_local_recovery_plan(
        {
            "code": "ASSET_SELECTION_HARD_REGION_COLLISION",
            "details": {"shotIds": ["shot-1", "shot-2"]},
        },
        _edit(),
        _workspace(event1_alt=True, event2_alt=False),
    )
    assert plan["decision"] == "scoped_asset_reacquisition"
    assert plan["sendBackAllowed"] is True
    assert plan["localRepairShotIds"] == ["shot-1"]
    assert plan["reacquireShotIds"] == ["shot-2"]
    assert plan["reacquireVisualEventIds"] == ["event-2"]


def _bootstrap_to_preflight(tmp_path: Path) -> None:
    audio = tmp_path.parent / f"{tmp_path.name}-voice.wav"
    audio.write_bytes(b"audio")
    bootstrap_persian_video(
        title="Run",
        narration_path=str(audio),
        approved_script="متن تأییدشده",
        project_id="run",
        pipeline_dir=tmp_path,
        backlot_opener=lambda _: 0,
        now=BASE,
    )
    state = load_workflow_state("run", pipeline_dir=tmp_path)
    while state["next_phase"] != "no_copy_preflight":
        phase = state["next_phase"]
        state = record_phase_attempt("run", phase, pipeline_dir=tmp_path, now=BASE)
        if phase in workflow._PHASE_CHECKPOINT:
            completed = list(state.get("completed_phases") or [])
            completed.append(phase)
            state["completed_phases"] = completed
            state["next_phase"] = PHASES[PHASES.index(phase) + 1]
            workflow._write_state(tmp_path / "run", state)
            continue
        evidence = None
        if phase == "prepare_inputs":
            evidence = {
                "authoritative_script_sha256": state["input"]["approved_script"]["sha256"],
                "narration_sha256": state["input"]["narration"]["sha256"],
            }
        state = complete_phase("run", phase, evidence=evidence, pipeline_dir=tmp_path, now=BASE)
    artifacts = tmp_path / "run" / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    (artifacts / "edit_decisions.json").write_text(json.dumps(_edit()), encoding="utf-8")


def test_acquire_assets_sendback_is_refused_while_local_reviewed_option_remains(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _bootstrap_to_preflight(tmp_path)
    monkeypatch.setattr(workflow, "asset_workspace_status", lambda _: _workspace(event1_alt=True))
    with pytest.raises(PersianVideoWorkflowError, match="existing reviewed asset option"):
        request_send_back(
            "run", "acquire_assets",
            reason="hard subject collision",
            diagnostic_code="ASSET_SELECTION_HARD_REGION_COLLISION",
            affected_shot_ids=["shot-1"],
            pipeline_dir=tmp_path,
            now=BASE,
        )
    assert load_workflow_state("run", pipeline_dir=tmp_path)["send_backs"] == 0


def _exhaust_candidate_ceiling(tmp_path: Path) -> int:
    """Spend the whole-run candidate ceiling and return it."""
    ceiling = int(workflow.get_workflow_budgets().max_candidates_total)
    state = load_workflow_state("run", pipeline_dir=tmp_path)
    usage = dict(state.get("asset_usage") or {})
    usage["semantic_candidates_reviewed"] = ceiling
    usage["bytes_downloaded"] = 0
    for key in ("pending_pass", "pending_output_dir", "pending_limits"):
        usage.pop(key, None)
    state["asset_usage"] = usage
    workflow._write_state(tmp_path / "run", state)
    return ceiling


def test_scoped_reacquisition_carries_a_bounded_candidate_grant(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A sanctioned scoped repair must be able to run the authored queries for the
    events it repairs.

    Observed on the L3 run: the whole-run candidate ceiling was already spent, so the
    repair's primary query consumed the single remaining candidate and its authored
    alternate query was refused with "shared asset download/candidate budget is
    exhausted". Every sanctioned scoped re-acquisition failed that way, which left the
    placement collision unrepairable (#152).
    """
    _bootstrap_to_preflight(tmp_path)
    monkeypatch.setattr(
        workflow, "asset_workspace_status",
        lambda _: _workspace(event1_alt=True, event2_alt=False),
    )
    monkeypatch.setattr(
        workflow, "read_checkpoint",
        lambda *_args, **_kwargs: _scene_checkpoint("event-2", "replacement event two"),
    )
    _exhaust_candidate_ceiling(tmp_path)

    rewound = request_send_back(
        "run", "acquire_assets",
        reason="shot-2 has no reviewed fitting option",
        diagnostic_code="ASSET_SELECTION_HARD_REGION_COLLISION",
        affected_shot_ids=["shot-1", "shot-2"],
        pipeline_dir=tmp_path,
        now=BASE,
    )

    grant = rewound["asset_reacquisition_grant"]
    assert grant["visualEventIds"] == ["event-2"]
    assert 0 < grant["candidates"] <= workflow._REACQUISITION_CANDIDATE_GRANT

    # With the grant, the repair can run its authored query...
    issued = bounded_asset_search_request(
        "run",
        {
            "queries": [{"query": "replacement event two", "slot_id": "event-2", "kind": "video"}],
            "sources": ["pexels", "pixabay_video"],
        },
        retry_pass=0,
        pipeline_dir=tmp_path,
        now=BASE,
    )
    assert issued["max_candidates_total"] == grant["candidates"]

    # ...and without it the very same request is refused, because the whole-run
    # ceiling was already spent when the repair was authorised.
    state = load_workflow_state("run", pipeline_dir=tmp_path)
    state.pop("asset_reacquisition_grant", None)
    usage = dict(state.get("asset_usage") or {})
    for key in ("pending_pass", "pending_output_dir", "pending_limits"):
        usage.pop(key, None)
    state["asset_usage"] = usage
    workflow._write_state(tmp_path / "run", state)

    with pytest.raises(PersianVideoWorkflowError, match="budget is exhausted"):
        bounded_asset_search_request(
            "run",
            {
                "queries": [{"query": "replacement event two", "slot_id": "event-2", "kind": "video"}],
                "sources": ["pexels", "pixabay_video"],
            },
            retry_pass=0,
            pipeline_dir=tmp_path,
            now=BASE,
        )


def test_scoped_candidate_grant_is_honoured_when_accounting_the_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The request side and the result side must honour the same grant.

    In production the sanctioned repair could be *requested* but its result could
    never be *accounted* once the whole-run ceiling was spent:
    `bounded_asset_search_request` added the grant and `record_asset_search_result`
    did not, so the repair still failed with "asset semantic candidate budget
    exceeded". A one-sided grant is not a grant (#152).
    """
    _bootstrap_to_preflight(tmp_path)
    monkeypatch.setattr(
        workflow, "asset_workspace_status",
        lambda _: _workspace(event1_alt=True, event2_alt=False),
    )
    monkeypatch.setattr(
        workflow, "read_checkpoint",
        lambda *_args, **_kwargs: _scene_checkpoint("event-2", "replacement event two"),
    )
    _exhaust_candidate_ceiling(tmp_path)

    rewound = request_send_back(
        "run", "acquire_assets",
        reason="shot-2 has no reviewed fitting option",
        diagnostic_code="ASSET_SELECTION_HARD_REGION_COLLISION",
        affected_shot_ids=["shot-1", "shot-2"],
        pipeline_dir=tmp_path,
        now=BASE,
    )
    granted = int(rewound["asset_reacquisition_grant"]["candidates"])

    issued = bounded_asset_search_request(
        "run",
        {
            "queries": [{"query": "replacement event two", "slot_id": "event-2", "kind": "video"}],
            "sources": ["pexels", "pixabay_video"],
        },
        retry_pass=0,
        pipeline_dir=tmp_path,
        now=BASE,
    )
    result_data = {
        "output_dir": issued["output_dir"],
        "resolved_sources": issued["sources"],
        "max_candidates_total": issued["max_candidates_total"],
        "max_bytes_per_clip": issued["max_bytes_per_clip"],
        "max_total_download_bytes": issued["max_total_download_bytes"],
        "candidates_considered": granted,
        "semantic_candidates_reviewed": granted,
        "technical_rejects": 0,
        "bytes_downloaded": 0,
        "clips": [],
    }

    # Without the grant the repair's own result exceeds the whole-run ceiling...
    state = load_workflow_state("run", pipeline_dir=tmp_path)
    state.pop("asset_reacquisition_grant", None)
    workflow._write_state(tmp_path / "run", state)

    with pytest.raises(PersianVideoWorkflowError, match="semantic candidate budget exceeded"):
        workflow.record_asset_search_result(
            "run", retry_pass=0, pipeline_dir=tmp_path, result_data=result_data, now=BASE,
        )

    # ...and with it, the sanctioned repair's result is accountable.
    state = load_workflow_state("run", pipeline_dir=tmp_path)
    state["asset_reacquisition_grant"] = {
        "candidates": granted,
        "visualEventIds": ["event-2"],
        "grantedAt": BASE.isoformat(),
    }
    workflow._write_state(tmp_path / "run", state)

    accounted = workflow.record_asset_search_result(
        "run", retry_pass=0, pipeline_dir=tmp_path, result_data=result_data, now=BASE,
    )
    assert accounted is not None


def test_scoped_candidate_grant_never_exceeds_the_whole_run_ceiling(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The grant re-sources a few named events; it does not reopen the search."""
    _bootstrap_to_preflight(tmp_path)
    monkeypatch.setattr(
        workflow, "asset_workspace_status",
        lambda _: _workspace(event1_alt=False, event2_alt=False),
    )
    monkeypatch.setattr(
        workflow, "read_checkpoint",
        lambda *_args, **_kwargs: _scene_checkpoint("event-1", "one", "two"),
    )
    state = load_workflow_state("run", pipeline_dir=tmp_path)
    ceiling = int(workflow.get_workflow_budgets().max_candidates_total)

    rewound = request_send_back(
        "run", "acquire_assets",
        reason="both shots exhausted",
        diagnostic_code="ASSET_SELECTION_HARD_REGION_COLLISION",
        affected_shot_ids=["shot-1", "shot-2"],
        pipeline_dir=tmp_path,
        now=BASE,
    )

    assert rewound["asset_reacquisition_grant"]["candidates"] <= ceiling


def test_scoped_asset_sendback_consumes_budget_and_search_cannot_escape_scope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _bootstrap_to_preflight(tmp_path)
    monkeypatch.setattr(workflow, "asset_workspace_status", lambda _: _workspace(event1_alt=True, event2_alt=False))
    monkeypatch.setattr(
        workflow, "read_checkpoint",
        lambda *_args, **_kwargs: _scene_checkpoint(
            "event-2", "replacement event two", "event two alternate"
        ),
    )
    rewound = request_send_back(
        "run", "acquire_assets",
        reason="shot-2 has no reviewed fitting option",
        diagnostic_code="ASSET_SELECTION_HARD_REGION_COLLISION",
        affected_shot_ids=["shot-1", "shot-2"],
        pipeline_dir=tmp_path,
        now=BASE,
    )
    assert rewound["send_backs"] == 1
    scope = rewound["asset_reacquisition_scope"]
    assert scope["shotIds"] == ["shot-2"]
    assert scope["visualEventIds"] == ["event-2"]
    assert rewound["send_back_history"][-1]["diagnostic_code"] == "ASSET_SELECTION_HARD_REGION_COLLISION"
    assert rewound["send_back_history"][-1]["shot_ids"] == ["shot-2"]

    with pytest.raises(PersianVideoWorkflowError, match="outside scoped reacquisition"):
        bounded_asset_search_request(
            "run",
            {
                "queries": [{"query": "wrong event", "slot_id": "event-1", "kind": "video"}],
                "sources": ["pexels", "pixabay_video"],
            },
            retry_pass=0,
            pipeline_dir=tmp_path,
            now=BASE,
        )

    issued = bounded_asset_search_request(
        "run",
        {
            "queries": [{"query": "replacement event two", "slot_id": "event-2", "kind": "video"}],
            "sources": ["pexels", "pixabay_video"],
        },
        retry_pass=0,
        pipeline_dir=tmp_path,
        now=BASE,
    )
    assert [item["slot_id"] for item in issued["queries"]] == ["event-2"]



def test_scoped_asset_request_rejects_unauthored_query_before_search_is_issued(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _bootstrap_to_preflight(tmp_path)
    monkeypatch.setattr(
        workflow,
        "asset_workspace_status",
        lambda _: _workspace(event1_alt=True, event2_alt=False),
    )
    request_send_back(
        "run", "acquire_assets",
        reason="shot-2 has no reviewed fitting option",
        diagnostic_code="ASSET_SELECTION_HARD_REGION_COLLISION",
        affected_shot_ids=["shot-1", "shot-2"],
        pipeline_dir=tmp_path,
        now=BASE,
    )
    monkeypatch.setattr(
        workflow, "read_checkpoint",
        lambda *_args, **_kwargs: _scene_checkpoint(
            "event-2", "authored event two", "authored event two alternate"
        ),
    )

    with pytest.raises(PersianVideoWorkflowError, match="not one of the authored queries"):
        bounded_asset_search_request(
            "run",
            {
                "queries": [{
                    "query": "invented provider query",
                    "slot_id": "event-2",
                    "kind": "video",
                }],
                "sources": ["pexels", "pixabay_video"],
            },
            retry_pass=0,
            pipeline_dir=tmp_path,
            now=BASE,
        )

    state = load_workflow_state("run", pipeline_dir=tmp_path)
    assert "pending_pass" not in (state.get("asset_usage") or {})

    issued = bounded_asset_search_request(
        "run",
        {
            "queries": [{
                "query": "authored event two",
                "slot_id": "event-2",
                "kind": "video",
            }],
            "sources": ["pexels", "pixabay_video"],
        },
        retry_pass=0,
        pipeline_dir=tmp_path,
        now=BASE,
    )
    assert issued["queries"][0]["query"] == "authored event two"

def test_unscoped_automatic_sendback_to_acquire_assets_is_forbidden(tmp_path: Path) -> None:
    _bootstrap_to_preflight(tmp_path)
    with pytest.raises(PersianVideoWorkflowError, match="requires --code and affected shot ids"):
        request_send_back(
            "run", "acquire_assets", reason="generic rewind",
            pipeline_dir=tmp_path, now=BASE,
        )


def test_scoped_reacquisition_records_next_workspace_discovery_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _bootstrap_to_preflight(tmp_path)
    workspace = _workspace(event1_alt=False)
    workspace["discoveryPassCount"] = 2
    monkeypatch.setattr(workflow, "asset_workspace_status", lambda _: workspace)
    monkeypatch.setattr(
        workflow, "read_checkpoint",
        lambda *_args, **_kwargs: _scene_checkpoint(
            "event-1", "replacement", "event one alternate"
        ),
    )
    passes: list[int] = []
    monkeypatch.setattr(
        workflow, "record_discovery_pass",
        lambda project, retry_pass, clips: passes.append(retry_pass) or {"idempotent": False},
    )
    request_send_back(
        "run", "acquire_assets",
        reason="shot-1 exhausted",
        diagnostic_code="ASSET_SELECTION_HARD_REGION_COLLISION",
        affected_shot_ids=["shot-1"],
        pipeline_dir=tmp_path, now=BASE,
    )
    request = bounded_asset_search_request(
        "run",
        {
            "queries": [{"query": "replacement", "slot_id": "event-1", "kind": "video"}],
            "sources": ["pexels", "pixabay_video"],
        },
        retry_pass=0, pipeline_dir=tmp_path, now=BASE,
    )
    clip_path = tmp_path / "run" / "assets" / "clips" / "replacement.mp4"
    clip_path.parent.mkdir(parents=True, exist_ok=True)
    clip_path.write_bytes(b"video")
    result = {
        "output_dir": request["output_dir"],
        "resolved_sources": request["sources"],
        "max_candidates_total": request["max_candidates_total"],
        "max_bytes_per_clip": request["max_bytes_per_clip"],
        "max_total_download_bytes": request["max_total_download_bytes"],
        "candidates_considered": 1,
        "bytes_downloaded": len(b"video"),
        "clips": [{
            "path": str(clip_path),
            "file_size_bytes": len(b"video"),
            "source": "pexels",
            "source_id": "new-source",
            "clip_id": "pexels_new-source",
            "slot_id": "event-1",
            "kind": "video",
            "duration": 6.0,
            "width": 1080,
            "height": 1920,
        }],
    }
    state = workflow.record_asset_search_result(
        "run", retry_pass=0, result_data=result,
        pipeline_dir=tmp_path, now=BASE,
    )
    assert passes == [2]
    assert state["asset_usage"]["completed_passes"] == [0]
    assert state["asset_usage"]["acquisition_cycle"] == 1


def test_layout_diagnostic_cannot_send_back_to_assets_even_without_shot_ids(tmp_path: Path) -> None:
    _bootstrap_to_preflight(tmp_path)
    with pytest.raises(PersianVideoWorkflowError, match="FILM_TYPE_LAYOUT must be repaired"):
        request_send_back(
            "run", "acquire_assets",
            reason="layout overflow",
            diagnostic_code="FILM_TYPE_LAYOUT_OVERFLOW",
            pipeline_dir=tmp_path, now=BASE,
        )
    assert load_workflow_state("run", pipeline_dir=tmp_path)["send_backs"] == 0


def _activate_scope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, event: str = "event-2"
) -> dict:
    _bootstrap_to_preflight(tmp_path)
    workspace = _workspace(event1_alt=(event != "event-1"), event2_alt=False)
    if event == "event-1":
        workspace = _workspace(event1_alt=False)
    monkeypatch.setattr(workflow, "asset_workspace_status", lambda _: workspace)
    shot_id = "shot-1" if event == "event-1" else "shot-2"
    return request_send_back(
        "run", "acquire_assets",
        reason=f"{shot_id} exhausted",
        diagnostic_code="ASSET_SELECTION_HARD_REGION_COLLISION",
        affected_shot_ids=[shot_id],
        pipeline_dir=tmp_path, now=BASE,
    )


def test_scoped_reacquisition_blocks_review_reject_and_select_for_unrelated_candidate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _activate_scope(tmp_path, monkeypatch, event="event-2")
    unrelated = {
        "candidateId": "candidate-event-1",
        "context": {"visualEventId": "event-1"},
    }
    monkeypatch.setattr(workflow, "load_asset_candidate", lambda *a, **k: unrelated)
    monkeypatch.setattr(
        workflow, "record_candidate_review",
        lambda *a, **k: pytest.fail("unrelated candidate review must not run"),
    )
    monkeypatch.setattr(
        workflow, "reject_asset_candidate",
        lambda *a, **k: pytest.fail("unrelated candidate rejection must not run"),
    )
    monkeypatch.setattr(
        workflow, "select_asset_candidate",
        lambda *a, **k: pytest.fail("unrelated candidate selection must not run"),
    )
    review_path = tmp_path / "run" / "review.json"
    review_path.write_text("{}", encoding="utf-8")

    with pytest.raises(PersianVideoWorkflowError, match="outside scoped reacquisition"):
        workflow.review_workflow_asset_candidate(
            "run", "candidate-event-1", review_path, pipeline_dir=tmp_path
        )
    with pytest.raises(PersianVideoWorkflowError, match="outside scoped reacquisition"):
        workflow.reject_workflow_asset_candidate(
            "run", "candidate-event-1", category="editorial", reason="x",
            pipeline_dir=tmp_path,
        )
    with pytest.raises(PersianVideoWorkflowError, match="outside scoped reacquisition"):
        workflow.select_workflow_asset_candidate(
            "run", "event-1", "candidate-event-1",
            rejected_alternatives={}, replace_existing=True, pipeline_dir=tmp_path,
        )


def test_shot_scoped_reacquisition_forbids_unrelated_music_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _activate_scope(tmp_path, monkeypatch, event="event-2")
    request_path = tmp_path / "run" / "music-request.json"
    metadata_path = tmp_path / "run" / "music-metadata.json"
    request_path.write_text("{}", encoding="utf-8")
    metadata_path.write_text("{}", encoding="utf-8")
    with pytest.raises(PersianVideoWorkflowError, match="music acquisition is forbidden"):
        workflow.search_workflow_music("run", request_path, pipeline_dir=tmp_path)
    with pytest.raises(PersianVideoWorkflowError, match="music acquisition is forbidden"):
        workflow.fetch_workflow_music(
            "run", "music-" + "a" * 24, metadata_path, pipeline_dir=tmp_path
        )


def test_send_back_parser_exposes_machine_readable_shot_scope() -> None:
    args = workflow.build_parser().parse_args([
        "send-back", "run", "acquire_assets",
        "--reason", "shot exhausted",
        "--code", "ASSET_SELECTION_HARD_REGION_COLLISION",
        "--shot-id", "shot-2",
        "--edit-attempt-id", "candidate-02",
    ])
    assert args.diagnostic_code == "ASSET_SELECTION_HARD_REGION_COLLISION"
    assert args.shot_ids == ["shot-2"]
    assert args.edit_attempt_id == "candidate-02"
