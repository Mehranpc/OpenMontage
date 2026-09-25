"""Issue #81 increment 1: one hook timing policy across preflight and rendered review.

These tests pin externally observable decisions: what preflight blocks, what the
persisted evidence says, and which exact candidate may reach awaiting_human.
"""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest
from jsonschema import ValidationError

import lib.persian_video_workflow as workflow
from lib.persian_editorial_hook import build_initial_hook_selection
from lib.persian_hook_quality import (
    HOOK_TIMING_POLICY_VERSION,
    hook_timing_policy,
    resolve_hook_timing_authority,
)
from lib.persian_preflight import NoCopyPersianCompose, aggregate_preflight_edit_decisions
from lib.persian_rendered_review import (
    PersianRenderedReviewError,
    validate_rendered_hook_review,
)
from lib.persian_video_workflow import PersianVideoWorkflowError, complete_phase
from tests.lib.test_persian_hook_final_review import (
    _bind_cold_viewer_input,
    _hook_audit,
    _hook_review,
)
from tests.lib.test_persian_hook_quality_controls import _hook
from tests.lib.test_persian_preflight_contract import _payload
from tests.lib.test_persian_video_workflow import BASE, _checkpoint, _review_ready_project

CANDIDATE_DIGEST = hashlib.sha256(b"candidate").hexdigest()
APPROVED_HOOK = "بعد از قرار اول، کی پیام بدی بهتره؟"
LATE_PAYOFF_SECONDS = 25.22
# The preflight payload fixture is a 12s timeline, so the late authored proof must
# still fall inside its own timeline while clearing the 6.0s ceiling.
PREFLIGHT_LATE_SECONDS = 7.5
ADVISORY_REASON = (
    "The approved user-authoritative question is answered by the study result at 25.22s; "
    "the opening keeps setup and payoff distinct instead of spoiling the answer."
)


def _preflight(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    hook: dict,
    *,
    hook_authority: dict | None = None,
    precomputed: dict | None = None,
) -> dict:
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"fixture")
    payload = _payload(str(source))
    payload["metadata"] = {"target_platform": "instagram-reels", "hookQuality": hook}

    def fake_build(_self, persian, *_args, **_kwargs):
        return deepcopy(persian), ["Video by Test on Pexels"]

    monkeypatch.setattr(NoCopyPersianCompose, "_build_props", fake_build)
    return aggregate_preflight_edit_decisions(
        payload,
        base_dir=tmp_path,
        precomputed_components=precomputed,
        hook_authority=hook_authority,
    )


def _late_hook() -> dict:
    hook = deepcopy(_hook())
    hook["firstProof"] = {
        "kind": "result",
        "atSeconds": PREFLIGHT_LATE_SECONDS,
        "evidence": "The morning-after study result is stated much later in the approved narration.",
    }
    return hook


def _make_authoritative(tmp_path: Path, text: str = APPROVED_HOOK) -> dict:
    state = workflow.load_workflow_state("run", pipeline_dir=tmp_path)
    selection = build_initial_hook_selection(text)
    state["hook_selection"] = selection
    workflow._write_state(tmp_path / "run", state)
    return selection


def _authoritative_provenance(selection: dict) -> dict:
    return {
        "mode": "user_supplied",
        "reference": "workflow.hook_selection",
        "selectedHookSha256": str(selection["sha256"]),
    }


def _authoritative_hook_audit(selection: dict) -> dict:
    """Preflight evidence shaped as the real audit records canonical authority."""
    return {
        **_hook_audit(),
        "semanticAuthority": "user-authoritative-awaiting-rendered-review",
        "timingPolicy": hook_timing_policy(),
        "timingDisposition": "late-authoritative-advisory",
        "authorityProvenance": {
            **_authoritative_provenance(selection),
            "authoritative": True,
            "valid": True,
        },
    }


def _candidate(tmp_path: Path) -> Path:
    path = tmp_path / "candidate.mp4"
    path.write_bytes(b"candidate")
    return path


def _late_review(candidate: Path, **overrides) -> dict:
    fields = {
        "actualPayoffSeconds": LATE_PAYOFF_SECONDS,
        "payoffBeginsPromptly": False,
        "authorityProvenance": {
            "mode": "user_supplied",
            "reference": "workflow.hook_selection",
            "selectedHookSha256": "c" * 64,
        },
    }
    fields.update(overrides)
    return _hook_review(candidate, **fields)


