"""#313 follow-up: a source window the render's luminance gate would refuse is refused at review.

f418063 run: the full film rendered before the gate refused 57-59s (YAVG 18.8) under
shot-13, and both reviewed windows of that source were the same dark seconds. Film
Type paints footage with no grade, so the window's own luma is what the render shows.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from lib import persian_video_workflow as workflow
from lib.persian_render_qa import measure_source_window_luma

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")


def _clip(path: Path) -> Path:
    """4s bright grey, 3s black, 3s bright grey (YAVG ~126 / ~16 / ~126)."""
    parts = []
    for index, (colour, seconds) in enumerate((("0x808080", 4), ("0x000000", 3), ("0x808080", 3))):
        part = path.parent / f"p{index}.mp4"
        subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i",
                        f"color=c={colour}:s=64x112:r=10:d={seconds}", "-pix_fmt", "yuv420p", str(part)],
                       check=True, stdin=subprocess.DEVNULL)
        parts.append(part)
    listing = path.parent / "list.txt"
    listing.write_text("".join(f"file '{p}'\n" for p in parts), encoding="utf-8")
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(listing),
                    "-c", "copy", str(path)], check=True, stdin=subprocess.DEVNULL)
    return path


def _state_with(monkeypatch, tmp_path: Path, clip: Path, start: float, end: float) -> dict:
    candidate = {
        "identity": {"sourceWindow": {"startSeconds": start, "endSeconds": end}},
        "source": {"path": str(clip)}, "context": {"visualEventId": "ev-13"},
    }
    import lib.persian_asset_workspace as ws

    monkeypatch.setattr(ws, "load_asset_candidate", lambda project, cid: candidate)
    monkeypatch.setattr(workflow, "_project_root", lambda state: tmp_path)
    return {}


def test_window_luma_is_relative_to_the_window(tmp_path) -> None:
    clip = _clip(tmp_path / "c.mp4")
    bins = measure_source_window_luma(clip, 3.0, 8.0)
    values = [round(v) for _, v in bins]
    assert values[0] > 100 and min(values) < 22 and bins[0][0] == 0.0


def test_a_window_over_the_dark_stretch_is_refused(tmp_path, monkeypatch) -> None:
    clip = _clip(tmp_path / "c.mp4")
    state = _state_with(monkeypatch, tmp_path, clip, 2.0, 8.0)
    with pytest.raises(workflow.PersianVideoWorkflowError, match=r"\[ASSET_SELECTION_DARK_FOOTAGE\].*ev-13.*YAVG"):
        workflow._refuse_dead_dark_source_window(state, "asset-x")


def test_a_window_outside_the_dark_stretch_passes(tmp_path, monkeypatch) -> None:
    clip = _clip(tmp_path / "c.mp4")
    state = _state_with(monkeypatch, tmp_path, clip, 0.0, 4.0)
    workflow._refuse_dead_dark_source_window(state, "asset-x")


def test_a_missing_file_never_blocks(tmp_path, monkeypatch) -> None:
    state = _state_with(monkeypatch, tmp_path, tmp_path / "missing.mp4", 0.0, 4.0)
    workflow._refuse_dead_dark_source_window(state, "asset-x")
