# Rehearsal fixture: first-date-message-timing

Source: the 2026-09-27 production run `first-date-message-timing` on 348af5d, exported read-only (see #260).

- `narration.mp3`, `approved_script.txt`: the real inputs. **Temporary**: once the testing/bug-fix phase is done, they get replaced with a synthetic narration of the same length (Mehran, 2026-09-27).
- `clips/`: every clip the run downloaded (Pexels License), re-encoded at the original geometry with CRF 46 and no audio. Resolution and duration still pass the production filters; picture detail is deliberately poor.
- `music-bed.mp3`: the run's Pixabay music bed, trimmed to 70s, mono, 48 kbps.
- `recorded/search-cache/`: the provider search results the run cached, keyed exactly like `direct_clip_search`'s `.search-cache`.
- `recorded/transcript.json`: the real `transcriber` (whisperx base) output for this narration.
- `recorded/word-timings.json`: the committed script word timings.
