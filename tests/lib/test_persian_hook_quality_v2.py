from __future__ import annotations

from lib.persian_hook_quality import audit_persian_hook_quality


def _judgements() -> dict:
    return {
        field: {"level": "strong", "rationale": f"author claim for {field}"}
        for field in (
            "semanticPredictionError",
            "audienceRelevance",
            "concreteness",
            "hookBodyAlignment",
            "visualVoiceAlignment",
        )
    }


def _edit(**hook_overrides) -> dict:
    hook = {
        "version": "2.0",
        "viewerValue": {
            "atSeconds": 0.37,
            "evidence": "این اشتباه می‌تواند نتیجه را برعکس کند.",
            "evidenceId": "spoken-opening-1",
        },
        "semanticTension": {
            "kind": "contradiction",
            "atSeconds": 0.72,
            "evidence": "چیزی که وقت‌تلفی به نظر می‌رسد شاید اثر دیگری داشته باشد.",
            "evidenceId": "spoken-opening-2",
        },
        "firstProof": {
            "atSeconds": 2.4,
            "kind": "result",
            "evidence": "در نتیجه آزمون، گروه بازی‌کننده در توجه امتیاز بالاتری گرفت.",
            "evidenceId": "spoken-payoff-1",
        },
        "judgements": _judgements(),
        "flags": {"metaIntroDelay": False, "vagueGap": False, "fullConclusionRevealed": False},
        "perceptualChanges": [],
    }
    hook.update(hook_overrides)
    return {
        "metadata": {"target_platform": "instagram-reels", "hookQuality": hook},
        "persian": {"durationSeconds": 47.5, "shots": [], "moments": []},
    }


def test_v2_refuses_double_credit_without_explicit_shared_evidence_justification() -> None:
    shared = {
        "atSeconds": 0.37,
        "evidence": "همین یک جمله هم وعده فایده است و هم تناقض را می‌سازد.",
        "evidenceId": "spoken-opening-shared",
    }
    edit = _edit(
        viewerValue=dict(shared),
        semanticTension={"kind": "contradiction", **shared},
    )

    audit = audit_persian_hook_quality(edit)

    assert audit["version"] == "2.0"
    assert audit["disposition"] == "weak"
    assert any("shared evidence" in problem.lower() for problem in audit["problems"])


def test_v2_rejects_meta_authority_language_as_first_proof() -> None:
    edit = _edit(
        firstProof={
            "atSeconds": 5.42,
            "kind": "authority_cue",
            "evidence": "بررسی‌های علمی نشان می‌دهند بازی‌های ویدیویی اثر دارند.",
            "evidenceId": "spoken-authority-cue",
        }
    )

    audit = audit_persian_hook_quality(edit)

    assert audit["disposition"] == "weak"
    assert any("concrete" in problem.lower() and "proof" in problem.lower() for problem in audit["problems"])
    assert audit["timing"]["timeToFirstProofSeconds"] is None


def test_v2_authored_strong_judgements_cannot_self_certify_preflight_strong() -> None:
    audit = audit_persian_hook_quality(_edit())

    assert audit["problems"] == []
    assert audit["disposition"] == "acceptable"
    assert audit["semanticAuthority"] == "authored-claim-awaiting-rendered-review"
