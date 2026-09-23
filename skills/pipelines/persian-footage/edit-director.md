# Edit Director — Persian Footage Pipeline

Film Type 2.16.0 / layout 16 is the default for every Persian-footage run. Read `film-type.md` and the edit phase card. Do not load `film-type-history.md` unless an older profile is explicitly pinned. Detailed authoring examples and rationale live in `references/edit-authoring.md` and are opened only for the failing rule.

## Output contract

Produce schema-valid `edit_decisions` with `render_runtime: "remotion"`, `composition_mode: "templated"`, `renderer_family: "persian-footage"`, and a `persian` block containing format, duration, shots, moments, audio timing, captions, music decision, design pin, and canonical brand lock.

Run joint preflight before persistence: exact/adaptable copy, selected shot/window/crop, truthful avoid regions, placement, fit, dwell, cuts, captions, music, and brand schedule must be feasible together. Never persist failed probes.

## Selective moments

Moments are editorial emphasis, not transcript chunks. Each is one grammatical Persian phrase represented by ordered `segments` (reading order top-to-bottom), exactly one `hero` per reveal step, at most one final `source`, and no retired `text`, `label`, `kicker`, `unit`, `highlight`, `cues`, or `hookText` keys. Spoken quantities stay whole inside the hero.

Use `phraseLocks` only for multi-word semantic units. Copy that must survive literally carries an exact-text SHA record. Normal copy must already be repository-normalized; never silently repair approved text.

Active Film Type accepts/rejects copy by measured Estedad pixel fit and curated recipes, not historical character ceilings. Placement is resolved from reviewed crop/avoid geometry; do not weaken an avoid region to force a candidate.

The first moment is the hook, starts by 0.6s, and must be earned by the approved narration/video. For production pattern interruption, retain clause-level meaning; do not collapse to a label to solve fit.

## Timing and pacing

Every narrated moment carries spoken-form `anchorText`. Re-derive timings from current word timings; never rescale an old edit by duration ratio. With `simultaneous_hook_typography=True`, each active 2.16 hook remains a complete 3–5 second composition.

```python
from lib.persian_sync import TimedWord, audit_sync, retime_moments

words = TimedWord.from_dicts(audio["wordTimings"])
moments = retime_moments(
    moments,
    words,
    simultaneous_hook_typography=True,
)
assert not audit_sync(moments, words).problems
```

Every reveal step must satisfy the canonical reading model; moments remain 2.4–9s, adjacent gaps ≥0.9s, density 7–9 per 60s, and total editorial text coverage ≤55%.

## Captions and music

`metadata.persianSubtitleScript` owns delivered words; ASR contributes timing only. `captionMode` is `sidecar_only`, `burned_captions`, or `hybrid` (default for new Instagram/Reels). Burned captions are runtime-derived, one/two lines, never karaoke, and yield to editorial moments. Read `subtitle-alignment.md` only when alignment/cue repair is active.

`persian.musicTrack` is the single music owner. Narrated mode requires it unless `omitMusicReason` records deliberate silence. Never also author `persian.audio.music`. Unknown risk requires `persian.acknowledgeUnknownMusicRisk`; high risk is refused.

```json
"musicTrack": {
  "path": "assets/music/track.mp3",
  "source": "pixabay_music",
  "license": {"name": "Pixabay Content License", "url": "https://pixabay.com/service/license-summary/", "downloadedAt": "2026-09-02"},
  "contentIdRisk": {"level": "low", "reason": "licensed use; third-party claims remain possible"}
}
```

```json
"audio": {
    "narration": "assets/audio/voiceover.mp3",
    "wordTimings": []
}
```

## Shots

Shots tile the timeline contiguously, one per visual event, with `semanticBeatId`, `visualEventId`, explicit cut grammar, source window, reviewed crop, truthful avoid regions, attribution, subject/human evidence, and selection reason. The opening carries visible hook evidence; the final quarter carries resolution. No missing path or black gap is acceptable.

## Gate

```python
from lib.persian_moments import audit_moments, build_moments
from lib.persian_text import normalize

moments = build_moments(authored_moments)
audit = audit_moments(moments, duration_seconds=duration_seconds, v2=True)
assert not audit.problems, audit.problems
assert all(normalize(s.text) == s.text for m in moments for s in m.segments)
```

Also run `python -m lib.persian_preflight`; require shot coverage, current-profile geometry, exact copy hashes, caption authority, music audit, sync audit, and canonical brand lock. Advisories require explicit checkpoint answers.

## Stop and success

Stop for copy changes, unsupported facts, missing timings, no feasible crop/placement/fit, incomplete shot coverage, invalid music/caption authority, or any audit problem. Send back only the owning scope.

Success is a single deterministic, schema-valid `edit_decisions` artifact that passes moment, sync, retention, caption, music, copy, geometry, and preflight gates. Open `references/edit-authoring.md` only for detailed examples or a named failure.