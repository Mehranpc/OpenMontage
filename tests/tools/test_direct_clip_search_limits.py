from __future__ import annotations

import time
from pathlib import Path

import pytest
import requests

from tools.video import direct_clip_search as module
from tools.video.direct_clip_search import DirectClipSearch
from tools.video.stock_sources.base import Candidate
from tools.video.stock_sources.nasa import _pick_video_url
from tools.video.stock_sources.pexels import _pick_video_rendition
from tools.video.stock_sources.pixabay_video import _pick_rendition as _pick_pixabay_rendition


class _Response:
    def __init__(self, chunks: list[bytes], content_length: str | None = None):
        self._chunks = chunks
        self.headers = {}
        if content_length is not None:
            self.headers["Content-Length"] = content_length

    def iter_content(self, **_kwargs):
        yield from self._chunks


class _Source:
    name = "pexels"

    def __init__(self, candidates_by_query: dict[str, list[Candidate]], size: int = 2048):
        self.candidates_by_query = candidates_by_query
        self.size = size

    def is_available(self):
        return True

    def search(self, query, _filters):
        return list(self.candidates_by_query.get(query, []))

    def download(self, _candidate, out_path: Path):
        Path(out_path).write_bytes(b"x" * self.size)
        return Path(out_path)


def _candidate(source_id: str, *, width: int = 1080, height: int = 1920, duration: float = 8.0):
    return Candidate(
        source="pexels",
        source_id=source_id,
        source_url=f"https://example.test/{source_id}",
        download_url=f"https://cdn.example.test/{source_id}.mp4",
        kind="video",
        width=width,
        height=height,
        duration=duration,
    )


def _install_source(monkeypatch, source):
    import tools.video.stock_sources as catalog

    monkeypatch.setattr(catalog, "all_sources", lambda: [source])
    monkeypatch.setattr(catalog, "available_sources", lambda: [source])
    monkeypatch.setattr(catalog, "get_source", lambda _name: source)
    monkeypatch.setattr(
        catalog,
        "source_summary",
        lambda: {"available_source_names": [source.name]},
    )


def _inputs(tmp_path, queries, **overrides):
    base = {
        "output_dir": str(tmp_path),
        "queries": [{"query": query, "kind": "video"} for query in queries],
        "sources": ["pexels"],
        "clips_per_query": 1,
        "extract_thumbnails": False,
        "filters": {"orientation": "portrait", "min_duration": 5},
        "max_candidates_total": 10,
        "max_bytes_per_clip": 10_000,
        "max_total_download_bytes": 20_000,
        "timeout_seconds": 30,
    }
    base.update(overrides)
    return base


def test_content_length_rejects_before_streaming(monkeypatch):
    response = _Response([b"x"], content_length="2001")
    monkeypatch.setattr(requests, "get", lambda *_a, **_k: response)
    budget = module._DownloadBudget(max_bytes_per_clip=2000, max_total_bytes=5000)
    budget.start_clip()
    with module._requests_deadline(time.time() + 5, download_budget=budget):
        with pytest.raises(module._DownloadQuotaExceeded, match="declared"):
            requests.get("https://example.test/large.mp4")
    assert budget.total_bytes == 0


def test_missing_content_length_still_stops_stream(monkeypatch):
    response = _Response([b"x" * 700, b"y" * 700])
    monkeypatch.setattr(requests, "get", lambda *_a, **_k: response)
    budget = module._DownloadBudget(max_bytes_per_clip=1000, max_total_bytes=5000)
    budget.start_clip()
    with module._requests_deadline(time.time() + 5, download_budget=budget):
        wrapped = requests.get("https://example.test/no-header.mp4")
        with pytest.raises(module._DownloadQuotaExceeded, match="while streaming"):
            list(wrapped.iter_content(chunk_size=1024))
    assert budget.total_bytes == 1400


def test_oversized_adapter_output_is_deleted(monkeypatch, tmp_path):
    source = _Source({"one": [_candidate("one")]}, size=2048)
    _install_source(monkeypatch, source)
    result = DirectClipSearch().execute(
        _inputs(
            tmp_path,
            ["one"],
            max_bytes_per_clip=1024,
            max_total_download_bytes=4096,
        )
    )
    assert result.success is False
    assert result.data["budget_exhausted"] is True
    assert not list((tmp_path / "clips").iterdir())


