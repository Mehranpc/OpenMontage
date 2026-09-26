"""Issue #107: re-running each deterministic CLI with identical inputs writes/downloads nothing.

The spec (Persian pipeline v2, P2/P3) requires every deterministic JSON CLI --
manifest/checkpoint, music search/fetch, region sheets, region proposals -- to be
stable and idempotent: a second run with byte-identical inputs must produce no
write and no download. This file asserts that contract end to end, at the real
filesystem boundary (only the external provider and ffmpeg are faked), for each
of the four P2 CLI units.

The manifest/checkpoint case is the one whose existing coverage
(tests/lib/test_persian_asset_commands.py) stubs both ``read_checkpoint`` and
``write_checkpoint``; here the real checkpoint reader/writer and the real files
are exercised, so a regression in the read<->write round trip would be caught.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from lib import persian_asset_commands as asset_commands
from lib import persian_music_commands as music_commands
from lib import persian_region_commands as region_commands
from lib.checkpoint import init_project, write_checkpoint
from tests.contracts.test_phase0_contracts import sample_artifact
from tests.lib.test_issue35_asset_candidate_workspace import _selected_candidate
from tests.lib.test_persian_music_commands import (
    _FakeMusicTool,
    _metadata,
    _request,
)
from tests.lib.test_persian_region_commands import (
    _annotations,
    _fake_ffmpeg,
    _project as _region_project,
)


def _snapshot(paths: list[Path]) -> dict[Path, tuple[bytes, int]]:
    """Capture exact bytes + nanosecond mtime, so any rewrite is visible."""
    return {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in paths}


def _history_entries(project: Path) -> list[str]:
    history = project / "history"
    return sorted(path.name for path in history.glob("*")) if history.is_dir() else []


def _persian_project_ready_for_assets(tmp_path: Path) -> Path:
    """A real persian-footage project whose assets-stage prerequisites exist.

    The checkpoint command refuses to advance without completed idea/script/
    scene_plan checkpoints, so this builds the genuine predecessor files rather
    than stubbing the writer.
    """
    init_project("run", title="Run", pipeline_type="persian-footage", pipeline_dir=tmp_path)
    project = tmp_path / "run"
    _selected_candidate(project)
    for stage, artifact in (("idea", "brief"), ("script", "script"), ("scene_plan", "scene_plan")):
        write_checkpoint(
            tmp_path, "run", stage, "completed",
            {artifact: sample_artifact(artifact)},
            pipeline_type="persian-footage",
        )
    return project


def test_manifest_and_checkpoint_cli_write_nothing_on_identical_rerun(tmp_path: Path) -> None:
    project = _persian_project_ready_for_assets(tmp_path)

    first_manifest = asset_commands.build_manifest(tmp_path, "run")
    first_checkpoint = asset_commands.write_assets_checkpoint(tmp_path, "run")
    tracked = [
        project / "artifacts" / "asset_manifest.json",
        project / "artifacts" / "asset_manifest.check.json",
        project / "checkpoint_assets.json",
    ]
    before = _snapshot(tracked)
    history_before = _history_entries(project)

    second_manifest = asset_commands.build_manifest(tmp_path, "run")
    second_checkpoint = asset_commands.write_assets_checkpoint(tmp_path, "run")

    assert first_manifest["changed"] is True
    assert first_checkpoint["changed"] is True
    assert second_manifest["idempotent"] is True and second_manifest["changed"] is False
    assert second_checkpoint["idempotent"] is True and second_checkpoint["changed"] is False
    assert _snapshot(tracked) == before
    # A superseded checkpoint would be archived to history/; an identical rerun must not.
    assert _history_entries(project) == history_before


def test_music_search_and_fetch_cli_download_nothing_on_identical_rerun(tmp_path: Path) -> None:
    (tmp_path / "run").mkdir()
    tool = _FakeMusicTool()

    first_search = music_commands.search_music(
        tmp_path, "run", _request(), tool_factory=lambda _provider: tool
    )
    first_fetch = music_commands.fetch_music(
        tmp_path, "run", first_search["searchId"], _metadata()
    )
    tracked = [
        Path(first_search["cachedPath"]),
        Path(first_fetch["audioPath"]),
        Path(first_fetch["trackPath"]),
    ]
    before = _snapshot(tracked)

    second_search = music_commands.search_music(
        tmp_path, "run", _request(), tool_factory=lambda _provider: tool
    )
    second_fetch = music_commands.fetch_music(
        tmp_path, "run", first_search["searchId"], _metadata()
    )

    assert tool.calls == 1  # identical inputs must not re-hit the provider/download
    assert second_search["idempotent"] is True and second_search["changed"] is False
    assert second_fetch["idempotent"] is True and second_fetch["changed"] is False
    assert _snapshot(tracked) == before


def test_region_sheets_and_proposal_cli_rebuild_nothing_on_identical_rerun(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _region_project(tmp_path)
    calls = _fake_ffmpeg(monkeypatch)

    first_sheets = region_commands.build_sheets(tmp_path, "run")
    first_proposal = region_commands.propose_regions(tmp_path, "run", _annotations())
    sheets_dir = project / "artifacts" / "subject-region-sheets"
    tracked = sorted(sheets_dir.glob("*.png")) + [
        Path(first_sheets["indexPath"]),
        Path(first_proposal["proposalPath"]),
    ]
    before = _snapshot(tracked)
    calls_before = len(calls)

    second_sheets = region_commands.build_sheets(tmp_path, "run")
    second_proposal = region_commands.propose_regions(tmp_path, "run", _annotations())

    assert len(calls) == calls_before  # a cache hit invokes no ffmpeg rebuild
    assert second_sheets["idempotent"] is True and second_sheets["rebuiltOutputs"] == []
    assert second_proposal["idempotent"] is True and second_proposal["changed"] is False
    assert _snapshot(tracked) == before
