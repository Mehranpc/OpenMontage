---
name: persian-video
description: Reliable front door for a fresh, bounded, resumable Persian video production.
---

# Persian Video

Use this skill when a new session starts a Persian video from narration audio, an approved Persian script, raw text, or an English article.

The ordered workflow, retry/send-back limits, stock-download ceilings, read isolation, and terminal state are owned by `lib/persian_video_workflow.py`. Do not reproduce or reorder its phase list in prose. The canonical stage contracts remain in `pipeline_defs/persian-footage.yaml` and `skills/pipelines/persian-footage/`.

## Start exactly once

Create a genuinely new project before reading any prior project artifact:

```bash
python -m lib.persian_video_workflow bootstrap --title "Title" --narration /abs/narration.wav
python -m lib.persian_video_workflow bootstrap --title "Title" --script-file /abs/script.txt
python -m lib.persian_video_workflow bootstrap --title "Title" --raw-text-file /abs/source.txt
python -m lib.persian_video_workflow bootstrap --title "Title" --english-article-file /abs/article.txt
```
Bootstrap creates `projects/<new-id>/`, copies text input into that project when needed, records a hash-bound workflow state, and opens that project's Backlot board. An existing project directory is a hard refusal, never a resume shortcut.

For a later session, resume the same bounded state without resetting durable counters:

```bash
python -m lib.persian_video_workflow resume <project-id>
python -m lib.persian_video_workflow status <project-id>
```

## Route only by code state

Read `next_phase` from `status`; do not infer progress from conversation memory or filenames.

- `prepare_narration` / `align_script_timing` → `source-to-persian-narration.md`
- `plan_scenes_moments` through `render_final_candidate` → `narration-to-persian-video.md`
- `final_review` / `awaiting_human` → `persian-final-review.md`

Before executing a phase, record its attempt. Complete only that same phase after its contract is satisfied:

```bash
python -m lib.persian_video_workflow attempt <project-id>
python -m lib.persian_video_workflow complete <project-id> --evidence-json /abs/evidence.json
```
If a review requires going backward, use `send-back`; never edit `next_phase` by hand. The code preserves attempt history and enforces the manifest's send-back ceiling.

Before reading any path not already opened by the current tool call, enforce project isolation:

```bash
python -m lib.persian_video_workflow guard-read <project-id> /absolute/path
```

Sibling `projects/<other-id>/` artifacts, checkpoints, timings, props, and renders are forbidden. Only the current project, its declared input source, and the canonical Persian workflow/skill paths are readable through this front door.

## Canonical contracts, not copies

Always follow these sources rather than restating their rules here:

- `pipeline_defs/persian-footage.yaml` — canonical stage/artifact contracts.
- `skills/pipelines/persian-footage/executive-producer.md` — stage execution and delegation.
- `skills/pipelines/persian-footage/subtitle-alignment.md` — exact approved-script/timing contract.
- `skills/pipelines/persian-footage/final-candidate-protocol.md` — no-copy preflight and candidate lifecycle.
- `skills/meta/checkpoint-protocol.md` — checkpoint persistence and approval protocol.

The front-door workflow terminates only after code verifies a real `compose` checkpoint with `status="awaiting_human"`, an unapproved `final_candidate`, a render path inside the current project, and a SHA-256 matching the exact MP4 bytes. At that point stop and wait for explicit user approval; do not continue to compose completion on your own.
