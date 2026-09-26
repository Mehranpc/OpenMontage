from __future__ import annotations

from lib.persian_hook_quality import audit_persian_hook_quality


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
