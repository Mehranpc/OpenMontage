from __future__ import annotations

from pathlib import Path

import pytest

from lib.persian_preflight import NoCopyPersianCompose, aggregate_preflight_edit_decisions
from tests.lib.test_persian_preflight_contract import _payload


def _base_hook() -> dict:
    return {
        "version": "1.0",
        "valueProposition": {"atSeconds": 0.5, "evidence": "Concrete value is visible."},
        "semanticTension": {"kind": "contradiction", "atSeconds": 0.7, "evidence": "Specific contradiction."},
        "firstProof": {"atSeconds": 1.4, "evidence": "Concrete proof begins."},
        "judgements": {
            key: {"level": "strong", "rationale": f"strong {key}"}
            for key in (
                "semanticPredictionError",
                "audienceRelevance",
                "concreteness",
                "hookBodyAlignment",
                "visualVoiceAlignment",
            )
        },
        "flags": {"metaIntroDelay": False, "vagueGap": False, "fullConclusionRevealed": False},
        "perceptualChanges": [{"kind": "action", "atSeconds": 0.8, "evidence": "Visible action."}],
    }


def _report(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, hook: dict) -> dict:
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"fixture")
    payload = _payload(str(source))
    payload["metadata"] = {"target_platform": "instagram-reels", "hookQuality": hook}

    def should_not_run(*_args, **_kwargs):
        raise AssertionError("browser must not run after hook refusal")

    monkeypatch.setattr(NoCopyPersianCompose, "_build_props", should_not_run)
    return aggregate_preflight_edit_decisions(payload, base_dir=tmp_path)


def test_visual_voice_mismatch_requests_visual_revision(monkeypatch, tmp_path):
    hook = _base_hook()
    hook["judgements"]["visualVoiceAlignment"] = {
        "level": "weak",
        "rationale": "Decorative footage does not depict the spoken conflict.",
    }
    report = _report(monkeypatch, tmp_path, hook)
    issue = next(item for item in report["blockingIssues"] if "visualVoiceAlignment" in item["message"])
    assert issue["recoveryClass"] == "HOOK_VISUAL_ALIGNMENT"


def test_late_proof_requests_timing_revision(monkeypatch, tmp_path):
    hook = _base_hook()
    hook["firstProof"] = {"atSeconds": 7.0, "evidence": "Proof starts too late."}
    report = _report(monkeypatch, tmp_path, hook)
    issue = next(item for item in report["blockingIssues"] if "first proof/example" in item["message"])
    assert issue["recoveryClass"] == "HOOK_TIMING"


def test_vague_gap_requests_authoring_revision(monkeypatch, tmp_path):
    hook = _base_hook()
    hook["flags"]["vagueGap"] = True
    report = _report(monkeypatch, tmp_path, hook)
    issue = next(item for item in report["blockingIssues"] if "too vague" in item["message"])
    assert issue["recoveryClass"] == "HOOK_AUTHORING"