def _review_with_late_advisory(
    tmp_path: Path, *, authority: dict | None = None, status: str = "pass"
) -> tuple[Path, Path]:
    _, candidate, review_path, report = _review_ready_project(tmp_path)
    review = json.loads(review_path.read_text(encoding="utf-8"))
    review["status"] = status
    review["recommended_action"] = "present_to_user" if status == "pass" else "revise_edit"
    if authority is None:
        selection = _make_authoritative(tmp_path)
        authority = _authoritative_provenance(selection)
        audit = _authoritative_hook_audit(selection)
    else:
        audit = _authoritative_hook_audit(
            {"sha256": str(authority.get("selectedHookSha256") or "")}
        )
    review["metadata"] = {
        "hookQualityAudit": audit,
        "hookQualityReview": _hook_review(
            candidate,
            actualPayoffSeconds=LATE_PAYOFF_SECONDS,
            timingDisposition="late-authoritative-advisory",
            payoffBeginsPromptly=False,
            advisoryReason=ADVISORY_REASON,
            authorityProvenance=authority,
        ),
    }
    _bind_cold_viewer_input(review, candidate, tmp_path / "run")
    review_path.write_text(json.dumps(review), encoding="utf-8")
    report["hook_strength"] = "acceptable"
    (tmp_path / "run" / "checkpoint_compose.json").write_text(
        json.dumps(_checkpoint(report)), encoding="utf-8"
    )
    return candidate, review_path


# --------------------------------------------------------------------------
# Shared, versioned policy
# --------------------------------------------------------------------------


def test_hook_timing_policy_is_versioned_and_names_one_authority_source() -> None:
    policy = hook_timing_policy()

    assert policy["version"] == HOOK_TIMING_POLICY_VERSION
    assert policy["proofBlockSeconds"] == 6.0
    assert policy["automaticDisposition"] == "late-blocked"
    assert policy["authoritativeDisposition"] == "late-authoritative-advisory"
    assert policy["authoritySource"] == "workflow.hook_selection"


def test_preflight_evidence_records_policy_disposition_and_authority_provenance(
    monkeypatch, tmp_path
) -> None:
    authority = build_initial_hook_selection(APPROVED_HOOK)
    report = _preflight(monkeypatch, tmp_path, _late_hook(), hook_authority=authority)

    audit = report["evidence"]["hookQualityAudit"]
    assert audit["timingPolicy"]["version"] == HOOK_TIMING_POLICY_VERSION
    assert audit["timingDisposition"] == "late-authoritative-advisory"
    assert audit["authorityProvenance"] == {
        "mode": "user_supplied",
        "authoritative": True,
        "valid": True,
        "reference": "workflow.hook_selection",
        "selectedHookSha256": authority["sha256"],
    }
    assert report["ok"] is True, report


# --------------------------------------------------------------------------
# Preflight: policy conflicts stop before expensive rendering
# --------------------------------------------------------------------------


def test_automatic_hook_with_known_late_proof_stops_before_rendering(monkeypatch, tmp_path) -> None:
    report = _preflight(monkeypatch, tmp_path, _late_hook())

    assert report["ok"] is False
    assert report["evidence"]["hookQualityAudit"]["timingDisposition"] == "late-blocked"
    assert any("blocking ceiling" in issue["message"] for issue in report["blockingIssues"])


def test_forged_authority_record_cannot_downgrade_late_proof(monkeypatch, tmp_path) -> None:
    forged = {
        "mode": "user_supplied",
        "authoritative": True,
        "text": APPROVED_HOOK,
        "sha256": "a" * 64,
    }

    report = _preflight(monkeypatch, tmp_path, _late_hook(), hook_authority=forged)

    audit = report["evidence"]["hookQualityAudit"]
    assert report["ok"] is False
    assert audit["timingDisposition"] == "late-blocked"
    assert audit["authorityProvenance"]["authoritative"] is False
    assert audit["authorityProvenance"]["valid"] is False
    assert any("rejected" in item for item in audit["advisories"])


def test_self_declared_authority_boolean_is_not_enough(monkeypatch, tmp_path) -> None:
    report = _preflight(
        monkeypatch,
        tmp_path,
        _late_hook(),
        hook_authority={"mode": "user_supplied", "authoritative": True},
    )

    assert report["ok"] is False
    assert report["evidence"]["hookQualityAudit"]["timingDisposition"] == "late-blocked"


