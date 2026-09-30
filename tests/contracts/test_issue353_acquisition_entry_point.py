"""#353: the middle-phase entry point must not prescribe double admission."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_normal_acquisition_uses_one_durable_front_door_command():
    text = (ROOT / "skills/persian-video/narration-to-persian-video.md").read_text()
    acquisition = text.split("For acquisition,", 1)[1].split("Before accepting assets,", 1)[0]
    assert " asset-search " in acquisition, "normal acquisition must use durable asset-search"
    assert " asset-request " not in acquisition, (
        "normal acquisition prescribes asset-request before asset-search, "
        "leaving the pass pending before its owner can admit it"
    )
    assert " asset-result " not in acquisition, "asset-search owns result accounting"


def test_director_does_not_require_deferring_valid_selection_until_all_passes():
    text = (ROOT / "skills/pipelines/persian-footage/asset-director.md").read_text()
    assert "select" in text
    # The explicit rule is review of primary candidates before retry, not deferral
    # of every already-valid selection until the end of all search cycles.
    assert "only after review" in text
