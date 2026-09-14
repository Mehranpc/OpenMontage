from __future__ import annotations

import pytest
from jsonschema import ValidationError

from schemas.artifacts import validate_artifact


def _record() -> dict:
    return {
        "version": "1.0",
        "project_id": "rewards-of-slowness-20260913-072138-698797fd",
        "platform": "instagram-reels",
        "published_at": "2026-09-14T08:00:00Z",
        "published_render": {
            "path": "renders/final-candidate-pixabay-music-01.mp4",
            "sha256": "9e9bf1581bd41531f09d460fd34a13adae39ac22510885f93226ae94d0b457ae",
        },
        "hook_quality": {
            "opening_hook_text": "آهسته‌تر جلو برو",
            "preflight_disposition": "weak",
            "preflight_audit": {"version": "1.0", "disposition": "weak"},
        },
        "calibration_mode": "observational",
        "snapshots": [
            {
                "checkpoint": "4h",
                "captured_at": "2026-09-14T12:00:00Z",
                "hours_since_publish": 4.0,
                "views": 11154,
                "viewers": 7796,
                "average_watch_time_seconds": 6.0,
                "skip_rate": 0.609,
                "likes": 228,
                "comments": 3,
                "reposts": 2,
                "shares": 69,
                "saves": 65,
                "follows": 0,
                "view_sources": {
                    "feed": 0.948,
                    "stories": 0.024,
                    "reels_tab": 0.022,
                    "explore": 0.004,
                    "profile": 0.001,
                },
                "retention_points": [
                    {"at_seconds": 0.0, "viewer_ratio": 1.0},
                    {"at_seconds": 3.0, "viewer_ratio": 0.39},
                ],
            }
        ],
    }


def test_post_publish_performance_schema_accepts_digest_bound_observational_history():
    validate_artifact("post_publish_performance", _record())


def test_post_publish_performance_schema_rejects_non_sha_render_binding():
    record = _record()
    record["published_render"]["sha256"] = "not-a-digest"
    with pytest.raises(ValidationError):
        validate_artifact("post_publish_performance", record)


def test_post_publish_performance_schema_rejects_invalid_or_inconsistent_timestamps():
    invalid = _record()
    invalid["published_at"] = "not-a-timestamp"
    with pytest.raises(ValidationError):
        validate_artifact("post_publish_performance", invalid)

    before_publish = _record()
    before_publish["snapshots"][0]["captured_at"] = "2026-09-14T07:00:00Z"
    with pytest.raises(ValidationError):
        validate_artifact("post_publish_performance", before_publish)

    inconsistent_hours = _record()
    inconsistent_hours["snapshots"][0]["hours_since_publish"] = 24.0
    with pytest.raises(ValidationError):
        validate_artifact("post_publish_performance", inconsistent_hours)
