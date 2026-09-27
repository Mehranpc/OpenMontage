"""#230: faces are hard regions, the brand keeps its distance, «یا» lists keep phrases whole."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from lib import persian_region_commands as commands
from tests.lib.test_persian_region_commands import _annotations, _fake_ffmpeg, _project

ROOT = Path(__file__).resolve().parents[2]


def _mark_human(project: Path, *event_ids: str) -> None:
    path = project / "artifacts" / "asset_manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    for asset in manifest["assets"]:
        if asset.get("visual_event_id") in event_ids or not event_ids:
            asset["human_presence"] = True
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def test_a_person_shot_without_a_marked_face_is_refused(tmp_path: Path, monkeypatch) -> None:
    project = _project(tmp_path)
    _mark_human(project)
    _fake_ffmpeg(monkeypatch)
    commands.build_sheets(tmp_path, "run")
    with pytest.raises(commands.PersianRegionCommandError, match="mark the face"):
        commands.propose_regions(tmp_path, "run", _annotations())


def test_a_marked_face_becomes_a_hard_region(tmp_path: Path, monkeypatch) -> None:
    project = _project(tmp_path)
    _mark_human(project)
    _fake_ffmpeg(monkeypatch)
    commands.build_sheets(tmp_path, "run")
    annotations = _annotations()
    for shot in annotations["shots"]:
        for frame in shot["frames"]:
            if not frame.get("clear"):
                frame["face"] = {"x1": 4, "y1": 1, "x2": 7, "y2": 3}
    result = commands.propose_regions(tmp_path, "run", annotations)
    proposal = json.loads(Path(result["proposalPath"]).read_text(encoding="utf-8"))
    rows = proposal["proposedEvidence"]["shot_regions"]
    faces = [r for row in rows for r in row["avoidRegions"]
             if r["priority"] == "hard" and r["y"] == pytest.approx(0.1) and r["h"] == pytest.approx(0.2)]
    assert faces, rows


def test_face_visible_false_is_an_explicit_answer(tmp_path: Path, monkeypatch) -> None:
    project = _project(tmp_path)
    _mark_human(project)
    _fake_ffmpeg(monkeypatch)
    commands.build_sheets(tmp_path, "run")
    annotations = _annotations()
    for shot in annotations["shots"]:
        for frame in shot["frames"]:
            if not frame.get("clear"):
                frame["face_visible"] = False
    commands.propose_regions(tmp_path, "run", annotations)


def test_shots_without_people_need_no_face(tmp_path: Path, monkeypatch) -> None:
    _project(tmp_path)
    _fake_ffmpeg(monkeypatch)
    commands.build_sheets(tmp_path, "run")
    commands.propose_regions(tmp_path, "run", _annotations())


def test_or_list_phrase_locks_are_derived() -> None:
    """Pure TS check through node: «همون شب یا فردا صبح یا صبر؟» locks «فردا صبح»."""
    import shutil
    import subprocess

    esbuild = ROOT / "remotion-composer" / "node_modules" / ".bin" / "esbuild"
    if shutil.which("node") is None or not esbuild.exists():
        pytest.skip("node/esbuild not available")
    composer = ROOT / "remotion-composer"
    driver = composer / ".issue230-driver.mjs"
    bundle = composer / ".issue230-bundle.mjs"
    driver.write_text(
        'import { deriveListPhraseLocks } from "./src/persian/semanticPhraseLocks.ts";\n'
        'process.stdout.write(JSON.stringify([\n'
        '  deriveListPhraseLocks("همون شب یا فردا صبح یا صبر؟"),\n'
        '  deriveListPhraseLocks("توجه دیداری، درک فضایی پیچیده، حافظه کاری"),\n'
        '  deriveListPhraseLocks("این یا آن"),\n'
        ']));\n', encoding="utf-8")
    try:
        subprocess.run([str(esbuild), str(driver), "--bundle", "--format=esm", "--platform=node",
                        f"--outfile={bundle}", "--log-level=error"], check=True, cwd=composer, timeout=120)
        out = json.loads(subprocess.run(["node", str(bundle)], check=True, capture_output=True,
                                        text=True, cwd=composer, timeout=60).stdout)
    finally:
        driver.unlink(missing_ok=True)
        bundle.unlink(missing_ok=True)
    assert out[0] == ["همون شب", "فردا صبح"]
    assert out[1] == ["توجه دیداری", "درک فضایی پیچیده", "حافظه کاری"]
    assert out[2] == []
