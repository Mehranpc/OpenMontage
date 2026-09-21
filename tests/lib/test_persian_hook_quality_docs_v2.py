from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
HOOK_DOC = REPO_ROOT / "skills/pipelines/persian-footage/hook-quality.md"
FINAL_REVIEW_DOC = REPO_ROOT / "skills/persian-video/persian-final-review.md"


def test_hook_quality_skill_documents_v2_semantics() -> None:
    text = HOOK_DOC.read_text(encoding="utf-8")
    assert '"version": "2.0"' in text
    assert '"viewerValue"' in text
    assert '"firstProof"' in text
    assert '"kind": "result"' in text
    assert '"sharedEvidenceJustifications"' in text
    assert "research shows" in text
    for field in ("semanticIntegrity", "requiredTopicAnchors", "anchorDelivery", "typographicDurationJustification"):
        assert field in text
    assert "HOOK_TOPIC_ANCHOR_MISSING" in text
    assert "HOOK_TYPOGRAPHIC_DURATION_EXCESS" in text
    assert "cannot" in text and "strong" in text and "rendered" in text


def test_final_review_skill_requires_independent_sha_bound_v2_evidence() -> None:
    text = FINAL_REVIEW_DOC.read_text(encoding="utf-8")
    assert 'version: "2.1"' in text
    for field in (
        "reviewSource",
        "reviewerRole",
        "reviewedCandidateSha256",
        "concretePayoffKind",
        "actualPayoffSeconds",
        "payoffEvidence",
        "coldViewer",
        "rendered_opening_only",
        "contextIsolated",
        "unresolvedReferents",
        "coldViewerReviewInput",
        "reviewInputSha256",
        "outputIntegratedLufs",
        "truePeakDbfs",
        "speechMusicSeparationLu",
    ):
        assert field in text
    assert 'version: "1.0"' not in text


def test_hook_docs_describe_the_same_versioned_timing_policy_as_the_code() -> None:
    from lib.persian_hook_quality import HOOK_TIMING_POLICY_VERSION

    for doc in (HOOK_DOC, FINAL_REVIEW_DOC):
        text = doc.read_text(encoding="utf-8")
        for field in ("timingPolicyVersion", "timingDisposition", "authorityProvenance"):
            assert field in text, f"{doc.name} must document {field}"
        assert "late-authoritative-advisory" in text
        assert "late-blocked" in text
        assert "hook_selection" in text

    assert HOOK_TIMING_POLICY_VERSION in HOOK_DOC.read_text(encoding="utf-8")
