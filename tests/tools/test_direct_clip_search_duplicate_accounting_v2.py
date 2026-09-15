from pathlib import Path

from tools.video import direct_clip_search as module
from tools.video.direct_clip_search import DirectClipSearch
from tools.video.stock_sources.base import Candidate


class _Source:
    name = "pexels"

    def __init__(self, candidates_by_query: dict[str, list[Candidate]]):
        self.candidates_by_query = candidates_by_query

    def is_available(self):
        return True

    def search(self, query, _filters):
        return list(self.candidates_by_query.get(query, []))

    def download(self, _candidate, out_path: Path):
        Path(out_path).write_bytes(b"x" * 2048)
        return Path(out_path)


def _candidate(source_id: str) -> Candidate:
    return Candidate(
        source="pexels",
        source_id=source_id,
        source_url=f"https://example.test/{source_id}",
        download_url=f"https://cdn.example.test/{source_id}.mp4",
        kind="video",
        width=720,
        height=1280,
        duration=8.0,
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


def test_duplicate_technical_reject_is_accounted_without_recharging_unique_reject(monkeypatch, tmp_path):
    duplicate = _candidate("same")
    source = _Source({"one": [duplicate], "two": [duplicate]})
    _install_source(monkeypatch, source)

    result = DirectClipSearch().execute({
        "output_dir": str(tmp_path),
        "queries": [
            {"query": "one", "kind": "video"},
            {"query": "two", "kind": "video"},
        ],
        "sources": ["pexels"],
        "clips_per_query": 1,
        "extract_thumbnails": False,
        "filters": {
            "orientation": "portrait",
            "min_duration": 5,
            "min_width": 1080,
        },
        "max_candidates_total": 1,
        "max_bytes_per_clip": 10_000,
        "max_total_download_bytes": 20_000,
        "timeout_seconds": 30,
    })

    assert result.success is True
    assert result.data["candidates_considered"] == 2
    assert result.data["semantic_candidates_reviewed"] == 0
    assert result.data["technical_rejects"] == 1
    assert result.data["duplicate_technical_rejects"] == 1
