from __future__ import annotations

from pathlib import Path

import pytest

from lib.persian_edit_contract import PersianEditContractError
import lib.persian_preflight as preflight
from lib.checkpoint import validate_checkpoint
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


def test_aggregate_report_preserves_structured_film_type_failure(monkeypatch, tmp_path: Path) -> None:
    from lib.persian_film_type import FilmTypePreflightError
    from lib.persian_preflight import aggregate_preflight_edit_decisions
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"fixture")
    payload = _payload("clip.mp4")

    def refuse(*args, **kwargs):
        raise FilmTypePreflightError(
            "coverage refused", code="WATERMARK_COVERAGE",
            diagnostics={"coverageRatio": 0.52, "coverageFloor": 0.7, "topBlockers": [{"shotId": "shot-9"}]},
        )

    monkeypatch.setattr(NoCopyPersianCompose, "_build_props", refuse)
    report = aggregate_preflight_edit_decisions(payload, base_dir=tmp_path)
    assert report["ok"] is False
    assert report["blockingIssues"][0]["code"] == "WATERMARK_COVERAGE"
    assert report["watermarkDiagnostics"]["coverageRatio"] == 0.52
    assert report["watermarkDiagnostics"]["topBlockers"][0]["shotId"] == "shot-9"
    assert report["mediaCopies"] == 0


def test_cli_persists_refusal_report(tmp_path: Path, monkeypatch) -> None:
    from lib.persian_preflight import main
    source = tmp_path / "edit.json"
    report_path = tmp_path / "preflight_report.json"
    source.write_text('{"persian": {"shots": [{"width": 1}]}}', encoding="utf-8")
    code = main([str(source), "--output", str(report_path)])
    assert code == 2
    report = __import__("json").loads(report_path.read_text(encoding="utf-8"))
    assert report["ok"] is False
    assert report["blockingIssues"]


def test_cutless_persian_bytes_pass_preflight_contract_and_checkpoint_schema(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"fixture")
    payload = {
        "version": "1.0",
        "render_runtime": "remotion",
        "renderer_family": "persian-footage",
        "composition_mode": "templated",
        **_payload(str(source)),
    }
    monkeypatch.setattr(preflight, "audit_persian_retention", lambda _: {"problems": []})
    monkeypatch.setattr(
        preflight, "browser_preflight_edit_decisions",
        lambda edit, base_dir=None: {"warnings": [], "watermarkDiagnostics": None},
    )
    report = preflight.aggregate_preflight_edit_decisions(payload, base_dir=tmp_path)
    assert report["ok"] is True, report

    checkpoint = {
        "version": "1.0",
        "project_id": "run",
        "pipeline_type": "persian-footage",
        "stage": "edit",
        "status": "completed",
        "timestamp": "2026-09-14T00:00:00+00:00",
        "checkpoint_policy": "guided",
        "human_approval_required": False,
        "human_approved": False,
        "artifacts": {"edit_decisions": payload},
    }
    validate_checkpoint(checkpoint)


def test_reels_preflight_refuses_structural_pass_with_weak_hook_evidence(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from lib.persian_preflight import aggregate_preflight_edit_decisions

    source = tmp_path / "clip.mp4"
    source.write_bytes(b"fixture")
    payload = _payload(str(source))
    payload["persian"]["platformTarget"] = "instagram-reels"
    payload["metadata"] = {
        "hookQuality": {
            "version": "2.0",
            "viewerValue": {
                "atSeconds": 4.96,
                "evidence": "The paradox is not complete until the first sentence ends.",
            },
            "semanticTension": {
                "kind": "contradiction",
                "atSeconds": 4.96,
                "evidence": "Slow can be faster, but the contradiction lands late.",
            },
            "firstProof": {
                "kind": "example",
                "atSeconds": 7.74,
                "evidence": "The first concrete example starts after the meta-intro.",
            },
            "judgements": {
                "semanticPredictionError": {"level": "acceptable", "rationale": "There is a real paradox."},
                "audienceRelevance": {"level": "acceptable", "rationale": "Progress is relevant but broad."},
                "concreteness": {"level": "weak", "rationale": "The opening starts with abstract progress language."},
                "hookBodyAlignment": {"level": "strong", "rationale": "The body does explain the opening claim."},
                "visualVoiceAlignment": {"level": "weak", "rationale": "Calm notebook B-roll does not express the contradiction."},
            },
            "flags": {
                "metaIntroDelay": True,
                "vagueGap": False,
                "fullConclusionRevealed": True,
            },
        }
    }

    def should_not_run(*args, **kwargs):  # pragma: no cover - assertion helper
        raise AssertionError("browser preparation must not run for a hook-quality refusal")

    monkeypatch.setattr(NoCopyPersianCompose, "_build_props", should_not_run)
    report = aggregate_preflight_edit_decisions(payload, base_dir=tmp_path)

    assert report["ok"] is False
    assert report["blockingIssues"][0]["code"] == "HOOK_QUALITY_GATE"
    audit = report["evidence"]["hookQualityAudit"]
    assert audit["disposition"] == "weak"
    assert audit["timing"]["timeToValueSeconds"] == 4.96
    assert audit["timing"]["timeToFirstProofSeconds"] == 7.74
    assert any("viewer value arrives" in problem for problem in audit["problems"])
