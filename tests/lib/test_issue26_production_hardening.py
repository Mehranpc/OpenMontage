from __future__ import annotations

import pytest

from lib.persian_captions import layout_caption_lines
from lib.persian_hook_quality import audit_persian_hook_quality
from lib.persian_rendered_review import PersianRenderedReviewError, validate_rendered_hook_review
from lib.persian_srt import PersianCue
from lib.persian_workflow_telemetry import reconcile_phase_telemetry
from tools.video.persian_compose_script_aligned import ScriptAlignedPersianCompose


def _judgements() -> dict:
    return {
        field: {"level": "strong", "rationale": f"author claim for {field}"}
        for field in (
            "semanticPredictionError",
            "audienceRelevance",
            "concreteness",
            "hookBodyAlignment",
            "visualVoiceAlignment",
        )
    }


def _hook_edit(display_text: str, *, source_text: str, anchors: list[str]) -> dict:
    return {
        "metadata": {
            "target_platform": "instagram-reels",
            "hookQuality": {
                "version": "2.0",
                "viewerValue": {"atSeconds": 0.4, "evidence": "value", "evidenceId": "value-1"},
                "semanticTension": {
                    "kind": "contradiction",
                    "atSeconds": 0.7,
                    "evidence": "tension",
                    "evidenceId": "tension-1",
                },
                "firstProof": {
                    "atSeconds": 2.4,
                    "kind": "result",
                    "evidence": "proof",
                    "evidenceId": "proof-1",
                },
                "judgements": _judgements(),
                "flags": {"metaIntroDelay": False, "vagueGap": False, "fullConclusionRevealed": False},
                "perceptualChanges": [],
                "semanticIntegrity": {
                    "sourceText": source_text,
                    "requiredTopicAnchors": anchors,
                    "anchorDelivery": "text",
                },
            },
        },
        "persian": {
            "durationSeconds": 47.5,
            "shots": [],
            "moments": [
                {
                    "id": "hook-1",
                    "kind": "hook",
                    "startSeconds": 0.0,
                    "endSeconds": 2.9,
                    "segments": [{"role": "hero", "text": display_text}],
                }
            ],
            "typographicBeats": [{"id": "plate-1", "startSeconds": 0.0, "endSeconds": 2.9}],
        },
    }


def test_contextless_typographic_hook_cannot_borrow_topic_from_hidden_metadata() -> None:
    audit = audit_persian_hook_quality(
        _hook_edit("فقط وقت تلف کردنه؟", source_text="بازی فقط وقت تلف کردنه؟", anchors=["بازی"])
    )

    assert audit["disposition"] == "weak"
    assert audit["semanticIntegrity"]["missingAnchors"] == ["بازی"]
    assert any("HOOK_TOPIC_ANCHOR_MISSING" in problem for problem in audit["problems"])


def test_self_contained_typographic_hook_preserves_required_topic_anchor() -> None:
    audit = audit_persian_hook_quality(
        _hook_edit("بازی فقط وقت تلف کردنه؟", source_text="بازی فقط وقت تلف کردنه؟", anchors=["بازی"])
    )

    assert audit["problems"] == []
    assert audit["semanticIntegrity"]["anchorSatisfiedBy"] == "text"


def test_phrase_aware_caption_wrap_keeps_compound_predicate_together() -> None:
    lines = layout_caption_lines("کنیم فقط وقت تلف کردنه و سرگرمی!")

    assert lines != ["کنیم فقط وقت تلف", "کردنه و سرگرمی!"]
    assert any("وقت تلف کردنه" in line for line in lines)


def test_phrase_aware_caption_wrap_avoids_splitting_auxiliary_phrase() -> None:
    lines = layout_caption_lines("مدام باید حواسش جمع باشه، تصمیم بگیره،")

    assert not (lines[0].endswith("جمع") and lines[1].startswith("باشه"))


