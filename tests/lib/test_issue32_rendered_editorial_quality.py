from __future__ import annotations

import pytest

from lib.persian_rendered_review import PersianRenderedReviewError, validate_rendered_hook_review

DIGEST = "a" * 64


def _review(visual: dict) -> dict:
    return {
        "version": "2.0",
        "reviewSource": "rendered_mp4",
        "reviewerRole": "independent_reviewer",
        "reviewedCandidateSha256": DIGEST,
        "strength": "strong",
        "rationale": "The muted opening is a designed editorial hook, not a subtitle-like overlay.",
        "observations": ["The subject and tension are readable on mute.", "The yellow phrase is the semantic hero."],
        "mutedHookDirectionConfirmed": True,
        "coldViewer": {
            "evidenceSource": "rendered_opening_only",
            "contextIsolated": True,
            "inferredTopic": "بازی‌های ویدیویی",
            "inferredClaim": "بازی فقط وقت تلف کردن نیست",
            "continuationReason": "می‌خواهم بدانم اثر واقعی چیست",
            "unresolvedReferents": [],
        },
        "visualTypography": visual,
        "visualVoiceAlignment": "strong",
        "actualPayoffSeconds": 4.2,
        "concretePayoffKind": "result",
        "payoffEvidence": "The first evidence-backed result begins by 4.2 seconds.",
        "payoffBeginsPromptly": True,
    }


def _visual_v2(**overrides) -> dict:
    value = {
        "policyVersion": "2.0",
        "evidenceSource": "rendered_opening_pixels",
        "recipeId": "editorial-hero-balanced",
        "occupancyRatio": 0.38,
        "durationSeconds": 4.0,
        "hierarchyPassed": True,
        "emphasisPassed": True,
        "lineBalancePassed": True,
        "opticalPlacementPassed": True,
        "displayFontFamily": "KahrobaEditorial",
        "alignment": "right",
        "wholeHookVisible": True,
        "semanticYellowVisible": True,
        "semanticAccentHex": "#FFEA00",
        "supportInkHex": "#FFFFFF",
        "plainSubtitleLike": False,
        "localContrastFieldVisible": True,
    }
    value.update(overrides)
    return value


def test_editorial_visual_policy_v2_requires_kahroba_white_yellow_and_complete_hook() -> None:
    validate_rendered_hook_review(_review(_visual_v2()), candidate_sha256=DIGEST, require_pass=True)

    bad_cases = [
        ({"displayFontFamily": "Estedad"}, "Kahroba"),
        ({"alignment": "left"}, "right or center"),
        ({"semanticYellowVisible": False}, "yellow"),
        ({"semanticAccentHex": "#1789FC"}, "#FFEA00"),
        ({"supportInkHex": "#EEEEEE"}, "#FFFFFF"),
        ({"wholeHookVisible": False}, "whole hook"),
        ({"plainSubtitleLike": True}, "subtitle-like"),
        ({"localContrastFieldVisible": False}, "contrast"),
    ]
    for override, message in bad_cases:
        with pytest.raises(PersianRenderedReviewError, match=message):
            validate_rendered_hook_review(
                _review(_visual_v2(**override)), candidate_sha256=DIGEST, require_pass=True
            )
