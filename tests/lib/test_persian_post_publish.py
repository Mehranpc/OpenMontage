from __future__ import annotations

import copy

import pytest

from lib.persian_post_publish import PostPublishPerformanceError, append_performance_snapshot


def _record() -> dict:
    return {
        "version": "1.0",
        "project_id": "project-1",
        "platform": "instagram-reels",
        "published_at": "2026-09-14T08:00:00Z",
        "published_render": {
            "path": "renders/final.mp4",
            "sha256": "a" * 64,
        },
        "hook_quality": {
            "opening_hook_text": "هوک",
            "preflight_disposition": "acceptable",
            "preflight_audit": {"version": "1.0", "disposition": "acceptable"},
        },
        "calibration_mode": "observational",
        "snapshots": [
            {
                "checkpoint": "1h",
                "captured_at": "2026-09-14T09:00:00Z",
                "hours_since_publish": 1.0,
                "views": 1000,
            }
        ],
    }


def test_append_snapshot_returns_new_history_without_mutating_existing_record():
    original = _record()
    before = copy.deepcopy(original)
    snapshot = {
        "checkpoint": "4h",
        "captured_at": "2026-09-14T12:00:00Z",
        "hours_since_publish": 4.0,
        "views": 2500,
        "skip_rate": 0.4,
    }

    updated = append_performance_snapshot(original, snapshot)

    assert original == before
    assert [item["checkpoint"] for item in updated["snapshots"]] == ["1h", "4h"]
    assert updated["snapshots"][-1]["views"] == 2500


def test_append_snapshot_refuses_duplicate_checkpoint_or_time_regression():
    record = _record()
    with pytest.raises(PostPublishPerformanceError, match="checkpoint"):
        append_performance_snapshot(record, {
            "checkpoint": "1h",
            "captured_at": "2026-09-14T09:30:00Z",
            "hours_since_publish": 1.5,
        })
    with pytest.raises(PostPublishPerformanceError, match="hours_since_publish"):
        append_performance_snapshot(record, {
            "checkpoint": "4h",
            "captured_at": "2026-09-14T08:30:00Z",
            "hours_since_publish": 0.5,
        })
