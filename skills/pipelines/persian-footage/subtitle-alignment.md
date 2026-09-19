# Script-aligned Persian captions

Use this contract for every narrated `persian-footage` caption surface: sidecar SRT, burned captions, or hybrid.

## Authority boundary

- `edit_decisions.metadata.persianSubtitleScript` is the authoritative delivery copy.
- `edit_decisions.persian.audio.wordTimings` is raw ASR/Whisper timing evidence only.
- Never copy ASR spelling into either SRT or burned pixels, even when alignment is fuzzy.

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


## Provider capability routing

Provider choice is a capability decision, not an agent preference. Before alignment execution, use the Persian front door `alignment-plan` command. A provider must be live-available, accept project-local `input_path` audio, and expose `word_timestamps`; known-unavailable providers are skipped without invocation. The deterministic fallback order is persisted with the alignment result, including selected provider/model, semantic outcome, execution duration, fallback reason/history, and heavy-recovery status.

In approved-script mode, the provider supplies timing evidence only. Exhaust policy-valid lightweight timing providers before any heavy transcription recovery. In narration-only mode, preserve the transcription-oriented full-transcription profile because the recording still owns lexical content. Never infer successful alignment from a wrapper/process exit code when the provider `ToolResult.success` is false or no word timestamps are produced.

## Required gate

The registered `persian_compose` implementation aligns groups of approved tokens to
raw ASR words, including one-to-many and many-to-one splits such as `می‌کنی` versus
`می` + `کنی`. It preserves script punctuation and phrase boundaries, then audits:

1. approved-script SHA-256 and exact/normalized lexical equality;
2. canonical Persian code points, single spacing, and valid ZWNJ placement;
3. ordered, non-overlapping ASR word windows;
4. alignment confidence and the fraction of unmatched ASR insertions;
5. cue ordering, extent, minimum duration, and configured reading speed;
6. coverage of every timed spoken word, including the head and tail;
7. for burned/hybrid mode, a tighter grouping ceiling that can be laid out in at most two conservative lines without changing approved words.

Any failure blocks before Remotion renders. The remedy is to correct the approved
script, supply the matching narration timing set, shorten an over-speed script, or
record a slower delivery. Never suppress the gate, hand-time three sentences into one
short cue, or substitute raw Whisper text. Sidecar grouping may be looser because the
platform owns line layout; burned grouping is deliberately tighter because OpenMontage
owns the pixels. Both are re-derived from the same aligned approved timed words.

## Caption modes and priority

`sidecar_only`, `burned_captions`, and `hybrid` are the only modes. Instagram /
Instagram Reels defaults to `hybrid` for new production; a missing platform on a legacy
artifact retains sidecar-only behavior. Burned captions are never authored props: the
registered `persian_compose` builds them at runtime. An editorial moment owns the frame
while it is active, so its overlapping caption is suppressed. The caption safe-area
band is also reserved from the moving watermark planner.

## Silent mode

Silent mode has neither narration nor `wordTimings`, so it produces no SRT and does
not need `persianSubtitleScript`.
