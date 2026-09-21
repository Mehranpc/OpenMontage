from __future__ import annotations

import io
import urllib.error
from pathlib import Path

from tools.audio.pixabay_music import PixabayMusic


def _fail_search(_inputs: dict) -> list[dict]:
    raise AssertionError("web search must not run in direct CDN mode")


def test_direct_cdn_mode_skips_cloudflare_search_and_preserves_provenance(
    tmp_path: Path, monkeypatch
) -> None:
    tool = PixabayMusic()
    monkeypatch.setattr(tool, "_search", _fail_search)

    seen: dict[str, object] = {}

    def fake_download(track: dict, inputs: dict) -> Path:
        seen["track"] = dict(track)
        output = Path(inputs["output_path"])
        output.write_bytes(b"ID3")
        return output

    monkeypatch.setattr(tool, "_download", fake_download)
    output = tmp_path / "bed.mp3"

    result = tool.execute(
        {
            "query": "warm intimate piano",
            "audio_url": "https://cdn.pixabay.com/audio/2026/01/01/audio_example.mp3",
            "track_title": "Intimate Piano",
            "artist": "ExampleArtist",
            "source_url": "https://pixabay.com/music/example-track-12345/",
            "duration_seconds": 120,
            "output_path": str(output),
        }
    )

    assert result.success is True, result.error
    assert result.data["search_strategy"] == "direct_cdn"
    assert result.data["track_title"] == "Intimate Piano"
    assert result.data["artist"] == "ExampleArtist"
    assert result.data["source_url"] == "https://pixabay.com/music/example-track-12345/"
    assert result.data["duration_seconds"] == 120
    assert output.read_bytes() == b"ID3"
    assert seen["track"] == {
        "title": "Intimate Piano",
        "artist": "ExampleArtist",
        "audio_url": "https://cdn.pixabay.com/audio/2026/01/01/audio_example.mp3",
        "duration": 120,
        "source_url": "https://pixabay.com/music/example-track-12345/",
    }


def test_direct_cdn_mode_rejects_non_pixabay_audio_hosts(
    tmp_path: Path, monkeypatch
) -> None:
    tool = PixabayMusic()
    monkeypatch.setattr(tool, "_search", _fail_search)

    result = tool.execute(
        {
            "query": "warm intimate piano",
            "audio_url": "https://example.com/not-pixabay.mp3",
            "track_title": "Wrong Host",
            "artist": "Unknown",
            "source_url": "https://pixabay.com/music/example-track-12345/",
            "duration_seconds": 120,
            "output_path": str(tmp_path / "bed.mp3"),
        }
    )

    assert result.success is False
    assert "cdn.pixabay.com/audio/" in (result.error or "")


def test_cloudflare_403_explains_that_music_search_has_no_public_api_fallback(
    monkeypatch,
) -> None:
    tool = PixabayMusic()

    def blocked(_inputs: dict) -> list[dict]:
        raise urllib.error.HTTPError(
            "https://pixabay.com/music/",
            403,
            "Forbidden",
            hdrs=None,
            fp=io.BytesIO(b"Just a moment..."),
        )

    monkeypatch.setattr(tool, "_search", blocked)
    result = tool.execute({"query": "warm intimate piano"})

    assert result.success is False
    error = result.error or ""
    assert "Cloudflare" in error
    assert "public Music API" in error
    assert "direct Pixabay CDN" in error
