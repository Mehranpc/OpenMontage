from __future__ import annotations

from pathlib import Path

from lib.persian_assets import audit_asset_manifest


def _event(event_id: str, duration: float = 2.0) -> dict:
    return {
        "id": event_id,
        "duration_seconds": duration,
        "narration_span": "بازی و توجه",
        "queries": ["focused gamer controller", "gamer reaction console"],
        "desired_affect": "attention",
        "human_presence": True,
        "shows_subject": True,
        "fallback_level": "exact_literal",
        "importance": 2,
    }


def _asset(path: Path, event_id: str, start: float, end: float) -> dict:
    return {
        "beat_id": "b1",
        "semantic_beat_id": "b1",
        "visual_event_id": event_id,
        "kind": "video",
        "path": str(path),
        "duration_seconds": 12.0,
        "source_in_seconds": start,
        "source_window_end_seconds": end,
        "width": 1080,
        "height": 1920,
        "provider": "pexels",
        "source_id": "12345",
        "original_url": "https://example.test/video",
        "license": "Pexels License",
        "attribution": "Video by Creator on Pexels",
        "narration_span": "بازی و توجه",
        "query": "focused gamer controller",
        "candidate_rank": 1,
        "selection_reason": "بازیکن و کنترلر در تمام پنجره دیده می‌شوند",
        "relevance_reason": "پنجرهٔ انتخابی مستقیماً بازی و توجه را نشان می‌دهد",
        "affect_match": True,
        "staged_stock_risk": "low",
        "human_presence": True,
        "shows_subject": True,
        "fallback_level": "exact_literal",
        "frame_review": {
            "start": True,
            "middle": True,
            "end": True,
            "observed": "بازیکن و کنترلر در قاب می‌مانند",
        },
    }


def _scene_plan() -> dict:
    return {
        "beats": [{
            "id": "b1",
            "duration_seconds": 4.0,
            "visual_events": [_event("e1"), _event("e2")],
        }]
    }


def test_same_source_distinct_non_overlapping_windows_are_legal(tmp_path: Path) -> None:
    clip = tmp_path / "long-source.mp4"
    clip.write_bytes(b"x" * 64)
    manifest = {
        "assets": [
            _asset(clip, "e1", 0.0, 2.0),
            _asset(clip, "e2", 3.0, 5.0),
        ]
    }

    assert audit_asset_manifest(manifest, _scene_plan()) == []


def test_same_source_overlapping_windows_are_rejected_even_with_distinct_local_paths(tmp_path: Path) -> None:
    first = tmp_path / "source-a.mp4"
    second = tmp_path / "source-a-copy.mp4"
    first.write_bytes(b"x" * 64)
    second.write_bytes(b"x" * 64)
    manifest = {
        "assets": [
            _asset(first, "e1", 0.0, 2.0),
            _asset(second, "e2", 1.5, 3.5),
        ]
    }

    problems = audit_asset_manifest(manifest, _scene_plan())
    assert any("overlapping source-time window" in problem for problem in problems)
