from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PIPELINE = ROOT / "skills/pipelines/persian-footage"
DIRECTORS = ("scene-director.md", "asset-director.md", "edit-director.md", "compose-director.md")
REFERENCES = {
    "scene-director.md": "references/scene-planning.md",
    "asset-director.md": "references/asset-acquisition.md",
    "edit-director.md": "references/edit-authoring.md",
    "compose-director.md": "references/compose-verification.md",
}


def test_large_persian_directors_have_bounded_first_read_context():
    for name in DIRECTORS:
        path = PIPELINE / name
        assert path.stat().st_size <= 15_000, (name, path.stat().st_size)


def test_each_bounded_director_routes_details_on_demand():
    for name, reference in REFERENCES.items():
        text = (PIPELINE / name).read_text(encoding="utf-8")
        assert reference in text
        assert "only" in text.lower() or "on demand" in text.lower()
        assert (PIPELINE / reference).is_file()


def test_phase_cards_do_not_eagerly_load_director_references():
    cards = PIPELINE / "phase-cards"
    for card in cards.glob("*.md"):
        text = card.read_text(encoding="utf-8")
        assert "references/" not in text