def test_post_download_probe_rejects_and_deletes_mismatch(monkeypatch, tmp_path):
    source = _Source({"one": [_candidate("one", width=0, height=0, duration=0)]})
    _install_source(monkeypatch, source)
    monkeypatch.setattr(
        module,
        "_probe_media",
        lambda *_a, **_k: {"width": 1920, "height": 1080, "duration": 1500.0},
    )
    result = DirectClipSearch().execute(
        _inputs(tmp_path, ["one"], filters={"orientation": "portrait", "max_duration": 10})
    )
    assert result.success is True
    assert result.data["clips_downloaded"] == 0
    assert result.data["errors"][0]["phase"] == "validation"
    assert not list((tmp_path / "clips").iterdir())


def test_aggregate_budget_stops_second_clip_and_removes_partial(monkeypatch, tmp_path):
    source = _Source(
        {"one": [_candidate("one")], "two": [_candidate("two")]}, size=1500
    )
    _install_source(monkeypatch, source)
    monkeypatch.setattr(
        module,
        "_probe_media",
        lambda *_a, **_k: {"width": 1080, "height": 1920, "duration": 8.0},
    )
    result = DirectClipSearch().execute(
        _inputs(
            tmp_path,
            ["one", "two"],
            max_bytes_per_clip=2000,
            max_total_download_bytes=2500,
        )
    )
    assert result.success is False
    assert result.data["clips_downloaded"] == 1
    assert result.data["bytes_downloaded"] == 3000
    names = sorted(path.name for path in (tmp_path / "clips").iterdir())
    assert names == ["pexels_one.mp4"]


def test_candidate_cap_is_hard(monkeypatch, tmp_path):
    source = _Source(
        {"one": [_candidate("one")], "two": [_candidate("two")]}, size=1500
    )
    _install_source(monkeypatch, source)
    monkeypatch.setattr(
        module,
        "_probe_media",
        lambda *_a, **_k: {"width": 1080, "height": 1920, "duration": 8.0},
    )
    result = DirectClipSearch().execute(
        _inputs(tmp_path, ["one", "two"], max_candidates_total=1)
    )
    assert result.success is False
    assert "candidate cap 1" in result.error
    assert result.data["candidates_considered"] == 1
    assert result.data["clips_downloaded"] == 1


def test_successful_query_does_not_consume_an_extra_candidate(monkeypatch, tmp_path):
    source = _Source(
        {
            "one": [_candidate("one"), _candidate("one-extra")],
            "two": [_candidate("two"), _candidate("two-extra")],
        },
        size=1500,
    )
    _install_source(monkeypatch, source)
    monkeypatch.setattr(
        module,
        "_probe_media",
        lambda *_a, **_k: {"width": 1080, "height": 1920, "duration": 8.0},
    )
    result = DirectClipSearch().execute(
        _inputs(tmp_path, ["one", "two"], max_candidates_total=2)
    )
    assert result.success is True
    assert result.data["candidates_considered"] == 2
    assert result.data["clips_downloaded"] == 2


def test_max_width_rejects_oversized_candidate_before_download(monkeypatch, tmp_path):
    source = _Source(
        {"one": [_candidate("large", width=1440, height=2560), _candidate("fit")]},
        size=1500,
    )
    _install_source(monkeypatch, source)
    monkeypatch.setattr(
        module,
        "_probe_media",
        lambda *_a, **_k: {"width": 1080, "height": 1920, "duration": 8.0},
    )
    result = DirectClipSearch().execute(
        _inputs(
            tmp_path,
            ["one"],
            filters={
                "orientation": "portrait",
                "min_duration": 5,
                "min_width": 1080,
                "max_width": 1080,
            },
        )
    )
    assert result.success is True
    assert result.data["clips_downloaded"] == 1
    assert result.data["clips"][0]["clip_id"] == "pexels_fit"
    assert any("exceeds maximum 1080" in item["error"] for item in result.data["errors"])


