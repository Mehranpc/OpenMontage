# Persian pipeline P0 baseline

This harness establishes a small, reproducible **measurement baseline** for Issue #107. It does not claim that the pipeline is faster and it does not enforce the later 45-minute target.

## Fixed briefs

The three versioned briefs live in `tests/eval/persian_baseline_briefs/`:

1. `first-date-first-text`
2. `coffee-hormones`
3. `rewards-of-slowness`

All runs are Persian, narrated, vertical, cold-cache, Remotion, and pinned to Film Type 2.16.

## Capture workflow

Use one exact green GitHub SHA for all three real Mac runs. Generate observation templates outside the repository (for example under the local project workspace):

```bash
python -m tests.eval.persian_baseline \
  --emit-templates /tmp/persian-p0-observations \
  --validate-briefs
```

Complete one JSON file per brief after the run reaches `awaiting_human`. Record:

- start and `awaiting_human` timestamps;
- ordered phase spans and explicit interphase spans;
- prompt/instruction text bytes actually loaded;
- temporary script paths;
- every render attempt;
- exact code revision, cold-cache state, runtime/hardware versions;
- critical-blocker count and quality disposition.

Do not commit downloaded media, renders, caches, project workspaces, or raw environment/secrets.

## Build the table

```bash
python -m tests.eval.persian_baseline \
  --observations-dir /tmp/persian-p0-observations \
  --json-output /tmp/persian-p0-baseline.json \
  --markdown-output /tmp/persian-p0-baseline.md
```

The command refuses missing briefs, warm-cache observations, mixed SHAs, invalid timestamps, incomplete runtime metadata, and non-canonical phase order. Output rows are sorted by brief ID, so identical observations produce byte-stable JSON and Markdown.

The baseline reports wall time, every phase, interphase time, prompt bytes, temporary scripts, render count, blockers, and disposition. Keep this table as the comparison input for later P1–P4 measurements; do not label it an improvement until the same three briefs are rerun under the later policy.