def test_cached_hook_audit_from_an_older_policy_is_not_reused(monkeypatch, tmp_path) -> None:
    stale = {
        "version": "2.0",
        "required": True,
        "disposition": "weak",
        "problems": ["stale policy verdict that must not survive a policy change"],
        "advisories": [],
        "timingPolicy": {"version": "1.0"},
    }

    report = _preflight(monkeypatch, tmp_path, _hook(), precomputed={"hookQualityAudit": stale})

    audit = report["evidence"]["hookQualityAudit"]
    assert audit["timingPolicy"]["version"] == HOOK_TIMING_POLICY_VERSION
    assert audit["problems"] == []
    assert report["ok"] is True, report


def test_resolve_hook_timing_authority_fails_closed_without_consistent_provenance() -> None:
    assert resolve_hook_timing_authority(None)["authoritative"] is False
    assert resolve_hook_timing_authority({"mode": "automatic"})["authoritative"] is False
    mismatched = {
        "mode": "user_supplied",
        "authoritative": True,
        "text": APPROVED_HOOK,
        "sha256": "0" * 64,
    }
    assert resolve_hook_timing_authority(mismatched)["authoritative"] is False
    assert (
        resolve_hook_timing_authority(build_initial_hook_selection(APPROVED_HOOK))[
            "authoritative"
        ]
        is True
    )


# --------------------------------------------------------------------------
# Rendered final review
# --------------------------------------------------------------------------


def test_late_authoritative_hook_reaches_awaiting_human_without_faking_prompt_payoff(tmp_path):
    candidate, review_path = _review_with_late_advisory(tmp_path)

    state = complete_phase(
        "run", "final_review", evidence={"final_review_path": str(review_path)},
        pipeline_dir=tmp_path, now=BASE,
    )

    assert state["next_phase"] == "awaiting_human"
    review = json.loads(review_path.read_text(encoding="utf-8"))
    hook_review = review["metadata"]["hookQualityReview"]
    assert hook_review["payoffBeginsPromptly"] is False
    assert hook_review["timingDisposition"] == "late-authoritative-advisory"
    assert hook_review["actualPayoffSeconds"] == LATE_PAYOFF_SECONDS
    assert hook_review["reviewedCandidateSha256"] == hashlib.sha256(
        candidate.read_bytes()
    ).hexdigest()


def test_late_authoritative_advisory_still_requires_independent_visual_voice_alignment(tmp_path):
    """The late-payoff exception never waives the other independent rendered checks.

    ``visualVoiceAlignment`` is enforced by ``validate_rendered_hook_review`` for a
    passing review (``require_pass``), so a valid authoritative late advisory paired
    with a weak alignment must still refuse to advance the phase.
    """
    _, review_path = _review_with_late_advisory(tmp_path)
    review = json.loads(review_path.read_text(encoding="utf-8"))
    review["metadata"]["hookQualityReview"]["visualVoiceAlignment"] = "weak"
    review_path.write_text(json.dumps(review), encoding="utf-8")

    with pytest.raises(PersianVideoWorkflowError, match="visual/voice alignment"):
        complete_phase(
            "run", "final_review", evidence={"final_review_path": str(review_path)},
            pipeline_dir=tmp_path, now=BASE,
        )


def test_late_payoff_is_blocked_when_durable_authority_is_automatic(tmp_path):
    _, candidate, review_path, report = _review_ready_project(tmp_path)
    selection = workflow.load_workflow_state("run", pipeline_dir=tmp_path)["hook_selection"]
    review = json.loads(review_path.read_text(encoding="utf-8"))
    review["metadata"] = {
        "hookQualityAudit": _hook_audit(),
        "hookQualityReview": _hook_review(
            candidate,
            actualPayoffSeconds=LATE_PAYOFF_SECONDS,
            timingDisposition="late-authoritative-advisory",
            payoffBeginsPromptly=False,
            advisoryReason=ADVISORY_REASON,
            authorityProvenance={
                "mode": "user_supplied",
                "reference": "workflow.hook_selection",
                "selectedHookSha256": str(selection.get("sha256") or "a" * 64),
            },
        ),
    }
    _bind_cold_viewer_input(review, candidate, tmp_path / "run")
    review_path.write_text(json.dumps(review), encoding="utf-8")
    report["hook_strength"] = "acceptable"
    (tmp_path / "run" / "checkpoint_compose.json").write_text(
        json.dumps(_checkpoint(report)), encoding="utf-8"
    )

    with pytest.raises(PersianVideoWorkflowError, match="hook-quality review"):
        complete_phase(
            "run", "final_review", evidence={"final_review_path": str(review_path)},
            pipeline_dir=tmp_path, now=BASE,
        )


