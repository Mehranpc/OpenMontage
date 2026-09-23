from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
POLICY_FILES = [
    ROOT / "AGENT_GUIDE.md",
    ROOT / "skills/meta/reviewer.md",
    ROOT / "skills/pipelines/animation/executive-producer.md",
    ROOT / "skills/pipelines/explainer/executive-producer.md",
    ROOT / "skills/pipelines/talking-head/executive-producer.md",
]


def test_review_exhaustion_never_permits_warning_pass():
    forbidden = ("pass with warnings", "pass_with_warnings")
    for path in POLICY_FILES:
        text = path.read_text().lower()
        assert not any(term in text for term in forbidden), path


def test_manifest_owns_persian_revision_ceiling_and_policy_version():
    manifest = yaml.safe_load((ROOT / "pipeline_defs/persian-footage.yaml").read_text())
    orchestration = manifest["orchestration"]
    assert orchestration["max_revisions_per_stage"] > 0
    assert orchestration["policy_version"] == "persian-speed-quality-v2"
    assert orchestration["active_profile"] == "film-type-2.16"


def test_exhaustion_contract_records_needs_decision():
    guide = (ROOT / "AGENT_GUIDE.md").read_text()
    reviewer = (ROOT / "skills/meta/reviewer.md").read_text()
    policy = (ROOT / "skills/pipelines/persian-footage/review-policy.md").read_text()
    for text in (guide, reviewer, policy):
        assert "needs_decision" in text
        assert "max_revisions_per_stage" in text
