from __future__ import annotations

from lib.persian_motion_qa import MotionDelta, MotionQa
from lib.persian_quality_evidence import compose_quality_evidence
from lib.persian_retention import audit_persian_retention


def _shot(shot_id: str, start: float, end: float) -> dict:
    return {"id": shot_id, "startSeconds": start, "endSeconds": end}


def _timeline(*, shots: list[dict], moments: list[dict] | None = None) -> dict:
    return {
        "durationSeconds": 6.0,
        "shots": shots,
        "moments": list(moments or []),
        "typographicBeats": [],
    }


def _motion(*values: float) -> dict:
    qa = MotionQa(
        passed=True,
        deltas=[MotionDelta((index + 1) * 0.5, value) for index, value in enumerate(values)],
    )
    return qa.to_dict()


def _cold_review(*, understood: bool = True) -> dict:
    return {
        "coldViewer": {
            "evidenceSource": "rendered_opening_only",
            "contextIsolated": True,
            "inferredTopic": "بازی‌های ویدیویی" if understood else "",
            "inferredClaim": "موضوع فقط وقت‌تلف‌کردن نیست" if understood else "",
            "continuationReason": "می‌خواهم نتیجه را ببینم" if understood else "",
            "unresolvedReferents": [],
        }
    }


def test_retention_no_change_is_explicitly_authored_not_rendered_stasis() -> None:
    audit = audit_persian_retention(_timeline(shots=[_shot("s1", 0.0, 6.0)]))
    assert any("no authored post-start shot/reveal change" in note for note in audit["advisories"])
    assert not any("perceptual stasis" in note for note in audit["advisories"])
    record = next(item for item in audit["observableEvidence"] if item["kind"] == "authored_no_post_start_change")
    assert record["provenance"]["domain"] == "authored_timeline"
    assert "rendered_pixel_motion" in record["cannotProve"]
    assert "semantic_comprehension" in record["cannotProve"]


def test_retention_overlay_is_authored_reveal_not_pixel_motion() -> None:
    audit = audit_persian_retention(
        _timeline(
            shots=[_shot("s1", 0.0, 6.0)],
            moments=[{"id": "m1", "startSeconds": 0.5, "endSeconds": 1.5}],
        )
    )
    records = audit["observableEvidence"]
    reveal = next(item for item in records if item["kind"] == "authored_overlay_reveal")
    assert reveal["scope"]["startSeconds"] == 0.5
    assert reveal["provenance"]["domain"] == "authored_timeline"
    assert "rendered_pixel_motion" in reveal["cannotProve"]
    assert not any("no authored post-start shot/reveal change" in note for note in audit["advisories"])


def test_motion_qa_uses_rendered_pixel_provenance_without_semantic_claims() -> None:
    motion = _motion(0.2, 4.0, 3.0, 0.4)
    records = motion["observableEvidence"]
    observed = next(item for item in records if item["kind"] == "rendered_pixel_motion")
    assert observed["provenance"]["domain"] == "rendered_pixels"
    assert observed["details"]["firstObservedAtSeconds"] == 1.0
    assert "authored_timeline_change" in observed["cannotProve"]
    assert "semantic_hook_quality" in observed["cannotProve"]


def test_same_shot_with_rendered_motion_is_explained_without_false_contradiction() -> None:
    retention = audit_persian_retention(_timeline(shots=[_shot("s1", 0.0, 6.0)]))
    quality = compose_quality_evidence(retention, _motion(0.2, 4.0, 3.0, 0.4))
    opening = quality["openingSummary"]
    assert opening["authoredPostStartShotOrRevealChange"] is False
    assert opening["renderedPixelMotionObserved"] is True
    assert opening["relationship"] == "different_provenance_not_contradictory"
    assert any("No authored post-start shot/reveal change" in item for item in opening["statements"])
    assert any("Rendered intra-shot pixel motion observed" in item for item in opening["statements"])


def test_authored_change_with_near_static_pixels_surfaces_render_mismatch() -> None:
    retention = audit_persian_retention(
        _timeline(shots=[_shot("s1", 0.0, 1.0), _shot("s2", 1.0, 6.0)])
    )
    quality = compose_quality_evidence(retention, _motion(0.1, 0.2, 0.3, 0.2, 0.1))
    opening = quality["openingSummary"]
    assert opening["authoredPostStartShotOrRevealChange"] is True
    assert opening["renderedPixelMotionObserved"] is False
    assert opening["relationship"] == "authored_change_not_observed_in_rendered_pixels"
    assert any(item["code"] == "authored_change_without_rendered_motion" for item in quality["diagnostics"])


def test_cold_view_semantics_remain_separate_from_timeline_and_pixel_measurement() -> None:
    retention = audit_persian_retention(_timeline(shots=[_shot("s1", 0.0, 6.0)]))
    quality = compose_quality_evidence(
        retention,
        _motion(0.2, 4.0, 3.0),
        hook_review=_cold_review(),
    )
    opening = quality["openingSummary"]
    assert opening["coldViewComprehension"] is True
    semantic = next(item for item in quality["evidence"] if item["kind"] == "cold_view_semantic_observation")
    assert semantic["provenance"]["domain"] == "semantic_review"
    assert "rendered_pixel_motion" in semantic["cannotProve"]
    assert "authored_timeline_change" in semantic["cannotProve"]
    assert any("Cold-view opening comprehension passed" in item for item in opening["statements"])


def test_quality_evidence_preserves_raw_source_records_instead_of_relabeling() -> None:
    retention = audit_persian_retention(
        _timeline(
            shots=[_shot("s1", 0.0, 2.0), _shot("s2", 2.0, 6.0)],
            moments=[{"id": "m1", "startSeconds": 0.4, "endSeconds": 1.2}],
        )
    )
    quality = compose_quality_evidence(retention, _motion(2.0, 2.5, 3.0), hook_review=_cold_review())
    domains = {item["provenance"]["domain"] for item in quality["evidence"]}
    assert domains == {"authored_timeline", "rendered_pixels", "semantic_review"}
    assert quality["version"] == "1.0"
