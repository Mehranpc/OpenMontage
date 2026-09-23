from __future__ import annotations

import json
from pathlib import Path

import pytest

from lib import persian_music_commands as commands
from lib import persian_video_workflow as workflow
from tools.base_tool import ToolResult, ToolStatus


class _FakeMusicTool:
    def __init__(self) -> None:
        self.calls = 0

    def get_status(self) -> ToolStatus:
        return ToolStatus.AVAILABLE

    def execute(self, inputs: dict) -> ToolResult:
        self.calls += 1
        output = Path(inputs["output_path"])
        output.write_bytes(b"deterministic-music-bytes")
        return ToolResult(
            success=True,
            data={
                "provider": "pixabay_music",
                "track_title": "Calm Track",
                "artist": "Test Artist",
                "duration_seconds": 90.0,
                "query": inputs["query"],
                "output": str(output),
                "source_url": "https://pixabay.com/music/test/",
            },
            artifacts=[str(output)],
        )


def _project(tmp_path: Path) -> Path:
    project = tmp_path / "run"
    project.mkdir()
    return project


def _request() -> dict:
    return {
        "provider": "pixabay_music",
        "query": "calm instrumental background",
        "min_duration": 60,
        "max_duration": 120,
    }


def _metadata() -> dict:
    return {
        "license": {
            "name": "Pixabay Content License",
            "url": "https://pixabay.com/service/license-summary/",
            "downloadedAt": "2026-09-23",
        },
        "contentIdRisk": {
            "level": "low",
            "reason": "Recognized Pixabay licence with recorded provenance.",
        },
    }


def test_music_search_cache_prevents_repeat_provider_download(tmp_path: Path) -> None:
    _project(tmp_path)
    tool = _FakeMusicTool()
    first = commands.search_music(
        tmp_path, "run", _request(), tool_factory=lambda _provider: tool
    )
    cache_path = Path(first["cachedPath"])
    record_path = tmp_path / "run" / ".asset-workspace" / "music" / "searches" / f"{first['searchId']}.json"
    cache_mtime = cache_path.stat().st_mtime_ns
    record_mtime = record_path.stat().st_mtime_ns

    second = commands.search_music(
        tmp_path, "run", _request(), tool_factory=lambda _provider: tool
    )

    assert tool.calls == 1
    assert second["idempotent"] is True
    assert second["changed"] is False
    assert cache_path.stat().st_mtime_ns == cache_mtime
    assert record_path.stat().st_mtime_ns == record_mtime
    assert json.dumps(
        json.loads(record_path.read_text(encoding="utf-8")),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ) + "\n" == record_path.read_text(encoding="utf-8")


def test_music_fetch_is_audited_and_idempotent(tmp_path: Path) -> None:
    _project(tmp_path)
    tool = _FakeMusicTool()
    searched = commands.search_music(
        tmp_path, "run", _request(), tool_factory=lambda _provider: tool
    )
    metadata = _metadata()
    metadata["source"] = "forged-provider"
    first = commands.fetch_music(
        tmp_path, "run", searched["searchId"], metadata
    )
    audio_path = Path(first["audioPath"])
    track_path = Path(first["trackPath"])
    audio_mtime = audio_path.stat().st_mtime_ns
    track_mtime = track_path.stat().st_mtime_ns

    second = commands.fetch_music(
        tmp_path, "run", searched["searchId"], metadata
    )

    assert first["changed"] is True
    assert second["idempotent"] is True
    assert second["changed"] is False
    assert audio_path.read_bytes() == b"deterministic-music-bytes"
    assert audio_path.stat().st_mtime_ns == audio_mtime
    assert track_path.stat().st_mtime_ns == track_mtime
    assert second["track"]["source"] == "pixabay_music"
    assert second["track"]["attribution"] == "Calm Track — Test Artist"


def test_music_fetch_refuses_high_content_id_risk(tmp_path: Path) -> None:
    _project(tmp_path)
    tool = _FakeMusicTool()
    searched = commands.search_music(
        tmp_path, "run", _request(), tool_factory=lambda _provider: tool
    )
    metadata = _metadata()
    metadata["contentIdRisk"] = {"level": "high", "reason": "Known claim history."}
    with pytest.raises(commands.PersianMusicCommandError, match="high Content-ID risk"):
        commands.fetch_music(tmp_path, "run", searched["searchId"], metadata)
    assert not (tmp_path / "run" / "assets" / "music" / "bed.mp3").exists()


def test_music_fetch_rejects_untrusted_search_id(tmp_path: Path) -> None:
    _project(tmp_path)
    with pytest.raises(commands.PersianMusicCommandError, match="invalid music search id"):
        commands.fetch_music(
            tmp_path, "run", "../../outside", _metadata()
        )


def test_music_fetch_confines_output_to_project(tmp_path: Path) -> None:
    _project(tmp_path)
    tool = _FakeMusicTool()
    searched = commands.search_music(
        tmp_path, "run", _request(), tool_factory=lambda _provider: tool
    )
    with pytest.raises(commands.PersianMusicCommandError, match="inside its project"):
        commands.fetch_music(
            tmp_path,
            "run",
            searched["searchId"],
            _metadata(),
            output_path=tmp_path / "outside.mp3",
        )


def test_front_door_exposes_nested_music_commands() -> None:
    parser = workflow.build_parser()
    searched = parser.parse_args([
        "assets", "music", "search", "run", "--json", "/tmp/search.json",
    ])
    assert searched.assets_command == "music"
    assert searched.music_command == "search"
    fetched = parser.parse_args([
        "assets", "music", "fetch", "run", "music-1",
        "--metadata-json", "/tmp/music.json",
    ])
    assert fetched.music_command == "fetch"
    assert fetched.search_id == "music-1"
