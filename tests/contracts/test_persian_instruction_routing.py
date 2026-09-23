from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
PIPELINE = ROOT / "skills/pipelines/persian-footage"
PHASES = ("idea", "script", "scene-plan", "assets", "edit", "compose")


def test_persian_eager_skills_do_not_load_every_director():
    manifest = yaml.safe_load((ROOT / "pipeline_defs/persian-footage.yaml").read_text())
    eager = manifest["required_skills"]
    assert not any(name.endswith("-director") for name in eager)
    assert "pipelines/persian-footage/executive-producer" in eager
    assert "pipelines/persian-footage/profile-routing" in eager


def test_every_persian_phase_has_a_small_routable_card():
    for phase in PHASES:
        path = PIPELINE / "phase-cards" / f"{phase}.md"
        text = path.read_text()
        assert path.stat().st_size <= 3_000
        for heading in ("**Inputs:**", "**Output:**", "**Use:**", "**Success:**", "**Stop:**"):
            assert heading in text, (phase, heading)


def test_default_profile_does_not_eagerly_load_history():
    routing = (PIPELINE / "profile-routing.md").read_text()
    assert "film-type-2.16" in routing
    assert "film-type-history.md" in routing
    assert "never eager context" in routing


def test_assets_phase_routes_region_review_to_canonical_cli():
    text = (PIPELINE / "phase-cards" / "assets.md").read_text()
    assert "regions build-sheets" in text
    assert "regions propose" in text
    assert "confirmationRequired" not in text or "non-final" in text
    assert ".workspace/*.py" in text
