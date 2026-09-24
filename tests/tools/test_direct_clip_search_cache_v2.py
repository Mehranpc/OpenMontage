import time
from pathlib import Path

from tools.video import direct_clip_search as module
from tools.video.direct_clip_search import DirectClipSearch
from tools.video.stock_sources.base import Candidate


class Source:
    name = "pexels"

    def __init__(self):
        self.search_calls = 0
        self.download_calls = 0

    def is_available(self):
        return True

    def search(self, query, filters):
        self.search_calls += 1
        return [Candidate(
            source=self.name,
            source_id=f"{query}-1",
            source_url=f"https://example.test/{query}",
            download_url=f"https://cdn.example.test/{query}.mp4",
            kind="video",
            width=1080,
            height=1920,
            duration=8.0,
        )]

    def download(self, candidate, out_path: Path):
        self.download_calls += 1
        Path(out_path).write_bytes(b"x" * 2048)
        return Path(out_path)


def install(monkeypatch, source):
    import tools.video.stock_sources as catalog
    monkeypatch.setattr(catalog, "all_sources", lambda: [source])
    monkeypatch.setattr(catalog, "available_sources", lambda: [source])
    monkeypatch.setattr(catalog, "get_source", lambda _name: source)
    monkeypatch.setattr(catalog, "source_summary", lambda: {"available_source_names": [source.name]})
    monkeypatch.setattr(module, "_probe_media", lambda *_a, **_k: {"duration": 8.0, "width": 1080, "height": 1920})


def inputs(tmp_path, **overrides):
    value = {
        "output_dir": str(tmp_path / "assets"),
        "queries": [{"query": "coffee hands", "slot_id": "event-1", "kind": "video"}],
        "sources": ["pexels"],
        "clips_per_query": 1,
        "extract_thumbnails": False,
        "filters": {"orientation": "portrait", "min_duration": 5, "min_width": 1080},
        "max_candidates_total": 4,
        "max_bytes_per_clip": 10_000,
        "max_total_download_bytes": 20_000,
        "timeout_seconds": 30,
        "search_cache_ttl_seconds": 3600,
    }
    value.update(overrides)
    return value


def test_identical_search_uses_project_cache_without_provider_call_or_rewrite(monkeypatch, tmp_path):
    source = Source()
    install(monkeypatch, source)
    monkeypatch.setattr(module.time, "time", lambda: 1000.0)
    first = DirectClipSearch().execute(inputs(tmp_path))
    assert first.success
    assert source.search_calls == 1
    cache_files = list((tmp_path / "assets" / ".search-cache").glob("*.json"))
    assert len(cache_files) == 1
    mtime = cache_files[0].stat().st_mtime_ns

    second = DirectClipSearch().execute(inputs(tmp_path))
    assert second.success
    assert source.search_calls == 1
    assert source.download_calls == 1
    assert second.data["search_cache_hits"] == 1
    assert second.data["search_cache_misses"] == 0
    assert cache_files[0].stat().st_mtime_ns == mtime


def test_filter_change_misses_search_cache(monkeypatch, tmp_path):
    source = Source()
    install(monkeypatch, source)
    monkeypatch.setattr(module.time, "time", lambda: 1000.0)
    assert DirectClipSearch().execute(inputs(tmp_path)).success
    changed = inputs(tmp_path, filters={"orientation": "portrait", "min_duration": 6, "min_width": 1080})
    assert DirectClipSearch().execute(changed).success
    assert source.search_calls == 2


def test_expired_search_cache_refetches_provider(monkeypatch, tmp_path):
    source = Source()
    install(monkeypatch, source)
    clock = {"now": 1000.0}
    monkeypatch.setattr(module.time, "time", lambda: clock["now"])
    assert DirectClipSearch().execute(inputs(tmp_path, search_cache_ttl_seconds=10)).success
    clock["now"] = 1011.0
    assert DirectClipSearch().execute(inputs(tmp_path, search_cache_ttl_seconds=10)).success
    assert source.search_calls == 2
