# Pixabay Music in OpenMontage

Pixabay Music is handled differently from Pixabay Images and Videos.

## Important API boundary

`PIXABAY_API_KEY` unlocks Pixabay's documented image/video API integrations in OpenMontage. It does **not** provide a public Pixabay Music search API. Do not route Music discovery through that key or describe it as a Music API credential.

The `pixabay_music` tool therefore has two modes:

- `web_search`: best-effort legacy search against the public Pixabay Music page. This can be blocked by Cloudflare and must not be treated as a reliable unattended discovery path.
- `direct_cdn`: the stable production path once a real public Pixabay track has been selected. It validates that the audio comes from Pixabay's public CDN and that the track has Pixabay Music provenance metadata.

## Canonical production flow

For production work, prefer this sequence:

1. Use `ego-browser` to open `https://pixabay.com/music/` in a normal browser session.
2. Search/browse for a track that fits the edit and inspect the real track page.
3. Verify the visible title, contributor/artist, duration, and Pixabay Content License context.
4. Arm the browser download event **before** clicking `Free download`.
5. Save the downloaded MP3 directly inside the current project, normally under `projects/<project-id>/assets/music/`.
6. Capture the browser-reported download URL and pass it to `pixabay_music` using `audio_url`, together with `track_title`, `artist`, `source_url`, and `duration_seconds`.
7. Persist the normalized `pixabay_music` result as the provenance source for the edit/music manifest, then probe the saved file with ffprobe before compose.

Conceptually:

```text
ego-browser discovery/download
    -> real Pixabay track page + browser download URL
    -> pixabay_music direct_cdn validation/provenance
    -> project-local MP3
    -> edit/musicTrack
```

## Browser policy

Use the normal `ego-browser` page and ordinary user-facing interactions. Do not build custom stealth logic, CAPTCHA bypasses, or headless anti-bot workarounds. If Pixabay requires an explicit human verification step, hand browser control to the user and resume the same TaskSpace afterward.

Do not invent a CDN URL or provenance fields. The direct-CDN mode is intentionally restricted to public Pixabay audio CDN paths and requires a Pixabay Music source page plus real title, artist, and duration metadata.

## Failure handling

- If legacy `pixabay_music` web search returns Cloudflare HTTP 403, do **not** retry it as if `PIXABAY_API_KEY` were a Music fallback.
- Prefer `ego-browser` discovery/download for the same provider.
- Do not silently switch to a different music provider unless the active pipeline contract explicitly permits that provider.
- Keep cookies/browser state local; never commit browser profiles, cookies, downloads outside project-local asset paths, or credentials to GitHub.

## Current implementation

`tools/audio/pixabay_music.py` implements the `direct_cdn` path. It accepts a real browser-observed Pixabay audio URL and validates the host/path before download. The provider result includes track metadata, license text, `source_url`, and `search_strategy=direct_cdn` for downstream provenance.