def test_late_advisory_provenance_must_match_the_durable_hook_selection(tmp_path):
    _, review_path = _review_with_late_advisory(
        tmp_path,
        authority={
            "mode": "user_supplied",
            "reference": "workflow.hook_selection",
            "selectedHookSha256": "b" * 64,
        },
    )

    with pytest.raises(PersianVideoWorkflowError, match="hook-quality review"):
        complete_phase(
            "run", "final_review", evidence={"final_review_path": str(review_path)},
            pipeline_dir=tmp_path, now=BASE,
        )


def test_late_advisory_review_requires_durable_authority_context(tmp_path) -> None:
    review = _late_review(_candidate(tmp_path), timingDisposition="late-authoritative-advisory",
                          advisoryReason=ADVISORY_REASON)

    with pytest.raises(PersianRenderedReviewError, match="durable workflow hook authority"):
        validate_rendered_hook_review(
            review, candidate_sha256=CANDIDATE_DIGEST, require_pass=True, hook_timing=None
        )


def test_payoff_begins_promptly_must_remain_truthful(tmp_path) -> None:
    candidate = _candidate(tmp_path)
    late = _late_review(candidate, timingDisposition="late-blocked", payoffBeginsPromptly=True)
    with pytest.raises(PersianRenderedReviewError, match="remain truthful"):
        validate_rendered_hook_review(late, candidate_sha256=CANDIDATE_DIGEST, require_pass=False)

    early = _hook_review(candidate, actualPayoffSeconds=2.0, payoffBeginsPromptly=False)
    with pytest.raises(PersianRenderedReviewError, match="remain truthful"):
        validate_rendered_hook_review(early, candidate_sha256=CANDIDATE_DIGEST, require_pass=False)


def test_prompt_disposition_cannot_claim_a_late_payoff(tmp_path) -> None:
    review = _hook_review(
        _candidate(tmp_path),
        actualPayoffSeconds=LATE_PAYOFF_SECONDS,
        timingDisposition="prompt",
        payoffBeginsPromptly=True,
    )

    with pytest.raises(PersianRenderedReviewError, match="prompt payoff"):
        validate_rendered_hook_review(review, candidate_sha256=CANDIDATE_DIGEST, require_pass=False)


def test_late_advisory_requires_a_recorded_reason(tmp_path) -> None:
    review = _late_review(
        _candidate(tmp_path),
        timingDisposition="late-authoritative-advisory",
        authorityProvenance={
            "mode": "user_supplied",
            "reference": "workflow.hook_selection",
            "selectedHookSha256": str(build_initial_hook_selection(APPROVED_HOOK)["sha256"]),
        },
    )

    with pytest.raises(PersianRenderedReviewError, match="advisoryReason"):
        validate_rendered_hook_review(
            review,
            candidate_sha256=CANDIDATE_DIGEST,
            require_pass=True,
            hook_timing=resolve_hook_timing_authority(build_initial_hook_selection(APPROVED_HOOK)),
        )


def test_late_payoff_persists_as_honest_blocked_evidence_on_a_revise_review(tmp_path):
    _, candidate, review_path, report = _review_ready_project(tmp_path)
    review = json.loads(review_path.read_text(encoding="utf-8"))
    review["status"] = "revise"
    review["recommended_action"] = "revise_edit"
    review["metadata"] = {
        "hookQualityAudit": _hook_audit(),
        "hookQualityReview": _hook_review(
            candidate,
            actualPayoffSeconds=LATE_PAYOFF_SECONDS,
            timingDisposition="late-blocked",
            payoffBeginsPromptly=False,
        ),
    }
    _bind_cold_viewer_input(review, candidate, tmp_path / "run")
    review_path.write_text(json.dumps(review), encoding="utf-8")
    report["hook_strength"] = "acceptable"
    (tmp_path / "run" / "checkpoint_compose.json").write_text(
        json.dumps(_checkpoint(report)), encoding="utf-8"
    )

    with pytest.raises(PersianVideoWorkflowError, match="must pass"):
        complete_phase(
            "run", "final_review", evidence={"final_review_path": str(review_path)},
            pipeline_dir=tmp_path, now=BASE,
        )

    persisted = json.loads(review_path.read_text(encoding="utf-8"))
    assert persisted["metadata"]["hookQualityReview"]["timingDisposition"] == "late-blocked"


