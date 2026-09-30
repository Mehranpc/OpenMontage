"""#353: acquisition instructions use the durable front door and valid defaults."""
import json
from pathlib import Path
import re

from lib.persian_video_workflow import bounded_asset_search_request
from tests.lib.test_persian_video_workflow import BASE, _bootstrap_to_assets

ROOT = Path(__file__).resolve().parents[2]


def test_normal_acquisition_uses_one_durable_front_door_command():
    text = (ROOT / "skills/persian-video/narration-to-persian-video.md").read_text()
    acquisition = text.split("For acquisition,", 1)[1].split("Before accepting assets,", 1)[0]
    commands = "\n".join(re.findall(r"```bash\n(.*?)```", acquisition, re.DOTALL))
    assert " asset-search " in commands, "normal acquisition must use durable asset-search"
    assert " asset-request " not in commands, "normal acquisition must not admit the pass twice"
    assert " asset-result " not in commands, "asset-search owns result accounting"


def test_documented_request_uses_current_project_policy_defaults(tmp_path: Path):
    _bootstrap_to_assets(tmp_path)
    text = (ROOT / "skills/pipelines/persian-footage/asset-director.md").read_text()
    request = json.loads(re.findall(r"```json\n(.*?)```", text, re.DOTALL)[0])
    assert set(request) == {"queries", "filters"}
    bounded = bounded_asset_search_request(
        "run", request, retry_pass=0, pipeline_dir=tmp_path, now=BASE
    )
    assert bounded["output_dir"] == str((tmp_path / "run" / "assets").resolve())
    assert bounded["sources"] == ["pexels", "pixabay_video"]
    assert bounded["clips_per_query"] == 1
    assert bounded["max_candidates_total"] == 16
    assert bounded["max_bytes_per_clip"] == 100663296
    assert bounded["max_total_download_bytes"] == 536870912
