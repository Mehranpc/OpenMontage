from __future__ import annotations

from lib.persian_assets import audit_asset_manifest


def _asset(*, event_id: str, candidate_id: str, identity_sha: str, start: float, end: float) -> dict:
    return {
        "beat_id": event_id,
        "visual_event_id": event_id,
        "kind": "video",
        "path": "shared.mp4",
        "provider": "pexels",
        "source_id": "source-123",
        "original_url": "https://example.test/video",
        "license": "Pexels License",
        "attribution": "Video by Example on Pexels",
        "source_in_seconds": start,
        "source_window_end_seconds": end,
        "asset_candidate_id": candidate_id,
        "asset_candidate_identity_sha256": identity_sha,
    }


def test_nonoverlapping_workspace_windows_may_reuse_one_source_file(tmp_path, monkeypatch) -> None:
    (tmp_path / "shared.mp4").write_bytes(b"x" * 64)
    monkeypatch.chdir(tmp_path)
    manifest = {
        "assets": [
            _asset(event_id="event-a", candidate_id="asset-a", identity_sha="a" * 64, start=0.0, end=4.0),
            _asset(event_id="event-b", candidate_id="asset-b", identity_sha="b" * 64, start=5.0, end=9.0),
        ]
    }
    assert audit_asset_manifest(manifest) == []


def test_overlapping_workspace_windows_from_one_source_still_fail(tmp_path, monkeypatch) -> None:
    (tmp_path / "shared.mp4").write_bytes(b"x" * 64)
    monkeypatch.chdir(tmp_path)
    manifest = {
        "assets": [
            _asset(event_id="event-a", candidate_id="asset-a", identity_sha="a" * 64, start=0.0, end=4.0),
            _asset(event_id="event-b", candidate_id="asset-b", identity_sha="b" * 64, start=3.5, end=8.0),
        ]
    }
    problems = audit_asset_manifest(manifest)
    assert any("reuses the clip" in problem for problem in problems)


def test_legacy_same_path_reuse_remains_rejected(tmp_path, monkeypatch) -> None:
    (tmp_path / "shared.mp4").write_bytes(b"x" * 64)
    monkeypatch.chdir(tmp_path)
    first = _asset(event_id="event-a", candidate_id="asset-a", identity_sha="a" * 64, start=0.0, end=4.0)
    second = _asset(event_id="event-b", candidate_id="asset-b", identity_sha="b" * 64, start=5.0, end=9.0)
    for asset in (first, second):
        asset.pop("asset_candidate_id")
        asset.pop("asset_candidate_identity_sha256")
        asset.pop("source_window_end_seconds")
    problems = audit_asset_manifest({"assets": [first, second]})
    assert any("reuses the clip" in problem for problem in problems)
