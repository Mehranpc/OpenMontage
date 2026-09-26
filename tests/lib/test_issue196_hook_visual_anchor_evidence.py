from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from lib import persian_edit_workspace as workspace
import lib.persian_preflight as preflight
from lib.persian_hook_quality import audit_persian_hook_quality
from lib.persian_preflight import NoCopyPersianCompose, aggregate_preflight_edit_decisions
from tests.lib.test_persian_hook_quality_controls import _hook
from tests.lib.test_persian_preflight_contract import _payload


def _judgements() -> dict:
    return {
        field: {"level": "strong", "rationale": f"fixture rationale for {field}"}
        for field in (
            "semanticPredictionError",
            "audienceRelevance",
            "concreteness",
            "hookBodyAlignment",
            "visualVoiceAlignment",
        )
    }


def _edit(display_text: str) -> dict:
    return {
        "metadata": {
            "target_platform": "instagram-reels",
            "hookQuality": {
                "version": "2.0",
                "viewerValue": {
                    "atSeconds": 0.4,
                    "evidenceId": "value-1",
                    "evidence": "The opening makes the viewer value concrete.",
                },
                "semanticTension": {
                    "kind": "contradiction",
                    "atSeconds": 0.8,
                    "evidenceId": "tension-1",
                    "evidence": "The opening establishes a specific contradiction.",
                },
                "firstProof": {
                    "kind": "result",
                    "atSeconds": 1.6,
                    "evidenceId": "proof-1",
                    "evidence": "A concrete result begins inside the opening.",
                },
                "judgements": _judgements(),
                "flags": {
                    "metaIntroDelay": False,
                    "vagueGap": False,
                    "fullConclusionRevealed": False,
                },
                "perceptualChanges": [],
                "semanticIntegrity": {
                    "sourceText": "بازی فقط وقت تلف کردنه؟",
                    "requiredTopicAnchors": ["بازی"],
                    "anchorDelivery": "visual",
                    "visualAnchorEvidence": "بازی در تصویر افتتاحیه دیده می‌شود.",
                },
            },
        },
        "persian": {
            "durationSeconds": 20.0,
            "shots": [
                {
                    "id": "hook-shot",
                    "narrativeRole": "hook",
                    "startSeconds": 0.0,
                    "endSeconds": 3.0,
                    "openingSemanticMatch": True,
                }
            ],
            "moments": [
                {
                    "id": "hook-moment",
                    "kind": "hook",
                    "startSeconds": 0.0,
                    "endSeconds": 3.0,
                    "segments": [{"role": "hero", "text": display_text}],
                }
            ],
            "typographicBeats": [],
        },
    }


def _preflight(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    precomputed: dict | None = None,
) -> dict:
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"fixture")
    payload = _payload(str(source))
    payload["metadata"] = {
        "target_platform": "instagram-reels",
        "hookQuality": deepcopy(_hook()),
    }

    def fake_build(_self, persian, *_args, **_kwargs):
        return deepcopy(persian), ["Video by Test on Pexels"]

    monkeypatch.setattr(NoCopyPersianCompose, "_build_props", fake_build)
    return aggregate_preflight_edit_decisions(
        payload,
        base_dir=tmp_path,
        precomputed_components=precomputed,
    )


def test_self_reported_visual_anchor_evidence_cannot_clear_missing_topic_anchor() -> None:
    audit = audit_persian_hook_quality(_edit("فقط وقت تلف کردنه؟"))

    assert audit["policy"]["semanticIntegrityPolicyVersion"] == "1.1"
    assert audit["disposition"] == "weak"
    assert audit["semanticIntegrity"]["anchorSatisfiedBy"] is None
    assert audit["semanticIntegrity"]["missingAnchors"] == ["بازی"]
    assert any("[HOOK_TOPIC_ANCHOR_MISSING]" in problem for problem in audit["problems"])


def test_delivered_text_still_satisfies_topic_anchor_under_policy_1_1() -> None:
    audit = audit_persian_hook_quality(_edit("بازی فقط وقت تلف کردنه؟"))

    assert audit["disposition"] == "acceptable", audit
    assert audit["semanticIntegrity"]["anchorSatisfiedBy"] == "text"
    assert audit["semanticIntegrity"]["missingAnchors"] == []
    assert not any("[HOOK_TOPIC_ANCHOR_MISSING]" in problem for problem in audit["problems"])


def test_stale_semantic_integrity_component_audit_is_recomputed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fresh = _preflight(monkeypatch, tmp_path)
    stale = deepcopy(fresh["evidence"]["hookQualityAudit"])
    stale["semanticIntegrity"]["policyVersion"] = "1.0"
    stale["disposition"] = "weak"
    stale["problems"] = ["stale semantic policy verdict must not be reused"]

    report = _preflight(
        monkeypatch,
        tmp_path,
        precomputed={"hookQualityAudit": stale},
    )

    audit = report["evidence"]["hookQualityAudit"]
    assert audit["semanticIntegrity"]["policyVersion"] == "1.1"
    assert audit["problems"] == []
    assert report["ok"] is True, report


def test_issue196_policy_change_invalidates_old_full_preflight_cache() -> None:
    digest = "c" * 64
    stale = {
        "artifactSha256": digest,
        "policyVersion": "2.4",
        "ok": True,
    }

    assert preflight.PREFLIGHT_POLICY_VERSION == "2.5"
    assert workspace._valid_cached_report(stale, digest=digest) is False
