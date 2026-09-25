from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from tests.fixture_support.p4_failed_shadow import (
    FIXTURE_PATH,
    FailedShadowFixtureError,
    fixture_case,
    fixture_digest,
    load_issue138_fixture,
)


def _write_with_fresh_digest(payload: dict, path: Path) -> None:
    payload["fixtureDigestSha256"] = fixture_digest(payload)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def test_issue138_fixture_is_portable_versioned_evidence() -> None:
    fixture = load_issue138_fixture()
    assert set(fixture["cases"]) == {"F1", "F2", "F3", "F4"}
    assert fixture["sourceEvidence"]["immutableSource"] is True
    assert fixture["sourceEvidence"]["projectId"] == "p4-shadow-first-date-first-text-2cc3664-20260925-000753"
    serialized = json.dumps(fixture, ensure_ascii=False).lower()
    assert "/users/" not in serialized
    assert "/home/" not in serialized
    assert ".mp4" not in serialized
    assert ".wav" not in serialized
    assert ".mp3" not in serialized


def test_issue138_fixture_digest_locks_the_recorded_evidence() -> None:
    raw = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    assert raw["fixtureDigestSha256"] == fixture_digest(raw)


def test_issue138_fixture_refuses_missing_review_authority(tmp_path: Path) -> None:
    broken = copy.deepcopy(load_issue138_fixture())
    del broken["authority"]["assetWorkspace"]["event-2"]["reviewSha256"]
    path = tmp_path / "broken.json"
    _write_with_fresh_digest(broken, path)
    with pytest.raises(FailedShadowFixtureError, match="reviewSha256"):
        load_issue138_fixture(path)


def test_f1_fixture_preserves_fast_hard_region_rejection_contract() -> None:
    fixture = load_issue138_fixture()
    case = fixture_case(fixture, "F1")
    assert case["input"]["moment"] == {
        "id": "moment-2",
        "startSeconds": 5.67,
        "endSeconds": 9.2,
        "displayCopy": {"mode": "adaptable", "text": "پژوهشگرا آزمایش کردند"},
    }
    assert case["expected"]["diagnosticCode"] == "ASSET_SELECTION_HARD_REGION_COLLISION"
    assert case["expected"]["stage"] == "geometric_precheck"
    assert set(case["expected"]["mustRejectBefore"]) == {"chromium", "candidate_counter_increment"}


def test_f2_fixture_preserves_user_supplied_authority_and_probe_divergence() -> None:
    fixture = load_issue138_fixture()
    case = fixture_case(fixture, "F2")
    hook = fixture["authority"]["hookSelection"]
    assert hook["mode"] == "user_supplied"
    assert hook["authoritative"] is True
    assert case["observed"]["standaloneExtraBlockingCode"] == "HOOK_QUALITY_GATE"
    assert case["observed"]["officialSameFactTreatment"] == "advisory"
    assert case["expected"] == {
        "blockingSetParity": True,
        "readOnly": True,
        "durableSideEffects": False,
    }


def test_f3_fixture_preserves_reviewed_vs_unreviewed_identity_mismatch() -> None:
    fixture = load_issue138_fixture()
    case = fixture_case(fixture, "F3")
    reviewed = fixture["authority"]["assetWorkspace"]["event-2"]
    attempted = case["input"]["attemptedEditIdentity"]
    assert reviewed["sourceId"] == attempted["sourceId"] == "6115070"
    assert reviewed["reviewedWindow"] == {"startSeconds": 0.0, "endSeconds": 8.14}
    assert attempted["sourceWindow"] == {"startSeconds": 13.36, "endSeconds": 21.5}
    assert attempted["cropTransformIdentity"] is None
    assert attempted["cropTransformAuthority"] == "missing_in_failed_edit_candidate"
    assert case["expected"]["diagnosticCode"] is None
    assert case["expected"]["diagnosticCodeAuthority"] == "not_defined_by_issue138"
    assert case["expected"]["recoveryRoute"] == "send_back:acquire_assets"


def test_f4_fixture_preserves_historical_silent_overrun_and_target_stop() -> None:
    case = fixture_case(load_issue138_fixture(), "F4")
    assert case["observed"]["wallSeconds"] > case["input"]["wallBudgetSeconds"]
    assert case["observed"]["budgetStop"] is None
    assert case["expected"]["status"] == "needs_decision"
    assert case["expected"]["reason"] == "wall_budget_exceeded"
    assert case["expected"]["startsNewExpensiveWork"] is False
