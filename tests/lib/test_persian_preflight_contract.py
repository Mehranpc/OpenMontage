from __future__ import annotations

from pathlib import Path

import pytest

from lib.persian_edit_contract import PersianEditContractError
from lib.persian_preflight import NoCopyPersianCompose, preflight_edit_decisions


def _payload(source: str = "clip.mp4") -> dict:
    return {
        "persian": {
            "format": "vertical",
            "durationSeconds": 12.0,
            "shots": [
                {
                    "id": "shot-1",
                    "source": source,
                    "startSeconds": 0.0,
                    "endSeconds": 12.0,
                    "camera": "none",
                    "attribution": "Video by Test on Pexels",
                    "avoidRegions": [{"x": 0.1, "y": 0.2, "w": 0.3, "h": 0.4}],
                }
            ],
            "moments": [
                {
                    "id": "moment-1",
                    "kind": "hook",
                    "startSeconds": 0.2,
                    "endSeconds": 4.2,
                    "segments": [
                        {"role": "hero", "text": "آهسته‌تر جلو برو", "accentWords": ["آهسته‌تر"]}
                    ],
                }
            ],
            "typographicBeats": [],
            "audio": {},
            "watermark": {"persianText": "طریقت تسلیم", "latinText": "Pathway_of_Surrender"},
        }
    }


def test_contract_failure_happens_before_browser_or_retention(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = _payload()
    region = payload["persian"]["shots"][0]["avoidRegions"][0]
    region["width"] = region.pop("w")

    def should_not_run(*args, **kwargs):  # pragma: no cover - assertion helper
        raise AssertionError("browser preparation must not run for a contract-invalid edit")

    monkeypatch.setattr(NoCopyPersianCompose, "_build_props", should_not_run)
    with pytest.raises(PersianEditContractError) as caught:
        preflight_edit_decisions(payload)
    assert any(
        item.pointer == "/persian/shots/0/avoidRegions/0/width"
        and item.hint
        and "'w'" in item.hint
        for item in caught.value.diagnostics
    )


def test_missing_asset_is_aggregate_preflight_failure_before_browser(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    payload = _payload("missing.mp4")

    def should_not_run(*args, **kwargs):  # pragma: no cover - assertion helper
        raise AssertionError("browser preparation must not run when a media path is missing")

    monkeypatch.setattr(NoCopyPersianCompose, "_build_props", should_not_run)
    with pytest.raises(PersianEditContractError) as caught:
        preflight_edit_decisions(payload, base_dir=tmp_path)
    assert any(
        item.code == "path.missing" and item.pointer == "/persian/shots/0/source"
        for item in caught.value.diagnostics
    )
