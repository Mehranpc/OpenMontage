# Prepare Persian Production Inputs

Use this capability only when `persian-video status` reports `prepare_inputs` or `align_script_timing`.

This is a **production-preparation** capability, not a writing capability. Never translate an article, improve narration, change tone, tighten wording, invent a hook, or otherwise editorially rewrite the authoritative spoken copy here.

## `prepare_inputs`

Read the current project's workflow state. `input.mode` is one of:

- `approved_script_with_narration` — the approved script owns wording; narration audio supplies delivery/timing evidence.
- `approved_script_only` — the approved script owns wording, but timing cannot proceed until narration audio exists.
- `narration_only` — the supplied recording owns the spoken wording; transcribe it faithfully to establish the production script and word timings.

The initial script/audio inputs are copied under the current project's `inputs/` directory at bootstrap. Do not reach back to an article, earlier writing session, sibling project, or external draft for alternate wording.
### Approved script is authoritative

When an approved script exists, preserve its lexical wording. Read `skills/pipelines/persian-footage/script-director.md` in its **authoritative-input/fidelity mode**: validate and package the supplied copy; do not author a replacement.

Technical corrections are limited to what the canonical subtitle contract permits. Prefer `matchPolicy: "exact"`. Use `normalized` only when Persian letter/digit canonicalization is required; normalization must never change lexical wording.

Run the canonical `idea` stage from the approved content so later visual planning has a valid brief. Then persist the canonical `script` artifact/checkpoint from the authoritative text. The fact that the pipeline needs these artifacts does not reopen the copy for editorial revision.

### Narration-only input

Transcribe the supplied narration faithfully with word-level timings. The audio, not ASR spelling, is the authority. Review uncertain ASR words against the recording and correct transcription errors to what was actually spoken; do not improve what the speaker said.

Use that faithful transcript as the production script, then create the normal `idea` and `script` artifacts/checkpoints. This is transcription and packaging, not narration authoring.
### Script-first without audio

If `input.mode` is `approved_script_only`, do not complete `prepare_inputs` yet. Present the production blocker plainly: timing requires narration audio.

Allowed next steps are:

- the user supplies/records narration, then run `persian-video attach-narration`;
- the user explicitly approves a TTS path, after which generate audio from the exact approved script and attach that result.

Do not silently synthesize speech, and do not use the missing audio as a reason to rewrite the script. Once narration is attached, re-read workflow state and continue the same project.

Complete `prepare_inputs` only when the project has both an authoritative production script and narration audio suitable for timing.

## `align_script_timing`

Read `skills/pipelines/persian-footage/subtitle-alignment.md` before alignment. Approved-script wording owns every delivered character; ASR owns timing evidence only. For narration-only projects, the reviewed faithful transcript becomes the approved production text for this rule.

Persist enough evidence inside the current project to bind the authoritative script hash to the narration/timing source. A successful alignment must be reproducible from current-project inputs and pass the repository's alignment gates.

If alignment reveals that approved script and recorded narration say materially different words, stop and surface the mismatch. Do not choose one silently, splice wording, or rewrite the script to make the gate pass.