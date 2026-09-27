"""Offline providers for the Persian pipeline rehearsal (#260).

When ``OPENMONTAGE_REHEARSAL_FIXTURE`` names a fixture directory, the three network
or machine-specific providers a production run touches are served from that
fixture's recordings of a real run instead:

- stock video search/download (``pexels``, ``pixabay_video``): each search is
  answered from ``recorded/search-cache/`` using the exact ``direct_clip_search``
  cache key, and each download copies ``clips/<clip_id>.mp4``. A query that was
  never recorded returns no candidates, like a provider with no match; it never
  reaches the network;
- word-timing transcription (``transcriber``): returns ``recorded/transcript.json``;
- music search (``pixabay_music``): copies ``music-bed.mp3``.

Everything else (every gate, preflight, region review, renders, mastering and
delivery evidence) runs for real. The variable is read in each process, so durable
child jobs see the same fixture. Nothing here is imported unless the variable is set.
"""
from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path
from typing import Any

FIXTURE_ENV = "OPENMONTAGE_REHEARSAL_FIXTURE"
REPLAYED_STOCK_SOURCES = ("pexels", "pixabay_video")


def fixture_root() -> Path | None:
    raw = str(os.environ.get(FIXTURE_ENV) or "").strip()
    if not raw:
        return None
    root = Path(raw).expanduser().resolve()
    if not root.is_dir():
        raise RuntimeError(f"{FIXTURE_ENV} does not name a directory: {root}")
    return root


def _recorded_candidates(root: Path, source: str, query: str, filters: Any) -> list[Any]:
    from tools.video.direct_clip_search import _search_cache_key
    from tools.video.stock_sources.base import Candidate

    key, payload = _search_cache_key(source, query, filters)
    path = root / "recorded" / "search-cache" / f"{key}.json"
    if not path.is_file():
        return []
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("key") != payload:
        return []
    return [Candidate(**dict(row)) for row in value.get("candidates") or [] if isinstance(row, dict)]


class ReplayStockSource:
    """Serves one production stock source from a recorded run."""

    priority = 0

    def __init__(self, name: str, root: Path) -> None:
        self.name = name
        self.display_name = f"{name} (rehearsal replay)"
        self.provider = name
        self._root = root

    def is_available(self) -> bool:
        return True

    def search(self, query: str, filters: Any) -> list[Any]:
        return _recorded_candidates(self._root, self.name, query, filters)

    def download(self, candidate: Any, out_path: Path) -> Path:
        source = self._root / "clips" / f"{candidate.clip_id}.mp4"
        if not source.is_file():
            raise FileNotFoundError(f"rehearsal fixture has no clip for {candidate.clip_id}")
        out = Path(out_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, out)
        return out


def replay_stock_sources() -> list[ReplayStockSource] | None:
    root = fixture_root()
    if root is None:
        return None
    return [ReplayStockSource(name, root) for name in REPLAYED_STOCK_SOURCES]


def _tool_base():
    from tools.base_tool import BaseTool, ToolResult, ToolStatus

    return BaseTool, ToolResult, ToolStatus


def replay_transcriber(real: Any) -> Any:
    """Wrap the real ``transcriber`` so its contract stays identical but output is recorded."""
    root = fixture_root()
    if root is None:
        return real
    _, ToolResult, ToolStatus = _tool_base()
    recorded = json.loads((root / "recorded" / "transcript.json").read_text(encoding="utf-8"))

    class _Replay(type(real)):  # type: ignore[misc, valid-type]
        def get_status(self):
            return ToolStatus.AVAILABLE

        def execute(self, inputs: dict[str, Any]):
            started = time.time()
            input_path = Path(inputs["input_path"])
            if not input_path.exists():
                return ToolResult(success=False, error=f"Input file not found: {input_path}")
            output_dir = Path(inputs.get("output_dir", input_path.parent))
            output_dir.mkdir(parents=True, exist_ok=True)
            data = dict(recorded)
            data["model_size"] = inputs.get("model_size", data.get("model_size", "base"))
            output_path = output_dir / f"{input_path.stem}_transcript.json"
            output_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
            return ToolResult(
                success=True, data=data, artifacts=[str(output_path)],
                duration_seconds=round(time.time() - started, 2),
            )

    return _Replay()


def replay_music_tool(real: Any) -> Any:
    root = fixture_root()
    if root is None:
        return real
    _, ToolResult, ToolStatus = _tool_base()
    bed = root / "music-bed.mp3"

    class _Replay(type(real)):  # type: ignore[misc, valid-type]
        def get_status(self):
            return ToolStatus.AVAILABLE

        def execute(self, inputs: dict[str, Any]):
            out = Path(inputs["output_path"])
            out.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(bed, out)
            return ToolResult(
                success=True,
                data={
                    "provider": "pixabay_music",
                    "track_title": "rehearsal music bed",
                    "artist": "recorded fixture",
                    "duration_seconds": 70,
                    "query": inputs.get("query"),
                    "output": str(out),
                    "format": "mp3",
                    "license": "Pixabay Content License (free, no attribution required)",
                    "source_url": "https://pixabay.com/music/",
                    "search_strategy": "rehearsal_replay",
                    "results_found": 1,
                    "results_after_filter": 1,
                },
                artifacts=[str(out)],
            )

    return _Replay()