def test_invalid_reused_file_is_deleted(monkeypatch, tmp_path):
    source = _Source({"one": [_candidate("one")]})
    _install_source(monkeypatch, source)
    clips_dir = tmp_path / "clips"
    clips_dir.mkdir()
    reused = clips_dir / "pexels_one.mp4"
    reused.write_bytes(b"x" * 2048)
    monkeypatch.setattr(
        module,
        "_probe_media",
        lambda *_a, **_k: {"width": 1920, "height": 1080, "duration": 8.0},
    )

    result = DirectClipSearch().execute(_inputs(tmp_path, ["one"]))

    assert result.success is True
    assert result.data["clips_reused"] == 0
    assert result.data["errors"][0]["phase"] == "validation"
    assert not reused.exists()


def test_ffprobe_local_timeout_rejects_candidate_without_claiming_global_timeout(
    monkeypatch,
):
    def raise_timeout(*_args, **kwargs):
        raise module.subprocess.TimeoutExpired("ffprobe", kwargs["timeout"])

    monkeypatch.setattr(module.subprocess, "run", raise_timeout)
    with pytest.raises(module._MediaValidationError, match="media-validation timeout"):
        module._probe_media(Path("candidate.mp4"), timeout_seconds=30)


def test_ffprobe_timeout_at_deadline_is_global_timeout(monkeypatch):
    def raise_timeout(*_args, **kwargs):
        raise module.subprocess.TimeoutExpired("ffprobe", kwargs["timeout"])

    monkeypatch.setattr(module.subprocess, "run", raise_timeout)
    with pytest.raises(module._DeadlineExceeded, match="remaining deadline"):
        module._probe_media(Path("candidate.mp4"), timeout_seconds=5)


def test_nasa_probe_prefers_bounded_rendition():
    urls = [
        "https://images-assets.nasa.gov/video/demo/demo~orig.mp4",
        "https://images-assets.nasa.gov/video/demo/demo~large.mp4",
        "https://images-assets.nasa.gov/video/demo/demo~small.mp4",
        "https://images-assets.nasa.gov/video/demo/demo~medium.mp4",
    ]
    assert _pick_video_url(urls).endswith("~medium.mp4")


def test_pexels_rendition_respects_explicit_max_width():
    files = [
        {"file_type": "video/mp4", "width": 1440, "link": "https://cdn/1440.mp4"},
        {"file_type": "video/mp4", "width": 1080, "link": "https://cdn/1080.mp4"},
        {"file_type": "video/mp4", "width": 720, "link": "https://cdn/720.mp4"},
    ]
    picked = _pick_video_rendition(files, min_width=1080, max_width=1080)
    assert picked is not None
    assert picked["width"] == 1080


def test_pixabay_rendition_respects_explicit_max_width():
    videos = {
        "large": {"url": "https://cdn/1440.mp4", "width": 1440, "height": 2560},
        "medium": {"url": "https://cdn/1080.mp4", "width": 1080, "height": 1920},
        "small": {"url": "https://cdn/720.mp4", "width": 720, "height": 1280},
    }
    picked = _pick_pixabay_rendition(videos, min_width=1080, max_width=1080)
    assert picked is not None
    assert picked["width"] == 1080


def test_metadata_technical_reject_does_not_consume_semantic_candidate_cap(monkeypatch, tmp_path):
    source = _Source(
        {"one": [_candidate("large", width=1440, height=2560), _candidate("fit")]},
        size=1500,
    )
    _install_source(monkeypatch, source)
    monkeypatch.setattr(
        module,
        "_probe_media",
        lambda *_a, **_k: {"width": 1080, "height": 1920, "duration": 8.0},
    )
    result = DirectClipSearch().execute(
        _inputs(
            tmp_path,
            ["one"],
            max_candidates_total=1,
            filters={
                "orientation": "portrait",
                "min_duration": 5,
                "min_width": 1080,
                "max_width": 1080,
            },
        )
    )
    assert result.success is True
    assert result.data["clips_downloaded"] == 1
    assert result.data["clips"][0]["clip_id"] == "pexels_fit"
    assert result.data["candidates_considered"] == 2
    assert result.data["technical_rejects"] == 1
    assert result.data["semantic_candidates_reviewed"] == 1
