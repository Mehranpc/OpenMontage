# Script-aligned Persian SRT

Use this contract whenever narrated `persian-footage` writes a sidecar subtitle.

## Authority boundary

- `edit_decisions.metadata.persianSubtitleScript` is the authoritative delivery copy.
- `edit_decisions.persian.audio.wordTimings` is raw ASR/Whisper timing evidence only.
- Never copy ASR spelling into the SRT, even when alignment is fuzzy.

The approved-script record is:

```json
{
  "text": "approved narration sections joined with one ASCII space",
  "sha256": "sha256 of the exact UTF-8 text bytes",
  "matchPolicy": "exact",
  "maxCps": 21
}
```

`matchPolicy` is either:

- `exact` — the cue texts, joined with one ASCII space, must equal `text` byte for byte.
- `normalized` — only OpenMontage Persian letter and digit canonicalization is allowed;
  lexical wording still must equal the approved script.

`maxCps` may lower the repository ceiling but cannot raise it above 21 visible
characters per second.

## Required gate

The registered `persian_compose` implementation aligns groups of approved tokens to
raw ASR words, including one-to-many and many-to-one splits such as `می‌کنی` versus
`می` + `کنی`. It preserves script punctuation and phrase boundaries, then audits:

1. approved-script SHA-256 and exact/normalized lexical equality;
2. canonical Persian code points, single spacing, and valid ZWNJ placement;
3. ordered, non-overlapping ASR word windows;
4. alignment confidence and the fraction of unmatched ASR insertions;
5. cue ordering, extent, minimum duration, and configured reading speed;
6. coverage of every timed spoken word, including the head and tail.

Any failure blocks before Remotion renders. The remedy is to correct the approved
script, supply the matching narration timing set, shorten an over-speed script, or
record a slower delivery. Never suppress the gate, hand-time three sentences into one
short cue, or substitute raw Whisper text.

## Silent mode

Silent mode has neither narration nor `wordTimings`, so it produces no SRT and does
not need `persianSubtitleScript`.
