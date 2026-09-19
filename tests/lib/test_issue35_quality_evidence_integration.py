from __future__ import annotations

import json
from pathlib import Path

import pytest

from lib.persian_motion_qa import MotionDelta, MotionQa
from lib.persian_quality_evidence import compose_quality_evidence
from lib.persian_retention import audit_persian_retention
from lib.persian_video_workflow import (
    PersianVideoWorkflowError,
    _final_review_quality_evidence,
)

ROOT = Path(__file__).resolve().parents[2]


def _retention() -> dict:
    return audit_persian_retention({
        "durationSeconds": 6.0,
        "shots": [{"id": "s1", "startSeconds": 0.0, "endSeconds": 6.0}],
        "moments": [],
        "typographicBeats": [],
    })


def _motion() -> dict:
    return MotionQa(
        passed=True,
        deltas=[MotionDelta(0.5, 0.2), MotionDelta(1.0, 4.0), MotionDelta(1.5, 3.0)],
    ).to_dict()


def _cold_review() -> dict:
    return {
        "coldViewer": {
            "evidenceSource": "rendered_opening_only",
            "contextIsolated": True,
            "inferredTopic": "بازی‌های ویدیویی",
            "inferredClaim": "فقط وقت‌تلف‌کردن نیست",
            "continuationReason": "می‌خواهم نتیجه را ببینم",
            "unresolvedReferents": [],
        }
    }


def _report(*, with_quality: bool) -> dict:
    retention = _retention()
    motion = _motion()
    report = {
        "retention_audit": retention,
        "post_render_motion_qa": motion,
    }
    if with_quality:
        report["quality_evidence"] = compose_quality_evidence(retention, motion)
    return report


def test_render_report_schema_declares_normalized_quality_evidence_without_making_it_required() -> None:
    schema = json.loads((ROOT / "schemas" / "artifacts" / "render_report.schema.json").read_text(encoding="utf-8"))
    props = schema["properties"]
    assert "quality_evidence" in props
    assert "quality_evidence" not in schema.get("required", [])
    assert "observableEvidence" in props["retention_audit"]["properties"]
    assert "observableEvidence" in props["post_render_motion_qa"]["properties"]


def test_final_review_accepts_legacy_report_without_normalized_quality_evidence() -> None:
    quality = _final_review_quality_evidence(_report(with_quality=False), hook_review=None)
    assert quality["openingSummary"]["renderedPixelMotionObserved"] is True
    assert quality["openingSummary"]["coldViewComprehension"] is None


def test_final_review_rejects_declared_render_quality_evidence_that_drifted_from_raw_sources() -> None:
    report = _report(with_quality=True)
    report["quality_evidence"]["openingSummary"]["renderedPixelMotionObserved"] = False
    with pytest.raises(PersianVideoWorkflowError, match="quality_evidence.*match"):
        _final_review_quality_evidence(report, hook_review=None)


def test_final_review_composes_cold_view_semantics_without_relabeling_authored_or_pixel_facts() -> None:
    quality = _final_review_quality_evidence(_report(with_quality=True), hook_review=_cold_review())
    opening = quality["openingSummary"]
    assert opening["authoredPostStartShotOrRevealChange"] is False
    assert opening["renderedPixelMotionObserved"] is True
    assert opening["coldViewComprehension"] is True
    assert opening["relationship"] == "different_provenance_not_contradictory"
    domains = {item["provenance"]["domain"] for item in quality["evidence"]}
    assert domains == {"authored_timeline", "rendered_pixels", "semantic_review"}
