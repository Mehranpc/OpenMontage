"""Music search and download from Pixabay Music.

Pixabay's public developer API exposes images and videos, not Music search.  This
source therefore supports two modes:

* best-effort web search against Pixabay Music's public pages; and
* a stable direct-CDN mode for a browser-selected public Pixabay track.

The direct mode deliberately accepts only Pixabay's public audio CDN plus a Pixabay
Music source page, so callers can avoid Cloudflare-dependent scraping without turning
this tool into a generic arbitrary-URL downloader.
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from tools.base_tool import (
    BaseTool,
    Determinism,
    ExecutionMode,
    ResourceProfile,
    RetryPolicy,
    ToolResult,
    ToolRuntime,
    ToolStability,
    ToolStatus,
    ToolTier,
)


class PixabayMusic(BaseTool):
    name = "pixabay_music"
    version = "0.2.0"
    tier = ToolTier.SOURCE
    capability = "music_search"
    provider = "pixabay_music"
    stability = ToolStability.EXPERIMENTAL
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.DETERMINISTIC
    runtime = ToolRuntime.API

    dependencies = []
    install_instructions = (
        "No API key enables Pixabay Music search: Pixabay's public API documents "
        "images and videos only. The tool can search the public Music page when it is "
        "reachable, or accept a browser-selected public cdn.pixabay.com audio URL "
        "with its Pixabay Music source-page metadata."
    )

    agent_skills = ["music"]

    capabilities = ["search_music", "download_music", "stock_music"]
    supports = {
        "duration_filter": True,
        "free_commercial_use": True,
        "direct_cdn": True,
        "music_api_key": False,
    }
    best_for = [
        "royalty-free Pixabay background music",
        "direct download of a browser-selected public Pixabay Music track",
        "best-effort Pixabay Music web search when the public page is reachable",
    ]
    not_good_for = [
        "reliable unattended Music search when Pixabay presents an anti-bot challenge",
        "precise metadata filtering",
        "offline use",
    ]

    fallback_tools = ["freesound_music", "music_gen"]

    input_schema = {
        "type": "object",
        "required": ["query"],
        "properties": {
            "query": {
                "type": "string",
                "description": "Search/provenance query (e.g. 'upbeat corporate background')",
            },
            "min_duration": {
                "type": "number",
                "default": 30,
                "minimum": 1,
                "description": "Minimum duration in seconds for web-search mode",
            },
            "max_duration": {
                "type": "number",
                "default": 120,
                "maximum": 600,
                "description": "Maximum duration in seconds for web-search mode",
            },
            "output_path": {
                "type": "string",
                "description": "File path to save the downloaded MP3",
            },
            "audio_url": {
                "type": "string",
                "description": (
                    "Optional public Pixabay audio CDN URL. When supplied, direct_cdn "
                    "mode skips Pixabay Music page search entirely."
                ),
            },
            "track_title": {
                "type": "string",
                "description": "Track title for direct_cdn provenance",
            },
            "artist": {
                "type": "string",
                "description": "Pixabay contributor/artist for direct_cdn provenance",
            },
            "source_url": {
                "type": "string",
                "description": "Public pixabay.com/music/ source page for the direct track",
            },
            "duration_seconds": {
                "type": "number",
                "minimum": 1,
                "description": "Published track duration for direct_cdn provenance",
            },
        },
    }

    resource_profile = ResourceProfile(
        cpu_cores=1, ram_mb=256, vram_mb=0, disk_mb=50, network_required=True
    )
    retry_policy = RetryPolicy(max_retries=2, retryable_errors=["timeout"])
    idempotency_key_fields = [
        "query",
        "audio_url",
        "min_duration",
        "max_duration",
    ]
    side_effects = [
        "writes audio file to output_path",
        "scrapes Pixabay website only when audio_url is absent",
    ]
    user_visible_verification = [
        "Listen to downloaded track for mood and quality",
    ]

    _USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    )

    _BROWSER_HEADERS = {
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;"
            "q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8"
        ),
        "Accept-Language": "en-US,en;q=0.9",
        "Sec-Ch-Ua": '"Chromium";v="131", "Not_A Brand";v="24"',
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": '"Windows"',
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Upgrade-Insecure-Requests": "1",
    }

    _DIRECT_AUDIO_PATH_PREFIXES = ("/audio/", "/download/audio/")

    def get_status(self) -> ToolStatus:
        # Direct-CDN mode remains available even when Pixabay's search page is blocked.
        return ToolStatus.AVAILABLE

    def estimate_cost(self, inputs: dict[str, Any]) -> float:
        return 0.0

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        start = time.time()

        try:
            if str(inputs.get("audio_url") or "").strip():
                track = self._direct_track(inputs)
                tracks = [track]
                filtered = tracks
                search_strategy = "direct_cdn"
            else:
                search_strategy = "web_search"
                try:
                    tracks = self._search(inputs)
                except urllib.error.HTTPError as exc:
                    if exc.code == 403:
                        raise RuntimeError(
                            "Pixabay Music web search was blocked by Cloudflare (HTTP 403). "
                            "Pixabay has no public Music API fallback; PIXABAY_API_KEY is for "
                            "the documented image/video API. Supply a browser-selected direct "
                            "Pixabay CDN audio_url from cdn.pixabay.com/audio/ together with "
                            "track_title, artist, source_url, and duration_seconds."
                        ) from exc
                    raise

                if not tracks:
                    return ToolResult(
                        success=False,
                        error=f"No music found on Pixabay for query: {inputs['query']}",
                        data={"query": inputs["query"]},
                        duration_seconds=round(time.time() - start, 2),
                    )

                min_dur = inputs.get("min_duration", 30)
                max_dur = inputs.get("max_duration", 120)
                filtered = [
                    candidate
                    for candidate in tracks
                    if candidate.get("duration") is not None
                    and min_dur <= candidate["duration"] <= max_dur
                ]
                if not filtered:
                    filtered = tracks
                track = filtered[0]

            output_path = self._download(track, inputs)

        except Exception as exc:
            return ToolResult(
                success=False,
                error=f"Pixabay music search failed: {exc}",
                duration_seconds=round(time.time() - start, 2),
            )

        return ToolResult(
            success=True,
            data={
                "provider": "pixabay_music",
                "track_title": track.get("title", "Unknown"),
                "artist": track.get("artist", "Unknown"),
                "duration_seconds": track.get("duration"),
                "query": inputs["query"],
                "output": str(output_path),
                "format": "mp3",
                "license": "Pixabay Content License (free, no attribution required)",
                "source_url": track.get("source_url"),
                "search_strategy": search_strategy,
                "results_found": len(tracks),
                "results_after_filter": len(filtered),
            },
            artifacts=[str(output_path)],
            cost_usd=0.0,
            duration_seconds=round(time.time() - start, 2),
        )

    def _direct_track(self, inputs: dict[str, Any]) -> dict[str, Any]:
        audio_url = str(inputs.get("audio_url") or "").strip()
        self._validate_audio_url(audio_url)

        source_url = str(inputs.get("source_url") or "").strip()
        parsed_source = urllib.parse.urlparse(source_url)
        if (
            parsed_source.scheme != "https"
            or parsed_source.hostname not in {"pixabay.com", "www.pixabay.com"}
            or not parsed_source.path.startswith("/music/")
        ):
            raise ValueError(
                "direct Pixabay music requires source_url on https://pixabay.com/music/"
            )

        title = str(inputs.get("track_title") or "").strip()
        artist = str(inputs.get("artist") or "").strip()
        if not title or not artist:
            raise ValueError("direct Pixabay music requires track_title and artist")
        try:
            duration = float(inputs["duration_seconds"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(
                "direct Pixabay music requires numeric duration_seconds"
            ) from exc
        if duration <= 0:
            raise ValueError("direct Pixabay music duration_seconds must be positive")

        return {
            "title": title,
            "artist": artist,
            "audio_url": audio_url,
            "duration": duration,
            "source_url": source_url,
        }

    def _validate_audio_url(self, audio_url: str) -> None:
        parsed = urllib.parse.urlparse(str(audio_url or "").strip())
        if (
            parsed.scheme != "https"
            or parsed.hostname != "cdn.pixabay.com"
            or not any(
                parsed.path.startswith(prefix)
                for prefix in self._DIRECT_AUDIO_PATH_PREFIXES
            )
        ):
            raise ValueError(
                "Pixabay music audio_url must use HTTPS on cdn.pixabay.com/audio/ "
                "(the legacy /download/audio/ CDN path is also accepted)"
            )

    def _build_opener(self) -> urllib.request.OpenerDirector:
        """Build a URL opener with cookie support for session persistence."""
        import http.cookiejar

        cj = http.cookiejar.CookieJar()
        return urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(cj)
        )

    def _search(self, inputs: dict[str, Any]) -> list[dict]:
        """Search Pixabay Music via the bootstrap JSON used by its public page."""
        query = inputs["query"]
        slug = re.sub(r"\s+", "-", query.strip().lower())
        slug = urllib.parse.quote(slug, safe="-")
        search_url = f"https://pixabay.com/music/search/{slug}/"

        opener = self._build_opener()
        request = urllib.request.Request(search_url)
        request.add_header("User-Agent", self._USER_AGENT)
        for key, val in self._BROWSER_HEADERS.items():
            request.add_header(key, val)

        with opener.open(request, timeout=30) as response:
            html = response.read().decode("utf-8", errors="replace")

        tracks = self._parse_bootstrap(html, search_url, opener)
        if tracks:
            return tracks
        return self._parse_tracks_html(html)

    def _parse_bootstrap(
        self,
        html: str,
        referer: str,
        opener: urllib.request.OpenerDirector,
    ) -> list[dict]:
        """Extract tracks from Pixabay's page bootstrap JSON endpoint."""
        match = re.search(
            r'window\.__BOOTSTRAP_URL__\s*=\s*["\']([^"\']+)["\']',
            html,
        )
        if not match:
            return []

        bootstrap_path = match.group(1)
        if not bootstrap_path:
            return []

        bootstrap_url = f"https://pixabay.com{bootstrap_path}"
        req = urllib.request.Request(bootstrap_url)
        req.add_header("User-Agent", self._USER_AGENT)
        req.add_header("Accept", "application/json, text/plain, */*")
        req.add_header("Referer", referer)
        req.add_header("Sec-Fetch-Dest", "empty")
        req.add_header("Sec-Fetch-Mode", "cors")
        req.add_header("Sec-Fetch-Site", "same-origin")

        try:
            with opener.open(req, timeout=15) as response:
                data = json.loads(response.read().decode("utf-8"))
        except Exception:
            return []

        results = data.get("page", {}).get("results", [])
        tracks: list[dict] = []
        for item in results:
            sources = item.get("sources", {})
            audio_url = sources.get("src")
            if not audio_url:
                continue
            user = item.get("user", {}) or {}
            tracks.append(
                {
                    "title": item.get("name")
                    or sources.get("filename", "Unknown"),
                    "audio_url": audio_url,
                    "duration": item.get("duration"),
                    "artist": user.get("username", "Unknown"),
                    "rating": item.get("rating"),
                    "download_count": item.get("downloadCount"),
                    "pixabay_id": item.get("id"),
                    "source_url": item.get("pageURL") or item.get("pageUrl"),
                }
            )

        return tracks

    def _parse_tracks_html(self, html: str) -> list[dict]:
        """Fallback: extract public Pixabay audio CDN URLs from page HTML."""
        tracks: list[dict] = []
        mp3_urls = re.findall(
            r'(https?://cdn\.pixabay\.com/(?:download/)?audio/[^\s"\'<>]+\.mp3[^\s"\'<>]*)',
            html,
        )
        seen: set[str] = set()
        for url in mp3_urls:
            if url not in seen:
                seen.add(url)
                tracks.append(
                    {
                        "title": "Unknown",
                        "audio_url": url,
                        "duration": None,
                        "artist": "Unknown",
                    }
                )
        return tracks

    def _download(self, track: dict, inputs: dict[str, Any]) -> Path:
        """Download an MP3 track to the output path."""
        audio_url = str(track.get("audio_url") or "").strip()
        if not audio_url:
            raise RuntimeError("No audio URL found for the selected track.")
        self._validate_audio_url(audio_url)

        track_title = track.get("title", "pixabay_music")
        safe_title = "".join(
            c if c.isalnum() or c in "._- " else "_" for c in track_title
        )
        default_filename = f"pixabay_music_{safe_title[:60]}.mp3"
        output_path = Path(inputs.get("output_path", default_filename))
        output_path.parent.mkdir(parents=True, exist_ok=True)

        request = urllib.request.Request(
            audio_url,
            headers={
                "User-Agent": self._USER_AGENT,
                "Referer": "https://pixabay.com/music/",
            },
        )
        with urllib.request.urlopen(request, timeout=60) as response:
            output_path.write_bytes(response.read())

        return output_path
