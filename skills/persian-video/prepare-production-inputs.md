# Prepare Persian Production Inputs

Use this capability only when `persian-video status` reports `prepare_inputs` or `align_script_timing`.

This is a **production-preparation** capability, not a writing capability. Never translate an article, improve narration, change tone, tighten wording, invent a hook, or otherwise editorially rewrite the authoritative spoken copy here.

## `prepare_inputs`

Read the current project's workflow state. `input.mode` is one of:

- `approved_script_with_narration` — the approved script owns wording; narration audio supplies delivery/timing evidence.
- `approved_script_only` — the approved script owns wording, but timing cannot proceed until narration audio exists.
- `narration_only` — the supplied recording owns the spoken wording; transcribe it faithfully to establish the production script and word timings.

The initial script/audio inputs are copied under the current project's `inputs/` directory at bootstrap. Do not reach back to an article, earlier writing session, sibling project, or external draft for alternate wording.

All mechanical probe/cache/helper/debug output belongs to the current project's official workspace. Never create temporary approved-copy, probe, or helper files in repository root. If approved copy is held by the agent rather than an existing external user file, bootstrap it directly or through stdin (`--approved-script-file -`) so the first durable copy is project-local.

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

Read the workflow's `alignment_policy`, then run the official capability probe before starting any semantic job:

```bash
python -m lib.persian_video_workflow alignment-plan <project-id>
```

The plan is authoritative for provider routing on the execution machine. It records every considered provider, live availability, `word_timestamps` capability/input fit, and the first policy-valid provider. Do **not** execute a provider that the plan already marks unavailable or incompatible. Normal production must then use the durable front door:

```bash
python -m lib.persian_video_workflow alignment-start <project-id>
python -m lib.persian_video_workflow alignment-status <project-id> <job-id>
python -m lib.persian_video_workflow alignment-commit <project-id> <job-id>
```

`alignment-start` freezes the live provider decision before the run-kernel job launches. The child rechecks provider status, persists a digest-bound alignment result, and writes semantic success/failure through the run-kernel result envelope. `alignment-commit` re-hashes the frozen plan and result before workflow advancement. The synchronous `execute_alignment_with_fallback` function is a low-level worker/test primitive, not a normal production entrypoint.

When `scriptAuthority` is `approved_script`, the default is `mode: timing_oriented`: use the smallest adequate word-timing profile first. Do **not** start with a heavy transcription-oriented model merely because it is available; the text is already authoritative and only timing evidence is missing. A heavy transcription model is recovery-only in approved-script mode and may begin only after all policy-valid lightweight providers fail semantic/timing validation.

Persist the returned `provider_decision` when completing `align_script_timing`. It records considered providers, availability/fit, selected provider/tool/model, semantic outcomes, provider execution timing, fallback history/reason, and whether heavy recovery was used. Completion also requires a positive `word_timing_count`; process exit success alone never certifies alignment success.

For `narration_only`, use the transcription-oriented policy because the recording still owns the lexical content as well as timing. Review and correct uncertain ASR spelling against the recording before treating the transcript as authoritative.

Regardless of policy, run the canonical script-alignment gates against the authoritative script and timing words. Persist enough evidence inside the current project to bind the authoritative script hash, narration hash, timing source/provider/model, alignment mode, and any recovery decision. A successful alignment must be reproducible from current-project inputs.

If alignment reveals that approved script and recorded narration say materially different words, stop and surface the mismatch. Do not choose one silently, splice wording, or rewrite the script to make the gate pass.