def test_checkpoint_layer_still_rejects_an_unbacked_late_advisory(tmp_path):
    """A review cannot lift the timing gate on its own word."""
    from schemas.artifacts import validate_artifact

    _, candidate, review_path, _ = _review_ready_project(tmp_path)
    review = json.loads(review_path.read_text(encoding="utf-8"))
    review["metadata"] = {
        # Preflight recorded no canonical user authority, so the exception is unavailable.
        "hookQualityAudit": _hook_audit(),
        "hookQualityReview": _hook_review(
            candidate,
            actualPayoffSeconds=LATE_PAYOFF_SECONDS,
            timingDisposition="late-authoritative-advisory",
            payoffBeginsPromptly=False,
            advisoryReason=ADVISORY_REASON,
            authorityProvenance={
                "mode": "user_supplied",
                "reference": "workflow.hook_selection",
                "selectedHookSha256": "c" * 64,
            },
        ),
    }
    _bind_cold_viewer_input(review, candidate, tmp_path / "run")

    with pytest.raises(ValidationError):
        validate_artifact("final_review", review)


def test_artifact_contract_and_workflow_agree_on_a_backed_late_advisory(tmp_path):
    """Every consumer sees the same artifact: shape in the contract, authority in the workflow."""
    from schemas.artifacts import validate_artifact

    _, candidate, review_path, _ = _review_ready_project(tmp_path)
    selection = _make_authoritative(tmp_path)
    authority = _authoritative_provenance(selection)
    review = json.loads(review_path.read_text(encoding="utf-8"))
    review["metadata"] = {
        "hookQualityAudit": _authoritative_hook_audit(selection),
        "hookQualityReview": _hook_review(
            candidate,
            actualPayoffSeconds=LATE_PAYOFF_SECONDS,
            timingDisposition="late-authoritative-advisory",
            payoffBeginsPromptly=False,
            advisoryReason=ADVISORY_REASON,
            authorityProvenance=authority,
        ),
    }
    _bind_cold_viewer_input(review, candidate, tmp_path / "run")

    # Preflight-backed evidence passes the shape contract without reading durable state.
    validate_artifact("final_review", review)

    # The durable-aware validator still refuses to authorize the same bytes on its own.
    with pytest.raises(PersianRenderedReviewError, match="durable workflow hook authority"):
        validate_rendered_hook_review(
            review["metadata"]["hookQualityReview"],
            candidate_sha256=hashlib.sha256(candidate.read_bytes()).hexdigest(),
            require_pass=True,
        )


def test_frozen_2_0_reviews_stay_readable_with_their_original_rule(tmp_path) -> None:
    candidate = _candidate(tmp_path)
    legacy = _hook_review(candidate, version="2.0")

    # A 2.0 record predates the versioned timing policy and never carried these fields.
    for field in ("timingPolicyVersion", "timingDisposition", "authorityProvenance"):
        legacy.pop(field)
    validate_rendered_hook_review(legacy, candidate_sha256=CANDIDATE_DIGEST, require_pass=True)

    legacy_late = dict(legacy, actualPayoffSeconds=LATE_PAYOFF_SECONDS, payoffBeginsPromptly=False)
    with pytest.raises(PersianRenderedReviewError, match="prompt payoff"):
        validate_rendered_hook_review(
            legacy_late, candidate_sha256=CANDIDATE_DIGEST, require_pass=True
        )


def test_timing_policy_identity_participates_in_hook_cache_invalidation(monkeypatch, tmp_path):
    from lib import persian_edit_workspace as workspace
    from tests.lib.test_issue35_convergence_workspace import _edit

    first = tmp_path / "first"
    workspace.stage_edit_draft(first, "base", _edit(), max_candidates=10)
    before = workspace.load_convergence_candidate(first, "base")["dependencyDigests"]["hook"]

    monkeypatch.setattr(workspace, "HOOK_TIMING_POLICY_VERSION", "9.9")
    second = tmp_path / "second"
    workspace.stage_edit_draft(second, "base", _edit(), max_candidates=10)
    after = workspace.load_convergence_candidate(second, "base")["dependencyDigests"]["hook"]

    assert before != after
