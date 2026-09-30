"""#353: the middle-phase entry point must not prescribe double admission."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_normal_acquisition_uses_one_durable_front_door_command():
    text = (ROOT / "skills/persian-video/narration-to-persian-video.md").read_text()
    acquisition = text.split("For acquisition,", 1)[1].split("Before accepting assets,", 1)[0]
    assert " asset-search " in acquisition, "normal acquisition must use durable asset-search"
    commands = "\n".join(acquisition.split("```bash")[1:]).split("```", 1)[0]
    assert " asset-request " not in commands, (
        "normal acquisition prescribes asset-request before asset-search, "
        "leaving the pass pending before its owner can admit it"
    )
    assert " asset-result " not in commands, "asset-search owns result accounting"

