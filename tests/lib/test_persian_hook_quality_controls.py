from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from lib.persian_preflight import NoCopyPersianCompose, aggregate_preflight_edit_decisions
from tests.lib.test_persian_preflight_contract import _payload


def _judgements(**levels: str) -> dict:
    defaults = {
        "semanticPredictionError": "strong",
        "audienceRelevance": "strong",
        "concreteness": "strong",
        "hookBodyAlignment": "strong",
        "visualVoiceAlignment": "strong",
    }
    defaults.update(levels)
    return {
        field: {"level": level, "rationale": f"fixture rationale for {field}: {level}"}
        for field, level in defaults.items()
    }


def _hook(**overrides) -> dict:
    value = {
        "version": "1.0",
        "valueProposition": {"atSeconds": 0.45, "evidence": "The viewer knows the concrete benefit immediately."},
        "semanticTension": {
            "kind": "contradiction",
            "atSeconds": 0.7,
            "evidence": "The opening states a specific expectation-breaking claim.",
        },
        "firstProof": {"atSeconds": 1.45, "evidence": "A concrete example starts inside the opening."},
        "judgements": _judgements(),
        "flags": {"metaIntroDelay": False, "vagueGap": False, "fullConclusionRevealed": False},
        "perceptualChanges": [
            {"kind": "action", "atSeconds": 0.8, "evidence": "The subject visibly performs the claimed action."}
        ],
    }
    for key, replacement in overrides.items():
        value[key] = replacement
    return value


def _run(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, hook: dict) -> dict:
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"fixture")
    payload = _payload(str(source))
    payload["metadata"] = {"target_platform": "instagram-reels", "hookQuality": hook}

    def fake_build(_self, persian, *_args, **_kwargs):
        return deepcopy(persian), ["Video by Test on Pexels"]

    monkeypatch.setattr(NoCopyPersianCompose, "_build_props", fake_build)
    return aggregate_preflight_edit_decisions(payload, base_dir=tmp_path)


def test_specific_contradiction_with_prompt_proof_is_strong(monkeypatch, tmp_path):
    report = _run(monkeypatch, tmp_path, _hook())
    assert report["ok"] is True, report
    audit = report["evidence"]["hookQualityAudit"]
    assert audit["disposition"] == "strong"
    assert audit["problems"] == []
    assert audit["timing"]["timeToFirstProofSeconds"] == 1.45


def test_semantically_strong_but_visually_static_hook_is_acceptable(monkeypatch, tmp_path):
    hook = _hook(perceptualChanges=[])
    report = _run(monkeypatch, tmp_path, hook)
    assert report["ok"] is True, report
    audit = report["evidence"]["hookQualityAudit"]
    assert audit["disposition"] == "acceptable"
    assert audit["perceptual"]["meaningfulChangeCountFirst3Seconds"] == 0
    assert any("no evidenced meaningful" in item for item in audit["advisories"])


def test_specific_question_gap_can_be_strong(monkeypatch, tmp_path):
    hook = _hook(
        semanticTension={
            "kind": "question",
            "atSeconds": 0.55,
            "evidence": "The viewer can name the exact missing answer.",
        }
    )
    report = _run(monkeypatch, tmp_path, hook)
    assert report["ok"] is True, report
    assert report["evidence"]["hookQualityAudit"]["disposition"] == "strong"


@pytest.mark.parametrize(
    ("hook", "needle"),
    [
        (
            _hook(flags={"metaIntroDelay": False, "vagueGap": True, "fullConclusionRevealed": False}),
            "too vague",
        ),
        (
            _hook(judgements=_judgements(visualVoiceAlignment="weak")),
            "visualVoiceAlignment is weak",
        ),
        (
            _hook(firstProof={"atSeconds": 6.5, "evidence": "The first example is delayed."}),
            "first proof/example arrives",
        ),
        (
            _hook(
                judgements=_judgements(audienceRelevance="weak"),
                perceptualChanges=[
                    {"kind": "action", "atSeconds": 0.3, "evidence": "change 1"},
                    {"kind": "reaction", "atSeconds": 0.7, "evidence": "change 2"},
                    {"kind": "detail", "atSeconds": 1.1, "evidence": "change 3"},
                    {"kind": "scale_change", "atSeconds": 1.5, "evidence": "change 4"},
                    {"kind": "reveal", "atSeconds": 1.9, "evidence": "change 5"},
                ],
            ),
            "audienceRelevance is weak",
        ),
    ],
)
def test_semantically_weak_hooks_block_even_when_structurally_busy(
    monkeypatch, tmp_path, hook, needle
):
    report = _run(monkeypatch, tmp_path, hook)
    assert report["ok"] is False
    assert all(issue["code"] == "HOOK_QUALITY_GATE" for issue in report["blockingIssues"])
    assert any(needle in issue["message"] for issue in report["blockingIssues"])


@pytest.mark.parametrize(
    ("hook", "needle"),
    [
        (
            _hook(flags={"metaIntroDelay": True, "vagueGap": False, "fullConclusionRevealed": False}),
            "meta-intro",
        ),
        (
            _hook(flags={"metaIntroDelay": False, "vagueGap": False, "fullConclusionRevealed": True}),
            "full conclusion",
        ),
        (
            _hook(
                perceptualChanges=[
                    {"kind": "action", "atSeconds": 0.25, "evidence": "change 1"},
                    {"kind": "reaction", "atSeconds": 0.65, "evidence": "change 2"},
                    {"kind": "detail", "atSeconds": 1.05, "evidence": "change 3"},
                    {"kind": "scale_change", "atSeconds": 1.45, "evidence": "change 4"},
                    {"kind": "reveal", "atSeconds": 1.85, "evidence": "change 5"},
                ]
            ),
            "chaotic over-editing",
        ),
    ],
)
def test_risk_signals_can_pass_as_actionable_acceptable_advisories(
    monkeypatch, tmp_path, hook, needle
):
    report = _run(monkeypatch, tmp_path, hook)
    assert report["ok"] is True, report
    audit = report["evidence"]["hookQualityAudit"]
    assert audit["disposition"] == "acceptable"
    assert any(needle in item for item in audit["advisories"])
