from __future__ import annotations

from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    file_path = Path(path)
    text = file_path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected one exact match, found {count}")
    file_path.write_text(text.replace(old, new, 1), encoding="utf-8")


replace_once(
    "tests/contracts/test_persian_artifact_schemas.py",
    '''    ts_fields = set()
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped.startswith("readonly "):
            continue
        name = stripped[len("readonly ") :].split(":", 1)[0]
        ts_fields.add(name.rstrip("?"))
''',
    '''    ts_fields = set()
    for line in body.splitlines():
        # Only two-space-indented members belong to PersianMoment itself.
        # Nested members (for example exactText.text/sha256) are properties of
        # their inline object and must not be compared with moment-level schema keys.
        if not line.startswith("  readonly "):
            continue
        name = line[len("  readonly ") :].split(":", 1)[0]
        ts_fields.add(name.rstrip("?"))
''',
)

replace_once(
    "tests/tools/test_documentary_governance.py",
    '''        def download(self, candidate, out_path: Path):
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_bytes(b"0" * 2048)
            clock["now"] = 2.0
            return out_path
''',
    '''        def download(self, candidate, out_path: Path):
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_bytes(b"0" * 2048)
            return out_path
''',
)

replace_once(
    "tests/tools/test_documentary_governance.py",
    '''    source = SlowThumbnailSource("thumb_source", True)
    monkeypatch.setattr(stock_sources, "all_sources", lambda: [source])
    monkeypatch.setattr(stock_sources, "available_sources", lambda: [source])
    monkeypatch.setattr(
        stock_sources,
        "source_summary",
        lambda: {
            "configured": 1,
            "total": 1,
            "available_source_names": ["thumb_source"],
            "unavailable_source_names": [],
        },
    )
    monkeypatch.setattr(direct_clip_search.time, "time", lambda: clock["now"])

    result = DirectClipSearch().execute(
''',
    '''    source = SlowThumbnailSource("thumb_source", True)
    monkeypatch.setattr(stock_sources, "all_sources", lambda: [source])
    monkeypatch.setattr(stock_sources, "available_sources", lambda: [source])
    monkeypatch.setattr(
        stock_sources,
        "source_summary",
        lambda: {
            "configured": 1,
            "total": 1,
            "available_source_names": ["thumb_source"],
            "unavailable_source_names": [],
        },
    )
    monkeypatch.setattr(direct_clip_search.time, "time", lambda: clock["now"])
    monkeypatch.setattr(
        direct_clip_search,
        "_probe_media",
        lambda _path, *, timeout_seconds: {
            "duration": 4.0,
            "width": 1920,
            "height": 1080,
        },
    )

    def timeout_thumbnail(_video_path, _thumb_path, *, timeout_seconds):
        clock["now"] = 2.0
        raise direct_clip_search._DeadlineExceeded("thumbnail deadline")

    monkeypatch.setattr(
        direct_clip_search,
        "_extract_mid_thumbnail",
        timeout_thumbnail,
    )

    result = DirectClipSearch().execute(
''',
)

print("materialized deterministic baseline test repairs")
