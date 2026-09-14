---
name: persian-video
description: Production-only front door for building a Persian video from approved Persian copy and/or narration audio.
---

# Persian Video

Use this skill only when the user explicitly asks to **make, build, render, continue, or resume a Persian video**.

This skill does not write, translate, improve, or rewrite narration. Text-only Persian writing belongs to separate user/global skills. **Do not create a project for a text-only request**, even if the user mentions `/persian-video` while asking only for narration, rewriting, translation, captions, hooks, or other copy.

The ordered workflow, retry/send-back limits, stock-download ceilings, read isolation, and terminal state are owned by `lib/persian_video_workflow.py`. Do not reproduce or reorder its phase list in prose. Canonical production-stage contracts remain in `pipeline_defs/persian-footage.yaml` and `skills/pipelines/persian-footage/`.

## Production input boundary

A fresh production may start from:

- narration audio whose spoken words are authoritative;
- an approved Persian script whose wording is authoritative;
- both, which is preferred when recorded narration must match approved copy.

"Approved" means the user supplied or selected that Persian wording as the copy to produce. The production pipeline may perform technical normalization allowed by the subtitle contract, but it must not editorially rewrite the wording.
## Start a fresh production

Create a genuinely new project only after video-production intent is explicit:

```bash
python -m lib.persian_video_workflow bootstrap --title "Title" --narration /abs/narration.wav
python -m lib.persian_video_workflow bootstrap --title "Title" --approved-script-file /abs/approved-script.txt
python -m lib.persian_video_workflow bootstrap --title "Title" --narration /abs/narration.wav --approved-script-file /abs/approved-script.txt
```

Raw notes, source articles, English articles, and unapproved draft copy are intentionally not valid bootstrap inputs. Author or revise those outside this production skill first.

Bootstrap creates `projects/<new-id>/`, copies the approved production inputs into that project, records hash-bound workflow state, and opens that project's Backlot board. An existing project directory is a hard refusal, never a resume shortcut.

If production starts from an approved script without audio, remain in input preparation. When recorded narration or an explicitly approved TTS result exists, attach it to the same project:

```bash
python -m lib.persian_video_workflow attach-narration <project-id> /abs/narration.wav
```

For a later session, resume the same bounded state without resetting durable counters:

```bash
python -m lib.persian_video_workflow resume <project-id>
python -m lib.persian_video_workflow status <project-id>
```
## Route only by code state

Read `next_phase` from `status`; do not infer progress from conversation memory, filenames, or an earlier writing session.

- `prepare_inputs` / `align_script_timing` → `prepare-production-inputs.md`
- `plan_scenes_moments` through `render_final_candidate` → `narration-to-persian-video.md`
- `final_review` / `awaiting_human` → `persian-final-review.md`

Before executing a phase, record its attempt. Complete only that same phase after its contract is satisfied:

```bash
python -m lib.persian_video_workflow attempt <project-id>
python -m lib.persian_video_workflow complete <project-id> --evidence-json /abs/evidence.json
```

For `no_copy_preflight`, never write `artifacts/edit_decisions.json` directly. Use the digest-bound draft lifecycle; failed probes remain under `.drafts/` / `.preflight/` and cannot replace the canonical edit:

```bash
python -m lib.persian_video_workflow edit-stage <project-id> <attempt-id> --json /allowed/edit-decisions.json
python -m lib.persian_video_workflow edit-preflight <project-id> <attempt-id>
python -m lib.persian_video_workflow edit-promote <project-id> <attempt-id>
printf '{"attempt_id":"<attempt-id>"}' > /tmp/preflight-evidence.json
python -m lib.persian_video_workflow complete <project-id> --phase no_copy_preflight --evidence-json /tmp/preflight-evidence.json
```

Long-running current-phase commands should use the durable runner instead of depending on one chat/terminal session. Use `--` before the child command. Re-running the same idempotence key reuses the same logical job; `job-status` reconciles detached/orphaned execution before any retry:

```bash
python -m lib.persian_video_workflow job-start <project-id> <job-id> --phase <next-phase> --idempotence-key <key> -- <command> [args...]
python -m lib.persian_video_workflow job-status <project-id> <job-id>
```

If a review requires going backward, use `send-back`; never edit `next_phase` by hand. The code preserves attempt history and enforces the manifest's send-back ceiling.

If explicit new user feedback identifies defects in a rendered candidate after that automatic ceiling is exhausted, use `python -m lib.persian_video_workflow send-back <project-id> <target-phase> --reason "..." --user-directed-revision` to open one fresh bounded revision cycle. The workflow records the old counters, archives invalid downstream checkpoints, and starts a fresh wall-time window; never reset counters or workflow JSON by hand.

Before reading any path not already opened by the current tool call, enforce project isolation:

```bash
python -m lib.persian_video_workflow guard-read <project-id> /absolute/path
```

Sibling `projects/<other-id>/` artifacts, checkpoints, timings, props, and renders are forbidden. The bootstrap copies initial production inputs into the current project so later stages do not depend on an external article, writing workspace, or another project.
## Canonical production contracts

Always follow these sources rather than restating their rules here:

- `pipeline_defs/persian-footage.yaml` — canonical stage/artifact contracts.
- `skills/pipelines/persian-footage/executive-producer.md` — stage execution and delegation.
- `skills/pipelines/persian-footage/script-director.md` — technical Persian script validation; in this front door, authoritative copy is preserved rather than newly authored.
- `skills/pipelines/persian-footage/subtitle-alignment.md` — approved-script/timing authority boundary.
- `skills/pipelines/persian-footage/hook-quality.md` — evidence-backed short-form hook quality, preflight recovery classes, rendered-hook review, and observational post-publish calibration.
- `skills/pipelines/persian-footage/final-candidate-protocol.md` — no-copy preflight and candidate lifecycle.
- `skills/meta/checkpoint-protocol.md` — checkpoint persistence and approval protocol.

The front-door workflow terminates only after code verifies a real `compose` checkpoint with `status="awaiting_human"`, an unapproved `final_candidate`, a render path inside the current project, and a SHA-256 matching the exact MP4 bytes. At that point stop and wait for explicit user approval; do not continue to compose completion on your own.