def test_runtime_injects_schema_compatible_hook_caption_handoff() -> None:
    runtime = ScriptAlignedPersianCompose._runtime_persian(
        {
            "metadata": {
                "hookCaptionHandoff": {
                    "mode": "semantic_replacement",
                    "resumeAtSeconds": 5.38,
                }
            },
            "persian": {"moments": []},
        }
    )

    assert runtime is not None
    assert runtime["_hookCaptionHandoff"]["mode"] == "semantic_replacement"
    assert "hookCaptionHandoff" not in runtime


def test_semantic_replacement_caption_handoff_skips_remainder_of_replaced_sentence() -> None:
    cues = [
        PersianCue("caption-1", "بزرگ‌ترین اشتباه درباره بازی‌های ویدیویی اینه که فکر", 0.0, 3.08),
        PersianCue("caption-2", "کنیم فقط وقت تلف کردنه و سرگرمی!", 3.08, 5.30),
        PersianCue("caption-3", "بررسی‌های علمی نشون می‌دن بازی کردن می‌تونه بعضی", 5.38, 8.26),
    ]
    persian = {
        "_hookCaptionHandoff": {"mode": "semantic_replacement", "resumeAtSeconds": 5.38},
        "moments": [{"kind": "hook", "startSeconds": 0.0, "endSeconds": 2.93}],
    }

    kept = ScriptAlignedPersianCompose._apply_hook_caption_handoff(cues, persian)

    assert [cue.id for cue in kept] == ["caption-3"]


def _hook_review(**overrides) -> dict:
    review = {
        "version": "2.0",
        "reviewSource": "rendered_mp4",
        "reviewerRole": "independent_reviewer",
        "reviewedCandidateSha256": "a" * 64,
        "strength": "acceptable",
        "rationale": "cold-view opening is understandable",
        "observations": ["0.8s hook is visible", "2.9s footage begins"],
        "mutedHookDirectionConfirmed": True,
        "visualVoiceAlignment": "acceptable",
        "concretePayoffKind": "result",
        "actualPayoffSeconds": 5.5,
        "payoffEvidence": "result begins in rendered captions",
        "payoffBeginsPromptly": True,
        "coldViewer": {
            "evidenceSource": "rendered_opening_only",
            "contextIsolated": True,
            "inferredTopic": "بازی‌های ویدیویی",
            "inferredClaim": "آیا بازی فقط وقت تلف کردن است؟",
            "continuationReason": "می‌خواهم پاسخ این تناقض را بدانم",
            "unresolvedReferents": [],
        },
    }
    review.update(overrides)
    return review


def test_passing_rendered_hook_review_requires_context_isolated_cold_viewer_evidence() -> None:
    validate_rendered_hook_review(_hook_review(), candidate_sha256="a" * 64, require_pass=True)

    broken = _hook_review()
    broken["coldViewer"] = {
        **broken["coldViewer"],
        "inferredTopic": "",
        "unresolvedReferents": ["چه چیزی وقت تلف کردنه؟"],
    }
    broken["mutedHookDirectionConfirmed"] = False

    with pytest.raises(PersianRenderedReviewError, match="cold-viewer"):
        validate_rendered_hook_review(broken, candidate_sha256="a" * 64, require_pass=True)


def test_terminal_workflow_reconciles_superseded_running_attempts() -> None:
    state = {
        "status": "awaiting_human",
        "completed_phases": ["render_final_candidate", "final_review", "awaiting_human"],
        "phase_telemetry": {
            "render_final_candidate": [
                {
                    "attempt": 1,
                    "started_at": "2026-09-16T10:15:22+00:00",
                    "finished_at": None,
                    "duration_seconds": None,
                    "execution_class": "external_durable",
                    "outcome": "running",
                },
                {
                    "attempt": 2,
                    "started_at": "2026-09-16T10:54:23+00:00",
                    "finished_at": "2026-09-16T11:17:03+00:00",
                    "duration_seconds": 1359.0,
                    "execution_class": "external_durable",
                    "outcome": "succeeded",
                },
            ]
        },
    }

    reconcile_phase_telemetry(state)

    first = state["phase_telemetry"]["render_final_candidate"][0]
    assert first["outcome"] == "superseded"
    assert first["finished_at"] == "2026-09-16T10:54:23+00:00"
    assert first["duration_seconds"] is not None
