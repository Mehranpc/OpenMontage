from __future__ import annotations

from pathlib import Path

import pytest

from lib import persian_asset_workspace as workspace
from lib.persian_asset_workspace import PersianAssetWorkspaceError
from lib.persian_rendered_review import PersianRenderedReviewError, validate_rendered_hook_review

DIGEST = "a" * 64


def _discovered(project: Path, source_id: str) -> dict:
    path = project / "assets" / f"{source_id}.mp4"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"video")
    return {
        "clip_id": f"pexels-{source_id}",
        "source": "pexels",
        "source_id": source_id,
        "source_url": f"https://example.test/{source_id}",
        "query": "gamer controller close up",
        "slot_id": "event-hook",
        "kind": "video",
        "path": str(path),
        "duration": 12.0,
        "width": 1080,
        "height": 1920,
        "creator": "Creator",
        "license": "Stock License",
        "source_tags": ["gamer", "controller"],
    }


def _stage(project: Path, discovery_id: str, *, event: str, narrative_role: str) -> dict:
    return workspace.stage_asset_candidate(
        project,
        discovery_id=discovery_id,
        visual_event_id=event,
        semantic_beat_id="beat-1",
        narrative_role=narrative_role,
        source_in_seconds=0.0,
        duration_seconds=4.0,
        intended_crop={"mode": "full_frame", "x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0},
        candidate_rank=1,
        query="gamer controller close up",
        narration_span="بازی‌های ویدیویی",
    )


def _asset_review(*, editorial_text_safe: bool | None = None) -> dict:
    geometry = {
        "crop_safe": True,
        "observed": "Subject stays visible across start, middle, and end.",
    }
    if editorial_text_safe is not None:
        geometry["editorial_text_safe"] = editorial_text_safe
    return {
        "frame_review": {
            "start": True,
            "middle": True,
            "end": True,
            "observed": "Player and controller remain visible throughout the selected window.",
        },
        "shows_subject": True,
        "human_presence": True,
        "affect_match": True,
        "staged_stock_risk": "low",
        "relevance_reason": "Visible gaming matches the opening topic.",
        "selection_reason": "The selected window clearly shows active controller play.",
        "geometry_review": geometry,
        "resolution_quality": "strong",
    }


def test_hook_asset_selection_requires_explicit_editorial_text_safety(tmp_path: Path) -> None:
    project = tmp_path / "project"
    ids = workspace.record_discovery_pass(
        project,
        0,
        [_discovered(project, "unsafe"), _discovered(project, "safe")],
    )["candidateIds"]
    unsafe = _stage(project, ids[0], event="event-hook-unsafe", narrative_role="hook")
    safe = _stage(project, ids[1], event="event-hook-safe", narrative_role="hook")
    workspace.record_candidate_review(project, unsafe["candidateId"], _asset_review())
    workspace.record_candidate_review(
        project, safe["candidateId"], _asset_review(editorial_text_safe=True)
    )

    with pytest.raises(PersianAssetWorkspaceError, match="editorial text safety"):
        workspace.select_asset_candidate(
            project, "event-hook-unsafe", unsafe["candidateId"], rejected_alternatives={}
        )
    selected = workspace.select_asset_candidate(
        project, "event-hook-safe", safe["candidateId"], rejected_alternatives={}
    )
    assert selected["selected"] is True


def test_non_hook_asset_keeps_backward_compatible_geometry_review(tmp_path: Path) -> None:
    project = tmp_path / "project"
    discovery_id = workspace.record_discovery_pass(
        project, 0, [_discovered(project, "body")]
    )["candidateIds"][0]
    candidate = _stage(project, discovery_id, event="event-body", narrative_role="exposition")
    workspace.record_candidate_review(project, candidate["candidateId"], _asset_review())
    selected = workspace.select_asset_candidate(
        project, "event-body", candidate["candidateId"], rejected_alternatives={}
    )
    assert selected["selected"] is True


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
        "subjectOverlapAcceptable": True,
        "displayFontFamily": "KahrobaEditorial",
        "alignment": "right",
        "wholeHookVisible": True,
        "semanticYellowVisible": True,
        "semanticAccentHex": "#FFEA00",
        "supportInkHex": "#FFFFFF",
        "plainSubtitleLike": False,
        "localContrastFieldVisible": True,
        "backgroundComplexity": "simple",
        "phoneScaleReadable": True,
        "fullFrameDarkening": False,
        "phraseMetrics": [
            {"semanticRole": "setup", "fontSizePx": 64, "visualRows": 1, "inkHex": "#FFFFFF"},
            {"semanticRole": "subject_hero", "fontSizePx": 118, "visualRows": 1, "inkHex": "#FFEA00"},
            {"semanticRole": "payoff", "fontSizePx": 76, "visualRows": 1, "inkHex": "#FFFFFF"},
        ],
    }
    value.update(overrides)
    return value


def _rendered_review(visual: dict) -> dict:
    return {
        "version": "2.0",
        "reviewSource": "rendered_mp4",
        "reviewerRole": "independent_reviewer",
        "reviewedCandidateSha256": DIGEST,
        "strength": "acceptable",
        "rationale": "The rendered opening was inspected at phone scale.",
        "observations": [
            "The subject and hook are readable on mute.",
            "Typography placement was inspected relative to the visible person.",
        ],
        "mutedHookDirectionConfirmed": True,
        "coldViewer": {
            "evidenceSource": "rendered_opening_only",
            "contextIsolated": True,
            "inferredTopic": "بازی‌های ویدیویی",
            "inferredClaim": "یک برداشت رایج درباره بازی به چالش کشیده می‌شود",
            "continuationReason": "می‌خواهم شواهد را ببینم",
            "unresolvedReferents": [],
        },
        "visualTypography": visual,
        "visualVoiceAlignment": "acceptable",
        "actualPayoffSeconds": 4.2,
        "concretePayoffKind": "evidence",
        "payoffEvidence": "Concrete evidence begins in the opening window.",
        "payoffBeginsPromptly": True,
    }


def test_rendered_visual_typography_v2_requires_explicit_acceptable_subject_overlap() -> None:
    validate_rendered_hook_review(
        _rendered_review(_visual_v2()), candidate_sha256=DIGEST, require_pass=True
    )

    for value in (None, False):
        visual = _visual_v2()
        if value is None:
            visual.pop("subjectOverlapAcceptable")
        else:
            visual["subjectOverlapAcceptable"] = value
        with pytest.raises(PersianRenderedReviewError, match="subject overlap"):
            validate_rendered_hook_review(
                _rendered_review(visual), candidate_sha256=DIGEST, require_pass=True
            )
