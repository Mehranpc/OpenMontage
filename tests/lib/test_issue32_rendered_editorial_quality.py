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


def _phrase_metrics() -> list[dict]:
    return [
        {"semanticRole": "setup", "fontSizePx": 64, "visualRows": 1, "inkHex": "#FFFFFF"},
        {"semanticRole": "bridge", "fontSizePx": 48, "visualRows": 1, "inkHex": "#FFFFFF"},
        {"semanticRole": "subject_hero", "fontSizePx": 118, "visualRows": 1, "inkHex": "#FFEA00"},
        {"semanticRole": "connector", "fontSizePx": 48, "visualRows": 1, "inkHex": "#FFFFFF"},
        {"semanticRole": "payoff", "fontSizePx": 76, "visualRows": 1, "inkHex": "#FFFFFF"},
    ]


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
        "backgroundComplexity": "busy",
        "blockScrimVisible": True,
        "blockScrimFeathered": True,
        "glyphSeparationStrong": True,
        "phoneScaleReadable": True,
        "fullFrameDarkening": False,
        "phraseMetrics": _phrase_metrics(),
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


def test_rendered_pixels_must_prove_semantic_hierarchy_and_one_row_subject_hero() -> None:
    near_flat = _phrase_metrics()
    near_flat[2] = {**near_flat[2], "fontSizePx": 78}
    with pytest.raises(PersianRenderedReviewError, match="near-flat"):
        validate_rendered_hook_review(
            _review(_visual_v2(phraseMetrics=near_flat)), candidate_sha256=DIGEST, require_pass=True
        )

    wrapped_hero = _phrase_metrics()
    wrapped_hero[2] = {**wrapped_hero[2], "visualRows": 2}
    with pytest.raises(PersianRenderedReviewError, match="one visual row"):
        validate_rendered_hook_review(
            _review(_visual_v2(phraseMetrics=wrapped_hero)), candidate_sha256=DIGEST, require_pass=True
        )

    wrong_subject_color = _phrase_metrics()
    wrong_subject_color[2] = {**wrong_subject_color[2], "inkHex": "#FFFFFF"}
    with pytest.raises(PersianRenderedReviewError, match="subject_hero.*#FFEA00"):
        validate_rendered_hook_review(
            _review(_visual_v2(phraseMetrics=wrong_subject_color)), candidate_sha256=DIGEST, require_pass=True
        )


def test_busy_background_requires_feathered_block_scrim_but_simple_fixture_does_not() -> None:
    for override, message in [
        ({"blockScrimVisible": False}, "block-level.*scrim"),
        ({"blockScrimFeathered": False}, "feathered"),
        ({"glyphSeparationStrong": False}, "glyph separation"),
        ({"phoneScaleReadable": False}, "phone scale"),
        ({"fullFrameDarkening": True}, "full-frame"),
    ]:
        with pytest.raises(PersianRenderedReviewError, match=message):
            validate_rendered_hook_review(
                _review(_visual_v2(**override)), candidate_sha256=DIGEST, require_pass=True
            )

    simple = _visual_v2(
        backgroundComplexity="simple",
        blockScrimVisible=False,
        blockScrimFeathered=False,
        glyphSeparationStrong=False,
    )
    validate_rendered_hook_review(_review(simple), candidate_sha256=DIGEST, require_pass=True)
