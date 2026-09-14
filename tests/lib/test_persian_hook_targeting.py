from __future__ import annotations

from pathlib import Path

import pytest

from lib.persian_preflight import NoCopyPersianCompose, aggregate_preflight_edit_decisions
from tests.lib.test_persian_preflight_contract import _payload


def test_instagram_reels_metadata_target_requires_hook_quality_before_browser(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"fixture")
    payload = _payload(str(source))
    payload["metadata"] = {"target_platform": "instagram-reels"}

    def should_not_run(*args, **kwargs):  # pragma: no cover - assertion helper
        raise AssertionError("browser preparation must not run before hook evidence exists")

    monkeypatch.setattr(NoCopyPersianCompose, "_build_props", should_not_run)
    report = aggregate_preflight_edit_decisions(payload, base_dir=tmp_path)

    assert report["ok"] is False
    assert report["blockingIssues"][0]["code"] == "HOOK_QUALITY_GATE"
    assert report["evidence"]["hookQualityAudit"]["platformTarget"] == "instagram-reels"
    assert any("requires metadata.hookQuality" in item["message"] for item in report["blockingIssues"])
